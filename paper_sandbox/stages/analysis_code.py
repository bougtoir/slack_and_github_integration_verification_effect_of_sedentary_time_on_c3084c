"""Generate an analysis script with the LLM and execute it in the sandbox.

The script may read only the acquired CSV files listed in the manifest and
must write `results/results.json`, optional `results/tables/*.csv` and
`results/figures/*.png`. Every number that later appears in the manuscript
must originate from results.json, which is written by the script, not the LLM.
"""
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from paper_sandbox.ai_client import AIClient


_FORBIDDEN = [
    r"\bimport\s+(os|subprocess|socket|shutil|requests|urllib|http|ftplib|ctypes|importlib|pickle)\b",
    r"\bfrom\s+(os|subprocess|socket|shutil|requests|urllib|http|ftplib|ctypes|importlib|pickle)\b",
    r"\b__import__\b", r"\beval\s*\(", r"\bexec\s*\(",
]

_RESULTS_SPEC = (
    "results/results.json must be a JSON object:\n"
    "{\n"
    '  "usable": true,   // false if the files do not contain data that can answer the topic\n'
    '  "unusable_reason": null,   // string explaining why, when usable is false\n'
    '  "datasets_used": [{"csv": "<path>", "description": "..."}],\n'
    '  "sample_description": "plain-language description of what rows/units were analysed",\n'
    '  "findings": [{"label": "...", "value": <number or string>, "unit": "...", "method": "how computed", "n": <int or null>}],\n'
    '  "tables": [{"id": 1, "caption": "...", "headers": ["..."], "rows": [["..."]]}],\n'
    '  "figures": [{"id": 1, "file": "results/figures/figure_1.png", "caption": "..."}],\n'
    '  "limitations": ["..."]\n'
    "}\n"
)


def _manifest_text(acquired):
    parts = []
    for a in acquired:
        for t in a.get("tables", []):
            note = ""
            if t.get("digitized"):
                prov = t.get("provenance") or {}
                note = (
                    f"\n  NOTE: values were extracted from published figure {prov.get('figure_label')} "
                    f"of {prov.get('pmcid')} (doi:{prov.get('doi')}). Method: {prov.get('method')}. "
                    f"Read-out error: {prov.get('readout_error_hint', 'one axis minor division')}. "
                    "Columns: x,series,y (the CSV starts with '#' comment lines). Label these values as "
                    "figure-derived (digitized/transcribed) in every result; never present them as your own measurements."
                )
            parts.append(
                f"- CSV: {t['csv']}\n  dataset: {a.get('name')} ({a.get('publisher')}); source URL: {a.get('download_url')}\n"
                f"  shape: {t['rows']} rows x {t['cols']} cols\n  first rows: {json.dumps(t['preview'][:6], ensure_ascii=False)[:1500]}{note}"
            )
    return "\n".join(parts)


def _static_guard(code):
    for pat in _FORBIDDEN:
        if re.search(pat, code):
            raise ValueError(f"generated script uses a forbidden construct: {pat}")


def _extract_code(text):
    m = re.search(r"```(?:python)?\s*\n(.*?)```", text, re.DOTALL)
    code = m.group(1) if m else text
    # drop any stray fence lines the model left behind
    code = "\n".join(l for l in code.splitlines() if not l.strip().startswith("```"))
    return code.strip()


def _run_script(script_path, workdir, timeout=300):
    env = {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONPATH": "",
        "MPLBACKEND": "Agg",
        "HOME": os.environ.get("HOME", str(workdir)),
        "MPLCONFIGDIR": str(workdir / ".mpl"),
        "PAPER_SANDBOX_NO_NETWORK": "1",
    }
    repo_root = Path(__file__).resolve().parents[2]
    workdir = Path(workdir).resolve()
    (workdir / ".mpl").mkdir(exist_ok=True)
    if shutil.which("docker") and workdir.is_relative_to(repo_root):
        try:
            check = subprocess.run(["docker", "compose", "ps", "--services", "--filter", "status=running"],
                                   cwd=str(repo_root), capture_output=True, text=True, timeout=20)
        except (subprocess.SubprocessError, OSError):
            check = None
        if check and "sandbox" in check.stdout:
            # the compose file mounts the repo root at /app
            c_workdir = Path("/app") / workdir.relative_to(repo_root)
            c_script = Path("/app") / Path(script_path).resolve().relative_to(repo_root)
            cmd = ["docker", "compose", "exec", "-T", "--workdir", str(c_workdir), "-e", "MPLBACKEND=Agg",
                   "sandbox", "python", "-E", "-B", str(c_script)]
            return subprocess.run(cmd, cwd=str(repo_root), capture_output=True, text=True, timeout=timeout)
    # -E ignores PYTHON* env vars, -B avoids .pyc; user site-packages remain visible
    return subprocess.run([sys.executable, "-E", "-B", str(script_path)], cwd=str(workdir), env=env,
                          capture_output=True, text=True, timeout=timeout)


class UnusableData(Exception):
    """The acquired files do not contain data that can answer the question (not a code bug)."""


