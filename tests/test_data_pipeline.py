"""Tests for the data discovery / acquisition / generated-analysis stages.

These stages must never turn a missing or unusable dataset into empirical results.
"""
import io
import json
import tempfile
from pathlib import Path
from unittest import mock

import pandas as pd

from paper_sandbox.stages import analysis_code, data_acquisition, data_discovery


class _Resp:
    def __init__(self, content, ctype="application/octet-stream", url="https://example.org/x"):
        self.content = content
        self.headers = {"Content-Type": ctype}
        self.url = url

    def raise_for_status(self):
        pass

    def iter_content(self, chunk_size=1):
        yield self.content

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _xlsx_bytes(df):
    buf = io.BytesIO()
    df.to_excel(buf, index=False, header=False)
    return buf.getvalue()


def test_machine_readable_urls():
    pmc = data_acquisition.machine_readable_urls("https://pmc.ncbi.nlm.nih.gov/articles/PMC7872333/")
    assert pmc[0] == "https://www.ebi.ac.uk/europepmc/webservices/rest/PMC7872333/fullTextXML"
    assert pmc[-1].endswith("PMC7872333/")
    estat = data_acquisition.machine_readable_urls("https://www.e-stat.go.jp/en/stat-search/files?stat_infid=000040045487")
    assert "file-download?statInfId=000040045487&fileKind=1" in estat[0]
    assert "fileKind=0" in estat[1]
    assert data_acquisition.machine_readable_urls("https://x.org/a.csv") == ["https://x.org/a.csv"]


def test_sniff_and_read_octet_stream_xlsx_and_cp932_csv():
    df = pd.DataFrame([["age", "n"], [65, 10], [70, 20], [75, 30]])
    frames = data_acquisition._read_tabular(_xlsx_bytes(df), "application/octet-stream", "https://x/file-download?statInfId=1")
    assert frames and data_acquisition._usable(frames[0][1])

    ragged = "令和５年,患者調査\n年齢,男,女\n65,10,20\n70,11,21\n75,12,22\n注) 脚注\n".encode("cp932")
    frames = data_acquisition._read_tabular(ragged, "text/csv", "https://x/file-download?statInfId=2")
    df2 = frames[0][1]
    assert df2.shape[0] == 6 and data_acquisition._usable(df2)
    assert "令和５年" in df2.iloc[0, 0]


def test_usable_rejects_metadata_only_tables():
    assert not data_acquisition._usable(pd.DataFrame([["a", "b"], ["c", "d"], ["e", "f"]]))
    assert not data_acquisition._usable(pd.DataFrame([[1, 2]]))
    assert data_acquisition._usable(pd.DataFrame({"y": [2000, 2001, 2002], "v": [1.0, 2.0, 3.0]}))


def test_looks_blocked_captcha():
    assert data_acquisition._looks_blocked(b"<html><body>Please verify you are human. reCAPTCHA</body></html>", "text/html")
    assert not data_acquisition._looks_blocked(b"<html><table><tr><td>1</td></tr></table></html>", "text/html")


def test_acquire_records_every_attempt_with_checksum():
    good = _xlsx_bytes(pd.DataFrame([["year", "cases"], [2000, 10], [2001, 12], [2002, 15]]))

    def fake_get(url, **kw):
        if "good" in url:
            return _Resp(good, url=url)
        if "junk" in url:
            return _Resp(b"just some prose without a table", "text/plain", url=url)
        raise ConnectionError("unreachable")

    candidates = [
        {"name": "Down", "publisher": "P", "download_url": "https://x/down.csv"},
        {"name": "Junk", "publisher": "P", "download_url": "https://x/junk.txt"},
        {"name": "Good", "publisher": "P", "download_url": "https://x/good"},
    ]
    with tempfile.TemporaryDirectory() as td, mock.patch.object(data_acquisition.requests, "get", side_effect=fake_get):
        acquired, log = data_acquisition.acquire_datasets(candidates, td)
        assert [e["status"] for e in log] == ["failed", "failed", "acquired"]
        assert "ConnectionError" in log[0]["error"]
        assert "no usable table" in log[1]["error"]
        assert len(acquired) == 1
        import hashlib
        assert acquired[0]["sha256"] == hashlib.sha256(good).hexdigest()
        assert Path(acquired[0]["raw_file"]).read_bytes() == good
        assert Path(acquired[0]["tables"][0]["csv"]).exists()
        prov = json.loads((Path(td) / "provenance.json").read_text())
        assert len(prov["attempts"]) == 3

        md = Path(td) / "log.md"
        data_acquisition.write_acquisition_log_md(md, {"method": "perplexity", "n_candidates": 3}, log, acquired)
        text = md.read_text()
        assert "failed" in text and "acquired" in text


