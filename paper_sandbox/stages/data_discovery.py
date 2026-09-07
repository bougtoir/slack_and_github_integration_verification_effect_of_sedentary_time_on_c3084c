"""Discover publicly downloadable datasets relevant to a research plan.

Pipeline:
  1. derive_data_requirements: DeepSeek turns the research plan into an explicit list
     of required variables (outcome / denominator / stratifiers / period / geography)
     and names the specific databases most likely to hold them.
  2. Tiered search, in priority order:
       tier 1  official statistics (governments, international organisations, societies)
               -- e-Stat keyword search (scraped, no API key) + Perplexity web search
       tier 2  published studies with open data (Europe PMC: OA full text with tables,
               supplementary data, linked repositories) + Perplexity
       tier 3  general open-data repositories via Perplexity
  3. rank_by_coverage: DeepSeek maps each candidate onto the requirements; candidates
     are ordered by how many *unmet* requirements they cover, then by tier.

Candidates are only *suggestions*: nothing in this module is treated as data until
the acquisition stage has actually downloaded and parsed the file and recorded its
provenance.
"""
import html
import json
import os
import re
from urllib.parse import quote

import requests

from paper_sandbox.ai_client import AIClient
from paper_sandbox.literature_search import perplexity_create_with_retry

_HEADERS = {"User-Agent": "PaperSandbox/0.2 (research data discovery; mailto:sandbox@example.com)"}
TIERS = {"official": 1, "published_data": 2, "open_repo": 3}

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
    "machine-readable datasets (CSV, XLSX, JSON, or HTML statistical tables) that contain the "
    "REQUIRED VARIABLES listed below. For each dataset give the DIRECT file download URL "
    "(ending in .csv/.xlsx/.xls/.json/.zip, or an e-Stat URL containing stat_infid=/statInfId=) "
    "as download_url, and the landing page as landing_url. Do not invent URLs; only report URLs "
    "you actually found. Set access to 'open' only if the file can be downloaded without login. "
    "Return 5-8 candidates."
)

_TIER_INSTRUCTIONS = {
    "official": (
        "Restrict yourself to OFFICIAL STATISTICS: national statistics portals (e-Stat, MHLW, "
        "ONS, Destatis, INSEE, KOSIS ...), international organisations (WHO GHO, OECD, World Bank, "
        "Eurostat, UN, IHME GBD), public agencies (CDC, NIH, NHS Digital) and professional-society "
        "registries with public downloads. Prefer specific statistical TABLES over portal home pages."
    ),
    "published_data": (
        "Restrict yourself to PUBLISHED PEER-REVIEWED STUDIES whose data are openly available: "
        "supplementary data files, tables in open-access full text (PMC / Europe PMC), and linked "
        "repositories (Zenodo, figshare, Dryad, OSF, GitHub). Give the PMC article URL or the "
        "repository file URL as download_url."
    ),
    "open_repo": (
        "Restrict yourself to general open-data repositories (Zenodo, figshare, Dryad, Kaggle open "
        "datasets, data.gov style portals, GitHub) with a direct file download."
    ),
}


# --------------------------------------------------------------------------- helpers
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


def _json_obj(text):
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if not m:
            return None
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            return None


def _parse_datasets(text):
    data = _json_obj(text)
    items = data.get("datasets", []) if isinstance(data, dict) else []
    out = []
    for it in items or []:
        if not isinstance(it, dict):
            continue
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


def _requirements_block(req):
    if not req:
        return ""
    lines = ["REQUIRED VARIABLES (derived from the research plan):"]
    for k in ("outcome_variables", "denominator_variables", "exposure_variables", "stratifiers"):
        if req.get(k):
            lines.append(f"- {k}: {', '.join(map(str, req[k]))}")
    if req.get("period"):
        lines.append(f"- period: {req['period']}")
    if req.get("geography"):
        lines.append(f"- geography/population: {req['geography']}")
    if req.get("unit_of_analysis"):
        lines.append(f"- unit of analysis: {req['unit_of_analysis']}")
    srcs = req.get("suggested_sources") or []
    if srcs:
        lines.append("DATABASES SUGGESTED BY THE PLAN (check these first):")
        for s in srcs[:10]:
            lines.append(f"- {s.get('name')} ({s.get('publisher', '')}; tier={s.get('tier')}): {s.get('why', '')}")
    return "\n".join(lines)


