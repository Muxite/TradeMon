import datetime

def date_minus(date, days):
    return (datetime.datetime.strptime(date, "%Y-%m-%d") - datetime.timedelta(days=days)).strftime("%Y-%m-%d")


def make_llm_payload(template, time, ticker, html_content) -> dict:
    content = (template
               .replace("{{TICKER}}", ticker)
               .replace("{{TIME}}", time))
    return {
        "model": "llama",
        "messages": [
            {
                "role": "system",
                "content": (
                    f"Here's is a search result for reference:\n```{html_content}```"
                )
            },
            {
              "role": "system",
              "content": content
            },
            {
                "role": "user",
                "content": "Do the extraction using the provided HTML and instructions."
            }
        ],
        "temperature": 0.6,
        "max_tokens": 3200,
        "response_format": {"type": "json_object"}
    }

def make_web_payload(template, time, ticker, period=90) -> dict:
    content = (template
               .replace("{{TICKER}}", ticker)
               .replace("{{TIME}}", time)
               .replace("{{DATE_MINUS}}", date_minus(time, period)))

    params = {
        "q": content,
        "count": "5",
        "spellcheck": "false",
        "summary": "true"
    }

    return params

def make_news_payload(template, time, ticker, count, period=90) -> dict:
    content = (template
               .replace("{{TICKER}}", ticker)
               .replace("{{TIME}}", time)
               .replace("{{DATE_MINUS}}", date_minus(time, period)))

    params = {
        "q": content,
        "count": str(count),
        "spellcheck": "false",
        "summary": "true"
    }

    return params

def package_web_results(web_results: dict) -> str:
    """
    Convert a dict of web results into a single string.
    :param web_results: A dict of web results from the API.
    :return: A large formatted string ready for LLM extraction.
    """
    package = ""
    if "web" in web_results and "results" in web_results["web"]:
        for num, result in enumerate(web_results["web"]["results"]):
            package += f"Website #{num}: {result.get('title', '')}\n"
            if "description" in result:
                package += f"{result['description']}\n"
            if "extra_snippets" in result and result["extra_snippets"]:
                for snippet in result["extra_snippets"]:
                    package += f"{snippet}\n"
            package += "\n"
    return package
