import pytest
from app.worker import Worker, date_minus
from shared.payloads import package_web_results
import logging

worker = Worker()


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
    await worker.open_connection()
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)

    try:
        assert goal in worker.prompt_templates, f"Goal '{goal}' invalid"

        logger.info(f"\nTesting search_internet with: {ticker} {date} {goal}")

        date_after = date_minus(date, 90)
        search_term = str(worker.prompt_templates[goal]["search"]
                   .replace("{{TICKER}}", ticker)
                        .replace("{{TIME}}", date)
                        .replace("{{DATE_MINUS}}", date_after))

        logger.info(f"\nSearch Term: {search_term}")

        result = await worker.search_internet(date, ticker, goal)
        packaged = package_web_results(result)

        assert isinstance(result, dict)
        assert "web" in result
        assert packaged != ""
        logger.info(f"\nPackage:\n{packaged[:256]}")

    finally:
            await worker.close_connection()


@pytest.mark.asyncio
@pytest.mark.parametrize("ticker, date, goal", [
    ("NVDA", "2022-01-25", "PE_RATIO"),
    ("", "2022-01-25", "PE_RATIO"),
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
    await worker.open_connection()

    try:
        assert goal in worker.prompt_templates, f"Goal '{goal}' invalid"

        logger.info(f"\nTesting process_goal with: {ticker} {date} {goal}")

        result = await worker.process_goal(date, ticker, goal)

        logger.info(f"\nExtracted Results: {result}")

        assert isinstance(result, dict), "Result should be a dictionary"
        assert goal in result, f"Result should contain the goal {goal}"


    finally:
        await worker.close_connection()


@pytest.mark.asyncio
@pytest.mark.parametrize("ticker, date", [
    ("AAPL", "2024-01-25")
])
async def test_news_sentiment_analysis_real(ticker, date):
    """
    Test the news_sentiment_analysis method.

    :param ticker: The ticker symbol to search for.
    :param date: The date to search for in YYYY-MM-DD
    """
    await worker.open_connection()
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)

    try:
        logger.info(f"\nTesting news_sentiment_analysis with: {ticker} {date}")

        result = await worker.news_sentiment_analysis(date, ticker)

        logger.info(f"\nSentiment Result: {result}")

        assert isinstance(result["NEWS_SENTIMENT"], (int, float)), "Result should be a numeric value"

    finally:
        await worker.close_connection()