# --------------------------------------------------------------------------- step 1
def derive_data_requirements(cfg, topic, idea_text="", protocol=""):
    """Ask DeepSeek what data the plan needs and which specific databases hold it."""
    client = AIClient(cfg.deepseek_api_key, cfg.deepseek_base_url, cfg.deepseek_model)
    prompt = (
        "You are a research data librarian and epidemiologist. Read the research plan and specify, "
        "concretely, what data would be needed to execute it and WHERE such data are publicly "
        "published. Be specific: name the exact statistical survey / table / registry / open dataset "
        "(e.g. 'MHLW Patient Survey, table on estimated patients by ICD-10 S72', 'Vital Statistics "
        "of Japan, deaths by cause', 'WHO GHO indicator X', 'NDB Open Data', 'JOA National Hip "
        "Fracture Database annual report'), the publisher, and why it satisfies the requirement. "
        "Order sources by priority: tier 'official' (governments, international organisations, "
        "professional societies) first, then 'published_data' (peer-reviewed papers with open "
        "supplementary data or tables), then 'open_repo'. Give 3-6 short search keywords per source "
        "(include Japanese keywords for Japanese sources). Do not invent URLs.\n\n"
        "Return ONLY a JSON object:\n"
        "{\"outcome_variables\": [..], \"denominator_variables\": [..], \"exposure_variables\": [..], "
        "\"stratifiers\": [..], \"period\": \"..\", \"geography\": \"..\", \"unit_of_analysis\": \"..\", "
        "\"suggested_sources\": [{\"name\": \"..\", \"publisher\": \"..\", \"tier\": \"official|published_data|open_repo\", "
        "\"why\": \"..\", \"search_keywords\": [..], \"url_hint\": \"..\"}]}\n\n"
        f"Topic: {topic}\n\nResearch idea:\n{(idea_text or '')[:3000]}\n\nProtocol / plan:\n{(protocol or '')[:4000]}"
    )
    text = client.chat(prompt, temperature=0.1)
    if not text or text.startswith("[AI"):
        return None, "DeepSeek unavailable for data-requirements derivation"
    data = _json_obj(text)
    if not isinstance(data, dict):
        return None, "data-requirements response was not valid JSON"
    for k in ("outcome_variables", "denominator_variables", "exposure_variables", "stratifiers", "suggested_sources"):
        v = data.get(k)
        data[k] = v if isinstance(v, list) else []
    data["suggested_sources"] = [s for s in data["suggested_sources"] if isinstance(s, dict) and s.get("name")]
    for s in data["suggested_sources"]:
        if s.get("tier") not in TIERS:
            s["tier"] = "official"
        if not isinstance(s.get("search_keywords"), list):
            s["search_keywords"] = []
    return data, None


# --------------------------------------------------------------------------- step 2 searchers
def estat_search(keyword, limit=8, timeout=20):
    """Keyword search on e-Stat (statistics portal of Japan) by scraping the public search page.

    Returns candidates whose download_url carries stat_infid so the acquisition stage can
    resolve it to a direct CSV/XLSX file-download link. No API key required.
    """
    url = ("https://www.e-stat.go.jp/stat-search/files?page=1&layout=dataset&data=1&metadata=1"
           f"&query={quote(keyword)}")
    r = requests.get(url, headers=_HEADERS, timeout=timeout)
    r.raise_for_status()
    page = r.text
    out, seen = [], set()
    # Each result: an <a ... stat_infid=ID ...> whose enclosing block carries survey name and table title.
    for m in re.finditer(r'<a[^>]*href="([^"]*stat_infid=(\d+)[^"]*)"[^>]*>(.*?)</a>', page, re.DOTALL):
        sid = m.group(2)
        if sid in seen:
            continue
        seen.add(sid)
        text = html.unescape(re.sub(r"<[^>]+>", " ", m.group(3)))
        text = re.sub(r"\s+", " ", text).strip()
        # survey name: nearest preceding heading-like text
        pre = page[max(0, m.start() - 4000):m.start()]
        pre_txt = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", pre)))
        survey = ""
        sm = re.findall(r"([^/]{2,60}) / [^/]{1,40} / [^ ]{1,80}", pre_txt)
        if sm:
            survey = sm[-1].strip()
        name = f"{survey}: {text}" if survey and text else (text or survey or f"e-Stat table {sid}")
        out.append({
            "name": name[:200],
            "publisher": "e-Stat (Statistics of Japan)",
            "landing_url": f"https://www.e-stat.go.jp/stat-search/files?stat_infid={sid}",
            "download_url": f"https://www.e-stat.go.jp/stat-search/files?stat_infid={sid}",
            "format": "csv/xlsx via e-Stat file-download",
            "description": f"e-Stat keyword search '{keyword}'",
            "variables": [], "years": "", "access": "open", "license": "e-Stat terms of use",
            "tier": "official", "discovered_by": "estat_keyword_search",
        })
        if len(out) >= limit:
            break
    return out


