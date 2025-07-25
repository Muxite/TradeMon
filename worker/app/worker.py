import json
import aiohttp
import os
import logging
import asyncio
from shared.payloads import *
from shared.rate_limiter import RateLimiter
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

#TODO make Worker into Scraper as a child class of a generalized worker.
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
        self.queries_name = os.environ.get("QUERIES_NAME")  # query is ticker, date.
        self.metrics_name = os.environ.get("METRICS_NAME")


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
            self.logger.error(f"REDIS CONNECTION FAILED: {str(e)}")
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
            await self.redis.aclose()
            self.redis = None


    async def __aenter__(self):
        """Async context manager entry."""
        await self.open_connection()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.close_connection()


    async def llm_extract(self, date: str, ticker: str, goal: str, content: str) -> dict:
        """
        Send a request to the LLM and return the predicted price with a dict response.
        :param date: The latest date of the stock to search for.
        :param ticker: The ticker symbol of the stock.
        :param goal: The value to extract.
        :param content: The content to extract from.

        :return dict: key-value pair(s).
        """

        prompt = self.prompt_templates[goal]["prompt"]
        payload = make_llm_payload(prompt, date, ticker, content)

        await self.rate_limiter.acquire()
        async with self.session.post(self.llm_url, json=payload) as resp:
            content = await resp.json()
            raw = content["choices"][0]["message"]["content"].strip()

        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {}

    async def search_internet(self, date: str, ticker: str, goal: str, count=5) -> dict:
        """
        Search the internet for the goal for the ticker and date.
        :param date: The date to search for.
        :param ticker: The ticker symbol to search for.
        :param goal: The goal to choose a template for.
        :param count: Number of pages to search for.
        :return dict: The search results.
        """

        if self.prompt_templates[goal]["api"] == "news":
            search_api_url = self.search_api_url_news
        else:
            search_api_url = self.search_api_url_web

        params = make_search_payload(self.prompt_templates[goal]["search"], date, ticker, count)

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
        #TODO make overarching search.
        if self.prompt_templates[goal]["api"] == "news":
            result_field = results["results"]
        else:
            result_field = results["web"]["results"]
        return result_field

    async def process_goal(self, date: str, ticker: str, goal : str) -> dict:
        if self.prompt_templates[goal]["type"] == "single":
            html_content = await self.search_internet(date, ticker, goal)
            packaged = package_web_results(html_content)
            results = await self.llm_extract(date, ticker, goal, packaged)
        else:
            results = await self.get_aggregate(date, ticker, goal)

        return results

    async def get_aggregate(self, date: str, ticker: str, goal : str, count=20) -> dict:
        """
        Goes per-site and combines sentiments into a single number.
        :param date: Date to search for.
        :param ticker: The ticker symbol to search for.
        :param goal: The goal to choose a template for.
        :param count: Number of news articles to search for.

        :return dict: key and value pair.
        """
        sum = 0
        valid_responses = 0

        results = await self.search_internet(date, ticker, goal, count)

        for result in results:
            to_read = f"{result.get('description', '')}\n\n{result.get('extra_snippets', '')}"
            if to_read != "":
                answer = await self.llm_extract(date, ticker, goal, to_read)
                try:
                    num_answer = float(answer[goal])
                    sum += num_answer
                    valid_responses += 1
                except KeyError:
                    self.logger.warning(f"Invalid answer from LLM: {answer}")
        sentiment = sum/valid_responses
        return {goal: sentiment}

    async def get_all_metrics(self, date: str, ticker: str) -> dict:
        if self.session is None:
            await self.open_connection()

        remaining_goals = set(self.prompt_templates.keys())
        results = {}

        #TODO add super search to get many goals in 1 request.

        if remaining_goals:
            for goal in remaining_goals.copy():
                result = await self.process_goal(date, ticker, goal)
                results.update(result)
                discard_goals(remaining_goals, result)

        return results

    async def process_task(self, task_dict: dict):
        """Process a single task from Redis"""
        try:
            self.logger.info(f"Processing task: {task_dict}")
            ticker = task_dict["ticker"]
            date = task_dict["date"]

            metrics = await self.get_all_metrics(date, ticker)

            result = {
                "ticker": ticker,
                "date": date,
                "metrics": metrics
            }

            return result

        except KeyError as e:
            self.logger.error(f"Missing key {e}")
        except Exception as e:
            self.logger.error(f"Processing failed {task_dict}: {str(e)}")

    async def run_worker(self):
        """Main worker loop that processes tasks from Redis"""
        await self.open_connection()
        self.logger.info("WORKER STARTED, NOW WAITING FOR TASKS.")

        try:
            while True:
                _, task_json = await self.redis.blpop([self.queries_name], timeout=0)  # tuple (title, content)
                if task_json:
                    try:
                        task_dict = json.loads(task_json.decode('utf-8'))
                        package = await self.process_task(task_dict)
                        await self.redis.sadd(self.metrics_name, json.dumps(package))
                    except json.JSONDecodeError:
                        self.logger.error(f"Invalid JSON task: {task_json}")

        except asyncio.CancelledError:
            self.logger.info("Worker shutdown requested")
        except Exception as e:
            self.logger.error(f"Error in loop: {str(e)}")
        finally:
            await self.close_connection()
            self.logger.info("Worker shutdown complete")

if __name__ == "__main__":
    pass