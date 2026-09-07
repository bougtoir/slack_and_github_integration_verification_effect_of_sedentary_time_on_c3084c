"""Literature stage: only verified, citable, relevant records may reach the manuscript."""
import json

from paper_sandbox.literature_search import CrossrefClient, is_citable, titles_match
from paper_sandbox.stages import literature, draft


class _Cfg:
    deepseek_api_key = ""
    deepseek_base_url = ""
    deepseek_model = ""
    pubmed_email = "t@example.com"
    perplexity_api_key = ""


class _Chat:
    def __init__(self, out):
        self.out = out

    def chat(self, *a, **k):
        return self.out


def test_is_citable_rejects_peer_review_files_and_issue_matter():
    ok = {"doi": "10.1002/jbm4.10428", "title": "Trends in Hip Fracture Incidence in Japan", "type": "journal-article"}
    assert is_citable(ok)
    bad = [
        {"doi": "10.1002/jbm4.10428/v1/review1", "title": 'Review for "Trends in Hip Fracture Incidence in Japan"'},
        {"doi": "10.1002/jbm4.10428/v2/decision1", "title": "Decision letter for something"},
        {"doi": "10.1002/x", "title": "Author response for something"},
        {"doi": "10.1002/y", "title": "Erratum: hip fracture trends"},
        {"doi": "10.1002/z", "title": "Issue Information"},
        {"doi": "10.1002/w", "title": "Hip fracture data", "type": "peer-review"},
        {"doi": "10.1002/v", "title": "Hip fracture figure", "type": "component"},
        {"doi": "10.1002/u", "title": "Unknown"},
        {"doi": "10.1002/t", "title": ""},
    ]
    for b in bad:
        assert not is_citable(b), b


def test_titles_match_is_strict():
    assert titles_match("Trends in Hip Fracture Incidence in Japan.", "Trends in hip fracture incidence in Japan")
    assert titles_match("Trends in Hip Fracture Incidence in Japan: Estimates Based on Nationwide Surveys",
                        "Trends in Hip Fracture Incidence in Japan: Estimates Based on Nationwide Surveys.")
    assert not titles_match("Hip fracture", "Hip fracture incidence in Norway 1990-2010")
    assert not titles_match("Osteoporosis in Japan", "Diabetes in Japan")


def test_crossref_verify_rejects_doi_whose_title_differs(monkeypatch=None):
    c = CrossrefClient()
    import paper_sandbox.literature_search as ls

    orig = ls._get

    def fake_get(url, params=None, headers=None, timeout=10):
        if "works/10.1/real" in url:
            return {"message": {"DOI": "10.1/real", "title": ["Real article about hip fracture trends"], "type": "journal-article"}}
        return None

    ls._get = fake_get
    try:
        assert c.verify(doi="10.1/real", title="Real article about hip fracture trends") is not None
        assert c.verify(doi="10.1/real", title="A completely different fabricated title here") is None
        assert c.verify(doi="10.1/does-not-exist") is None
    finally:
        ls._get = orig


def test_collect_literature_never_falls_back_to_unverified_records():
    import paper_sandbox.stages.literature as lit

    class FakeSearcher:
        def __init__(self, cfg):
            self.crossref = CrossrefClient()

        def search(self, q, limit=10, verify_with_crossref=False):
            return [
                {"doi": "10.9/fake", "title": "Hip fracture incidence trends in Japan (fabricated)", "year": 2020, "authors": ["X"], "journal": "J"},
                {"doi": "", "pmid": "123", "title": "Hip fracture incidence in Japan 2010-2020", "year": 2021, "authors": ["Y"], "journal": "Bone",
                 "type": "journal-article", "verified_by": "pubmed"},
                {"doi": "10.1002/jbm4.10428/v1/review1", "title": 'Review for "Hip fracture incidence in Japan"', "year": 2020},
            ]

    orig_searcher = lit.MultiSourceSearcher
    orig_verify = CrossrefClient.verify
    lit.MultiSourceSearcher = FakeSearcher
    CrossrefClient.verify = lambda self, doi=None, title=None: None  # Crossref knows none of them
    try:
        refs = lit.collect_literature(_Cfg(), "hip fracture incidence Japan", limit=10, idea_text="",
                                      queries=["hip fracture incidence Japan"], client=_Chat("[AI request failed]"))
    finally:
        lit.MultiSourceSearcher = orig_searcher
        CrossrefClient.verify = orig_verify
    # only the PubMed-proven record survives; fake DOI and peer-review file are dropped
    assert [r.get("pmid") for r in refs] == ["123"]
    assert refs[0]["id"] == 1


def test_screen_relevance_can_only_pick_from_given_records():
    cands = [{"title": "A", "year": 2020}, {"title": "B", "year": 2021}, {"title": "C", "year": 2022}]
    out = literature.screen_relevance(_Cfg(), "t", "plan", cands, client=_Chat("[2, 0, 7, 2]"))
    assert [r["title"] for r in out] == ["C", "A"]
    assert literature.screen_relevance(_Cfg(), "t", "plan", cands, client=_Chat("[AI request failed]")) is None
    assert literature.screen_relevance(_Cfg(), "t", "plan", [], client=_Chat("[0]")) == []


def test_renumber_drops_citations_to_nonexistent_references():
    parsed = {
        "abstract": "Burden is high {3}.",
        "sections": {"introduction": "Prior work {1,7} and {12}. More {3-4}."},
        "references": [{"id": 1, "title": "one"}, {"id": 3, "title": "three"}],
    }
    out = draft.renumber_citations_vancouver(parsed)
    assert out["abstract"] == "Burden is high {1}."
    assert out["sections"]["introduction"] == "Prior work {2} and . More {1}."
    assert [r["title"] for r in out["references"]] == ["three", "one"]


def test_ref_text_forbids_citing_when_nothing_verified():
    assert "Do NOT cite" in draft._ref_text([])
    txt = draft._ref_text([{"title": "T", "year": 2020, "doi": "10.1/x", "journal": "J"}])
    assert "ONLY" in txt and "[1] T (2020); J; DOI:10.1/x" in txt


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"{name}: ok")
    print("All tests passed")
