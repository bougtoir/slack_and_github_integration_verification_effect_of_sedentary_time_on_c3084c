"""Digitize quantitative figures of open-access articles (tier 2: published data).

Pipeline per article (PMCID):
  JATS XML -> <fig> list (label, caption, graphic)   -> text LLM picks figures whose
  caption matches the plan's data requirements        -> image downloaded (sha256 kept)
  -> vision LLM reads ONLY chart structure (type, tick labels, series colours)
  -> axes/ticks are detected from the pixels and MUST agree with the labels read
  -> curve/bar values are read from the coloured pixels (never from the LLM)
  -> CSV (x, series, y) with provenance header.

Values that cannot pass the calibration check are not emitted. Digitized values are
always flagged as digitized (approximate read-out), never as the authors' exact numbers.
"""
import hashlib
import html
import io
import json
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import requests
from PIL import Image

_HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"}

_NAMED_RGB = {
    "red": (220, 40, 40), "salmon": (240, 128, 114), "pink": (240, 130, 180), "maroon": (128, 0, 32),
    "orange": (245, 140, 30), "yellow": (235, 210, 40), "gold": (220, 180, 40),
    "green": (40, 160, 60), "teal": (30, 150, 150), "cyan": (40, 190, 220),
    "blue": (40, 90, 200), "navy": (20, 30, 110), "purple": (130, 60, 170), "violet": (140, 80, 200),
    "brown": (140, 80, 40), "black": (20, 20, 20), "dark": (40, 40, 40), "grey": (128, 128, 128),
    "gray": (128, 128, 128), "white": (255, 255, 255),
}


def _get(url, timeout=30):
    """GET url -> (status, content_type, bytes). Falls back to curl when the python client
    is served a bot-challenge page (pmc.ncbi.nlm.nih.gov does this to `requests`)."""
    try:
        r = requests.get(url, headers=_HEADERS, timeout=timeout)
        if not (r.ok and b"recaptcha" in r.content[:2000].lower()):
            return r.status_code, r.headers.get("Content-Type", ""), r.content
    except requests.RequestException:
        pass
    if not shutil.which("curl"):
        return 0, "", b""
    p = subprocess.run(["curl", "-sL", "--max-time", str(timeout), "--max-filesize", str(30_000_000),
                        "-A", _HEADERS["User-Agent"], "-w", "\n%{http_code} %{content_type}", url],
                       capture_output=True, timeout=timeout + 5)
    body, _, tail = p.stdout.rpartition(b"\n")
    parts = tail.decode(errors="replace").split(" ", 1)
    try:
        return int(parts[0]), (parts[1] if len(parts) > 1 else ""), body
    except ValueError:
        return 0, "", b""


# --------------------------------------------------------------------------- article side
def list_figures(pmcid, timeout=30):
    """Figures (label, caption, graphic file) from the Europe PMC JATS full text."""
    r = requests.get(f"https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML",
                     headers=_HEADERS, timeout=timeout)
    r.raise_for_status()
    xml = r.text
    figs = []
    for m in re.finditer(r"<fig\b[^>]*?id=\"([^\"]+)\"[^>]*>(.*?)</fig>", xml, re.DOTALL):
        body = m.group(2)
        lab = re.search(r"<label>(.*?)</label>", body, re.DOTALL)
        cap = re.search(r"<caption>(.*?)</caption>", body, re.DOTALL)
        gr = re.search(r"<graphic[^>]*xlink:href=\"([^\"]+)\"", body)
        if not gr:
            continue
        caption = html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", cap.group(1) if cap else ""))).strip()
        figs.append({
            "fig_id": m.group(1),
            "label": html.unescape(re.sub(r"<[^>]+>", "", lab.group(1))).strip() if lab else m.group(1),
            "caption": caption[:1500],
            "graphic": gr.group(1),
        })
    doi = re.search(r"<article-id pub-id-type=\"doi\">([^<]+)</article-id>", xml)
    return figs, (doi.group(1).strip() if doi else None)


