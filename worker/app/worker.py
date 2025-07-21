import json
import aiohttp
import os
import logging
import asyncio
from shared.payloads import *
from shared.rate_limiter import RateLimiter


def discard_goals(remaining_goals: set[str], extracted_results: dict) -> set[str]:
    """
    remove goals that have been filled.
    :param remaining_goals: set of goals to be extracted.
    :param extracted_results: dict of already extracted results.

    :return set: set of remaining goals to be extracted.
    """

    return {
        goal for goal in remaining_goals if goal not in extracted_results
                                            or extracted_results[goal] in (None, "", "null")
    }

def date_minus(date, days):
    import datetime
    return (datetime.datetime.strptime(date, "%Y-%m-%d") - datetime.timedelta(days=days)).strftime("%Y-%m-%d")

class Worker:
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.prompt_templates = json.load(open(os.environ.get("PROMPT_TEMPLATES_PATH")))
        self.llm_url = f"{os.environ.get('MODEL_API_URL')}/v1/chat/completions"
        self.search_api_url_web = os.environ.get("SEARCH_API_URL_WEB")
        self.search_api_url_news = os.environ.get("SEARCH_API_URL_NEWS")
        self.search_api_url_period = os.environ.get("SEARCH_API_PERIOD")
        self.search_api_key = os.environ.get("SEARCH_API_KEY")
        self.rate_limiter = RateLimiter(period=float(self.search_api_url_period))
        self.session = None


    async def wait_for_llm(self, max_attempts: int = 120, timeout: int = 10) -> bool:
        """
        Wait for the LLM to become operational.

        :param max_attempts: Maximum number of attempts to make before giving up.
        :param timeout: Timeout in seconds for each attempt.

        :return bool: True if the LLM is operational, False otherwise.
        """

        self.logger.info("Waiting for LLM to become available...")

        test_payload = {
            "model": "llama",
            "messages": [
                {"role": "user", "content": "test"}
            ],
            "max_tokens": 1
        }

        for attempt in range(max_attempts):
            try:
                if self.session is None:
                    self.session = aiohttp.ClientSession()

                async with self.session.post(self.llm_url, json=test_payload, timeout=timeout) as resp:
                    if resp.status != 503:
                        if resp.status == 200:
                            self.logger.info("LLM OPERATIONAL")
                            return True
                        else:
                            self.logger.warning(f"LLM returned unexpected status: {resp.status}")

            except asyncio.TimeoutError:
                self.logger.debug(f"Attempt {attempt + 1}/{max_attempts}: Connection timed out")
            except aiohttp.ClientError as e:
                self.logger.debug(f"Attempt {attempt + 1}/{max_attempts}: Connection error: {str(e)}")

            await asyncio.sleep(5)

        self.logger.error("LLM CONNECTION FAILED")
        return False

    async def open_connection(self):
        """Initialize the aiohttp client session."""
        if self.session is None:
            self.session = aiohttp.ClientSession()

        if not await self.wait_for_llm():
            await self.close_connection()
            return None

        return self.session

    async def close_connection(self):
        """Close the aiohttp client session if it exists."""
        if self.session is not None:
            await self.session.close()
            self.session = None

    async def __aenter__(self):
        """Async context manager entry."""
        await self.open_connection()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.close_connection()


    async def llm_extract(self, time: str, ticker: str, goal: str, content: str) -> dict:
        """
        Send a request to the LLM and return the predicted price with a dict response.
        param ticker: The ticker symbol of the stock.
        param goal: The value to extract.

        :return dict: key-value pair(s).
        """
        if self.session is None:
            await self.open_connection()

        prompt = self.prompt_templates[goal]["prompt"]
        payload = make_llm_payload(prompt, time, ticker, content)

        await self.rate_limiter.acquire()
        async with self.session.post(self.llm_url, json=payload) as resp:
            content = await resp.json()
            raw = content["choices"][0]["message"]["content"].strip()

        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {}

    async def search_internet(self, time: str, ticker: str, goal: str) -> dict:
        """
        Search the internet for the goal for the ticker and time.
        :param time: The time to search for.
        :param ticker: The ticker symbol to search for.
        :param goal: The goal to choose a template for.
        :return dict: The search results.
        """
        if self.session is None:
            await self.open_connection()

        search_template = self.prompt_templates[goal]["search"]
        date_after = date_minus(time, 90)

        query = (
            search_template
            .replace("{{TICKER}}", ticker)
            .replace("{{TIME}}", time)
            .replace("{{DATE_MINUS}}", date_after)
        )

        search_api_url = self.search_api_url_web
        params = make_web_payload(self.prompt_templates[goal]["search"], time, ticker)

        await self.rate_limiter.acquire()
        async with self.session.get(
                search_api_url,
                headers={
                    "Accept": "application/json",
                    "Accept-Encoding": "gzip",
                    "x-subscription-token": str(self.search_api_key)
                },
                params=params) as resp:
            results = await resp.json()

        return results

    async def process_goal(self, time: str, ticker: str, goal : str) -> dict:
        html_content = await self.search_internet(time, ticker, goal)
        packaged = package_web_results(html_content)
        results = await self.llm_extract(time, ticker, goal, packaged)
        return results

    async def news_sentiment_analysis(self, time: str, ticker: str, count=5) -> dict:
        """
        A special goal that aggregates many news sources together to create a combined number.
        :param time: Time to search for.
        :param ticker: The ticker symbol to search for.
        :param count: Number of news articles to search for.

        :return dict: key and value pair.
        """
        sentiment = 0

        search_api_url = self.search_api_url_news
        params = make_news_payload(self.prompt_templates["NEWS_SENTIMENT"]["search"], time, ticker, count)
        async with self.session.get(
                search_api_url,
                headers={
                    "Accept": "application/json",
                    "Accept-Encoding": "gzip",
                    "x-subscription-token": str(self.search_api_key)
                },
                params=params) as resp:
            results = await resp.json()["web"]["results"]

        for result in results:
            to_read = result.get("extra_snippets", "")
            if to_read != "":
                answer = await self.llm_extract(time, ticker, "NEWS_SENTIMENT", to_read)
                num_answer = float(answer["NEWS_SENTIMENT"])
                sentiment += num_answer

        return sentiment


    async def get_all_metrics(self, time: str, ticker: str) -> dict:
        if self.session is None:
            await self.open_connection()

        remaining_goals = set(self.prompt_templates.keys())
        results = {}

        if "SUPER" in remaining_goals:
            remaining_goals.remove("SUPER")
            results.update(await self.process_goal(time, ticker, "SUPER"))
            remaining_goals = discard_goals(remaining_goals, results)

        if "NEWS_SENTIMENT" in remaining_goals:
            remaining_goals.remove("NEWS_SENTIMENT")
            value = await self.news_sentiment_analysis(time, ticker)
            results.update({"NEWS_SENTIMENT": value})

        for goal in remaining_goals:
            results.update(await self.process_goal(time, ticker, goal))

        return results

if __name__ == "__main__":
    import asyncio
    import time