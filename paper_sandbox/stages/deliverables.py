import json
import zipfile
from pathlib import Path

from paper_sandbox.docx_writer import ManuscriptWriter
from paper_sandbox.figure_generator import FigureGenerator
from paper_sandbox.stages import checks


def build_deliverables(cfg, draft, chosen_journal, figures, tables_path, check_report, review_report, data_summary=None):
    out = cfg.output_dir
    out.mkdir(parents=True, exist_ok=True)
    writer = ManuscriptWriter(cfg)

    manuscript_path = writer.write_manuscript(draft, out, figure_paths=figures, table_path=tables_path)
    cover_path = writer.write_cover_letter(draft, chosen_journal, out)
    review_path = writer.write_report("Reviewer Review", review_report, out)
    check_path = writer.write_report("Validation Report", check_report, out)

    checklist_md = checks.pre_submission_checklist(draft, chosen_journal=chosen_journal, data_summary=data_summary, language=cfg.language)
    checklist_md_path = out / "pre_submission_checklist.md"
    checklist_md_path.write_text(checklist_md, encoding="utf-8")
    checklist_path = writer.write_report("Pre-Submission Checklist", checklist_md, out, filename="pre_submission_checklist.docx")

    packaged = {
        "manuscript": str(manuscript_path),
        "cover_letter": str(cover_path),
        "review_report": str(review_path),
        "checks_report": str(check_path),
        "pre_submission_checklist": str(checklist_path),
        "pre_submission_checklist_md": str(checklist_md_path),
        "figures": [str(p) for p in figures],
        "tables": str(tables_path) if tables_path else None,
    }
    provenance_items = [
        out / "data_acquisition_log.md", out / "dataset_candidates.json", out / "analysis.py",
        out / "analysis_log.json", out / "data_summary.json", out / "data_error.txt",
        out / "references.json",
    ]
    provenance_dirs = [out / "data", out / "results"]
    packaged["provenance"] = [str(p) for p in provenance_items if p.exists()] + [str(d) for d in provenance_dirs if d.exists()]
    with open(out / "manifest.json", "w") as f:
        json.dump(packaged, f, indent=2, ensure_ascii=False)

    zip_path = out / "package.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(manuscript_path, manuscript_path.name)
        zf.write(cover_path, cover_path.name)
        zf.write(review_path, review_path.name)
        zf.write(check_path, check_path.name)
        zf.write(checklist_path, checklist_path.name)
        zf.write(checklist_md_path, checklist_md_path.name)
        for p in figures:
            zf.write(p, f"figures/{Path(p).name}")
        if tables_path:
            zf.write(tables_path, f"tables/{Path(tables_path).name}")
        for p in provenance_items:
            if p.exists():
                zf.write(p, f"provenance/{p.name}")
        for d in provenance_dirs:
            if d.exists():
                for p in d.rglob("*"):
                    if p.is_file():
                        zf.write(p, f"provenance/{p.relative_to(out)}")

    return packaged, zip_path
