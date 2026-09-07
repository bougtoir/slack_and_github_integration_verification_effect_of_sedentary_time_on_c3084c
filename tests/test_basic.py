from paper_sandbox.config import Config
from paper_sandbox.docx_writer import ManuscriptWriter
from paper_sandbox.figure_generator import FigureGenerator
from paper_sandbox.journal_db import JournalDB
from paper_sandbox.stages.checks import run_all_checks
from pathlib import Path
import tempfile


def test_checks():
    draft = {
        "sections": {
            "introduction": "This is important.{1}",
            "methods": "Simulated data used.",
            "results": "Outcome shown in Fig. 1.",
            "discussion": "Results are exploratory.{2}",
        },
        "figures": [{"id": 1, "caption": "Simulated outcome."}],
        "references": [{"id": 1, "title": "A"}, {"id": 2, "title": "B"}],
    }
    results = run_all_checks(draft, language="en")
    assert results["fabrication"] == []
    assert results["formatting"] == []
    assert results["revision"] == []


def test_journal_db():
    db = JournalDB()
    ranked = db.rank("health policy")
    assert ranked[0]["topic_match"]


def test_docx_writer():
    cfg = Config()
    with tempfile.TemporaryDirectory() as td:
        writer = ManuscriptWriter(cfg)
        doc = writer.write_manuscript({
            "title": "Test",
            "abstract": "Abstract{1}",
            "authors": ["A"],
            "sections": {"introduction": "Intro{1}"},
            "references": [{"id": 1, "title": "Ref", "year": 2024, "doi": ""}],
        }, td)
        assert Path(doc).exists()


def test_figure_generator():
    with tempfile.TemporaryDirectory() as td:
        fg = FigureGenerator(td)
        png, tiff, pptx = fg.demo_figure("Test figure")
        assert Path(png).exists()
        assert Path(tiff).exists()
        assert Path(pptx).exists()


if __name__ == "__main__":
    test_checks()
    test_journal_db()
    test_docx_writer()
    test_figure_generator()
    print("All tests passed")