def figure_image(pmcid, fig, timeout=30):
    """Download the figure image (PMC figure page -> CDN blob, then Europe PMC bin)."""
    errors = []
    urls = []
    base = fig["graphic"] if "." in fig["graphic"] else fig["graphic"] + ".jpg"
    stem = base.rsplit(".", 1)[0]
    for page_url in (f"https://pmc.ncbi.nlm.nih.gov/articles/{pmcid}/figure/{fig['fig_id']}/",
                     f"https://pmc.ncbi.nlm.nih.gov/articles/{pmcid}/"):
        status, _, body = _get(page_url, timeout)
        if 200 <= status < 300:
            found = re.findall(r"https://cdn\.ncbi\.nlm\.nih\.gov/pmc/blobs/[^\"'\s]+", body.decode(errors="replace"))
            urls += [u for u in found if stem in u] or (found if "figure" in page_url else [])
            if urls:
                break
            errors.append(f"{page_url}: no figure blob URL found")
        else:
            errors.append(f"{page_url}: HTTP {status}")
    urls.append(f"https://europepmc.org/articles/{pmcid}/bin/{base}")
    for u in dict.fromkeys(urls):
        try:
            status, ctype, content = _get(u, timeout)
            if 200 <= status < 300 and ("image" in ctype or content[:3] in (b"\x89PN", b"\xff\xd8\xff")):
                mime = "image/png" if content[:4] == b"\x89PNG" else "image/jpeg"
                return content, u, mime
            errors.append(f"{u}: HTTP {status} {ctype}")
        except (subprocess.SubprocessError, OSError) as e:
            errors.append(f"{u}: {e}")
    raise ValueError("figure image not retrievable: " + "; ".join(errors)[:400])


def _json_from(text):
    if not text:
        return None
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def select_figures(ai, requirements, figures, max_figs=3):
    """Text LLM: which captions describe line/bar charts of the quantities the plan needs."""
    if not figures:
        return []
    req = json.dumps({k: requirements.get(k) for k in
                      ("outcome_variables", "denominator_variables", "exposure_variables", "stratifiers", "period")},
                     ensure_ascii=False)
    caps = "\n".join(f"[{i}] {f['label']}: {f['caption'][:500]}" for i, f in enumerate(figures))
    out = ai.chat(
        "A research plan needs these quantities:\n" + req +
        "\n\nBelow are figure captions of an open-access article. Select figures that are LINE or BAR charts "
        "plotting one of the needed quantities against time, age or another numeric axis, so that values could be "
        "read off the plot. Exclude maps, photographs, flowcharts, forest plots, scatter plots and schematic diagrams. "
        "Return JSON {\"selected\": [{\"index\": int, \"why\": str}]} (at most " + str(max_figs) + ", may be empty).\n\n" + caps,
        temperature=0.0, json_mode=True,
    )
    data = _json_from(out) or {}
    picks = []
    for s in data.get("selected", []) or []:
        try:
            i = int(s.get("index"))
        except (TypeError, ValueError):
            continue
        if 0 <= i < len(figures):
            picks.append((i, str(s.get("why", ""))))
    return picks[:max_figs]


_STRUCTURE_PROMPT = """You are helping to CALIBRATE a pixel digitizer for a scientific chart. Read only what is printed.
Return ONLY a JSON object:
{"chart_type": "line" | "bar" | "km" | "scatter" | "other",
 "n_panels": 1,
 "x_axis": {"label": "", "tick_labels": [numbers exactly as printed, left to right], "categorical_labels": [strings, if the x axis is categorical]},
 "y_axis": {"label": "", "tick_labels": [numbers exactly as printed, bottom to top], "log_scale": false},
 "series": [{"name": "", "color": "one of red, salmon, pink, maroon, orange, yellow, green, teal, cyan, blue, navy, purple, brown, black, grey", "style": "line|bar|points|dashed"}],
 "legend_inside_plot": false,
 "data_labels_printed": false,
 "notes": ""}
Set data_labels_printed to true ONLY if the authors printed the numeric value of every data point next to it.
Do NOT estimate any data values. If the image has several panels, describe the first (top-left) panel and set n_panels."""


def read_chart_structure(ai, image_bytes, mime):
    text = ai.vision(_STRUCTURE_PROMPT, image_bytes, mime=mime)
    data = _json_from(text)
    if not data:
        raise ValueError("vision model returned no chart structure")
    return data


