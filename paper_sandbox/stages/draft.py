import json
import re
from pathlib import Path

from paper_sandbox.ai_client import AIClient
from paper_sandbox.stages.checks import contains_placeholder


def _repair_json(s):
    # Remove line comments that start a line (a bare "//" would also hit URLs inside strings)
    s = re.sub(r"(?m)^\s*//[^\n]*", "", s)
    # Remove trailing commas before } or ]
    s = re.sub(r",(\s*[}\]])", r"\1", s)
    return s


def _loads(s):
    # strict=False tolerates raw newlines/tabs inside strings, which LLMs often emit
    try:
        return json.loads(s, strict=False)
    except json.JSONDecodeError:
        return json.loads(_repair_json(s), strict=False)


def _extract_json(text):
    text = text.strip()
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    if m:
        return _loads(m.group(1))
    m = re.search(r"(\{.*\})", text, re.DOTALL)
    if m:
        return _loads(m.group(1))
    raise ValueError("No JSON object found")


def _normalize_manuscript(parsed, references, data_summary=None):
    sections = parsed.get("sections", {})
    normalized = {
        "title": parsed.get("title", "Untitled protocol"),
        "abstract": parsed.get("abstract", ""),
        "sections": {
            "introduction": sections.get("introduction", sections.get("Introduction", "")),
            "methods": sections.get("methods", sections.get("Methods", "")),
            "results": sections.get("results", sections.get("Results", "")),
            "discussion": sections.get("discussion", sections.get("Discussion", "")),
            "conclusion": sections.get("conclusion", sections.get("Conclusion", "")),
        },
        "figures": parsed.get("figures", []),
        "tables": parsed.get("tables", []),
        "references": parsed.get("references") or references,
        "data_summary": data_summary,
    }
    return normalized


def _parse_citation_marker(marker):
    """Expand a marker like '1,3' or '1-3' or '1,3-5' into ordered ids."""
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


def _collapse_numbers(nums):
    """Collapse a sorted int list into a comma-separated range string."""
    if not nums:
        return ""
    collapsed = []
    start = prev = nums[0]
    for n in nums[1:]:
        if n == prev + 1:
            prev = n
        else:
            collapsed.append(f"{start}-{prev}" if prev != start else str(start))
            start = prev = n
    collapsed.append(f"{start}-{prev}" if prev != start else str(start))
    return ",".join(collapsed)


def renumber_citations_vancouver(parsed):
    """Renumber citations in order of appearance and reorder references."""
    sections = parsed.get("sections", {})
    text_all = " ".join([parsed.get("abstract", "")] + list(sections.values()))
    markers = re.findall(r"\{([^}]+)\}", text_all)

    seen = []
    seen_set = set()
    for marker in markers:
        for cid in _parse_citation_marker(marker):
            if cid not in seen_set:
                seen_set.add(cid)
                seen.append(cid)

    mapping = {old: new for new, old in enumerate(seen, 1)}
    ref_by_id = {r.get("id", i + 1): r for i, r in enumerate(parsed.get("references", []))}

    def _renumber_marker(match):
        old_ids = _parse_citation_marker(match.group(1))
        new_ids = sorted({mapping[oid] for oid in old_ids if oid in mapping})
        return "{" + _collapse_numbers(new_ids) + "}"

    if parsed.get("abstract"):
        parsed["abstract"] = re.sub(r"\{([^}]+)\}", _renumber_marker, parsed["abstract"])
    for key in sections:
        parsed["sections"][key] = re.sub(r"\{([^}]+)\}", _renumber_marker, sections[key])

    new_refs = []
    for old_id in seen:
        ref = ref_by_id.get(old_id)
        if ref is None:
            continue
        ref["id"] = mapping[old_id]
        new_refs.append(ref)
    parsed["references"] = new_refs
    return parsed


def _ensure_figures_tables_cited(parsed):
    """Append explicit citations if the model omitted them."""
    sections = parsed.get("sections", {})
    text = " ".join([parsed.get("abstract", "")] + list(sections.values())).lower()
    target_key = None
    for k in sections:
        if k.lower() == "results":
            target_key = k
            break
    if target_key is None:
        for k in sections:
            if k.lower() == "methods":
                target_key = k
                break
    if target_key is None:
        return

    additions = []
    for fig in parsed.get("figures", []):
        i = fig.get("id", 1)
        caption = fig.get("caption", "")
        if f"fig. {i}" not in text and f"figure {i}" not in text:
            additions.append(f"{caption} is shown in Fig. {i}.")
    for table in parsed.get("tables", []):
        i = table.get("id", 1)
        caption = table.get("caption", "")
        if f"table {i}" not in text:
            additions.append(f"{caption} is summarized in Table {i}.")
    if additions:
        sections[target_key] = sections[target_key].rstrip() + "\n\n" + " ".join(additions)


