import json
import aiohttp
import os
import logging
import asyncio
from shared.payloads import *
from shared.rate_limiter import RateLimiter
import datetime
from redis.asyncio import Redis



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
        self.redis = None
        self.redis_url = os.environ.get("REDIS_URL")


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

    async def init_redis(self) -> bool:
        """Initialize Redis connection."""
        try:
            self.redis = Redis.from_url(self.redis_url, decode_responses=True)
            await self.redis.ping()
            return True
        except Exception as e:
            self.logger.error(f"Redis connection failed: {str(e)}")
            return False


    async def open_connection(self):
        """Initialize the aiohttp client session."""
        if self.session is None:
            self.session = aiohttp.ClientSession()

        if not await self.init_redis():
            await self.close_connection()
            return None

        if not await self.wait_for_llm():
            await self.close_connection()
            return None

        return self.session

    async def close_connection(self):
        """Close the aiohttp client session if it exists."""
        if self.session is not None:
            await self.session.close()
            self.session = None

        if self.redis is not None:
            await self.redis.close()
            self.redis = None


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

    async def search_internet(self, date: str, ticker: str, goal: str) -> dict:
        """
        Search the internet for the goal for the ticker and date.
        :param date: The date to search for.
        :param ticker: The ticker symbol to search for.
        :param goal: The goal to choose a template for.
        :return dict: The search results.
        """

        search_api_url = self.search_api_url_web
        params = make_web_payload(self.prompt_templates[goal]["search"], date, ticker)

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

    async def process_goal(self, date: str, ticker: str, goal : str) -> dict:
        html_content = await self.search_internet(date, ticker, goal)
        packaged = package_web_results(html_content)
        results = await self.llm_extract(date, ticker, goal, packaged)
        return results

    async def news_sentiment_analysis(self, date: str, ticker: str, count=10) -> dict:
        """
        A special goal that aggregates many news sources together to create a combined number.
        :param date: Date to search for.
        :param ticker: The ticker symbol to search for.
        :param count: Number of news articles to search for.

        :return dict: key and value pair.
        """
        sum = 0

        search_api_url = self.search_api_url_news
        params = make_news_payload(self.prompt_templates["NEWS_SENTIMENT"]["search"], date, ticker, count)
        async with self.session.get(
                search_api_url,
                headers={
                    "Accept": "application/json",
                    "Accept-Encoding": "gzip",
                    "x-subscription-token": str(self.search_api_key)
                },
                params=params) as resp:
            response = await resp.json()

            results = response["results"]

        for result in results:
            to_read = result.get("extra_snippets", "")
            if to_read != "":
                answer = await self.llm_extract(date, ticker, "NEWS_SENTIMENT", to_read)
                try:
                    num_answer = float(answer["NEWS_SENTIMENT"])
                    sum += num_answer
                except KeyError:
                    self.logger.warning(f"Invalid answer from LLM: {answer}")
        sentiment = sum/count
        return {"NEWS_SENTIMENT": sentiment}

    async def get_all_metrics(self, date: str, ticker: str) -> dict:
        if self.session is None:
            await self.open_connection()

        remaining_goals = set(self.prompt_templates.keys())
        results = {}

        # Super search should be done first, to clear as many goals as possible.

        if "NEWS_SENTIMENT" in remaining_goals:
            remaining_goals.remove("NEWS_SENTIMENT")
            result = await self.news_sentiment_analysis(date, ticker)
            results.update(result)

        if remaining_goals:
            tasks = [self.process_goal(date, ticker, goal) for goal in remaining_goals]
            goal_results = await asyncio.gather(*tasks)
            for result in goal_results:
                results.update(result)
                remaining_goals.discard(result.keys()[0])
        return results

if __name__ == "__main__":
    import asyncio
    import time