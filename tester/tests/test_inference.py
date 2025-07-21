import requests
import time
import os
import pytest

llama_path = os.environ.get("MODEL_API_URL")
url = f"{llama_path}/v1/chat/completions"

prompts = [
    pytest.param(
        'A stock costs $100, the earnings per year are $100 million, 2 million shares have been issued. '
        'Respond with "EPS=<Earnings per share>".',
        ["EPS=50"],
        id='EPS'
    ),
    pytest.param(
        'A stock is bought on Jan 1st. On Jan 2nd, the stock goes up 50%. On Jan 3rd, it goes down 50% relative to the previous day. '
        'Think carefully of what has happened, perhaps with an example number.'
        'Overall, has the stock gained or lost value? Respond with "RETURN=GAIN" or "RETURN=LOSS" or "RETURN=NEUTRAL".',
        ['RETURN=LOSS'],
        id='VOLATILITY_LOSS'
    ),
    pytest.param(
        'A stock costs $100. It goes up by $10. What is the new price? Respond with "PRICE=XXX".',
        ['PRICE=110'],
        id='GAIN'
    ),
    pytest.param(
        'A stock is worth $50. It drops by $5. What is the new price? Respond with "PRICE=XX".',
        ['PRICE=45'],
        id='LOSS'
    ),
    pytest.param(
        'You buy 10 shares of a stock at $20 each. What is your total cost? Respond with "COST=XXX".',
        ['COST=200'],
        id='BUY_SHARES'
    ),
    pytest.param(
        'You buy a stock for $30 and sell it for $40. Did you gain or lose? Respond with "RESULT=GAIN" or "RESULT=LOSS".',
        ['RESULT=GAIN'],
        id='SELL_PROFIT'
    ),
    pytest.param(
    'You buy a stock for $60 and sell it for $50. Did you gain or lose? Respond with "RESULT=GAIN" or "RESULT=LOSS".',
    ['RESULT=LOSS'],
    id='SELL_LOSS'
    ),
    pytest.param(
        'A stock goes from $10 to $20. Did it go up by 50% or 100%? Respond with "GAIN=XXX%".',
        ['GAIN=100%'],
        id='PERCENTAGE_GAIN'
    ),
    pytest.param(
        'A stock at $60 does a 2-for-1 split. What is the new price? Respond with "PRICE=XX".',
        ['PRICE=30'],
        id='STOCK_SPLIT'
    ),
    pytest.param(
        'Stock A costs $50. Stock B costs $100. Which is cheaper? Respond with "CHEAPER=A" or "CHEAPER=B".',
        ['CHEAPER=A'],
        id='COMPARE_PRICE'
    ),
    pytest.param(
        'A stock is worth $25. It does not move. What is its price now? Respond with "PRICE=XX".',
        ['PRICE=25'],
        id='NO_CHANGE'
    )
]

def make_test_payload(prompt) -> dict:
    return {
        "model": "llama",
        "messages": [
            {
                "role": "system",
                "content": (
                    "Your job is as a calculator. Explain your calculations very shortly before the answer. "
                    "Speak in a cute way with poor grammar and short sentences. Do not include units in your final answer."
                    "Do your calculations prior to the format. Your response must contain the answer in the exact format requested. "
                    'Do not interrupt the format. Answer as "<ANSWER_NAME>=<ANSWER_NUMBER>" '
                    'For example, if asked "how many quarters are in a year", say "QUARTERS=4".'    
                    'FINAL NUMERICAL RESPONSE FORMAT MUST BE IN ALL CAPS WITH NO UNITS'
                )
            },
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.7,
        "max_tokens": 300
    }

@pytest.mark.parametrize("prompt,expected_answers", prompts)
@pytest.mark.repeat(10)
def test_inference(prompt, expected_answers):
    payload = make_test_payload(prompt)

    # Retry logic
    for attempt in range(120):
        try:
            resp = requests.post(url, json=payload, timeout=10)
            if resp.status_code != 503:
                break
        except requests.exceptions.ConnectionError:
            time.sleep(1)
        time.sleep(1)
    else:
        pytest.fail("Model API unavailable after retries")

    try:
        content = resp.json()["choices"][0]["message"]["content"]
    except Exception:
        pytest.skip("Invalid response from model")

    if not any(ans in content for ans in expected_answers):
        pytest.fail(f"Wrong answer. Got: '{content}'")
