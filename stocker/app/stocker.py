import json
import logging
import asyncio
import os
from shared.worker import Worker
from shared.rate_limiter import RateLimiter
from datetime import datetime, timedelta


def find_nearest_valid_date(dataset: dict, target_date: str) -> str:
    """
    Find the nearest valid date in dataset with error handling
    :param dataset: dict of dates and prices
    :param target_date: date to get near
    """
    try:
        current_date = datetime.strptime(target_date, "%Y-%m-%d")
        for delta in range(0, 7):
            for sign in [1, -1]:
                if delta == 0 and sign == -1:
                    continue
                check_date = current_date + timedelta(days=sign * delta)
                check_str = check_date.strftime("%Y-%m-%d")
                if check_str in dataset:
                    return check_str
        return ""
    except ValueError:
        return ""


class Stocker(Worker):
    def __init__(self):
        super().__init__(
            input_queue=os.environ.get("STOCK_QUERIES_NAME"),
            data_type="stock"
        )
        self.base_url = "https://www.alphavantage.co/query"
        self.stock_api_key = os.environ["STOCK_API_KEY"]

        self.rate_limiter = RateLimiter(period=float(os.environ.get("STOCK_API_PERIOD", "15.0")))

    async def fetch_stock_data(self, ticker: str) -> dict:
        """
        Fetch stock data with simplified caching - no TTL, no read warnings
        :param ticker: Stock ticker symbol
        :return dict: Stock data or empty dict on failure
        """
        cache_key = f"stock_data:{ticker}"

        cached = await self.redis.get(cache_key)
        if cached and "Time Series (Daily)" in cached:
            return json.loads(cached)

        try:
            await self.rate_limiter.acquire()
            params = {
                "function": "TIME_SERIES_DAILY",
                "symbol": ticker,
                "apikey": self.stock_api_key,
                "outputsize": "full"
            }

            async with self.session.get(self.base_url, params=params, timeout=10) as response:
                if response.status != 200:
                    return {}
                data = await response.json()

            if "Time Series (Daily)" not in data:
                return {}

            time_series = data["Time Series (Daily)"]

            await self.redis.set(cache_key, json.dumps(time_series))
            return time_series
        except Exception as e:
            logging.exception(f"Failed to fetch stock data: {e}")
            return {}


    def calculate_performance(self, data: dict, first_day: str, last_day: str) -> float:
        """
        Calculate percentage change
        :param data: dict of dates and prices
        :param first_day: first day to calculate
        :param last_day: last day to calculate
        :return float: percentage change in stock price from first_day to last_day, or 0.0 if no data available.
        """
        try:
            real_first_day = find_nearest_valid_date(data, first_day)
            real_last_day = find_nearest_valid_date(data, last_day)

            if not real_first_day or not real_last_day:
                return 0.0

            start_price = float(data[real_first_day]["4. close"])
            end_price = float(data[real_last_day]["4. close"])
            return (end_price - start_price) / start_price * 100
        except (KeyError, ValueError):
            return 0.0

    async def process_task(self, task: str) -> dict:
        """Process task"""
        try:
            ticker, first_date, last_date = task.split(",", 2)
            self.logger.info(f"Processing: {ticker} from {first_date} to {last_date}")

            stock_data, index_data = await asyncio.gather(
                self.fetch_stock_data(ticker),
                self.fetch_stock_data("SPY")
            )

            if not stock_data or not index_data:
                return {"ticker": ticker, "error": "Data unavailable"}

            stock_perf = self.calculate_performance(stock_data, first_date, last_date)
            index_perf = self.calculate_performance(index_data, first_date, last_date)

            return {
                "ticker": ticker,
                "first_day": first_date,
                "last_day": last_date,
                "outperformed": stock_perf > index_perf,
                "ticker_performance": stock_perf,
                "index_performance": index_perf
            }

        except ValueError:
            return {"error": f"Invalid task format: {task}"}
        except Exception as e:
            self.logger.error(f"Processing failed: {str(e)}")
            return {"error": f"Processing failed: {str(e)}"}