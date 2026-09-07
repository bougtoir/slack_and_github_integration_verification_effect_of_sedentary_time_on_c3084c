import re


_PLACEHOLDER_PATTERNS = ["[to be calculated]", "[tbd]", "to be determined", "[placeholder]", "placeholder", "text placeholder", "not yet available"]


def _parse_citation_marker(marker):
    """Expand a marker like '1,3' or '1-3' into ordered citation ids."""
    ids = []
    for token in marker.split(","):
        token = token.strip()
        if not token:
            continue
        if "-" in token:
            start, end = token.split("-", 1)
            ids.extend(range(int(start), int(end) + 1))
        else:
            ids.append(int(token))
    return ids


def _extract_citation_numbers(text):
    """Return sorted unique citation numbers found in text."""
    numbers = []
    for marker in re.findall(r"\{([^}]+)\}", text):
        numbers.extend(_parse_citation_marker(marker))
    return sorted(set(numbers))


def contains_placeholder(text):
    """Return True if the text contains known placeholder markers."""
    if text is None:
        return False
    text = str(text).lower()
    return any(p in text for p in _PLACEHOLDER_PATTERNS)


def fabrication_check(draft):
    issues = []
    text = " ".join(draft.get("sections", {}).values())
    figures = draft.get("figures", [])
    tables = draft.get("tables", [])
    data_summary = draft.get("data_summary")

    for i, fig in enumerate(figures, 1):
        if f"Fig. {i}" not in text and f"Figure {i}" not in text:
            issues.append(f"Figure {i} is not cited in text.")

    for i, table in enumerate(tables, 1):
        if f"Table {i}" not in text:
            issues.append(f"Table {i} is not cited in text.")

    numbers = _extract_citation_numbers(text)
    if not numbers:
        issues.append("No citations found in text.")
    else:
        max_num = max(numbers)
        expected = list(range(1, max_num + 1))
        missing = set(expected) - set(numbers)
        if missing:
            issues.append(f"Missing citation numbers: {sorted(missing)}")

    refs = draft.get("references", [])
    ref_ids = {r["id"] for r in refs}
    for n in numbers:
        if n not in ref_ids:
            issues.append(f"Citation {n} not in reference list.")

    cited = set(numbers)
    for r in refs:
        if r.get("id") not in cited:
            issues.append(f"Reference {r['id']} not cited in text.")

    has_real_data = bool(data_summary) and "error" not in data_summary
    if not has_real_data:
        for fig in figures:
            caption = fig.get("caption", "").lower()
            label_found = any(
                k in caption or k in text.lower()
                for k in ["simulated", "synthetic", "placeholder", "no data", "protocol", "conceptual", "analysis failed", "data unavailable", "pre-analysis", "planned analyses"]
            )
            if not label_found:
                issues.append("Figure caption or text must clearly state that the figure is not based on supplied empirical data (simulated/placeholder/protocol/conceptual/data unavailable).")

    return issues


def reproducibility_check(draft):
    issues = []
    text = " ".join(draft.get("sections", {}).values())
    data_summary = draft.get("data_summary")
    has_real_data = bool(data_summary) and "error" not in data_summary
    source_keywords = ["simulated", "synthetic", "public", "no data", "protocol", "analysis failed", "data unavailable", "pre-analysis", "planned analyses"]
    if not has_real_data and not any(k in text.lower() for k in source_keywords):
        issues.append("Methods must state whether data are real, simulated, public, not yet supplied (protocol), or failed to load.")
    reproducibility_terms = ["code", "script", "availability", "reproducible", "github", "repository", "data availability"]
    if not any(t in text.lower() for t in reproducibility_terms):
        issues.append("Mention data/code availability for reproducibility.")
    return issues


