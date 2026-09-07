from paper_sandbox.literature_search import MultiSourceSearcher


def collect_literature(cfg, query, limit=10):
    searcher = MultiSourceSearcher(cfg)
    return searcher.search(query, limit=limit, verify_with_crossref=True)
