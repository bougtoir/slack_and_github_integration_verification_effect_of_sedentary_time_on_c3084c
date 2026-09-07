"""Content-based journal selection.

The LLM proposes journals from the actual manuscript content (topic, background, abstract, study
design, whether real data were obtained); every proposal is then verified against the Crossref
journal registry (title/ISSN/publisher). Impact factor and APC are LLM estimates and are labelled
as unverified in the output; unverifiable journals are dropped, not invented.
"""
import json
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

from paper_sandbox.ai_client import AIClient
from paper_sandbox.journal_db import JournalDB

_CROSSREF_JOURNALS = "https://api.crossref.org/journals"


def _norm(s):
    return re.sub(r"[^a-z0-9]+", " ", str(s).lower()).strip()


def _crossref_verify(name, timeout=10):
    """Return Crossref registry record for a journal title, or None if no close title match."""
    try:
        r = requests.get(_CROSSREF_JOURNALS, params={"query": name, "rows": 5}, timeout=timeout,
                         headers={"User-Agent": "paper-sandbox (mailto:paper-sandbox@example.org)"})
        r.raise_for_status()
        items = r.json().get("message", {}).get("items", [])
    except (requests.RequestException, ValueError):
        return None
    target = _norm(name)
    target_tokens = set(target.split())
    for it in items:
        title = _norm(it.get("title", ""))
        if not title:
            continue
        tokens = set(title.split())
        exact = title == target
        # accept only near-identical titles (all target words present and length within ~30%)
        close = target_tokens <= tokens and len(tokens) <= max(len(target_tokens) + 1, int(len(target_tokens) * 1.3))
        if exact or close:
            return {
                "crossref_title": it.get("title"),
                "publisher": it.get("publisher"),
                "issn": (it.get("ISSN") or [None])[0],
                "total_dois": (it.get("counts") or {}).get("total-dois"),
            }
    return None


def _content_block(topic, background, manuscript):
    parts = [f"Topic: {topic}"]
    if background:
        parts.append(f"Background / brainstorm:\n{str(background)[:3000]}")
    if manuscript:
        parts.append(f"Title: {manuscript.get('title', '')}")
        parts.append(f"Abstract:\n{manuscript.get('abstract', '')[:2500]}")
        sections = manuscript.get("sections", {}) or {}
        parts.append(f"Methods (excerpt):\n{str(sections.get('methods', ''))[:2000]}")
        has_tables = bool(manuscript.get("tables")) or bool(manuscript.get("figures"))
        parts.append(
            "Article type: EMPIRICAL analysis with real data and tables/figures" if has_tables
            else "Article type: STUDY PROTOCOL / feasibility report (data acquisition did not yield analysable data; "
                 "no empirical results). Only journals that publish protocols or methods/feasibility papers fit."
        )
    return "\n\n".join(parts)


def _propose(client, content, n=10):
    prompt = (
        "You are an experienced academic editor. Based ONLY on the manuscript content below, propose the "
        f"{n} most suitable peer-reviewed journals (real, currently publishing, indexed). Prioritise scope fit "
        "with the specific disease area, population/country, study design and article type; include a mix of "
        "specialty journals and broader epidemiology/public-health journals; exclude predatory journals.\n\n"
        f"{content}\n\n"
        "Return ONLY JSON: {\"journals\": [{\"name\": \"exact journal title\", \"publisher\": \"...\", "
        "\"scope_fit\": 0.0-1.0, \"why\": \"one specific sentence tying THIS manuscript to the journal's scope\", "
        "\"article_type_ok\": true/false, \"oa_model\": \"full OA|hybrid|subscription\", "
        "\"est_if\": number or null, \"est_apc_usd\": number or null, \"concerns\": \"...\"}]}"
    )
    out = client.chat(prompt, temperature=0.3, json_mode=True)
    if not out or out.startswith("[AI"):
        return None
    try:
        data = json.loads(out, strict=False)
        journals = data.get("journals") if isinstance(data, dict) else None
    except json.JSONDecodeError:
        return None
    return [j for j in (journals or []) if isinstance(j, dict) and j.get("name")]


def _to_row(prop, ver, maximize_open_access):
    oa = str(prop.get("oa_model", "")).lower()
    hybrid = "hybrid" in oa
    fit = float(prop.get("scope_fit") or 0)
    score = fit * 10 + (1.0 if prop.get("article_type_ok", True) else -3.0)
    if maximize_open_access and "full" in oa:
        score += 1.0
    return {
        "name": ver["crossref_title"] or prop["name"],
        "publisher": ver.get("publisher") or prop.get("publisher") or "",
        "issn": ver.get("issn"),
        "verified": True,
        "if_2023": prop.get("est_if"),
        "apc_usd": prop.get("est_apc_usd"),
        "hybrid": hybrid,
        "oa_model": prop.get("oa_model"),
        "scope_fit": fit,
        "article_type_ok": bool(prop.get("article_type_ok", True)),
        "why": prop.get("why", ""),
        "concerns": prop.get("concerns", ""),
        "score": round(score, 2),
    }


def _table(ranked, note):
    lines = [note, "", "| # | Journal | Publisher (Crossref) | ISSN | OA model | IF (LLM est., unverified) | APC USD (LLM est., unverified) | Fit | Why this manuscript fits |",
             "|---|---|---|---|---|---|---|---|---|"]
    for i, j in enumerate(ranked[:10], start=1):
        lines.append(
            f"| {i} | {j['name']} | {j.get('publisher','')} | {j.get('issn') or ''} | {j.get('oa_model') or ('hybrid' if j.get('hybrid') else '')} | "
            f"{j.get('if_2023') if j.get('if_2023') is not None else 'n/a'} | {j.get('apc_usd') if j.get('apc_usd') is not None else 'n/a'} | "
            f"{j.get('scope_fit', '')} | {str(j.get('why', '')).replace('|', '/')} |"
        )
    return "\n".join(lines)


def select_journals(cfg, topic, maximize_open_access=False, background="", manuscript=None, client=None):
    client = client or AIClient(cfg.deepseek_api_key, cfg.deepseek_base_url, cfg.deepseek_model)
    content = _content_block(topic, background, manuscript)
    proposals = _propose(client, content)
    if proposals:
        with ThreadPoolExecutor(max_workers=5) as ex:
            verifications = list(ex.map(lambda p: _crossref_verify(p["name"]), proposals))
        ranked, dropped = [], []
        for p, v in zip(proposals, verifications):
            if v:
                ranked.append(_to_row(p, v, maximize_open_access))
            else:
                dropped.append(p["name"])
        ranked.sort(key=lambda x: x["score"], reverse=True)
        if ranked:
            note = ("Candidates proposed from the manuscript content and verified against the Crossref journal registry"
                    + (f"; not verifiable and dropped: {', '.join(dropped)}" if dropped else "") + ".")
            return ranked, _table(ranked, note)

    # honest fallback: static list, keyword match only
    db_path = Path("/app/data/journals.json")
    if not db_path.exists():
        db_path = cfg.workspace / "data" / "journals.json"
    db = JournalDB(db_path if db_path.exists() else None)
    ranked = db.rank(f"{topic} {background or ''}", maximize_open_access=maximize_open_access)
    for r in ranked:
        r.setdefault("verified", False)
        r.setdefault("why", "keyword match against built-in list (LLM/Crossref unavailable)")
    table = "FALLBACK: LLM or Crossref unavailable; keyword match against the built-in journal list.\n\n" + db.to_table(ranked)
    return ranked, table
