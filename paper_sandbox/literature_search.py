import json
import os
import re
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed


def _get(url, params=None, headers=None, timeout=10):
    try:
        r = requests.get(url, params=params, headers=headers, timeout=timeout)
        r.raise_for_status()
        return r.json()
    except requests.RequestException:
        return None


class CrossrefClient:
    def __init__(self, mailto=None):
        self.mailto = mailto or "sandbox@example.com"
        self.headers = {
            "User-Agent": f"PaperSandbox/0.1 (mailto:{self.mailto})",
        }

    def search(self, query, limit=5):
        url = "https://api.crossref.org/works"
        params = {"query": query, "rows": limit, "mailto": self.mailto, "select": "DOI,title,author,published-print,published-online,container-title"}
        data = _get(url, params=params, headers=self.headers)
        if not data or "message" not in data:
            return []
        return data["message"].get("items", [])

    def to_reference(self, item):
        doi = item.get("DOI", "")
        title = item.get("title")
        if isinstance(title, list) and title:
            title = title[0]
        title = (title or "Unknown").strip().replace("\n", " ")
        year = None
        for key in ["published-print", "published-online", "published"]:
            if item.get(key) and item[key].get("date-parts"):
                parts = item[key]["date-parts"][0]
                if parts:
                    year = int(parts[0])
                    break
        authors = []
        for a in item.get("author", [])[:3]:
            name = a.get("family", "")
            given = a.get("given", "")
            if given:
                name = f"{given} {name}".strip()
            if name:
                authors.append(name)
        if not authors:
            authors = ["Unknown"]
        journal = item.get("container-title")
        if isinstance(journal, list) and journal:
            journal = journal[0]
        journal = (journal or "Unknown").strip().replace("\n", " ")
        return {
            "doi": doi,
            "title": title or "Unknown",
            "year": year,
            "authors": authors,
            "journal": journal or "Unknown",
        }

    def verify(self, doi=None, title=None):
        if doi:
            data = _get(f"https://api.crossref.org/works/{doi}", headers=self.headers)
            if data and "message" in data:
                return data["message"]
        if title:
            items = self.search(title, limit=3)
            for item in items:
                if item.get("title") and title.lower() in item["title"][0].lower():
                    return item
        return None


class PubMedClient:
    def __init__(self, mailto=None):
        self.base = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
        self.mailto = mailto or "sandbox@example.com"

    def search(self, query, limit=10):
        esearch = _get(
            f"{self.base}/esearch.fcgi",
            params={"db": "pubmed", "term": query, "retmax": limit, "retmode": "json", "email": self.mailto},
        )
        if not esearch or "esearchresult" not in esearch:
            return []
        ids = esearch["esearchresult"].get("idlist", [])
        if not ids:
            return []
        esummary = _get(
            f"{self.base}/esummary.fcgi",
            params={"db": "pubmed", "id": ",".join(ids), "retmode": "json", "email": self.mailto},
        )
        if not esummary or "result" not in esummary:
            return []
        results = []
        for pmid in ids:
            doc = esummary["result"].get(pmid, {})
            doi = ""
            for artid in doc.get("articleids", []):
                if artid.get("idtype") == "doi":
                    doi = artid.get("value", "")
                    break
            title = (doc.get("title", "") or "").strip().replace("\n", " ")
            year = None
            if doc.get("pubdate"):
                m = re.search(r"\d{4}", doc["pubdate"])
                if m:
                    year = int(m.group(0))
            raw_authors = doc.get("authors", [])[:3] if doc.get("authors") else []
            authors = []
            for a in raw_authors:
                if isinstance(a, dict):
                    authors.append(a.get("name", ""))
                elif isinstance(a, str):
                    authors.append(a)
            if not authors:
                authors = ["Unknown"]
            journal = (doc.get("fulljournalname", "Unknown") or "Unknown").strip().replace("\n", " ")
            results.append({
                "doi": doi,
                "title": title,
                "year": year,
                "authors": authors,
                "journal": journal,
            })
        return results


