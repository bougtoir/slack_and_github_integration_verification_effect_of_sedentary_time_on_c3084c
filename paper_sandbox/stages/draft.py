import json
import re

from paper_sandbox.ai_client import AIClient
from paper_sandbox.stages.checks import contains_placeholder


def _repair_json(s):
    # Remove single-line C++/JavaScript-style comments (not valid in JSON)
    s = re.sub(r"//[^\n]*", "", s)
    # Remove trailing commas before } or ]
    s = re.sub(r",(\s*[}\]])", r"\1", s)
    return s


def _extract_json(text):
    text = text.strip()
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    if m:
        return json.loads(_repair_json(m.group(1)))
    m = re.search(r"(\{.*\})", text, re.DOTALL)
    if m:
        return json.loads(_repair_json(m.group(1)))
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

    if data_summary and "error" not in data_summary:
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
        data_block = f"Data file was supplied but analysis failed: {data_summary['error']}"
        mode_instruction = (
            "A data file was supplied but could not be analyzed. Do not invent sample sizes, "
            "p-values, medians, regression coefficients, or any other empirical numbers. "
            "Do not use placeholders such as [to be calculated] or [TBD]. Clearly state in Methods "
            "that data access or analysis failed and describe the planned analysis once data are available. "
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

    text = client.chat(prompt, temperature=0.6)
    if not text or text.startswith("[AI"):
        return _normalize_manuscript({"title": "Research protocol", "abstract": "AI client unavailable; protocol not generated."}, references, data_summary)

    try:
        parsed = _extract_json(text)
        _check_for_placeholders(parsed)
        if not parsed.get("references"):
            parsed["references"] = references
        parsed = renumber_citations_vancouver(parsed)
        return _normalize_manuscript(parsed, references, data_summary)
    except (json.JSONDecodeError, ValueError) as e:
        print(f"[draft] Failed to parse AI JSON ({e}); using fallback.")
        return _normalize_manuscript({"title": "Research protocol"}, references, data_summary)