def europepmc_open_data_search(query, limit=8, timeout=20):
    """Published studies with open data (OA full text + supplementary/linked data) via Europe PMC."""
    q = f"({query}) AND OPEN_ACCESS:Y AND (HAS_SUPPL:Y OR HAS_DATA:Y OR HAS_FT:Y)"
    r = requests.get(
        "https://www.ebi.ac.uk/europepmc/webservices/rest/search",
        params={"query": q, "format": "json", "pageSize": limit, "resultType": "lite", "sort": "CITED desc"},
        headers=_HEADERS, timeout=timeout,
    )
    r.raise_for_status()
    out = []
    for res in (r.json().get("resultList", {}) or {}).get("result", []) or []:
        pmcid = res.get("pmcid")
        if not pmcid:
            continue
        out.append({
            "name": f"{res.get('title', '').strip()} ({res.get('journalTitle', '')} {res.get('pubYear', '')})",
            "publisher": "Europe PMC (open-access full text)",
            "landing_url": f"https://europepmc.org/article/PMC/{pmcid}",
            "download_url": f"https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML",
            "format": "jats xml (tables)",
            "description": f"open-access article; hasSuppl={res.get('hasSuppl')}, hasData={res.get('hasData')}; doi={res.get('doi')}",
            "variables": [], "years": str(res.get("pubYear", "")), "access": "open", "license": "CC (see article)",
            "tier": "published_data", "discovered_by": "europepmc_search",
        })
    return out


def _perplexity_discover(cfg, query, tier=None):
    api_key = (getattr(cfg, "perplexity_api_key", None) or os.getenv("PERPLEXITY_API_KEY") or "").strip()
    if not api_key:
        return [], "Perplexity API key not configured"
    try:
        from perplexity import Perplexity
        client = Perplexity(api_key=api_key)
        instructions = _INSTRUCTIONS + ("\n\n" + _TIER_INSTRUCTIONS[tier] if tier in _TIER_INSTRUCTIONS else "")
        params = {
            "input": query,
            "instructions": instructions,
            "tools": [{"type": "web_search", "search_context_size": "high"}],
            "response_format": _SCHEMA,
            "max_steps": max(int(getattr(cfg, "perplexity_max_steps", 3) or 3), 5),
        }
        if getattr(cfg, "perplexity_model", None):
            params["model"] = cfg.perplexity_model
        else:
            params["preset"] = getattr(cfg, "perplexity_preset", None) or "pro-search"
        response = perplexity_create_with_retry(client, params)
        items = _parse_datasets(_extract_text(response))
        for it in items:
            it["tier"] = tier or "open_repo"
            it["discovered_by"] = "perplexity_web_search"
        return items, None
    except Exception as e:  # network / SDK errors are reported, never hidden
        return [], f"Perplexity discovery ({tier or 'general'}) failed: {e}"


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
        it["tier"] = "open_repo"
    return items, None


def _is_japanese(*texts):
    return any(re.search(r"[\u3040-\u30ff\u4e00-\u9fff]", t or "") for t in texts)


# --------------------------------------------------------------------------- step 3
def rank_by_coverage(cfg, requirements, candidates):
    """DeepSeek maps candidates to requirements; order by unmet-requirement coverage, then tier."""
    if not candidates:
        return candidates, None
    if not requirements:
        candidates.sort(key=lambda c: TIERS.get(c.get("tier"), 3))
        return candidates, "no requirements; ordered by tier only"
    client = AIClient(cfg.deepseek_api_key, cfg.deepseek_base_url, cfg.deepseek_model)
    req_vars = (requirements.get("outcome_variables", []) + requirements.get("denominator_variables", [])
                + requirements.get("exposure_variables", []) + requirements.get("stratifiers", []))
    listing = "\n".join(
        f"[{i}] {c.get('name')} | {c.get('publisher')} | {c.get('description', '')[:200]} | vars={c.get('variables')} | years={c.get('years')} | url={c.get('download_url')}"
        for i, c in enumerate(candidates)
    )
    prompt = (
        "Given the data requirements of a research plan and a list of candidate public data sources, "
        "judge for EACH candidate which required variables it plausibly contains, based only on its "
        "title/description/publisher (be conservative; unknown = not covered). Return ONLY JSON:\n"
        "{\"coverage\": [{\"index\": 0, \"covers\": [\"<required variable>\", ...], \"relevance\": 0.0-1.0, \"note\": \"..\"}]}\n\n"
        f"{_requirements_block(requirements)}\n\nRequired variable list: {req_vars}\n\nCandidates:\n{listing}"
    )
    text = client.chat(prompt, temperature=0.0)
    data = _json_obj(text) if text and not text.startswith("[AI") else None
    if not isinstance(data, dict) or not isinstance(data.get("coverage"), list):
        candidates.sort(key=lambda c: TIERS.get(c.get("tier"), 3))
        return candidates, "coverage scoring unavailable; ordered by tier only"
    for item in data["coverage"]:
        try:
            c = candidates[int(item.get("index"))]
        except (TypeError, ValueError, IndexError):
            continue
        c["covers"] = [str(v) for v in (item.get("covers") or []) if v]
        try:
            c["relevance"] = float(item.get("relevance") or 0.0)
        except (TypeError, ValueError):
            c["relevance"] = 0.0
        c["coverage_note"] = str(item.get("note") or "")[:300]
    # greedy: prefer candidates that cover requirements not yet covered, then relevance, then tier
    remaining, ordered, pool = set(map(str, req_vars)), [], list(candidates)
    while pool:
        pool.sort(key=lambda c: (-len(remaining & set(c.get("covers", []))), -c.get("relevance", 0.0), TIERS.get(c.get("tier"), 3)))
        best = pool.pop(0)
        remaining -= set(best.get("covers", []))
        ordered.append(best)
    return ordered, None