class PerplexityClient:
    def __init__(self, api_key=None, base_url=None, model=None, preset=None, system_prompt=None, max_steps=3):
        self.api_key = (api_key or os.getenv("PERPLEXITY_API_KEY") or "").strip()
        self.base_url = base_url or os.getenv("PERPLEXITY_BASE_URL", "https://api.perplexity.ai")
        self.model = model or os.getenv("PERPLEXITY_MODEL")
        self.preset = preset or os.getenv("PERPLEXITY_PRESET", "pro-search")
        default_prompt = (
            "You are a research assistant. Find peer-reviewed papers and return a JSON object "
            "with a 'references' array. Each item must have doi, title, year, authors (list), and journal. "
            "Only include real, verifiable academic publications."
        )
        self.system_prompt = system_prompt or os.getenv("PERPLEXITY_PROMPT") or default_prompt
        self.max_steps = int(os.getenv("PERPLEXITY_MAX_STEPS", max_steps))

    def available(self):
        return bool(self.api_key)

    def _response_schema(self):
        return {
            "type": "json_schema",
            "json_schema": {
                "name": "references",
                "schema": {
                    "type": "object",
                    "properties": {
                        "references": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "doi": {"type": "string"},
                                    "title": {"type": "string"},
                                    "year": {"type": ["integer", "null"]},
                                    "authors": {
                                        "type": "array",
                                        "items": {"type": "string"},
                                    },
                                    "journal": {"type": ["string", "null"]},
                                },
                                "required": ["title"],
                                "additionalProperties": False,
                            },
                        }
                    },
                    "required": ["references"],
                    "additionalProperties": False,
                },
            },
        }

    def _extract_text(self, response):
        """Extract output_text from SDK response object."""
        # The SDK convenience property is preferred when populated.
        text = getattr(response, "output_text", "") or ""
        if text:
            return text
        # Fallback: iterate over the output list and collect message text.
        for item in getattr(response, "output", []) or []:
            if item.get("type") == "message" and item.get("role") == "assistant":
                for block in item.get("content", []):
                    if block.get("type") in ("output_text", "text"):
                        return block.get("text", "")
        return ""

    def search(self, query, limit=5):
        if not self.api_key:
            return []
        try:
            from perplexity import Perplexity
            client = Perplexity(api_key=self.api_key)
            params = {
                "input": query,
                "instructions": self.system_prompt,
                "tools": [{"type": "web_search", "search_context_size": "medium"}],
                "response_format": self._response_schema(),
                "max_steps": self.max_steps,
            }
            if self.model:
                params["model"] = self.model
            else:
                params["preset"] = self.preset

            response = client.responses.create(**params)
            text = self._extract_text(response)
            refs = []
            if text:
                try:
                    data = json.loads(text)
                    refs = data.get("references", []) if isinstance(data, dict) else []
                except json.JSONDecodeError:
                    # Fallback: regex extract DOIs/titles from free text
                    refs = self._fallback_parse(text, limit)
            # Normalize fields
            out = []
            for r in refs[:limit]:
                out.append({
                    "doi": (r.get("doi") or "").strip(),
                    "title": (r.get("title", "") or "").strip().replace("\n", " "),
                    "year": r.get("year"),
                    "authors": r.get("authors") or ["Unknown"],
                    "journal": (r.get("journal") or "").strip().replace("\n", " "),
                })
            return out
        except Exception as e:
            print(f"Perplexity agent search failed: {e}")
            return []

    def _fallback_parse(self, text, limit):
        refs = []
        for line in text.splitlines():
            m = re.search(r"10\.\d{4,9}/[-._;()/:A-Za-z0-9]+", line)
            if m:
                doi = m.group(0).rstrip(".")
                title = re.sub(r"\[\d+\]|\*|\d{4}|10\.\S+|\*\*|\|", "", line).strip("- ").strip().replace("\n", " ")
                year = None
                ym = re.search(r"\b(19|20)\d{2}\b", line)
                if ym:
                    year = int(ym.group(0))
                refs.append({"doi": doi, "title": title, "year": year, "authors": ["Unknown"], "journal": ""})
            if len(refs) >= limit:
                break
        return refs


class OpenAlexClient:
    def __init__(self, api_key=None, mailto=None):
        self.api_key = api_key or os.getenv("OPENALEX_API_KEY")
        self.mailto = mailto or "sandbox@example.com"

    def search(self, query, limit=5):
        url = "https://api.openalex.org/works"
        params = {"search": query, "per-page": limit, "mailto": self.mailto}
        try:
            r = requests.get(url, params=params, timeout=10)
            r.raise_for_status()
            return r.json().get("results", [])
        except requests.RequestException:
            return []

    def to_reference(self, work):
        title = (work.get("display_name") or "Unknown").strip().replace("\n", " ")
        return {
            "doi": work.get("doi", "").replace("https://doi.org/", "") if isinstance(work.get("doi"), str) else "",
            "title": title,
            "year": work.get("publication_year"),
            "authors": [a["author"]["display_name"] for a in work.get("authorships", [])[:3]] if work.get("authorships") else ["Unknown"],
            "journal": (work.get("host_venue") or {}).get("display_name")
                       or ((work.get("primary_location") or {}).get("source") or {}).get("display_name", "Unknown"),
        }