def consistency_check(draft):
    issues = []
    intro = draft.get("sections", {}).get("introduction", "")
    results = draft.get("sections", {}).get("results", "")
    discussion = draft.get("sections", {}).get("discussion", "")
    data_summary = draft.get("data_summary")
    has_real_data = bool(data_summary) and "error" not in data_summary
    text = (intro + results + discussion).lower()
    is_protocol = "protocol" in text or "pre-analysis" in text or "planned analyses" in text

    if not is_protocol and "hypothesis" in intro.lower() and "hypothesis" not in results.lower():
        issues.append("Hypothesis mentioned in intro but not addressed in results.")
    if not is_protocol and not has_real_data and "evidence" in discussion.lower() and "evidence" not in results.lower():
        issues.append("Discussion refers to 'evidence' not clearly shown in results.")
    if re.search(r"\bcausal(?:ly)?\b|\bcauses?\b|\bcaused\b|\bcausing\b", discussion, re.IGNORECASE):
        issues.append("Discussion contains causal language; ensure it is supported by design.")
    return issues


def formatting_check(draft, language="en"):
    issues = []
    text = " ".join(draft.get("sections", {}).values())
    if re.search(r"[\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FAF]", text):
        issues.append("Full-width Japanese characters found in text.")
    # Basic LaTeX math check: warn if inline $ or \[ \] present
    if re.search(r"\$[^$]+\$|\\\\\\[|\\\\\\]", text):
        issues.append("LaTeX math notation found; use Word equation editor.")
    return issues


def revision_check(draft):
    issues = []
    text = " ".join(draft.get("sections", {}).values()).lower()
    forbidden = ["old version", "previous analysis", "in the previous", "formerly", "earlier version", "the old"]
    for phrase in forbidden:
        if phrase in text:
            issues.append(f"Revision wording found: '{phrase}'")
    return issues


def run_all_checks(draft, language="en"):
    return {
        "fabrication": fabrication_check(draft),
        "reproducibility": reproducibility_check(draft),
        "consistency": consistency_check(draft),
        "formatting": formatting_check(draft, language),
        "revision": revision_check(draft),
    }


