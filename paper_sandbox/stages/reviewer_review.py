import json

from paper_sandbox.ai_client import AIClient


def _provenance(data_summary):
    if not data_summary:
        return {"data": "none supplied or acquired (protocol)"}
    if "error" in data_summary:
        return {"data": "acquisition/analysis failed", "error": data_summary["error"],
                "attempted_sources": data_summary.get("attempted_sources", [])}
    return {"source": data_summary.get("source"),
            "datasets": [{k: d.get(k) for k in ("name", "publisher", "download_url", "sha256")}
                         for d in data_summary.get("datasets", [])],
            "n_findings": len((data_summary.get("analysis") or {}).get("findings", []))}


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
        f"Abstract: {draft.get('abstract')}\n\n"
        f"Methods: {draft.get('sections', {}).get('methods', '')}\n\n"
        f"Results: {draft.get('sections', {}).get('results', '')}\n\n"
        f"Discussion: {draft.get('sections', {}).get('discussion', '')}\n\n"
        f"Tables: {json.dumps(draft.get('tables', []), ensure_ascii=False)[:4000]}\n"
        f"Figures: {json.dumps(draft.get('figures', []), ensure_ascii=False)[:1000]}\n"
        f"Data provenance summary: {json.dumps(_provenance(draft.get('data_summary')), ensure_ascii=False)[:3000]}\n"
    )
    return client.chat(prompt, temperature=0.3)
