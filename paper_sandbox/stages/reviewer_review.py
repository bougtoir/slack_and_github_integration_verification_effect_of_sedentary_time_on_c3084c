from paper_sandbox.ai_client import AIClient


def reviewer_review(cfg, draft, journal, client=None):
    client = client or AIClient(cfg.deepseek_api_key, cfg.deepseek_base_url)
    prompt = (
        "You are a critical peer reviewer. Review the draft from these 5 areas:\n"
        "1. Manuscript novelty, focus, logic, methods, consistency\n"
        "2. Statistical design and uncertainty\n"
        "3. Figures/tables supporting claims\n"
        "4. Reproducibility and data provenance\n"
        "5. Strength of claims vs evidence\n\n"
        "Rank issues as: Must-fix (pre-submission), High, Medium, Optional. "
        "For each, provide a concrete fix.\n\n"
        f"Draft title: {draft.get('title')}\n"
        f"Target journal: {journal.get('name')}\n"
        f"Abstract: {draft.get('abstract')}\n"
    )
    return client.chat(prompt, temperature=0.3)