def test_discovery_reports_failure_honestly():
    cfg = mock.Mock(perplexity_api_key="", deepseek_api_key="")
    with mock.patch.object(data_discovery, "_perplexity_discover", return_value=([], "Perplexity: 429")), \
         mock.patch.object(data_discovery, "_llm_memory_discover", return_value=([], "DeepSeek unavailable")):
        cands, log = data_discovery.discover_datasets(cfg, "hip fracture Japan")
    assert cands == []
    assert log["n_candidates"] == 0
    assert any("429" in str(e) for e in log.get("errors", []))


def test_parse_datasets_marks_candidates_unverified():
    text = json.dumps({"datasets": [{"name": "A", "publisher": "B", "download_url": "https://x/a.csv"}]})
    cands = data_discovery._parse_datasets(text)
    assert cands and cands[0]["download_url"] == "https://x/a.csv"
    assert not cands[0].get("verified")


def test_static_guard_and_code_extraction():
    code = analysis_code._extract_code("here\n```python\nimport pandas as pd\nprint(1)\n```\n")
    assert code == "import pandas as pd\nprint(1)"
    for bad in ("import os", "import subprocess", "eval('1')", "__import__('os')", "import requests"):
        try:
            analysis_code._static_guard(bad)
        except ValueError:
            continue
        raise AssertionError(f"guard did not reject {bad!r}")


class _FakeClient:
    def __init__(self, scripts):
        self.scripts = list(scripts)
        self.prompts = []

    def chat(self, prompt, **kw):
        self.prompts.append(prompt)
        return "```python\n" + self.scripts.pop(0) + "\n```"


def _acquired(td):
    csv = Path(td) / "d.csv"
    pd.DataFrame({"year": [2000, 2001, 2002], "cases": [10, 12, 15]}).to_csv(csv, index=False)
    return [{"name": "D", "publisher": "P", "download_url": "https://x/d.csv",
             "tables": [{"csv": str(csv), "rows": 3, "cols": 2, "preview": [["2000", "10"]]}]}]


def _run(td, scripts, **kw):
    client = _FakeClient(scripts)
    cfg = mock.Mock(deepseek_api_key="k")
    results, log = analysis_code.run_generated_analysis(
        cfg, "topic", "idea", _acquired(td), Path(td), client=client, **kw)
    return results, log, client


def test_generated_analysis_success_uses_results_json():
    script = (
        "import json, pathlib\n"
        "import pandas as pd\n"
        "df = pd.read_csv(r'CSVPATH')\n"
        "slope = float(df['cases'].diff().mean())\n"
        "pathlib.Path('results').mkdir(exist_ok=True)\n"
        "json.dump({'usable': True, 'sample_description': '3 years', 'findings': [{'name': 'mean annual change', 'value': slope}],"
        " 'tables': [], 'figures': [], 'limitations': []}, open('results/results.json', 'w'))\n"
    )
    with tempfile.TemporaryDirectory() as td:
        results, log, _ = _run(td, [script.replace("CSVPATH", _acquired(td)[0]["tables"][0]["csv"])])
        assert results is not None
        assert results["findings"][0]["value"] == 2.5
        assert log["attempts"][0]["status"] == "ok"


def test_generated_analysis_missing_results_then_nonzero_exit_returns_none():
    with tempfile.TemporaryDirectory() as td:
        results, log, client = _run(td, ["print('no results written')", "raise SystemExit(3)"], max_attempts=2)
        assert results is None
        assert "results/results.json" in log["attempts"][0]["error"]
        assert log["attempts"][1]["returncode"] == 3
        assert "previous script failed" in client.prompts[1].lower()


def test_generated_analysis_timeout_returns_none():
    with tempfile.TemporaryDirectory() as td, mock.patch.object(analysis_code, "_run_script",
                                                                side_effect=analysis_code.subprocess.TimeoutExpired("x", 1)):
        results, log, _ = _run(td, ["print(1)"], max_attempts=1)
        assert results is None
        assert log["attempts"][0]["error"] == "script timed out"


