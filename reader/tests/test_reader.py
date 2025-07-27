import pytest
from app.reader import Reader, date_minus
from shared.payloads import package_web_results
import logging

reader = Reader()

def search_log(logger, ticker, date, goal):
    logger.info(f"\nTesting process_goal with: {ticker} {date} {goal}")
    search_term = str(reader.prompt_templates[goal]["search"]
                      .replace("{{TICKER}}", ticker))

    logger.info(f"\nSearch Term: {search_term}")


@pytest.mark.asyncio
@pytest.mark.parametrize("ticker, date, goal", [
    ("NVDA", "2020-01-25", "PE_RATIO"),
])
async def test_search_internet_real(ticker, date, goal):
    """
    Test the search_internet method.

    :param ticker: The ticker symbol to search for.
    :param date: The date to search for in YYYY-MM-DD
    :param goal: goal from templates.
    """
    await reader.open_connection()
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)

    try:
        assert goal in reader.prompt_templates, f"Goal '{goal}' invalid"

        result = await reader.search_internet(date, ticker, goal)
        packaged = package_web_results(result)

        assert isinstance(result, list)
        assert packaged != ""
        logger.info(f"\nPackage:\n{packaged[:256]}")

    finally:
            await reader.close_connection()


@pytest.mark.asyncio
@pytest.mark.parametrize("ticker, date, goal", [
    ("AMZN", "2024-06-04", "PE_RATIO"),
    ("ORCL", "2024-06-04", "NEWS_SENTIMENT"),
])
async def test_process_goal_real(ticker, date, goal):
    """
    Test the process_goal method which combines search_internet and llm_extract.

    :param ticker: The ticker symbol to search for.
    :param date: The date to search for in YYYY-MM-DD
    :param goal: goal from templates.
    """
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)
    await reader.open_connection()

    try:
        assert goal in reader.prompt_templates, f"Goal '{goal}' invalid"

        search_log(logger, ticker, date, goal)

        result = await reader.process_goal(date, ticker, goal)

        logger.info(f"\nExtracted Results: {result}")

        assert isinstance(result, dict), "Result should be a dict"
        assert goal in result, f"Result should contain the goal {goal}"

    finally:
        await reader.close_connection()


@pytest.mark.asyncio
@pytest.mark.parametrize("ticker, date", [
    ("JPM", "2023-01-01")
])
async def test_get_all_metrics_real(ticker, date):
    """
    Test the get_all_metrics method.
    :param ticker: The ticker symbol to search for.
    :param date: The date to search for in YYYY-MM-DD
    """
    await reader.open_connection()
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)

    try:
        logger.info(f"\nTesting get_all_metrics with: {ticker} {date}")

        num_metrics = len(reader.prompt_templates)

        result = await reader.get_all_metrics(date, ticker)

        logger.info(f"\nMetrics Result: {result}")

        assert isinstance(result, dict), "Result should be a dictionary"
        assert len(result) >= num_metrics, f"Expected at least {num_metrics} metrics"
        assert all(isinstance(value, (int, float, type(None))) for value in result.values()), \
            "All metric values should be numbers or None"

    finally:
        await reader.close_connection()

