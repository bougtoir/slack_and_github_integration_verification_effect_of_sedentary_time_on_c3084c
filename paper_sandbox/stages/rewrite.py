from paper_sandbox.ai_client import AIClient


def rewrite_sections(cfg, draft, client=None):
    client = client or AIClient(cfg.deepseek_api_key, cfg.deepseek_base_url)
    rewritten = {}
    for section, text in draft.get("sections", {}).items():
        prompt = (
            "Rewrite the following academic section in natural, native-speaker English. "
            "Suppress AI-like phrasing. Keep all citation markers like {1}, {2-3} intact.\n\n"
            f"{text}"
        )
        result = client.chat(prompt, temperature=0.2)
        if result.startswith("[AI"):
            rewritten[section] = text
        else:
            rewritten[section] = result
    draft["sections"] = rewritten
    return draft