def test_generated_analysis_explicit_unusable_is_not_retried_or_fabricated():
    script = (
        "import json, pathlib\n"
        "pathlib.Path('results').mkdir(exist_ok=True)\n"
        "json.dump({'usable': False, 'unusable_reason': 'only denominators present', 'findings': []},"
        " open('results/results.json', 'w'))\n"
    )
    with tempfile.TemporaryDirectory() as td:
        results, log, client = _run(td, [script, "print('should not run')"], max_attempts=3)
        assert results is None
        assert log["unusable_reason"] == "only denominators present"
        assert len(client.prompts) == 1


def test_non_numeric_findings_rejected():
    script = (
        "import json, pathlib\n"
        "pathlib.Path('results').mkdir(exist_ok=True)\n"
        "json.dump({'usable': True, 'findings': [{'name': 'x', 'value': 'No numeric data available'}]},"
        " open('results/results.json', 'w'))\n"
    )
    with tempfile.TemporaryDirectory() as td:
        results, log, _ = _run(td, [script], max_attempts=1)
        assert results is None
        assert "numeric" in log["unusable_reason"]


def test_llm_unavailable_stops_without_results():
    class Down:
        def chat(self, prompt, **kw):
            return "[AI request failed (x)]"

    with tempfile.TemporaryDirectory() as td:
        results, log = analysis_code.run_generated_analysis(
            mock.Mock(deepseek_api_key="k"), "t", "i", _acquired(td), Path(td), client=Down())
        assert results is None
        assert log["attempts"][0]["error"] == "LLM unavailable"


def test_expand_sections_rejects_short_or_placeholder_output():
    from paper_sandbox.stages import draft as draft_stage

    class C:
        def __init__(self, reply):
            self.reply = reply

        def chat(self, prompt, **kw):
            return self.reply

    parsed = {"title": "T", "sections": {"methods": "Original methods text with detail."}, "figures": [], "tables": []}
    long_text = " ".join(["word"] * 1000)
    out = draft_stage.expand_sections(C(json.dumps({"text": long_text})), dict(parsed, sections=dict(parsed["sections"])), "idea", "{}", "[1] r")
    assert out["sections"]["methods"] == long_text
    out = draft_stage.expand_sections(C(json.dumps({"text": "short"})), dict(parsed, sections=dict(parsed["sections"])), "idea", "{}", "[1] r")
    assert out["sections"]["methods"] == "Original methods text with detail."
    bad = " ".join(["word"] * 1000) + " value to be determined"
    out = draft_stage.expand_sections(C(json.dumps({"text": bad})), dict(parsed, sections=dict(parsed["sections"])), "idea", "{}", "[1] r")
    assert out["sections"]["methods"] == "Original methods text with detail."
    out = draft_stage.expand_sections(C("[AI request failed]"), dict(parsed, sections=dict(parsed["sections"])), "idea", "{}", "[1] r")
    assert out["sections"]["methods"] == "Original methods text with detail."


def test_strip_unsupported_access_dates():
    from paper_sandbox.stages.draft import strip_unsupported_access_dates
    p = {"sections": {"methods": "A (accessed on 2023-10-05, no checksum). B (accessed 2026-09-07). Rate 5 per 100."}}
    out = strip_unsupported_access_dates(p, {"attempted_sources": [{"attempted_at_utc": "2026-09-07T13:00:00+00:00"}]})
    assert "2023-10-05" not in out["sections"]["methods"]
    assert "(accessed 2026-09-07)" in out["sections"]["methods"]
    assert "Rate 5 per 100." in out["sections"]["methods"]


def test_plan_word_budget_clamps_and_falls_back():
    from paper_sandbox.stages import draft as d

    class C:
        def __init__(self, out):
            self.out = out

        def chat(self, *a, **k):
            return self.out

    parsed = {"title": "t", "abstract": "a", "sections": {}}
    plan, _ = d.plan_word_budget(C(json.dumps({"introduction": 100, "methods": 2500, "results": 100, "discussion": 300, "rationale": "sim"})), parsed, "i", "{}")
    assert abs(sum(plan.values()) - d.BODY_WORDS) <= 4
    assert plan["methods"] <= d.BODY_WORDS * 0.45 + 1 and plan["introduction"] >= d.BODY_WORDS * 0.10 - 1
    plan2, why = d.plan_word_budget(C("[AI request failed]"), parsed, "i", "{}")
    assert plan2 == d.default_word_plan() and "default" in why
    plan3, _ = d.plan_word_budget(C("{not json"), parsed, "i", "{}")
    assert plan3 == d.default_word_plan()


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"{name}: ok")
    print("All tests passed")