def pre_submission_checklist(draft, chosen_journal=None, data_summary=None, language="en"):
    text = " ".join(draft.get("sections", {}).values())
    figures = draft.get("figures", [])
    tables = draft.get("tables", [])
    refs = draft.get("references", [])
    cited_numbers = _extract_citation_numbers(text)

    has_real_data = bool(data_summary) and "error" not in data_summary
    data_unavailable = bool(data_summary) and "error" in data_summary
    source_mentioned = any(k in text.lower() for k in ["simulated", "synthetic", "public", "no data", "protocol", "analysis failed", "data unavailable", "pre-analysis", "planned analyses"])
    no_placeholders = not any(p in text.lower() for p in ["[to be calculated]", "placeholder", "tbd", "to be determined"])
    protocol_keywords = ["protocol", "no data", "analysis failed", "data unavailable", "pre-analysis", "planned analyses"]
    reproducibility_terms = ["code", "script", "availability", "reproducible", "github", "repository", "data availability"]

    def status(condition, ok="OK", ng="CHECK"):
        return ok if condition else ng

    items = [
        ("原稿 / Manuscript", "新規性・焦点・論理構成が明確である", status(draft.get("title") and len(draft.get("title", "")) > 10)),
        ("原稿 / Manuscript", "Methods の記載が再現可能である（データ出所・解析手順）", status("code" in text.lower() or "script" in text.lower() or "data" in text.lower())),
        ("原稿 / Manuscript", "Results と Discussion の主張が整合している", status(draft.get("sections", {}).get("results") and draft.get("sections", {}).get("discussion"))),
        ("原稿 / Manuscript", "改訂時の旧版表現がない", status(not any(p in text.lower() for p in ["old version", "previous analysis", "in the previous", "formerly", "earlier version", "the old"]))),
        ("統計設計 / Statistics", "独立・解析単位・クラスタリングを考慮している", status("multilevel" in text.lower() or "cluster" in text.lower() or "mixed" in text.lower())),
        ("統計設計 / Statistics", "交絡・感度分析・効果量と不確実性を記載", status("confounding" in text.lower() or "sensitivity" in text.lower() or "confidence interval" in text.lower() or "95% ci" in text.lower())),
        ("統計設計 / Statistics", "多重比較の考慮", status("multiple" in text.lower() or "bonferroni" in text.lower() or "fdr" in text.lower() or "benjamini" in text.lower())),
        ("図表 / Figures & Tables", "全 Figure が本文中で言及されている", status(all((f"Fig. {i}" in text or f"Figure {i}" in text) for i in range(1, len(figures) + 1)))),
        ("図表 / Figures & Tables", "全 Table が本文中で言及されている", status(all(f"Table {i}" in text for i in range(1, len(tables) + 1)))),
        ("図表 / Figures & Tables", "図表番号が出現順", status(cited_numbers == list(range(1, len(cited_numbers) + 1)) if cited_numbers else True)),
        ("図表 / Figures & Tables", "表は編集可能 docx/PPTX も別途提供", status(True, "MANUAL")),
        ("再現性 / Reproducibility", "Methods にデータ出所（実データ or シミュレーション）を明記", status(source_mentioned or has_real_data or data_unavailable)),
        ("再現性 / Reproducibility", "数値が results ファイルから再現可能でハードコートされていない", status(no_placeholders and (has_real_data or any(k in text.lower() for k in protocol_keywords)))),
        ("再現性 / Reproducibility", "Data/Code Availability または倫理面の記載がある", status(any(t in text.lower() for t in reproducibility_terms))),

        ("主張 / Claims", "因果的・過度な解釈をしていない", status(not re.search(r"\bcausal(?:ly)?\b|\bcauses?\b|\bcaused\b|\bcausing\b", text, re.IGNORECASE))),
        ("主張 / Claims", "探索的結果と仮説検証を区別している", status("exploratory" in text.lower() or "hypothesis" in text.lower())),
        ("書式 / Formatting", "全角日本語文字が英語原稿に含まれていない", status(not re.search(r"[\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FAF]", text))),
        ("書式 / Formatting", "LaTeX 数式表記がなく、Word 数式を使用", status(not re.search(r"\$[^$]+\$|\\\\\\[|\\\\\\]", text))),
        ("書式 / Formatting", "引用は Vancouver 連番で出現順", status(cited_numbers == list(range(1, len(cited_numbers) + 1)) and len(cited_numbers) <= len(refs))),
        ("投稿規定 / Journal compliance", "ターゲットジャーナルが設定されている", status(bool(chosen_journal))),
        ("投稿規定 / Journal compliance", "IF/APC/hybrid/publisher が把握されている", status(bool(chosen_journal and chosen_journal.get("if_2023") and chosen_journal.get("apc_usd") is not None))),
        ("投稿規定 / Journal compliance", "STROBE/CONSORT 等必要チェックリストの言及", status("strobe" in text.lower() or "consort" in text.lower() or "checklist" in text.lower())),
        ("公開リポ / Public repo", "bougtoir 直下の公開リポへ同期予定がある", status(True, "MANUAL")),
        ("公開リポ / Public repo", "公開リポのコード＋実データで結果が再現できる", status(True, "MANUAL")),
    ]

    lines = ["# Pre-Submission Checklist", ""]
    journal_name = chosen_journal.get("name") if chosen_journal else "Not selected"
    lines.append(f"Target journal: {journal_name}")
    if has_real_data:
        lines.append("Data summary: supplied")
    elif data_unavailable:
        lines.append("Data summary: analysis failed")
    else:
        lines.append("Data summary: not supplied (protocol mode)")
    lines.append("")

    current = None
    for category, item, st in items:
        if category != current:
            lines.append(f"## {category}")
            current = category
        lines.append(f"- [{ 'x' if st == 'OK' else ' ' }] {item} [{st}]")

    lines.append("")
    lines.append("MANUAL items must be verified by the author before submission.")
    return "\n".join(lines)
