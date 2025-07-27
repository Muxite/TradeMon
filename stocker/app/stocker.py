import json
import logging
import asyncio
import os
from shared.worker import Worker
from shared.rate_limiter import RateLimiter
from datetime import datetime, timedelta


def find_nearest_valid_date(dataset: dict, target_date: str, date_format: str="%Y-%m-%d") -> str:
    """
    Find the nearest valid date by incrementally adjusting.

    :param dataset: Dictionary with dates as keys.
    :param target_date: Target date in string format
    :param date_format: Date format string

    :return str: Nearest valid date in string format or empty string if no valid date is found.
    """
    try:
        current_date = datetime.strptime(target_date, date_format)
        for delta in [0, 1, -1, 2, -2, 3, -3, 4, -4]:
            check_date = current_date + timedelta(days=delta)
            check_str = check_date.strftime(date_format)
            if check_str in dataset:
                return check_str
        return ""
    except ValueError:
        return ""


def calculate_performance(data: dict, first_day: str, last_day: str) -> float:
    """
    Calculate percentage change between first and last day.

    :param first_day: First day in string format.
    :param last_day: Last day in string format.
    :param data: Dictionary with dates as keys.

    :return: Percentage change between the first and last day.
    """
    real_first_day = find_nearest_valid_date(data, first_day)
    real_last_day = find_nearest_valid_date(data, last_day)

    start_price = float(data[real_first_day]["5. adjusted close"])
    end_price = float(data[real_last_day]["5. adjusted close"])
    return (end_price - start_price) / start_price * 100


class Stocker(Worker):
    def __init__(self):
        super().__init__(
            input_queue=os.environ.get("STOCK_QUERIES_NAME"),
            output_queue=os.environ.get("STOCK_ANSWERS_NAME")
        )
        self.logger = logging.getLogger(__name__)
        self.base_url = "https://www.alphavantage.co/query"
        self.stock_api_key = os.environ["STOCK_API_KEY"]
        self.rate_limiter = RateLimiter(period=float(os.environ.get("SEARCH_API_PERIOD")))
        self.cache_ttl = 864000

    async def fetch_stock_data(self, ticker: str) -> dict:
        """
        Fetch stock data with Redis caching.
        :param ticker: Stock ticker symbol
        :return dict: Stock data in JSON format, or None if no data is found.
        """
        cache_key = f"stock_data:{ticker}"

        cached = await self.redis.get(cache_key)
        if cached:
            return json.loads(cached)

        await self.rate_limiter.acquire()
        params = {
            "function": "TIME_SERIES_DAILY_ADJUSTED",
            "symbol": ticker,
            "apikey": self.stock_api_key,
            "outputsize": "full"
        }

        async with self.session.get(self.base_url, params=params) as response:
            if response.status != 200:
                return {}
            data = await response.json()

        if "Time Series (Daily)" not in data:
            return {}

        time_series = data["Time Series (Daily)"]
        await self.redis.set(cache_key, json.dumps(time_series))
        return time_series

    async def process_task(self, task_data: dict) -> dict:
        ticker = task_data["ticker"]
        first_day = task_data["first_day"]
        last_day = task_data["last_day"]

        stock_data, index_data = await asyncio.gather(
            self.fetch_stock_data(ticker),
            self.fetch_stock_data("SPY")
        )

        if not stock_data or not index_data:
            return {"ticker": ticker, "error": "Data unavailable"}

        stock_perf = calculate_performance(stock_data, first_day, last_day)
        index_perf = calculate_performance(index_data, first_day, last_day)

        self.logger.debug(f"{ticker} performance: {stock_perf} vs Index performance: {index_perf}")

        if None in (stock_perf, index_perf):
            return {"ticker": ticker, "error": "Performance calculation failed"}

        result = {
            "ticker": ticker,
            "first_day": first_day,
            "last_day": last_day,
            "outperformed": stock_perf > index_perf,
            "ticker_performance": stock_perf,
            "index_performance": index_perf
        }

        return result