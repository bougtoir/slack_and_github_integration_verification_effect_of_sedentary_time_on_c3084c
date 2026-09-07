import re


def fabrication_check(draft):
    issues = []
    text = " ".join(draft.get("sections", {}).values())
    figures = draft.get("figures", [])
    tables = draft.get("tables", [])

    for i, fig in enumerate(figures, 1):
        if f"Fig. {i}" not in text and f"Figure {i}" not in text:
            issues.append(f"Figure {i} is not cited in text.")

    for i, table in enumerate(tables, 1):
        if f"Table {i}" not in text:
            issues.append(f"Table {i} is not cited in text.")

    citations = re.findall(r"\{(\d+(?:-\d+)?)\}", text)
    numbers = []
    if not citations:
        issues.append("No citations found in text.")
    else:
        for c in citations:
            if "-" in c:
                start, end = c.split("-")
                numbers.extend(range(int(start), int(end) + 1))
            else:
                numbers.append(int(c))
        expected = list(range(1, max(numbers or [0]) + 1))
        missing = set(expected) - set(numbers)
        if missing:
            issues.append(f"Missing citation numbers: {sorted(missing)}")

    refs = draft.get("references", [])
    ref_ids = {r["id"] for r in refs}
    for n in numbers:
        if n not in ref_ids and n <= len(refs):
            issues.append(f"Citation {n} not in reference list.")

    for fig in figures:
        if "simulated" not in fig.get("caption", "").lower() and "synthetic" not in fig.get("caption", "").lower():
            if "simulated" not in text.lower() and "synthetic" not in text.lower():
                issues.append("Figure caption lacks explicit simulated/synthetic label.")

    return issues


def reproducibility_check(draft):
    issues = []
    text = " ".join(draft.get("sections", {}).values())
    if "simulated" not in text.lower() and "synthetic" not in text.lower():
        issues.append("Methods must state whether data are real, simulated, or from a public source.")
    if "code" not in text.lower() and "script" not in text.lower():
        issues.append("Mention data/code availability for reproducibility.")
    return issues


def consistency_check(draft):
    issues = []
    intro = draft.get("sections", {}).get("introduction", "")
    results = draft.get("sections", {}).get("results", "")
    discussion = draft.get("sections", {}).get("discussion", "")

    if "hypothesis" in intro.lower() and "hypothesis" not in results.lower():
        issues.append("Hypothesis mentioned in intro but not addressed in results.")
    if "evidence" in discussion.lower() and "evidence" not in results.lower():
        issues.append("Discussion refers to 'evidence' not clearly shown in results.")
    if "causal" in discussion.lower() or "cause" in discussion.lower():
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
    citations = re.findall(r"\{(\d+(?:-\d+)?)\}", text)
    cited_numbers = []
    for c in citations:
        if "-" in c:
            start, end = c.split("-")
            cited_numbers.extend(range(int(start), int(end) + 1))
        else:
            cited_numbers.append(int(c))
    cited_numbers = sorted(set(cited_numbers))

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
        ("図表 / Figures & Tables", "表は編集可能 docx/PPTX も別途提供", status(True, "MANUAL")),  # deliverables responsibility
        ("再現性 / Reproducibility", "Methods にデータ出所（実データ or シミュレーション）を明記", status("simulated" in text.lower() or "synthetic" in text.lower() or "public" in text.lower() or bool(data_summary))),
        ("再現性 / Reproducibility", "数値が results ファイルから再現可能でハードコートされていない", status(bool(data_summary) or "placeholder" in text.lower() or "to be calculated" in text.lower())),
        ("再現性 / Reproducibility", "Data/Code Availability または倫理面の記載がある", status("availability" in text.lower() or "code" in text.lower() or "data" in text.lower())),
        ("主張 / Claims", "因果的・過度な解釈をしていない", status("causal" not in text.lower() and "cause" not in text.lower())),
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
    if data_summary:
        lines.append("Data summary: supplied")
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