def _validate_results(results_dir):
    rpath = results_dir / "results.json"
    if not rpath.exists():
        raise ValueError("script did not write results/results.json")
    results = json.loads(rpath.read_text(encoding="utf-8"))
    if results.get("usable") is False:
        raise UnusableData(results.get("unusable_reason") or "script reported the data as unusable")
    findings = results.get("findings")
    if not isinstance(findings, list) or not findings:
        raise ValueError("results.json has no findings")
    numeric = [f for f in findings if isinstance(f.get("value"), (int, float)) and not isinstance(f.get("value"), bool)]
    if not numeric:
        raise UnusableData("no finding has a numeric value computed from the data")
    for f in results.get("figures", []):
        p = results_dir.parent / f.get("file", "")
        if not p.exists():
            raise ValueError(f"figure file listed in results.json does not exist: {f.get('file')}")
    return results


def run_generated_analysis(cfg, topic, idea_text, acquired, output_dir, max_attempts=3, client=None):
    """Returns (results dict or None, log dict)."""
    client = client or AIClient(cfg.deepseek_api_key, cfg.deepseek_base_url, cfg.deepseek_model)
    output_dir = Path(output_dir)
    results_dir = output_dir / "results"
    (results_dir / "tables").mkdir(parents=True, exist_ok=True)
    (results_dir / "figures").mkdir(parents=True, exist_ok=True)
    script_path = output_dir / "analysis.py"

    manifest = _manifest_text(acquired)
    base_prompt = (
        "You are a biostatistician writing a REPRODUCIBLE Python analysis script.\n"
        f"Research topic:\n{topic}\n\nContext:\n{idea_text[:2500]}\n\n"
        "Available data files (the ONLY files you may read; use these exact paths):\n"
        f"{manifest}\n\n"
        "Rules:\n"
        "- Use only pandas, numpy, matplotlib, scipy (if installed; guard with try/except), json, math, pathlib, re.\n"
        "- Never import os, subprocess, requests, urllib, socket, shutil. No network. Do not hard-code any result numbers.\n"
        "- Parsed CSV files are RAW grids with NO header row (read with pd.read_csv(path, header=None, dtype=str)). "
        "Official statistics have multi-row headers, merged cells, duplicated/empty labels and footnotes: locate header "
        "rows programmatically, address columns by position (df.iloc[:, i]) rather than by name, never rely on unique "
        "column names, coerce numerics with pd.to_numeric(errors='coerce') on a Series, and drop footnotes. "
        "If a file is unusable, skip it and say so in limitations.\n"
        "- If NONE of the files contain the quantities the topic needs (e.g. only metadata, variable lists, "
        "or unrelated tables), do NOT improvise: write results.json with \"usable\": false and an "
        "\"unusable_reason\", and exit 0. Never fabricate or assume numbers.\n"
        "- Compute analyses that address the research topic (e.g. trends, rates, group comparisons, regressions) "
        "with uncertainty where possible. Every finding must be computed from the data.\n"
        f"- OUTPUT LOCATIONS (use these EXACT absolute paths; do not derive paths from the input files): "
        f"results JSON -> {results_dir / 'results.json'}; figures -> {results_dir / 'figures'}/figure_N.png (dpi=300); "
        f"tables -> {results_dir / 'tables'}/*.csv. In results.json, refer to figures as "
        "results/figures/figure_N.png (relative).\n"
        f"- {_RESULTS_SPEC}"
        "- Print a short summary at the end.\n"
        "Return ONLY the Python code in a single ```python block."
    )

    log = {"attempts": []}
    prompt = base_prompt
    for attempt in range(1, max_attempts + 1):
        text = client.chat(prompt, temperature=0.2)
        if not text or text.startswith("[AI"):
            log["attempts"].append({"attempt": attempt, "error": "LLM unavailable"})
            break
        code = _extract_code(text)
        rec = {"attempt": attempt}
        try:
            _static_guard(code)
            script_path.write_text(code, encoding="utf-8")
            proc = _run_script(script_path, output_dir)
            rec["returncode"] = proc.returncode
            rec["stdout_tail"] = proc.stdout[-1500:]
            rec["stderr_tail"] = proc.stderr[-1500:]
            if proc.returncode != 0:
                raise RuntimeError(proc.stderr[-2000:] or "non-zero exit")
            results = _validate_results(results_dir)
            results["script"] = str(script_path)
            results["analysis_attempts"] = attempt
            rec["status"] = "ok"
            log["attempts"].append(rec)
            return results, log
        except subprocess.TimeoutExpired:
            rec["error"] = "script timed out"
        except UnusableData as e:
            rec["error"] = f"UnusableData: {e}"
            rec["status"] = "data_unusable"
            log["attempts"].append(rec)
            log["unusable_reason"] = str(e)
            return None, log
        except Exception as e:
            rec["error"] = f"{type(e).__name__}: {str(e)[:1500]}"
        log["attempts"].append(rec)
        prompt = (
            base_prompt
            + "\n\nYour previous script failed. Fix it. Error:\n"
            + rec["error"]
            + "\n\nPrevious script:\n```python\n" + code[:6000] + "\n```"
        )
    return None, log
