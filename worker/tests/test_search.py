import pytest
from app.worker import Worker
import logging

worker = Worker()

@pytest.mark.asyncio
@pytest.mark.parametrize("ticker, time, goal", [
    ("NVDA", "2020-01-25", "PE_RATIO"),
    ("NVDA", "2024-01-25", "EPS"),
    ("JPM", "2024-06-10", "EPS")
])

async def test_search_internet_real(ticker, time, goal):
    """
    Test the search_internet method.

    :param ticker: The ticker symbol to search for.
    :param time: The time to search for in YYYY-MM-DD
    :param goal: goal from templates.
    """

    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)

    try:
        assert goal in worker.prompt_templates, f"Goal '{goal}' invalid"

        logger.info(f"\nTesting search_internet with: {ticker} {time} {goal}")

        search_term = (worker.prompt_templates[goal]["search"]
                   .replace("{{TICKER}}", ticker)
                   .replace("{{TIME}}", time))

        logger.info(f"\nSearch Term: {search_term}")

        result = await worker.search_internet(time, ticker, goal)

        assert isinstance(result, dict)
        assert (len(result.get("mixed", [])) > 0
                or len(result.get("web", [])) > 0
                or len(result.get("news", [])) > 0), "No search results"

    finally:
            await worker.close_connection()
