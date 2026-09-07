from paper_sandbox.ai_client import AIClient


def deepen_idea(cfg, idea, protocol=None, client=None):
    client = client or AIClient(cfg.deepseek_api_key, cfg.deepseek_base_url)
    prompt_parts = [
        "You are an academic collaborator and epidemiologist. Turn the research idea below into a concrete, "
        "data-driven study specification in Markdown with these sections: "
        "1) Research question (one sentence); 2) Population / exposure or trend of interest / outcome / time period; "
        "3) Data requirements: the exact variables and granularity (e.g. counts by year, age group, sex) needed; "
        "4) Candidate PUBLIC data sources: named official statistics or open datasets likely to hold these variables, "
        "with publisher and, if you know it, the portal (do not invent URLs); "
        "5) Analysis plan with the specific estimands (rates, trends, comparisons) and statistical methods; "
        "6) Key limitations. Be specific and concise.",
    ]
    if protocol:
        prompt_parts.append(f"Research protocol / plan:\n{protocol}\n")
    prompt_parts.append(f"Idea: {idea}")
    prompt = "\n\n".join(prompt_parts)
    return client.chat(prompt)