def _check_for_placeholders(parsed):
    """Raise if the parsed manuscript still contains placeholder markers."""
    for section, text in parsed.get("sections", {}).items():
        if contains_placeholder(text):
            raise RuntimeError(f"Placeholder marker found in section '{section}'; refusing to produce manuscript with fabricated values.")
    for fig in parsed.get("figures", []):
        if contains_placeholder(fig.get("caption", "")):
            raise RuntimeError("Placeholder marker found in figure caption; refusing to produce manuscript with fabricated values.")
    for table in parsed.get("tables", []):
        if contains_placeholder(table.get("caption", "")):
            raise RuntimeError("Placeholder marker found in table caption; refusing to produce manuscript with fabricated values.")
        for row in table.get("rows", []):
            for cell in row:
                if contains_placeholder(cell):
                    raise RuntimeError("Placeholder marker found in table cell; refusing to produce manuscript with fabricated values.")


def _ref_text(references):
    if not references:
        return "No references retrieved."
    return "\n".join(
        f"[{i}] {r.get('title','Untitled')} ({r.get('year','n.d.')}); DOI:{r.get('doi','')}"
        for i, r in enumerate(references, 1)
    )


def generate_draft(cfg, idea, references, data_summary=None, chosen_journal=None, client=None):
    client = client or AIClient(
        cfg.deepseek_api_key, cfg.deepseek_base_url, cfg.deepseek_model
    )

    refs = _ref_text(references)

    analysis = (data_summary or {}).get("analysis") if data_summary and "error" not in data_summary else None
    if analysis:
        data_block = json.dumps({
            "datasets": data_summary.get("datasets"),
            "sample_description": analysis.get("sample_description"),
            "findings": analysis.get("findings"),
            "tables": analysis.get("tables"),
            "figures": analysis.get("figures"),
            "limitations": analysis.get("limitations"),
            "sources_attempted_but_failed": [s for s in data_summary.get("attempted_sources", []) if s.get("status") == "failed"],
        }, indent=2, ensure_ascii=False)
        mode_instruction = (
            "Real PUBLIC datasets were downloaded by the pipeline (URLs, publishers and SHA-256 checksums are in "
            "`datasets`) and analysed by a reproducible script (analysis.py) whose outputs are in `findings`, "
            "`tables` and `figures`. Write an EMPIRICAL manuscript: in Methods, name each data source with its "
            "publisher and URL, describe the sample (`sample_description`) and the computations described in each "
            "finding's `method`. In Results report ONLY the numbers in `findings`/`tables`, verbatim, with units. "
            "Do not invent sample sizes, p-values, confidence intervals or any number absent from the data. "
            "Do not assign meanings to variables beyond what the dataset names and finding labels state. "
            "If a dataset is a published article or report (e.g. a PMC/journal URL), describe it honestly as data "
            "extracted from the published tables of that article, name the article, and treat the work as a secondary "
            "analysis of published aggregate data; do not call it a registry or primary dataset. "
            "Do NOT describe the data as simulated, synthetic or hypothetical. Mention `limitations` in Discussion. "
            "Cite the tables and figures listed (Table N / Fig. N) using the SAME ids and captions; copy `tables` "
            "and `figures` into the JSON output unchanged. State that code and data are available in the repository."
        )
    elif data_summary and "error" not in data_summary:
        data_block = json.dumps(data_summary, indent=2, ensure_ascii=False)
        mode_instruction = (
            "A real dataset has been supplied. Its source is included in the data summary. "
            "Use ONLY the numbers in the data summary when writing Results. "
            "Do not invent sample sizes, p-values, medians, confidence intervals, "
            "or any other numeric values that are not in the data summary. "
            "Do not assign exposure, outcome, or group meanings that are not in the data summary; "
            "describe groups using the exact labels supplied and do not relabel columns. "
            "Do NOT describe the data as simulated, synthetic, or hypothetical. "
            "Cite the analysis as performed by the sandbox pipeline."
        )
    elif data_summary and "error" in data_summary:
        attempted = data_summary.get("attempted_sources") or []
        data_block = f"Data acquisition/analysis failed: {data_summary['error']}"
        if attempted:
            data_block += "\nSources the pipeline actually attempted:\n" + "\n".join(
                f"- {s.get('name')}: {s.get('url')} -> {s.get('status')} ({s.get('error') or 'ok'})" for s in attempted)
        mode_instruction = (
            "The pipeline tried to obtain data but could not analyse any. Do not invent sample sizes, "
            "p-values, medians, regression coefficients, or any other empirical numbers. "
            "Do not use placeholders such as [to be calculated] or [TBD]. Clearly state in Methods "
            "that data access or analysis failed, list the sources that were attempted and why each failed, "
            "and describe the planned analysis once data are available. Label the manuscript as a protocol. "
            "Omit the `tables` field; do not include empirical tables. "
            "If a figure is included, describe it as a conceptual workflow and cite it as (Fig. 1), not empirical results."
        )
    else:
        data_block = "No data file was supplied."
        mode_instruction = (
            "No data file was supplied. Produce a detailed research PROTOCOL / pre-analysis plan. "
            "Do not invent sample sizes, p-values, medians, regression coefficients, or any "
            "other empirical numbers. Do not use placeholders such as [to be calculated] or [TBD]. "
            "Clearly state that Results are planned analyses and that the current draft is a protocol. "
            "Omit the `tables` field from the JSON; do not include empirical tables. "
            "If a figure is included, describe it as a conceptual workflow and cite it as (Fig. 1), not empirical results."
        )

    journal_block = ""
    if chosen_journal:
        journal_block = (
            f"Target journal: {chosen_journal.get('name')} (IF {chosen_journal.get('if_2023', 'n/a')}, "
            f"APC USD {chosen_journal.get('apc_usd', 'n/a')}, hybrid={chosen_journal.get('hybrid')}, "
            f"publisher={chosen_journal.get('publisher')}). "
            "Tailor the tone, length, and emphasis to this journal.\n\n"
        )

    prompt = (
        "Write a detailed IMRaD academic manuscript as a JSON object. "
        "Cite references using Vancouver numbered superscript markers like {1}, {2-3}. "
        "Reference all figures as (Fig. 1), (Fig. 2), etc. and tables as (Table 1). "
        "Never fabricate empirical numbers.\n\n"
        f"Research idea:\n{idea}\n\n"
        + journal_block
        + f"{mode_instruction}\n\n"
        f"Data summary:\n{data_block}\n\n"
        f"References:\n{refs}\n\n"
        "Return ONLY a JSON object with this structure:\n"
        '{\n'
        '  "title": "...",\n'
        '  "abstract": "...",\n'
        '  "sections": {\n'
        '    "introduction": "...",\n'
        '    "methods": "...",\n'
        '    "results": "...",\n'
        '    "discussion": "...",\n'
        '    "conclusion": "..."\n'
        '  },\n'
        '  "figures": [{"id": 1, "caption": "..."}],\n'
        '  "tables": [{"id": 1, "caption": "...", "headers": ["..."], "rows": [["..."]]]\n'
        '}'
    )

    text = client.chat(prompt, temperature=0.6, json_mode=True)
    if not text or text.startswith("[AI"):
        return _normalize_manuscript({"title": "Research protocol", "abstract": "AI client unavailable; protocol not generated."}, references, data_summary)

    try:
        try:
            parsed = _extract_json(text)
        except (json.JSONDecodeError, ValueError) as e:
            # one repair round-trip before giving up: ask the model to re-emit strictly valid JSON
            fixed = client.chat(
                "The following was supposed to be a single valid JSON object but failed to parse "
                f"({e}). Return the SAME content as strictly valid JSON only, escaping newlines and quotes "
                "inside strings; do not change any numbers or wording.\n\n" + text,
                temperature=0.0,
                json_mode=True,
            )
            parsed = _extract_json(fixed)
        if analysis:
            # numbers in tables/figures must come from the analysis output, not the LLM
            parsed["tables"] = [
                {"id": t.get("id", i), "caption": t.get("caption", ""), "headers": t.get("headers", []), "rows": t.get("rows", [])}
                for i, t in enumerate(analysis.get("tables", []), 1)
            ]
            parsed["figures"] = [
                {"id": f.get("id", i), "caption": f.get("caption", "")}
                for i, f in enumerate(analysis.get("figures", []), 1)
            ]
        _ensure_figures_tables_cited(parsed)
        _check_for_placeholders(parsed)
        if not parsed.get("references"):
            parsed["references"] = references
        parsed = renumber_citations_vancouver(parsed)
        return _normalize_manuscript(parsed, references, data_summary)
    except (json.JSONDecodeError, ValueError) as e:
        print(f"[draft] Failed to parse AI JSON ({e}); using fallback.")
        out_dir = getattr(cfg, "output_dir", None)
        if out_dir:
            (Path(out_dir) / "draft_raw_response.txt").write_text(text, encoding="utf-8")
        return _normalize_manuscript({"title": "Research protocol"}, references, data_summary)
