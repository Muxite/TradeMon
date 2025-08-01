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
                "content": "You are a financial analyst. Return ONLY valid JSON with no commentary."
            },
            {
                "role": "user",
                "content": f"{content}\nHTML context:\n```{html_content}```"
            }
        ],
        "temperature": 0.4,
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
               .replace("{{TIME}}", date))

    params = {
        "q": content,
        "count": str(count),
        "spellcheck": "false",
        "summary": "true",
        "freshness": date_pack(date, period)
    }

    return params


def package_web_results(web_results: list) -> str:
    """
    Enhanced result packaging with more context
    web_results: list of dicts with search results.
    """
    package = ""
    for num, result in enumerate(web_results):
        package += f"=== RESULT {num + 1} ===\n"

        # Add title
        package += f"Title: {result.get('title', '')}\n"

        # Add date information if available
        if "age" in result:
            package += f"Date: {result['age']}\n"
        elif "page_age" in result:
            package += f"Date: {result['page_age']}\n"

        # Add main content
        if "description" in result:
            package += f"\nDescription:\n{result['description']}\n\n"

        # Add extra snippets
        if "extra_snippets" in result and result["extra_snippets"]:
            package += "Additional Information:\n"
            for snippet in result["extra_snippets"]:
                package += f"- {snippet}\n"
            package += "\n"

        # Add video transcript
        if "video" in result and "transcript" in result["video"]:
            package += f"Video Transcript:\n{result['video']['transcript']}\n\n"

        package += "\n\n"

    return package.strip()