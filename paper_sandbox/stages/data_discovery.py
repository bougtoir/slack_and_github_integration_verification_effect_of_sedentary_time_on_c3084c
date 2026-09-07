"""Discover publicly downloadable datasets relevant to a research topic.

Perplexity (web_search) is used to locate real, machine-readable public data
(CSV/XLSX/JSON/HTML tables). Candidates are only *suggestions*: nothing in this
module is treated as data until the acquisition stage has actually downloaded
and parsed the file and recorded its provenance.
"""
import json
import os
import re

from paper_sandbox.ai_client import AIClient
from paper_sandbox.literature_search import perplexity_create_with_retry


_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "datasets",
        "schema": {
            "type": "object",
            "properties": {
                "datasets": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "publisher": {"type": "string"},
                            "landing_url": {"type": "string"},
                            "download_url": {"type": "string"},
                            "format": {"type": "string"},
                            "description": {"type": "string"},
                            "variables": {"type": "array", "items": {"type": "string"}},
                            "years": {"type": "string"},
                            "access": {"type": "string"},
                            "license": {"type": "string"},
                        },
                        "required": ["name", "download_url"],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["datasets"],
            "additionalProperties": False,
        },
    },
}

_INSTRUCTIONS = (
    "You are a research data librarian. Using web search, find PUBLICLY DOWNLOADABLE, "
    "machine-readable datasets (CSV, XLSX, JSON, or HTML statistical tables) that could be "
    "used to empirically answer the research question below. Prefer official statistics "
    "(government statistics portals such as e-Stat, MHLW, WHO GHO, OECD, World Bank, "
    "Eurostat, CDC, NIH), disease registries, and open data repositories (Zenodo, figshare, "
    "Dryad, Kaggle open datasets, GitHub). For each dataset give the DIRECT file download URL "
    "(ending in .csv/.xlsx/.xls/.json/.zip where possible) as download_url, and the landing "
    "page as landing_url. Do not invent URLs; only report URLs you actually found. Set access "
    "to 'open' only if the file can be downloaded without login. Return 5-8 candidates."
)


def _extract_text(response):
    text = getattr(response, "output_text", "") or ""
    if text:
        return text
    for item in getattr(response, "output", []) or []:
        if isinstance(item, dict) and item.get("type") == "message":
            for block in item.get("content", []):
                if block.get("type") in ("output_text", "text"):
                    return block.get("text", "")
    return ""


def _parse_datasets(text):
    if not text:
        return []
    try:
        data = json.loads(text)
        items = data.get("datasets", []) if isinstance(data, dict) else []
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if not m:
            return []
        try:
            items = json.loads(m.group(0)).get("datasets", [])
        except json.JSONDecodeError:
            return []
    out = []
    for it in items:
        url = (it.get("download_url") or "").strip()
        if not url.startswith("http"):
            continue
        out.append({
            "name": (it.get("name") or "").strip(),
            "publisher": (it.get("publisher") or "").strip(),
            "landing_url": (it.get("landing_url") or "").strip(),
            "download_url": url,
            "format": (it.get("format") or "").strip().lower(),
            "description": (it.get("description") or "").strip(),
            "variables": it.get("variables") or [],
            "years": (it.get("years") or "").strip(),
            "access": (it.get("access") or "unknown").strip().lower(),
            "license": (it.get("license") or "").strip(),
        })
    return out


def _perplexity_discover(cfg, query):
    api_key = (getattr(cfg, "perplexity_api_key", None) or os.getenv("PERPLEXITY_API_KEY") or "").strip()
    if not api_key:
        return [], "Perplexity API key not configured"
    try:
        from perplexity import Perplexity
        client = Perplexity(api_key=api_key)
        params = {
            "input": query,
            "instructions": _INSTRUCTIONS,
            "tools": [{"type": "web_search", "search_context_size": "high"}],
            "response_format": _SCHEMA,
            "max_steps": max(int(getattr(cfg, "perplexity_max_steps", 3) or 3), 5),
        }
        if getattr(cfg, "perplexity_model", None):
            params["model"] = cfg.perplexity_model
        else:
            params["preset"] = getattr(cfg, "perplexity_preset", None) or "pro-search"
        response = perplexity_create_with_retry(client, params)
        return _parse_datasets(_extract_text(response)), None
    except Exception as e:  # network / SDK errors are reported, never hidden
        return [], f"Perplexity discovery failed: {e}"


def _llm_memory_discover(cfg, query):
    """Fallback without web search. Candidates are flagged as unverified."""
    client = AIClient(cfg.deepseek_api_key, cfg.deepseek_base_url, cfg.deepseek_model)
    prompt = (
        _INSTRUCTIONS
        + "\n\nYou do NOT have web access; list only well-known official datasets whose download URL "
        "you are highly confident about. Return ONLY a JSON object {\"datasets\": [...]} with keys "
        "name, publisher, landing_url, download_url, format, description, variables, years, access, license.\n\n"
        f"Research question:\n{query}"
    )
    text = client.chat(prompt, temperature=0.2)
    if not text or text.startswith("[AI"):
        return [], "DeepSeek unavailable"
    items = _parse_datasets(text)
    for it in items:
        it["discovered_by"] = "llm_memory_unverified"
    return items, None


def discover_datasets(cfg, topic, idea_text="", limit=8):
    """Return (candidates, log). Candidates are unverified until acquired."""
    query = f"Research question / topic: {topic}"
    if idea_text:
        query += f"\n\nResearch idea context:\n{idea_text[:3000]}"

    log = {"method": None, "query": topic, "errors": [], "n_candidates": 0}
    candidates, err = _perplexity_discover(cfg, query)
    if err:
        log["errors"].append(err)
    if candidates:
        log["method"] = "perplexity_web_search"
        for c in candidates:
            c.setdefault("discovered_by", "perplexity_web_search")
    else:
        candidates, err2 = _llm_memory_discover(cfg, query)
        if err2:
            log["errors"].append(err2)
        if candidates:
            log["method"] = "llm_memory_unverified"

    # de-dupe by download_url
    seen = set()
    unique = []
    for c in candidates:
        if c["download_url"] in seen:
            continue
        seen.add(c["download_url"])
        unique.append(c)
    unique = unique[:limit]
    log["n_candidates"] = len(unique)
    return unique, log
