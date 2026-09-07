import io
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from PIL import Image


def _save_tiff_from_png(png_bytes):
    buf = io.BytesIO(png_bytes)
    img = Image.open(buf)
    tiff_buf = io.BytesIO()
    img.save(tiff_buf, format="TIFF")
    tiff_buf.seek(0)
    return tiff_buf.getvalue()


class FigureGenerator:
    def __init__(self, output_dir):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def _save_figure(self, name, caption=""):
        png_path = self.output_dir / f"{name}.png"
        tiff_path = self.output_dir / f"{name}.tiff"
        pptx_path = self.output_dir / f"{name}.pptx"

        plt.tight_layout()
        buf = io.BytesIO()
        plt.savefig(buf, format="png", dpi=300)
        buf.seek(0)
        png_bytes = buf.read()
        png_path.write_bytes(png_bytes)
        tiff_path.write_bytes(_save_tiff_from_png(png_bytes))
        self._make_pptx(pptx_path, caption, png_bytes)
        plt.close()
        return str(png_path), str(tiff_path), str(pptx_path)

    def _make_pptx(self, path, title, png_bytes):
        from pptx import Presentation
        from pptx.util import Inches
        prs = Presentation()
        prs.slide_width = Inches(13.333)
        prs.slide_height = Inches(7.5)
        blank = prs.slide_layouts[6]
        slide = prs.slides.add_slide(blank)
        top = Inches(0.3)
        title_box = slide.shapes.add_textbox(Inches(0.5), top, Inches(12.333), Inches(0.6))
        title_box.text_frame.text = title or "Figure"
        tmp_png = self.output_dir / ".tmp_pptx_image.png"
        tmp_png.write_bytes(png_bytes)
        pic_left = Inches(0.8)
        pic_top = Inches(1.0)
        pic_width = Inches(11.733)
        pic_height = Inches(5.4)
        slide.shapes.add_picture(str(tmp_png), pic_left, pic_top, width=pic_width, height=pic_height)
        caption_box = slide.shapes.add_textbox(Inches(0.5), Inches(6.5), Inches(12.333), Inches(0.8))
        caption_box.text_frame.text = title or ""
        prs.save(path)
        return str(path)

    def from_png(self, src_png, caption, name="figure_1"):
        """Register a PNG produced by the analysis script (copy + TIFF + PPTX)."""
        png_bytes = Path(src_png).read_bytes()
        png_path = self.output_dir / f"{name}.png"
        tiff_path = self.output_dir / f"{name}.tiff"
        pptx_path = self.output_dir / f"{name}.pptx"
        png_path.write_bytes(png_bytes)
        tiff_path.write_bytes(_save_tiff_from_png(png_bytes))
        self._make_pptx(pptx_path, caption, png_bytes)
        return str(png_path), str(tiff_path), str(pptx_path)

    def demo_figure(self, caption, name="figure_1"):
        """Generate a clear placeholder figure when no data is supplied."""
        plt.figure(figsize=(6, 4))
        plt.text(
            0.5,
            0.55,
            "No data supplied.\nNo empirical figure is generated;\ninsert real data after data is provided.",
            ha="center",
            va="center",
            fontsize=12,
        )
        plt.title(caption)
        plt.axis("off")
        return self._save_figure(name, caption)

    def from_data_summary(self, summary, name="figure_1"):
        """Generate a bar plot from group statistics when available."""
        group_stats = summary.get("group_stats")
        numeric_summary = summary.get("numeric_summary")
        caption = "Summary of the supplied dataset."
        if group_stats:
            key = next(iter(group_stats))
            stats = group_stats[key]
            labels = list(stats.keys())
            means = [stats[l].get("mean", 0) for l in labels]
            stds = [stats[l].get("std", 0) for l in labels]
            plt.figure(figsize=(8, 5))
            x = np.arange(len(labels))
            plt.bar(x, means, yerr=stds, capsize=4, color="#4c78a8")
            plt.xticks(x, labels, rotation=45, ha="right")
            plt.ylabel(key)
            caption = f"Mean {key} by group (error bars: SD)."
        elif numeric_summary:
            cols = [c for c in numeric_summary if c != "count"]
            means = [numeric_summary[c].get("mean", 0) for c in cols]
            plt.figure(figsize=(8, 5))
            plt.bar(range(len(cols)), means, color="#4c78a8")
            plt.xticks(range(len(cols)), cols, rotation=45, ha="right")
            caption = "Mean values of numeric variables in the supplied dataset."
        else:
            plt.figure(figsize=(6, 4))
            plt.text(0.5, 0.5, "No plottable summary available.", ha="center", va="center")
            plt.axis("off")
        plt.title(caption)
        return self._save_figure(name, caption)

    def table_docx(self, tables=None):
        """Generate an editable tables docx and optional pptx."""
        from docx import Document
        from pptx import Presentation
        from pptx.util import Inches

        doc = Document()
        doc.add_heading("Tables", level=1)

        prs = Presentation()
        prs.slide_width = Inches(13.333)
        prs.slide_height = Inches(7.5)

        if tables:
            for t in tables:
                table = doc.add_table(rows=1 + len(t.get("rows", [])), cols=len(t.get("headers", [])))
                table.style = "Table Grid"
                hdr = table.rows[0].cells
                for i, h in enumerate(t.get("headers", [])):
                    hdr[i].text = str(h)
                for i, row in enumerate(t.get("rows", []), start=1):
                    cells = table.rows[i].cells
                    for j, val in enumerate(row):
                        cells[j].text = str(val)
                caption = doc.add_paragraph()
                caption.add_run(f"Table {t.get('id', '?')}. {t.get('caption', '')}").italic = True

                # PPTX table slide
                slide = prs.slides.add_slide(prs.slide_layouts[6])
                title_box = slide.shapes.add_textbox(Inches(0.5), Inches(0.3), Inches(12.333), Inches(0.6))
                title_box.text_frame.text = f"Table {t.get('id', '?')}. {t.get('caption', '')}"
                rows = 1 + len(t.get("rows", []))
                cols = max(len(t.get("headers", [])), 1)
                left = Inches(0.8)
                top = Inches(1.0)
                width = Inches(11.733)
                height = Inches(5.4)
                ppt_table = slide.shapes.add_table(rows, cols, left, top, width, height).table
                for i, h in enumerate(t.get("headers", [])):
                    ppt_table.cell(0, i).text = str(h)
                for r_idx, row in enumerate(t.get("rows", []), start=1):
                    for c_idx, val in enumerate(row):
                        ppt_table.cell(r_idx, c_idx).text = str(val)
        else:
            note = doc.add_paragraph()
            note.add_run("No tables were supplied because no data file was provided.").italic = True

            slide = prs.slides.add_slide(prs.slide_layouts[6])
            title_box = slide.shapes.add_textbox(Inches(0.5), Inches(0.3), Inches(12.333), Inches(0.6))
            title_box.text_frame.text = "Tables"
            body_box = slide.shapes.add_textbox(Inches(0.5), Inches(1.5), Inches(12.333), Inches(5.0))
            body_box.text_frame.text = "No tables were supplied because no data file was provided."

        path = self.output_dir.parent / "tables.docx"
        doc.save(path)
        pptx_path = self.output_dir.parent / "tables.pptx"
        prs.save(pptx_path)
        return str(path), str(pptx_path)