class MultiSourceSearcher:
    def __init__(self, cfg=None, mailto=None):
        self.mailto = mailto or (cfg.pubmed_email if cfg else None) or "sandbox@example.com"
        self.crossref = CrossrefClient(mailto=self.mailto)
        self.pubmed = PubMedClient(mailto=self.mailto)
        self.openalex = OpenAlexClient(mailto=self.mailto)
        perplexity_key = getattr(cfg, "perplexity_api_key", None) if cfg else None
        perplexity_base = getattr(cfg, "perplexity_base_url", None) if cfg else None
        perplexity_model = getattr(cfg, "perplexity_model", None) if cfg else None
        perplexity_preset = getattr(cfg, "perplexity_preset", None) if cfg else None
        perplexity_prompt = getattr(cfg, "perplexity_prompt", None) if cfg else None
        perplexity_max_steps = getattr(cfg, "perplexity_max_steps", None) if cfg else None
        self.perplexity = PerplexityClient(
            api_key=perplexity_key,
            base_url=perplexity_base,
            model=perplexity_model,
            preset=perplexity_preset,
            system_prompt=perplexity_prompt,
            max_steps=perplexity_max_steps or 3,
        )

    def _dedupe(self, refs):
        seen = set()
        out = []
        for r in refs:
            title = r.get("title", "")
            if isinstance(title, list) and title:
                title = title[0]
            title = (title or "").lower()
            key = r.get("doi") or title
            if not key:
                continue
            if key in seen:
                continue
            seen.add(key)
            out.append(r)
        return out

    def _normalize(self, raw):
        """Convert raw work/item into the internal reference dict."""
        if isinstance(raw, dict) and "display_name" in raw:
            return self.openalex.to_reference(raw)
        if isinstance(raw, dict) and "DOI" in raw:
            return self.crossref.to_reference(raw)
        if isinstance(raw, dict) and "doi" in raw and "title" in raw:
            # already a reference
            return raw
        return None

    def search(self, query, limit=10, verify_with_crossref=True):
        candidates = []

        def _run(name, fn):
            try:
                result = fn()
                return name, result or []
            except Exception as e:
                print(f"{name} search failed: {e}")
                return name, []

        tasks = []
        if self.perplexity.available():
            tasks.append(("perplexity", lambda: self.perplexity.search(query, limit=limit)))
        tasks.extend([
            ("crossref", lambda: [self.crossref.to_reference(item) for item in self.crossref.search(query, limit=limit)]),
            ("pubmed", lambda: self.pubmed.search(query, limit=limit)),
            ("openalex", lambda: [self.openalex.to_reference(work) for work in self.openalex.search(query, limit=limit)]),
        ])

        with ThreadPoolExecutor(max_workers=len(tasks)) as executor:
            futures = {executor.submit(_run, name, fn): name for name, fn in tasks}
            for future in as_completed(futures):
                _, result = future.result()
                candidates.extend(result)

        # Deduplicate before verifying to limit Crossref calls
        candidates = self._dedupe(candidates)

        # Verify and enrich with Crossref (existence proof)
        if verify_with_crossref and candidates:
            to_verify = candidates[:limit]

            def _verify_one(c):
                try:
                    if c.get("doi"):
                        item = self.crossref.verify(doi=c["doi"])
                    elif c.get("title") and c.get("title") != "Unknown":
                        item = self.crossref.verify(title=c["title"])
                    else:
                        return c
                    if item:
                        return self.crossref.to_reference(item)
                except Exception as e:
                    print(f"Crossref verify failed: {e}")
                return c

            with ThreadPoolExecutor(max_workers=min(10, len(to_verify))) as executor:
                verified = list(executor.map(_verify_one, to_verify))
        else:
            verified = candidates

        deduped = self._dedupe(verified)
        # Re-number ids
        for i, r in enumerate(deduped, 1):
            r["id"] = i
        return deduped[:limit]
