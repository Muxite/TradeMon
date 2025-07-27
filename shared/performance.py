import redis.asyncio as redis
import json

async def calculate_performance(ticker, first_day, last_day):
    # Get cached data
    cache_key = f"stock:{ticker}"
    data = await redis.get(cache_key)
    if not data:
        return None

    # Get SPY data
    spy_key = "stock:SPY"
    spy_data = await redis.get(spy_key)

    # Calculate performance (pseudocode)
    stock_series = json.loads(data)["Time Series (Daily)"]
    spy_series = json.loads(spy_data)["Time Series (Daily)"]

    stock_perf = calculate_change(stock_series, first_day, last_day)
    spy_perf = calculate_change(spy_series, first_day, last_day)

    return {
        "ticker": ticker,
        "outperformed": stock_perf > spy_perf
    }