import json
import aiohttp
import os

def make_payload(ticker, goal, template) -> dict:
    content = template.replace("TICKER", ticker).replace("GOAL", goal)
    return {
        "model": "llama",
        "messages": [
            {
                "role": "system",
                "content": (
                )
            },
            {"role": "user", "content": content}
        ],
        "temperature": 0.6,
        "max_tokens": 3200
    }

class Worker:
    def __init__(self):
        self.prompt_templates = json.load(open(os.environ.get("PROMPT_TEMPLATES_PATH")))
        self.llm_url = f"{os.environ.get("MODEL_API_URL")}/v1/chat/completions"
        self.session = aiohttp.ClientSession()

    async def llm(self, ticker : str, goal : str, html_str : str) -> float:
        prompt = self.prompt_templates[goal]["prompt"]
        payload = make_payload(ticker, goal, prompt)
        async with self.session.post(self.llm_url, json=payload) as resp:
            content = await resp.json()
            return float(content["choices"][0]["message"]["content"])