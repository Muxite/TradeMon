import datetime


def date_minus(date, days):
    return (datetime.datetime.strptime(date, "%Y-%m-%d") - datetime.timedelta(days=days)).strftime("%Y-%m-%d")


def date_pack(date, days):
    return f"{date_minus(date, days)}to{date}"


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


def make_search_payload(template, date, ticker, count, period=90) -> dict:
    """
    Make a payload for the search API.
    :param template: Use template from the prompt templates.json file.
    :param date: The latest date of the stock to search for.
    :param ticker: Stock's ticker.
    :param count: How many articles to search for.
    :param period: The date range.
    :return: parameters.
    """
    content = (template
               .replace("{{TICKER}}", ticker)
               .replace("{{TIME}}", date)
               .replace("{{DATE_MINUS}}", date_minus(date, period)))

    params = {
        "q": content,
        "count": str(count),
        "spellcheck": "false",
        "summary": "true",
        "freshness": date_pack(date, period)
    }

    return params

def package_web_results(web_results: dict) -> str:
    """
    Convert a dict of web results into a single string.
    :param web_results: A dict of web results from the API.
    :return: A large formatted string ready for LLM extraction.
    """
    package = ""
    if "results" in web_results:
        for num, result in enumerate(web_results):
            package += f"Website #{num}: {result.get('title', '')}\n"
            if "description" in result:
                package += f"{result['description']}\n"
            if "extra_snippets" in result and result["extra_snippets"]:
                for snippet in result["extra_snippets"]:
                    package += f"{snippet}\n"
            package += "\n"
    return package