# --------------------------------------------------------------------------- entry point
def discover_datasets(cfg, topic, idea_text="", limit=10, protocol=""):
    """Return (candidates, log). Candidates are unverified until acquired."""
    log = {"method": None, "query": topic, "errors": [], "n_candidates": 0, "tiers": {}, "requirements": None}

    req, err = derive_data_requirements(cfg, topic, idea_text, protocol)
    if err:
        log["errors"].append(err)
    log["requirements"] = req

    base_query = f"Research question / topic: {topic}"
    if idea_text:
        base_query += f"\n\nResearch idea context:\n{idea_text[:2000]}"
    if req:
        base_query += "\n\n" + _requirements_block(req)

    candidates, methods = [], []

    # ---- tier 1: official statistics
    jp = _is_japanese(topic, idea_text, protocol) or "japan" in f"{topic} {idea_text} {protocol}".lower()
    if jp:
        kws = []
        for s in (req or {}).get("suggested_sources", []):
            if s.get("tier") == "official" and ("e-stat" in f"{s.get('name')} {s.get('publisher')} {s.get('url_hint', '')}".lower()
                                               or _is_japanese(s.get("name"), *s.get("search_keywords", []))):
                kws += [k for k in s.get("search_keywords", []) if _is_japanese(k)]
        for kw in dict.fromkeys(kws[:6]):
            try:
                found = estat_search(kw, limit=6)
                candidates += found
                if found:
                    methods.append("estat_keyword_search")
            except Exception as e:
                log["errors"].append(f"e-Stat search '{kw}' failed: {e}")
    found, e1 = _perplexity_discover(cfg, base_query, tier="official")
    candidates += found
    if e1:
        log["errors"].append(e1)
    elif found:
        methods.append("perplexity_web_search")

    # ---- tier 2: published studies with open data
    try:
        pmc_q = topic
        if req and req.get("outcome_variables"):
            pmc_q = f"{topic} {' '.join(map(str, req['outcome_variables'][:2]))}"
        found = europepmc_open_data_search(pmc_q, limit=6)
        candidates += found
        if found:
            methods.append("europepmc_search")
    except Exception as e:
        log["errors"].append(f"Europe PMC search failed: {e}")
    found, e2 = _perplexity_discover(cfg, base_query, tier="published_data")
    candidates += found
    if e2:
        log["errors"].append(e2)

    # ---- tier 3: general repositories (only if the higher tiers were thin)
    if len(candidates) < 4:
        found, e3 = _perplexity_discover(cfg, base_query, tier="open_repo")
        candidates += found
        if e3:
            log["errors"].append(e3)
    if not candidates:
        found, e4 = _llm_memory_discover(cfg, base_query)
        candidates += found
        if e4:
            log["errors"].append(e4)
        elif found:
            methods.append("llm_memory_unverified")

    # de-dupe by download_url (keep first = highest tier / earliest source)
    seen, unique = set(), []
    for c in candidates:
        key = re.sub(r"[&?]query=[^&]*", "", c["download_url"])
        if key in seen:
            continue
        seen.add(key)
        c.setdefault("tier", "open_repo")
        unique.append(c)

    unique, rank_note = rank_by_coverage(cfg, req, unique)
    if rank_note:
        log["errors"].append(rank_note)
    unique = unique[:limit]
    for t in TIERS:
        log["tiers"][t] = sum(1 for c in unique if c.get("tier") == t)
    log["method"] = "+".join(dict.fromkeys(methods)) or None
    log["n_candidates"] = len(unique)
    return unique, log
