import json
import re
from concurrent.futures import ThreadPoolExecutor

from paper_sandbox.ai_client import AIClient
from paper_sandbox.literature_search import MultiSourceSearcher, is_citable

_STOP = {"the", "of", "in", "and", "on", "a", "an", "to", "for", "with", "by", "from", "at", "is", "are", "study", "effect", "effects"}


def _tokens(text):
    return {t for t in re.findall(r"[a-z0-9]+", (text or "").lower()) if len(t) > 2 and t not in _STOP}


POOL_MIN, POOL_MAX = 20, 30


def generate_search_queries(cfg, topic, idea_text="", n=6, client=None):
    """Ask the LLM for several English bibliographic queries; fall back to the topic."""
    client = client or AIClient(cfg.deepseek_api_key, cfg.deepseek_base_url, cfg.deepseek_model)
    prompt = (
        f"Generate {n} distinct English literature-search queries (PubMed/Crossref style, 4-10 words, "
        "no boolean operators) that together cover what the Introduction, Methods and Discussion of a paper on "
        "this research plan will need to cite: disease burden/epidemiology, prior incidence or trend estimates "
        "(same country and international comparators), the data sources named in the plan, the statistical "
        "methods (e.g. age standardisation, joinpoint/Poisson regression), and mechanisms or interventions "
        f"discussed. Return ONLY a JSON array of strings.\n\nTopic: {topic}\n\nResearch plan: {idea_text[:3000]}"
    )
    text = client.chat(prompt, temperature=0.3)
    queries = []
    if text and not text.startswith("[AI"):
        m = re.search(r"\[.*\]", text, re.DOTALL)
        if m:
            try:
                queries = [q for q in json.loads(m.group(0)) if isinstance(q, str) and q.strip()]
            except json.JSONDecodeError:
                queries = []
    queries = [topic] + [q for q in queries if q.lower() != topic.lower()]
    return queries[: n + 1]


def _relevance(ref, topic_tokens):
    title = ref.get("title") or ""
    if not is_citable(ref):
        return -1
    if re.search(r"[\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FAF]", title):
        return -1
    return len(_tokens(title) & topic_tokens)


def screen_relevance(cfg, topic, idea_text, candidates, client=None):
    """Ask the LLM which of the *given* verified records are relevant to the research plan.

    It may only pick from the supplied list (by index) - it cannot add references. Returns the
    subset in the LLM's ranked order; on any failure returns None so the caller keeps the
    token-overlap ranking."""
    if not candidates:
        return []
    client = client or AIClient(cfg.deepseek_api_key, cfg.deepseek_base_url, cfg.deepseek_model)
    lines = []
    for i, r in enumerate(candidates):
        extra = f" | {r['abstract'][:300]}" if r.get("abstract") else ""
        lines.append(f"[{i}] {r.get('year')} {r.get('title')} ({r.get('journal')}){extra}")
    prompt = (
        "You are screening bibliographic records for a manuscript. Below is the research plan and a "
        "numbered list of REAL records found in PubMed/Crossref/OpenAlex.\n"
        "Return ONLY a JSON array of the indices of records that could genuinely support or complement some "
        "part of the manuscript (Introduction: burden/prior estimates incl. international comparators; Methods: "
        "data sources, statistical approach; Discussion: mechanisms, interventions, limitations), ordered from "
        f"most to least useful. Keep up to {POOL_MAX}. Exclude case reports, unrelated conditions, editorials, errata, peer-review "
        "files, and anything you cannot tell is relevant from the record. Do NOT add records that are not "
        "in the list.\n\n"
        f"Research topic: {topic}\n\nPlan: {idea_text[:2000]}\n\nRecords:\n" + "\n".join(lines)
    )
    text = client.chat(prompt, temperature=0.0)
    if not text or text.startswith("[AI"):
        return None
    m = re.search(r"\[[\d,\s]*\]", text)
    if not m:
        return None
    try:
        idx = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    out, seen = [], set()
    for i in idx:
        if isinstance(i, int) and 0 <= i < len(candidates) and i not in seen:
            seen.add(i)
            out.append(candidates[i])
    return out


def collect_literature(cfg, query, limit=POOL_MAX, verify_with_crossref=True, idea_text="", queries=None, client=None):
    """Build the reference pool for a research plan (target POOL_MIN-POOL_MAX records).

    Queries are derived from the plan; Perplexity is given the plan as context so it looks for
    papers that support/complement it. Only records whose existence is proven (PubMed record or
    Crossref DOI record) and that pass a relevance screen are returned. If nothing verifiable is
    found, return [] - never fall back to unverified LLM/Perplexity output. The draft stage cites
    from this pool and only the cited records end up in the manuscript's reference list."""
    searcher = MultiSourceSearcher(cfg)
    queries = queries or generate_search_queries(cfg, query, idea_text, client=client)
    topic_tokens = _tokens(query) | _tokens(" ".join(queries))
    per_query = max(10, (limit * 2) // max(1, len(queries)) + 5)

    def _one(q):
        try:
            return searcher.search(q, limit=per_query, verify_with_crossref=False, context=idea_text or None)
        except Exception as e:
            print(f"literature search failed for '{q}': {e}")
            return []

    with ThreadPoolExecutor(max_workers=len(queries)) as ex:
        batches = list(ex.map(_one, queries))

    seen = set()
    merged = []
    for batch in batches:
        for r in batch:
            key = (r.get("doi") or (r.get("title") or "").lower()).strip().lower()
            if not key or key in seen:
                continue
            seen.add(key)
            merged.append(r)

    scored = [(s, r) for r in merged if (s := _relevance(r, topic_tokens)) >= 1]
    scored.sort(key=lambda x: (x[0], x[1].get("year") or 0), reverse=True)
    selected = [r for _, r in scored[: limit * 3]]
    print(f"[literature] {len(queries)} queries -> {len(merged)} candidates, {len(selected)} pass token screen")

    if verify_with_crossref and selected:
        def _verify(c):
            try:
                item = searcher.crossref.verify(doi=c.get("doi") or None, title=c.get("title"))
            except Exception:
                item = None
            if item:
                ref = searcher.crossref.to_reference(item)
                if c.get("pmid"):
                    ref["pmid"] = c["pmid"]
                return ref
            return c if c.get("pmid") else None

        with ThreadPoolExecutor(max_workers=min(10, len(selected))) as ex:
            selected = [v for v in ex.map(_verify, selected) if v]
    else:
        selected = [r for r in selected if r.get("pmid") or r.get("verified_by") == "crossref"]

    selected = [r for r in selected if is_citable(r)]
    seen_titles, deduped = set(), []
    for r in selected:
        k = re.sub(r"[^a-z0-9]+", " ", (r.get("title") or "").lower()).strip()
        if k in seen_titles:
            continue
        seen_titles.add(k)
        deduped.append(r)
    selected = deduped
    print(f"[literature] {len(selected)} verified (PubMed/Crossref) and citable")

    screened = screen_relevance(cfg, query, idea_text, selected, client=client)
    if screened is not None:
        selected = screened

    selected = selected[:limit]
    print(f"[literature] pool: {len(selected)} verified references (target {POOL_MIN}-{POOL_MAX})")
    for i, r in enumerate(selected, 1):
        r["id"] = i
    return selected
