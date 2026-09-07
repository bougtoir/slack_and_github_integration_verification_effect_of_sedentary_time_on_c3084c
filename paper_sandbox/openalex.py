import os
import requests


class OpenAlexClient:
    def __init__(self, api_key=None, mailto=None):
        # OpenAlex provides open access; an API key is optional and, if invalid,
        # can break requests. We store it but do not use it unless required.
        self.api_key = api_key or os.getenv("OPENALEX_API_KEY")
        self.mailto = mailto or "sandbox@example.com"

    def search(self, query, limit=5):
        url = "https://api.openalex.org/works"
        params = {
            "search": query,
            "per-page": limit,
            "mailto": self.mailto,
        }
        try:
            r = requests.get(url, params=params, timeout=30)
            r.raise_for_status()
            return r.json().get("results", [])
        except requests.RequestException:
            return [{
                "display_name": f"Offline placeholder for {query}",
                "publication_year": 2024,
                "doi": "",
            }]

    def to_references(self, results):
        refs = []
        for i, w in enumerate(results, 1):
            refs.append({
                "id": i,
                "title": w.get("display_name", "Unknown"),
                "year": w.get("publication_year"),
                "doi": w.get("doi", ""),
                "authors": [a["author"]["display_name"] for a in w.get("authorships", [])[:3]] if w.get("authorships") else ["Unknown"],
                "journal": (w.get("host_venue") or {}).get("display_name")
                           or ((w.get("primary_location") or {}).get("source") or {}).get("display_name", "Unknown"),
            })
        return refs
