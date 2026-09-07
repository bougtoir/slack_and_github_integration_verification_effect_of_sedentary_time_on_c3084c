import json
import re

from paper_sandbox.ai_client import AIClient


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
        "references": references,
        "data_summary": data_summary,
    }
    return normalized


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

    if data_summary:
        data_block = json.dumps(data_summary, indent=2, ensure_ascii=False)
        mode_instruction = (
            "A real data summary has been supplied. Use ONLY the numbers in the data summary "
            "when writing Results. Do not invent sample sizes, p-values, medians, confidence "
            "intervals, or any other numeric values that are not in the data summary. Cite the "
            "analysis as performed by the sandbox pipeline."
        )
    else:
        data_block = "No data file was supplied."
        mode_instruction = (
            "No data file was supplied. Produce a detailed research PROTOCOL / pre-analysis plan. "
            "Do not invent sample sizes, p-values, medians, regression coefficients, or any "
            "other empirical numbers. Use placeholders such as [to be calculated] for values "
            "that will be derived from data. Clearly state that Results are planned analyses "
            "and that the current draft is a protocol."
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
        return _normalize_manuscript({"title": "Research protocol", "abstract": "[AI unavailable; protocol placeholder]"}, references, data_summary)

    try:
        parsed = _extract_json(text)
        return _normalize_manuscript(parsed, references, data_summary)
    except (json.JSONDecodeError, ValueError) as e:
        print(f"[draft] Failed to parse AI JSON ({e}); using fallback.")
        return _normalize_manuscript({"title": "Research protocol"}, references, data_summary)