_LABELS_PROMPT = """This chart prints the numeric value of each data point next to it. TRANSCRIBE those printed
value labels exactly as written (no estimation from the plot position; skip any point without a printed value).
Return ONLY JSON: {"points": [{"series": "", "x": <x category or number>, "y": <printed value as number>}]}
Ignore confidence intervals in parentheses; transcribe the point estimate only."""


def _num(v):
    try:
        return float(str(v).replace(",", "").replace("%", "").strip())
    except ValueError:
        return None


def transcribe_printed_labels(ai, image_bytes, mime, structure):
    """Two independent vision transcriptions of the printed value labels. A point is accepted only
    when both reads give the identical value; any value conflict rejects the figure, and points seen
    in one read only are dropped and reported. Values must lie inside the printed axis ranges.
    Returns (rows, dropped)."""
    reads = []
    for _ in range(2):
        data = _json_from(ai.vision(_LABELS_PROMPT, image_bytes, mime=mime)) or {}
        pts = {}
        for p in data.get("points") or []:
            y = _num(p.get("y"))
            x = _num(p.get("x"))
            if y is None:
                continue
            pts[(str(p.get("series", "")).strip().lower(), x if x is not None else str(p.get("x")).strip())] = y
        reads.append(pts)
    a, b = reads
    conflicts = [k for k in a.keys() & b.keys() if a[k] != b[k]]
    if conflicts:
        raise ValueError(f"printed value labels: the two transcriptions give different values for {conflicts[:3]} - rejected")
    agreed = {k: a[k] for k in a.keys() & b.keys()}
    dropped = sorted(str(k) for k in a.keys() ^ b.keys())
    union = len(a.keys() | b.keys())
    if not agreed or len(agreed) < 0.8 * union:
        raise ValueError(f"printed value labels: only {len(agreed)}/{union} points transcribed identically twice - rejected")
    yl = [_num(v) for v in (structure.get("y_axis") or {}).get("tick_labels") or []]
    yl = [v for v in yl if v is not None]
    xl = [_num(v) for v in (structure.get("x_axis") or {}).get("tick_labels") or []]
    xl = [v for v in xl if v is not None]
    rows = []
    for (series, x), y in sorted(agreed.items(), key=lambda kv: (kv[0][0], str(kv[0][1]))):
        if yl and not (min(yl) <= y <= max(yl) * 1.05):
            raise ValueError(f"transcribed value {y} lies outside the printed y axis range {min(yl)}-{max(yl)}")
        if xl and isinstance(x, float) and not (min(xl) <= x <= max(xl)):
            raise ValueError(f"transcribed x {x} lies outside the printed x axis range")
        rows.append({"x": x, "series": series, "y": y})
    if len(rows) < 3:
        raise ValueError("fewer than 3 printed value labels transcribed")
    return rows, dropped


# --------------------------------------------------------------------------- pixel side
def _clusters(idx, gap=4):
    if len(idx) == 0:
        return []
    grp = [[int(idx[0])]]
    for v in idx[1:]:
        if v - grp[-1][-1] <= gap:
            grp[-1].append(int(v))
        else:
            grp.append([int(v)])
    return [float(np.mean(g)) for g in grp]


