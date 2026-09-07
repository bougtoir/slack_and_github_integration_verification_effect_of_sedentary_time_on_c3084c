import re
from pathlib import Path

from docx import Document
from docx.shared import Pt, Inches
from docx.enum.text import WD_ALIGN_PARAGRAPH


def add_superscript_runs(paragraph, text):
    """Parse {1-3} markers and add Word font superscript runs."""
    parts = re.split(r'(\{[^}]+\})', text)
    for part in parts:
        run = paragraph.add_run()
        if part.startswith("{") and part.endswith("}"):
            run.text = part[1:-1]
            run.font.superscript = True
        else:
            run.text = part


class ManuscriptWriter:
    def __init__(self, cfg):
        self.cfg = cfg

    def write_manuscript(self, data, output_dir, figure_paths=None, table_path=None, filename="manuscript.docx"):
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        doc = Document()

        # Title
        title = doc.add_paragraph()
        title.alignment = WD_ALIGN_PARAGRAPH.CENTER
        title_run = title.add_run(data.get("title", "Untitled"))
        title_run.bold = True
        title_run.font.size = Pt(16)

        # Authors
        authors = doc.add_paragraph()
        authors.alignment = WD_ALIGN_PARAGRAPH.CENTER
        authors.add_run(", ".join(data.get("authors", ["Sandbox Author"])))

        # Abstract
        doc.add_heading("Abstract", level=1)
        add_superscript_runs(doc.add_paragraph(), data.get("abstract", ""))

        figure_map = {}
        for fp in (figure_paths or []):
            p = Path(fp)
            if p.suffix in [".png", ".tiff"]:
                figure_map[p.stem] = str(p)

        tables = data.get("tables", [])
        figures = data.get("figures", [])

        # Sections
        for section in ["Introduction", "Methods", "Results", "Discussion", "Conclusion"]:
            doc.add_heading(section, level=1)
            text = data.get("sections", {}).get(section.lower(), "")
            add_superscript_runs(doc.add_paragraph(), text)

            # Insert figures/tables after first mention in this section
            for fig in figures:
                if f"Fig. {fig['id']}" in text or f"Figure {fig['id']}" in text:
                    img = figure_map.get(f"figure_{fig['id']}")
                    if img and self.cfg.figure_embedded:
                        doc.add_picture(img, width=Inches(5.5))
                    caption = doc.add_paragraph()
                    caption.add_run(f"Fig. {fig['id']}. {fig.get('caption', '')}").italic = True
                    caption.paragraph_format.space_before = Pt(12)

            for table in tables:
                if f"Table {table['id']}" in text:
                    self._add_table(doc, table)
                    caption = doc.add_paragraph()
                    caption.add_run(f"Table {table['id']}. {table.get('caption', '')}").italic = True
                    caption.paragraph_format.space_before = Pt(12)

        # If no inline embedding, append figures at end
        if not self.cfg.figure_embedded:
            doc.add_page_break()
            doc.add_heading("Figures", level=1)
            for fig in figures:
                img = figure_map.get(f"figure_{fig['id']}")
                if img:
                    doc.add_picture(img, width=Inches(5.5))
                caption = doc.add_paragraph()
                caption.add_run(f"Fig. {fig['id']}. {fig.get('caption', '')}").italic = True
                caption.paragraph_format.space_before = Pt(12)

        # References
        doc.add_heading("References", level=1)
        for ref in data.get("references", []):
            p = doc.add_paragraph(style="List Number")
            authors = ", ".join(str(a) for a in ref.get("authors", ["Unknown"]))
            year = ref.get("year") or "n.d."
            doi = ref.get("doi", "")
            journal = ref.get("journal", "")
            line = f"{authors}. {ref.get('title', 'Untitled')}. {journal} {year}."
            if doi:
                line += f" doi:{doi}"
            add_superscript_runs(p, line)

        path = out / filename
        doc.save(path)
        return path

    def _add_table(self, doc, table_data):
        rows = 1 + len(table_data.get("rows", []))
        cols = max(len(table_data.get("headers", [])), 1)
        table = doc.add_table(rows=rows, cols=cols)
        table.style = "Table Grid"
        hdr = table.rows[0].cells
        for i, h in enumerate(table_data.get("headers", [])):
            hdr[i].text = str(h)
        for i, row in enumerate(table_data.get("rows", []), start=1):
            cells = table.rows[i].cells
            for j, val in enumerate(row):
                cells[j].text = str(val)

    def write_cover_letter(self, data, journal, output_dir):
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        doc = Document()

        doc.add_paragraph(data.get("date", "2026-01-01"))
        doc.add_paragraph("Editorial Office")
        doc.add_paragraph(journal.get("name", "Target Journal"))

        body = doc.add_paragraph()
        body.add_run("Dear Editor,").bold = True
        body = doc.add_paragraph(
            f"We wish to submit our manuscript, \"{data.get('title', 'Manuscript')}\", "
            f"for consideration for publication in {journal.get('name', 'your journal')}. "
            f"The work addresses {data.get('topic', 'the stated topic')}."
        )
        doc.add_paragraph(
            "We confirm that this work is original and has not been published elsewhere."
        )
        doc.add_paragraph("Sincerely,")
        doc.add_paragraph(", ".join(data.get("authors", ["Corresponding Author"])))

        path = out / "cover_letter.docx"
        doc.save(path)
        return path

    def write_report(self, name, content, output_dir, filename=None):
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        doc = Document()
        doc.add_heading(name, level=1)
        for line in content.splitlines():
            add_superscript_runs(doc.add_paragraph(), line)
        docx_name = filename or f"{name.replace(' ', '_').lower()}.docx"
        path = out / docx_name
        doc.save(path)
        return path
