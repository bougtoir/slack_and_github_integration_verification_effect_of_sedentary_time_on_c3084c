"""Figure digitization (tier 2, published data): values come from pixels or from labels the
authors printed; anything that cannot be calibrated or confirmed is rejected, never guessed."""
import io
import json
import tempfile
from pathlib import Path
from unittest import mock

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from paper_sandbox.stages import data_acquisition, figure_digitize as fd


def _chart_png(kind="line"):
    x = np.arange(2007, 2023)
    y = 100 + 3 * (x - 2007)
    fig, ax = plt.subplots(figsize=(6, 4), dpi=100)
    if kind == "line":
        ax.plot(x, y, color="red")
    else:
        ax.bar(x, y * 0.3, color="tab:blue")
    ax.set_xticks([2007, 2012, 2017, 2022])
    ax.set_yticks([0, 50, 100, 150, 200])
    ax.set_ylim(0, 200)
    buf = io.BytesIO()
    fig.savefig(buf, format="png")
    plt.close(fig)
    return buf.getvalue()


_STRUCT = {"chart_type": "line", "n_panels": 1,
           "x_axis": {"tick_labels": [2007, 2012, 2017, 2022]},
           "y_axis": {"tick_labels": [0, 50, 100, 150, 200]},
           "series": [{"name": "red line", "color": "red"}]}


def test_line_chart_values_read_from_pixels():
    r = fd.digitize_image(_chart_png("line"), _STRUCT)
    got = {p["x"]: p["y"] for p in r["rows"]}
    for xv, yv in got.items():
        assert abs(yv - (100 + 3 * (xv - 2007))) < 2.5, (xv, yv)
    assert r["calibration"]["y_tick_values"] == [200.0, 150.0, 100.0, 50.0, 0.0]


def test_bar_chart_values_read_from_pixels():
    st = dict(_STRUCT, chart_type="bar", series=[{"name": "bars", "color": "blue"}])
    r = fd.digitize_image(_chart_png("bar"), st)
    got = {p["x"]: p["y"] for p in r["rows"]}
    assert set(got) == {2007.0, 2012.0, 2017.0, 2022.0}
    for xv, yv in got.items():
        assert abs(yv - 0.3 * (100 + 3 * (xv - 2007))) < 2.5, (xv, yv)


def test_rejects_unsupported_or_uncalibratable_charts():
    png = _chart_png()
    for bad, msg in [
        (dict(_STRUCT, chart_type="scatter"), "chart type"),
        (dict(_STRUCT, n_panels=2), "panel"),
        (dict(_STRUCT, y_axis={"tick_labels": [1, 10, 100], "log_scale": True}), "log"),
        (dict(_STRUCT, y_axis={"tick_labels": [0, 50, 100]}), "calibration failed"),
        (dict(_STRUCT, series=[{"name": "a", "color": "black"}, {"name": "b", "color": "black"}]), "colour"),
        (dict(_STRUCT, series=[{"name": "a", "color": "black"}, {"name": "b", "color": "red"}]), "monochrome"),
    ]:
        try:
            fd.digitize_image(png, bad)
        except ValueError as e:
            assert msg.lower() in str(e).lower(), (msg, e)
        else:
            raise AssertionError(f"accepted {bad}")


def test_match_ticks_keeps_only_equally_spaced_subset():
    px, vals = fd._match_ticks([10.0, 48.0, 125.0, 202.0, 279.0, 356.0, 370.0], [0, 50, 100, 150, 200], "y")
    assert px == [48.0, 125.0, 202.0, 279.0, 356.0]
    try:
        fd._match_ticks([48.0, 125.0, 202.0], [0, 50, 100, 150, 200], "y")
    except ValueError as e:
        assert "calibration failed" in str(e)
    else:
        raise AssertionError


class _Vision:
    def __init__(self, outputs):
        self.outputs = list(outputs)

    def vision(self, prompt, image_bytes, mime="image/png", max_tokens=6000):
        return self.outputs.pop(0)

    def chat(self, *a, **k):
        return json.dumps({"selected": [{"index": 0, "why": "line chart of the outcome"}]})