def detect_axes(gray):
    """(yaxis_x, xaxis_y): longest dark vertical line in the left half, horizontal line in the bottom half."""
    h, w = gray.shape
    dark = gray < 120
    col_runs = dark[:, : w // 2].sum(axis=0)
    yaxis_x = int(np.argmax(col_runs))
    row_runs = dark[h // 2:, :].sum(axis=1)
    xaxis_y = int(np.argmax(row_runs)) + h // 2
    if col_runs[yaxis_x] < 0.3 * h or row_runs[xaxis_y - h // 2] < 0.3 * w:
        raise ValueError("axis lines not detected (frame too faint or non-cartesian chart)")
    return yaxis_x, xaxis_y


def _ticks_y(gray, yaxis_x, top, xaxis_y):
    for band in ((yaxis_x - 9, yaxis_x - 1), (yaxis_x + 2, yaxis_x + 10)):
        lo, hi = max(0, band[0]), max(1, band[1])
        sub = gray[top:xaxis_y + 3, lo:hi] < 130
        rows = np.where(sub.sum(axis=1) >= 3)[0] + top
        t = _clusters(rows)
        if len(t) >= 2:
            return t
    return []


def _ticks_x(gray, xaxis_y, yaxis_x, right):
    for band in ((xaxis_y + 2, xaxis_y + 10), (xaxis_y - 9, xaxis_y - 1)):
        sub = gray[band[0]:band[1], max(0, yaxis_x - 3):right] < 130
        cols = np.where(sub.sum(axis=0) >= 3)[0] + max(0, yaxis_x - 3)
        t = _clusters(cols)
        if len(t) >= 2:
            return t
    return []


def _match_ticks(px, labels, axis):
    """Ticks detected in pixels must correspond 1:1 to the printed labels."""
    labels = [float(v) for v in labels]
    if len(labels) < 2:
        raise ValueError(f"{axis}-axis: fewer than 2 numeric tick labels read")
    n = len(labels)
    if len(px) > n and n >= 3:
        # extra dark marks (frame corners, label glyphs, minor ticks): the printed labels are
        # equally spaced in value, so pick the unique equally spaced subset of detected ticks
        px = sorted(px)
        vals = np.array(labels)
        if np.allclose(np.diff(vals), vals[1] - vals[0], rtol=0.02):
            hits = []
            for i in range(len(px)):
                for j in range(i + 1, len(px)):
                    step = (px[j] - px[i]) / (n - 1)
                    if step < 4:
                        continue
                    want = [px[i] + k * step for k in range(n)]
                    got = [min(px, key=lambda p: abs(p - w)) for w in want]
                    if all(abs(g - w) <= 2.5 for g, w in zip(got, want)):
                        hits.append(got)
            uniq = {tuple(round(v, 1) for v in h) for h in hits}
            if len(uniq) == 1:
                px = list(uniq.pop())
    if len(px) != n:
        raise ValueError(f"{axis}-axis calibration failed: {len(px)} tick marks detected but "
                         f"{n} labels read ({labels})")
    return list(px), labels


def _mask_for(arr, color, box):
    xlo, xhi, ylo, yhi = box
    sub = arr[ylo:yhi, xlo:xhi].astype(int)
    r, g, b = sub[:, :, 0], sub[:, :, 1], sub[:, :, 2]
    key = (color or "").lower().strip()
    ref = _NAMED_RGB.get(key)
    if key in ("black", "dark", "grey", "gray"):
        m = (r < 120) & (g < 120) & (b < 120) & (np.abs(r - g) < 25) & (np.abs(g - b) < 25)
    elif ref is None:
        raise ValueError(f"unknown series colour '{color}'")
    else:
        sat = np.max(sub, axis=2) - np.min(sub, axis=2)
        dist = np.sqrt(((sub - np.array(ref)) ** 2).sum(axis=2))
        m = (dist < 95) & (sat > 40)
        if m.sum() > 50:  # refine reference to the actual ink colour
            ref2 = np.median(sub[m], axis=0)
            dist = np.sqrt(((sub - ref2) ** 2).sum(axis=2))
            m = (dist < 60) & (sat > 40)
    full = np.zeros(arr.shape[:2], bool)
    full[ylo:yhi, xlo:xhi] = m
    return full


def digitize_image(image_bytes, structure):
    """Read series values from pixels using tick-calibrated axes. Returns dict with rows/calibration."""
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    arr = np.asarray(img)
    gray = np.asarray(img.convert("L"))
    h, w = gray.shape
    ctype = (structure.get("chart_type") or "").lower()
    if ctype not in ("line", "bar", "km"):
        raise ValueError(f"chart type '{ctype}' is not digitizable by this tool")
    if int(structure.get("n_panels") or 1) != 1:
        raise ValueError("multi-panel figure: per-panel digitization not supported")
    xa, ya = structure.get("x_axis") or {}, structure.get("y_axis") or {}
    if ya.get("log_scale"):
        raise ValueError("log-scale y axis not supported")
    yaxis_x, xaxis_y = detect_axes(gray)
    ytick_px, yvals = _match_ticks(_ticks_y(gray, yaxis_x, 0, xaxis_y), ya.get("tick_labels") or [], "y")
    # y labels are bottom-to-top, pixel rows top-to-bottom
    yvals = yvals[::-1]
    y_fit = np.polyfit(ytick_px, yvals, 1)
    y_of = np.poly1d(y_fit)
    y_res = float(np.max(np.abs(y_of(ytick_px) - yvals)))
    y_span = abs(yvals[0] - yvals[-1])
    if y_span == 0 or y_res > 0.03 * y_span:
        raise ValueError("y-axis ticks are not linear in the labels read (check failed)")

    xcat = xa.get("categorical_labels") or []
    xtick_px = _ticks_x(gray, xaxis_y, yaxis_x, w - 2)
    if xcat and not xa.get("tick_labels"):
        if len(xtick_px) != len(xcat):
            raise ValueError(f"x-axis: {len(xtick_px)} ticks but {len(xcat)} category labels")
        x_positions = [(lbl, px) for lbl, px in zip(xcat, xtick_px)]
    else:
        xtick_px, xvals = _match_ticks(xtick_px, xa.get("tick_labels") or [], "x")
        x_fit = np.polyfit(xtick_px, xvals, 1)
        if np.max(np.abs(np.poly1d(x_fit)(xtick_px) - xvals)) > 0.03 * abs(xvals[-1] - xvals[0]):
            raise ValueError("x-axis ticks are not linear in the labels read (check failed)")
        x_of = np.poly1d(x_fit)
        if ctype == "bar":
            x_positions = [(v, px) for v, px in zip(xvals, xtick_px)]
        else:
            step = (xvals[-1] - xvals[0]) / max(1, 2 * (len(xvals) - 1))
            xs = np.arange(xvals[0], xvals[-1] + 1e-9, step)
            px_of_x = np.poly1d(np.polyfit(xvals, xtick_px, 1))
            x_positions = [(float(round(v, 6)), float(px_of_x(v))) for v in xs]

    box = (yaxis_x + 3, w - 2, 2, xaxis_y - 2)
    series = structure.get("series") or [{"name": "series", "color": "black"}]
    colours = [(s.get("color") or "").lower().strip() for s in series]
    if len(set(colours)) < len(colours):
        raise ValueError(f"series are not separable by colour ({colours}); refusing to guess which line is which")
    if len(series) > 1 and any(c in ("black", "dark", "grey", "gray") for c in colours):
        raise ValueError("monochrome multi-series chart: black/grey series cannot be told apart from text, "
                         "markers and other series by colour")
    rows = []
    half = max(3, int(0.35 * np.min(np.diff(xtick_px)))) if len(xtick_px) > 1 else 5
    for s in series:
        mask = _mask_for(arr, s.get("color"), box)
        if mask.sum() < 20:
            continue
        for xv, px in x_positions:
            cx = int(round(px))
            if ctype == "bar":
                col = mask[:, max(box[0], cx - half):cx + half + 1]
                ys = np.where(col.any(axis=1))[0]
                val = float(y_of(ys.min())) if len(ys) else None
            else:
                col = mask[:, max(box[0], cx - 2):cx + 3]
                ys = np.where(col.any(axis=1))[0]
                val = float(y_of(np.median(ys))) if len(ys) else None
            if val is not None:
                rows.append({"x": xv, "series": s.get("name") or s.get("color"), "y": round(val, 4)})
    if len(rows) < 3:
        raise ValueError("fewer than 3 points could be read from the series colours")
    minor = y_span / max(1, len(yvals) - 1)
    return {
        "rows": rows,
        "calibration": {
            "yaxis_x_px": yaxis_x, "xaxis_y_px": xaxis_y,
            "y_ticks_px": [round(p, 1) for p in ytick_px], "y_tick_values": yvals,
            "x_ticks_px": [round(p, 1) for p in xtick_px],
            "x_tick_values": xa.get("tick_labels") or xcat,
            "y_linearity_residual": round(y_res, 5),
        },
        "readout_error_hint": f"about {round(minor / 10, 4)} (1/10 of a y-axis division)",
        "image_size": [w, h],
    }


# --------------------------------------------------------------------------- orchestration
def digitize_article(ai, pmcid, requirements, data_dir, idx, doi=None, max_figs=3):
    """Digitize plan-relevant figures of one open-access article. Returns (tables, attempts)."""
    data_dir = Path(data_dir)
    fig_dir = data_dir / "figures"
    parsed_dir = data_dir / "parsed"
    fig_dir.mkdir(parents=True, exist_ok=True)
    parsed_dir.mkdir(parents=True, exist_ok=True)
    tables, attempts = [], []
    figures, doi_xml = list_figures(pmcid)
    doi = doi or doi_xml
    picks = select_figures(ai, requirements, figures, max_figs=max_figs)
    if not picks:
        attempts.append({"pmcid": pmcid, "status": "no_relevant_figure",
                         "detail": f"{len(figures)} figures; none matched the plan's quantities"})
        return tables, attempts
    for i, why in picks:
        fig = figures[i]
        att = {"pmcid": pmcid, "doi": doi, "figure": fig["label"], "fig_id": fig["fig_id"],
               "why_selected": why, "attempted_at": datetime.now(timezone.utc).isoformat()}
        try:
            content, url, mime = figure_image(pmcid, fig)
            sha = hashlib.sha256(content).hexdigest()
            ext = ".png" if mime == "image/png" else ".jpg"
            img_path = fig_dir / f"{idx:02d}_{pmcid}_{re.sub(r'[^A-Za-z0-9]+', '_', fig['label'])}{ext}"
            img_path.write_bytes(content)
            att.update({"image_url": url, "sha256": sha, "image_file": str(img_path)})
            structure = read_chart_structure(ai, content, mime)
            att["structure"] = structure
            if structure.get("data_labels_printed"):
                rows, dropped = transcribe_printed_labels(ai, content, mime, structure)
                result = {"rows": rows, "calibration": {"points_dropped_as_unconfirmed": dropped},
                          "readout_error_hint": "none expected: values transcribed from labels printed by the authors"}
                method = ("transcription of the numeric value labels printed on the figure by the authors "
                          "(two independent vision-model reads, accepted only when identical and within axis range)")
                role = "transcribe printed value labels (OCR); no estimation from plot position"
                head = "TRANSCRIBED printed value labels"
            else:
                result = digitize_image(content, structure)
                method = ("in-house pixel digitizer: axes/ticks detected from pixels and checked against tick labels "
                          "read by a vision model; series values read from coloured pixels")
                role = "chart structure and tick labels only (no data values)"
                head = "DIGITIZED"
            prov = {
                "pmcid": pmcid, "doi": doi, "figure_label": fig["label"], "caption": fig["caption"][:300],
                "image_url": url, "image_sha256": sha, "image_file": str(img_path),
                "method": method,
                "vision_model_role": role,
                "calibration": result["calibration"],
                "readout_error_hint": result["readout_error_hint"],
                "digitized_at": att["attempted_at"],
            }
            csv_path = parsed_dir / f"{idx:02d}_{pmcid}_{re.sub(r'[^A-Za-z0-9]+', '_', fig['label'])}_digitized.csv"
            with open(csv_path, "w", encoding="utf-8") as f:
                f.write(f"# {head} from {pmcid} {fig['label']} (doi:{doi}); image sha256={sha}\n")
                f.write(f"# {method}; read-out error {result['readout_error_hint']}; "
                        f"x axis: {structure.get('x_axis', {}).get('label', '')}; y axis: {structure.get('y_axis', {}).get('label', '')}\n")
                f.write("x,series,y\n")
                for r in result["rows"]:
                    f.write(f"{r['x']},\"{str(r['series']).replace(chr(34), '')}\",{r['y']}\n")
            preview = [["x", "series", "y"]] + [[str(r["x"]), str(r["series"]), str(r["y"])] for r in result["rows"][:7]]
            tables.append({
                "label": f"figure:{fig['label']} (digitized)",
                "csv": str(csv_path), "rows": len(result["rows"]), "cols": 3,
                "preview": preview, "digitized": True, "provenance": prov,
            })
            att["status"] = "digitized"
            att["n_points"] = len(result["rows"])
        except Exception as e:  # honest per-figure failure
            att["status"] = "failed"
            att["error"] = f"{type(e).__name__}: {str(e)[:300]}"
        attempts.append(att)
    return tables, attempts
