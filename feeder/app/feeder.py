import tensorflow as tf
import argparse
import asyncio
import json
import random
import time
from datetime import datetime, timedelta
from redis.asyncio import Redis
import logging
import os


class Feeder:
    def __init__(self):
        logging.basicConfig(level=logging.INFO)
        self.logger = logging.getLogger('Feeder')

        #TODO find Brave Search API date limits.
        self.start_date = datetime(2020, 1, 1)
        self.end_date = datetime(2024, 12, 31)
        self.time_delta = timedelta(days=365)

        self.redis_url = os.environ.get("REDIS_URL")
        self.search_queue = os.getenv("SEARCH_QUERIES_NAME")
        self.stock_queue = os.getenv("STOCK_QUERIES_NAME")
        self.feeding_timeout = int(os.getenv("FEEDING_TIMEOUT"))
        self.tickers_path = os.getenv("TICKERS_PATH")
        self.output_dir = os.getenv("DATA_DIR")
        self.logger.info(f"Search Queue: {self.search_queue}")
        self.logger.info(f"Stock Queue: {self.stock_queue}")
        self.logger.info(f"Redis URL: {self.redis_url}")
        self.redis = None
        self.tf_writer = None
        self.metrics = set()
        self.stats = {
            'total_requested': 0,
            'generated': 0,
            'cached': 0,
            'failed': 0,
            'skipped': 0
        }

    async def init_redis(self) -> bool:
        try:
            self.redis = Redis.from_url(self.redis_url, decode_responses=False)
            await self.redis.ping()
            return True
        except Exception as e:
            self.logger.error(f"REDIS CONNECTION FAILED: {str(e)}")
            return False

    async def open_connection(self):
        """Initialize Redis connection"""
        return await self.init_redis()

    async def close_connection(self):
        """Close connections"""
        if self.redis:
            await self.redis.aclose()
            self.redis = None

    async def __aenter__(self):
        await self.open_connection()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close_connection()

    async def fetch_datapoint(self, ticker: str, date: datetime):
        """
        Retrieve or create both search and stock data points in parallel for a ticker and date.
        :param ticker: The ticker symbol.
        :param date: The date to fetch data for.
        """

        start_str = date.strftime("%Y-%m-%d")
        end_str = (date + self.time_delta).strftime("%Y-%m-%d")

        search_key = f"search:{ticker},{start_str}"
        stock_key = f"stock:{ticker},{start_str},{end_str}"

        search_data, stock_data = await asyncio.gather(
            self.fetch_or_queue_data(self.search_queue, search_key),
            self.fetch_or_queue_data(self.stock_queue, stock_key),
            return_exceptions=True
        )

        if isinstance(search_data, Exception):
            self.logger.error(f"Search data fetch failed: {str(search_data)}")
            search_data = None
        if isinstance(stock_data, Exception):
            self.logger.error(f"Stock data fetch failed: {str(stock_data)}")
            stock_data = None

        return search_data, stock_data

    async def fetch_or_queue_data(self, queue_name: str, redis_key: str):
        """
        Fetch cached data or queue for processing and get response.
        """
        try:
            data = await self.redis.get(redis_key)
            if not data:
                await self.redis.lpush(queue_name, redis_key)
                data = await self.wait_for_key(redis_key)
            else:
                self.stats['cached'] += 1
                data = json.loads(data)

            return data
        except json.JSONDecodeError:
            self.logger.error(f"Invalid JSON: {redis_key}")
        except Exception as e:
            self.logger.error(f"Error fetching: {str(e)}")
            raise

        return None

    async def wait_for_key(self, key):
        """
        Wait for a Redis key to be populated with results and get it.
        :param key: The Redis key to wait for.
        :return: The value of the key or None if it times out.
        """
        #TODO make feeding_timeout class-wide to address lock.
        start_time = time.time()
        while time.time() - start_time < self.feeding_timeout:
            data = await self.redis.get(key)
            if data:
                try:
                    result = json.loads(data)
                    if "error" in result:
                        self.logger.error(f"Worker error for {key}: {result['error']}")
                        return None
                    return result
                except json.JSONDecodeError:
                    self.logger.error(f"Invalid JSON for key: {key}")
                    return None
            await asyncio.sleep(1)

        self.logger.warning(f"Timeout waiting for {key}, skipping...")
        return None

    def create_tf_example(self, search_data, stock_data):
        """
        Make TensorFlow Example from search and stock data. Returns None if metrics are missing or empty.
        :param search_data: Search data dict.
        :param stock_data: Stock data dict.

        :return tf.train.Example: TensorFlow Example object or None if missing metrics or empty.
        """

        if not search_data or not isinstance(search_data.get("metrics"), dict) or not search_data["metrics"]:
            self.logger.warning(f"Skipping {search_data} due to missing metrics. ")
            return None

        features = {}
        metrics = search_data["metrics"]

        for metric, value in metrics.items():
            self.metrics.add(metric)
            if isinstance(value, (int, float)):
                features[metric] = tf.train.Feature(
                    float_list=tf.train.FloatList(value=[float(value)]))
            elif isinstance(value, bool):
                features[metric] = tf.train.Feature(
                    int64_list=tf.train.Int64List(value=[int(value)]))

        if stock_data and "outperformed" in stock_data:
            outperformed = stock_data["outperformed"]
            features["label"] = tf.train.Feature(
                int64_list=tf.train.Int64List(value=[int(outperformed)]))
        else:
            self.logger.warning("Missing outperformed in stock data, using default")
            features["label"] = tf.train.Feature(
                int64_list=tf.train.Int64List(value=[0]))

        return tf.train.Example(features=tf.train.Features(feature=features))

    async def generate_datapoint(self, ticker):
        """
        Generate a single data point for a ticker
        """
        self.stats['total_requested'] += 1

        max_start = self.end_date - self.time_delta
        rand_days = random.randint(0, (max_start - self.start_date).days)
        date = self.start_date + timedelta(days=rand_days)

        search_data, stock_data = await self.fetch_datapoint(ticker, date)
        if not search_data or not stock_data:
            self.stats['failed'] += 1
            return None

        example = self.create_tf_example(search_data, stock_data)

        if example is None:
            self.stats['skipped'] += 1
            return None

        if self.tf_writer:
            self.tf_writer.write(example.SerializeToString())
        self.stats['generated'] += 1
        return example

    async def run(self, num_points=10):
        """
        Entry point to run the Feeder through the ticker file
        """

        # Load tickers from text file.
        try:
            with open(self.tickers_path) as f:
                tickers = [line.strip() for line in f if line.strip()]
            self.logger.info(f"Loaded {len(tickers)} tickers from {self.tickers_path}")
        except Exception as e:
            self.logger.error(f"Failed to load tickers: {str(e)}")
            return

        # make name for the training data.
        timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        output_filename = f"analysis_data_{timestamp}.tfrecord"
        output_path = os.path.join(self.output_dir, output_filename)
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        with tf.io.TFRecordWriter(output_path) as self.tf_writer:
            tasks = []
            for i in range(min(num_points, len(tickers))):
                ticker = tickers[i]
                tasks.append(self.generate_datapoint(ticker))
            await asyncio.gather(*tasks)

        self.logger.info(f"Dataset generation complete."
                         f"Success: {self.stats['generated']}, "
                         f"Cached: {self.stats['cached']}, "
                         f"Failed: {self.stats['failed']}, "
                         f"Skipped: {self.stats['skipped']}")

        metadata = {
            "generated_at": datetime.utcnow().isoformat() + 'Z',
            "num_points": self.stats['generated'],
            "tickers_used": list(set(tickers)),
            "date_range": {
                "start": self.start_date.strftime("%Y-%m-%d"),
                "end": self.end_date.strftime("%Y-%m-%d"),
                "time_delta_days": self.time_delta.days
            },
            "metrics": list(self.metrics),
            "stats": self.stats
        }

        metadata_path = os.path.splitext(output_path)[0] + "_meta.json"
        with open(metadata_path, "w") as f:
            json.dump(metadata, f, indent=2)

        self.logger.info(f"Dataset saved to: {output_path}")
        self.logger.info(f"Metadata saved to: {metadata_path}")