def test_printed_labels_need_two_identical_reads():
    st = {"x_axis": {"tick_labels": [1992, 2017]}, "y_axis": {"tick_labels": [0, 200000]}}
    a = json.dumps({"points": [{"series": "Total", "x": 1992, "y": "76,600"}, {"series": "Total", "x": 1997, "y": 92400},
                               {"series": "Total", "x": 2002, "y": 117900}]})
    rows, dropped = fd.transcribe_printed_labels(_Vision([a, a]), b"", "image/jpeg", st)
    assert [r["y"] for r in rows] == [76600.0, 92400.0, 117900.0] and dropped == []
    b = a.replace("117900", "117000")
    try:
        fd.transcribe_printed_labels(_Vision([a, b]), b"", "image/jpeg", st)
    except ValueError as e:
        assert "different values" in str(e)
    else:
        raise AssertionError
    out_of_range = a.replace("117900", "9117900")
    try:
        fd.transcribe_printed_labels(_Vision([out_of_range, out_of_range]), b"", "image/jpeg", st)
    except ValueError as e:
        assert "outside" in str(e)
    else:
        raise AssertionError


def test_list_figures_parses_jats():
    xml = ('<article><article-id pub-id-type="doi">10.1/x</article-id><fig id="f1"><label>Fig 1</label>'
           '<caption><p>Incidence by <italic>year</italic>.</p></caption>'
           '<graphic xlink:href="img-g001.jpg"/></fig><fig id="f2"><label>Fig 2</label></fig></article>')
    with mock.patch.object(fd.requests, "get", return_value=mock.Mock(text=xml, raise_for_status=lambda: None)):
        figs, doi = fd.list_figures("PMC1")
    assert doi == "10.1/x" and len(figs) == 1
    assert figs[0]["caption"] == "Incidence by year." and figs[0]["graphic"] == "img-g001.jpg"


def test_digitize_article_writes_provenance_and_logs_failures():
    png = _chart_png()
    good = json.dumps(_STRUCT)
    figs = [{"fig_id": "f1", "label": "Fig 1", "caption": "Incidence by year", "graphic": "g1.png"}]
    with tempfile.TemporaryDirectory() as td, \
            mock.patch.object(fd, "list_figures", return_value=(figs, "10.1/x")), \
            mock.patch.object(fd, "figure_image", return_value=(png, "https://cdn/x.png", "image/png")):
        tables, att = fd.digitize_article(_Vision([good]), "PMC1", {"outcome_variables": ["incidence"]}, td, 3)
        assert att[0]["status"] == "digitized" and len(tables) == 1
        t = tables[0]
        assert t["digitized"] is True and t["provenance"]["doi"] == "10.1/x"
        assert t["provenance"]["image_sha256"] == att[0]["sha256"]
        text = Path(t["csv"]).read_text()
        assert text.startswith("# DIGITIZED from PMC1 Fig 1") and "x,series,y" in text
        assert Path(att[0]["image_file"]).exists()

        bad = json.dumps(dict(_STRUCT, chart_type="other"))
        tables2, att2 = fd.digitize_article(_Vision([bad]), "PMC1", {"outcome_variables": ["incidence"]}, td, 4)
        assert tables2 == [] and att2[0]["status"] == "failed" and "chart type" in att2[0]["error"]


def test_acquire_datasets_uses_digitizer_for_published_data_only():
    calls = []

    def digitizer(pmcid, idx):
        calls.append(pmcid)
        return ([{"label": "figure:Fig 1 (digitized)", "csv": "/x.csv", "rows": 5, "cols": 3,
                  "preview": [], "digitized": True, "provenance": {"pmcid": pmcid}}],
                [{"pmcid": pmcid, "status": "digitized"}])

    cands = [
        {"name": "oa article", "download_url": "https://www.ebi.ac.uk/europepmc/webservices/rest/PMC77/fullTextXML",
         "tier": "published_data"},
        {"name": "gov", "download_url": "https://gov.example/PMC77.html", "tier": "official"},
    ]
    with tempfile.TemporaryDirectory() as td, \
            mock.patch.object(data_acquisition, "_download", return_value=(b"<html><p>no table</p></html>", "text/html", "u")):
        acquired, log = data_acquisition.acquire_datasets(cands, td, figure_digitizer=digitizer)
    assert calls == ["PMC77"]
    assert log[0]["status"] == "acquired" and acquired[0]["tables"][0]["digitized"]
    assert log[1]["status"] == "failed" and "figure_attempts" not in log[1]
    with tempfile.TemporaryDirectory() as td2:
        data_acquisition.write_acquisition_log_md(Path(td2) / "log.md", {"method": "m"}, log, acquired)
        assert "figure(s) digitized (approximate pixel read-out)" in (Path(td2) / "log.md").read_text()


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"{name}: ok")
    print("All tests passed")
