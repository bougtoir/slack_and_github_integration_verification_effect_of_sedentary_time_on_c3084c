import json
import re
from concurrent.futures import ThreadPoolExecutor

from paper_sandbox.ai_client import AIClient
from paper_sandbox.literature_search import MultiSourceSearcher

_STOP = {"the", "of", "in", "and", "on", "a", "an", "to", "for", "with", "by", "from", "at", "is", "are", "study", "effect", "effects"}


def _tokens(text):
    return {t for t in re.findall(r"[a-z0-9]+", (text or "").lower()) if len(t) > 2 and t not in _STOP}


def generate_search_queries(cfg, topic, idea_text="", n=3, client=None):
    """Ask the LLM for several English bibliographic queries; fall back to the topic."""
    client = client or AIClient(cfg.deepseek_api_key, cfg.deepseek_base_url, cfg.deepseek_model)
    prompt = (
        f"Generate {n} distinct English literature-search queries (PubMed/Crossref style, 4-10 words, "
        "no boolean operators) covering epidemiology, methods, and prior findings for this research topic. "
        f"Return ONLY a JSON array of strings.\n\nTopic: {topic}\n\nContext: {idea_text[:1500]}"
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
    if not title or title.strip().lower() == "unknown":
        return -1
    if re.search(r"[\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FAF]", title):
        return -1
    overlap = len(_tokens(title) & topic_tokens)
    return overlap


def collect_literature(cfg, query, limit=10, verify_with_crossref=True, idea_text="", queries=None):
    searcher = MultiSourceSearcher(cfg)
    queries = queries or generate_search_queries(cfg, query, idea_text)
    topic_tokens = _tokens(query) | _tokens(" ".join(queries))

    def _one(q):
        try:
            return searcher.search(q, limit=limit, verify_with_crossref=False)
        except Exception as e:
            print(f"literature search failed for '{q}': {e}")
            return []

    with ThreadPoolExecutor(max_workers=len(queries)) as ex:
        batches = list(ex.map(_one, queries))

    seen = set()
    merged = []
    for batch in batches:
        for r in batch:
            key = (r.get("doi") or (r.get("title") or "").lower()).strip()
            if not key or key in seen:
                continue
            seen.add(key)
            merged.append(r)

    scored = [(s, r) for r in merged if (s := _relevance(r, topic_tokens)) >= 1]
    scored.sort(key=lambda x: (x[0], x[1].get("year") or 0), reverse=True)
    selected = [r for _, r in scored[: limit * 2]]

    if verify_with_crossref and selected:
        with ThreadPoolExecutor(max_workers=min(10, len(selected))) as ex:
            def _verify(c):
                try:
                    item = searcher.crossref.verify(doi=c.get("doi") or None, title=None if c.get("doi") else c.get("title"))
                    return searcher.crossref.to_reference(item) if item else None
                except Exception:
                    return c
            verified = [v for v in ex.map(_verify, selected) if v]
        selected = verified or selected

    selected = [r for r in selected if (r.get("title") or "").strip().lower() != "unknown"][:limit]
    for i, r in enumerate(selected, 1):
        r["id"] = i
    return selected
