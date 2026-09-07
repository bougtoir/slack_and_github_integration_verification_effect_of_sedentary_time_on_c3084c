"""Download, parse, and record provenance for discovered dataset candidates.

Every attempt (success or failure) is logged. Only files that were actually
downloaded and parsed into a tabular form are returned as acquired datasets.
"""
import hashlib
import csv
import io
import json
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests


MAX_BYTES = 60 * 1024 * 1024
TIMEOUT = 30
_HEADERS = {"User-Agent": "PaperSandbox/0.2 (research data acquisition; mailto:sandbox@example.com)"}


def _slug(s):
    s = re.sub(r"[^a-zA-Z0-9]+", "_", s or "").strip("_").lower()
    return (s or "dataset")[:60]


def machine_readable_urls(url):
    """Map well-known landing pages to stable machine-readable endpoints, most specific first.

    - PubMed Central article pages -> Europe PMC full-text JATS XML (tables intact, no captcha)
    - e-Stat dataset pages (stat_infid=...) -> e-Stat file-download CSV / XLSX
    The original URL is always kept as the last fallback.
    """
    out = []
    m = re.search(r"(PMC\d+)", url)
    if m and ("ncbi.nlm.nih.gov" in url or "europepmc.org" in url):
        out.append(f"https://www.ebi.ac.uk/europepmc/webservices/rest/{m.group(1)}/fullTextXML")
    m = re.search(r"stat_?inf_?id=(\d+)", url, re.IGNORECASE)
    if m and "e-stat.go.jp" in url:
        out.append(f"https://www.e-stat.go.jp/stat-search/file-download?statInfId={m.group(1)}&fileKind=1")
        out.append(f"https://www.e-stat.go.jp/stat-search/file-download?statInfId={m.group(1)}&fileKind=0")
    out.append(url)
    return out


def _download_one(url):
    with requests.get(url, headers=_HEADERS, timeout=TIMEOUT, stream=True, allow_redirects=True) as r:
        r.raise_for_status()
        ctype = (r.headers.get("Content-Type") or "").lower()
        buf = io.BytesIO()
        for chunk in r.iter_content(chunk_size=1 << 16):
            buf.write(chunk)
            if buf.tell() > MAX_BYTES:
                raise ValueError(f"file exceeds {MAX_BYTES} bytes")
        return buf.getvalue(), ctype, r.url


def _looks_blocked(content, ctype):
    if "html" not in ctype:
        return False
    head = content[:4000].lower()
    return b"recaptcha" in head or b"captcha" in head or b"access denied" in head


def _download(url):
    """Download from the first machine-readable variant of url that works. Returns (content, ctype, final_url)."""
    errors = []
    for candidate in machine_readable_urls(url):
        try:
            content, ctype, final = _download_one(candidate)
            if _looks_blocked(content, ctype):
                raise ValueError("server returned a captcha/access-denied page")
            return content, ctype, final
        except Exception as e:
            errors.append(f"{candidate}: {type(e).__name__}: {str(e)[:120]}")
    raise ValueError("; ".join(errors))


def _sniff(content):
    """Detect the real container format from magic bytes (servers often send octet-stream)."""
    head = content[:8]
    if head.startswith(b"PK\x03\x04"):
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as zf:
                names = zf.namelist()
            if "[Content_Types].xml" in names and any(n.startswith("xl/") for n in names):
                return "xlsx"
        except zipfile.BadZipFile:
            return None
        return "zip"
    if head.startswith(b"\xd0\xcf\x11\xe0"):
        return "xls"
    stripped = content[:2000].lstrip()
    if stripped[:1] in (b"{", b"["):
        return "json"
    if stripped[:1] == b"<":
        return "html"
    return None


def _read_tabular(content, ctype, url):
    """Return list of (label, DataFrame). Raises if nothing tabular found."""
    lower = url.lower().split("?")[0]
    kind = _sniff(content)
    if kind in ("xlsx", "xls"):
        ctype = "spreadsheet"
    elif kind == "zip":
        ctype = "zip"
    elif kind == "json":
        ctype = "json"
    elif kind == "html":
        ctype = "html"
    frames = []
    if lower.endswith(".zip") or "zip" in ctype:
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            for name in zf.namelist():
                if name.lower().endswith((".csv", ".tsv", ".xlsx", ".xls", ".json")):
                    try:
                        frames.extend(_read_tabular(zf.read(name), "", name))
                    except Exception:
                        continue
                if len(frames) >= 5:
                    break
        if not frames:
            raise ValueError("zip contains no parsable tabular file")
        return frames
    if lower.endswith((".xlsx", ".xls")) or "spreadsheet" in ctype or "excel" in ctype:
        sheets = pd.read_excel(io.BytesIO(content), sheet_name=None, header=None)
        for name, df in sheets.items():
            frames.append((f"sheet:{name}", df))
        return frames
    if lower.endswith(".json") or "json" in ctype:
        data = json.loads(content.decode("utf-8", errors="replace"))
        df = pd.json_normalize(data if isinstance(data, list) else _first_list(data))
        return [("json", df)]
    if lower.endswith((".csv", ".tsv", ".txt")) or "csv" in ctype or "text/plain" in ctype:
        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError:
            # Japanese official statistics (e-Stat etc.) are commonly Shift_JIS
            text = content.decode("cp932", errors="replace")
        sep = "\t" if lower.endswith(".tsv") or text.count("\t") > text.count(",") else ","
        # Official statistics CSVs often have ragged title/footnote rows; pad instead of dropping rows
        rows = list(csv.reader(io.StringIO(text), delimiter=sep))
        width = max((len(r) for r in rows), default=0)
        df = pd.DataFrame([r + [None] * (width - len(r)) for r in rows]).replace({"": None})
        return [("csv", df)]
    if "html" in ctype or "xml" in ctype or lower.endswith((".html", ".htm", ".xml")) or lower.endswith("/"):
        tables = pd.read_html(io.BytesIO(content))
        for i, df in enumerate(tables[:5]):
            frames.append((f"html_table_{i}", df))
        if not frames:
            raise ValueError("no HTML tables found")
        return frames
    # last resort: try csv then html
    try:
        return _read_tabular(content, "csv", url + ".csv")
    except Exception:
        return _read_tabular(content, "html", url + ".html")


def _first_list(obj):
    if isinstance(obj, list):
        return obj
    if isinstance(obj, dict):
        for v in obj.values():
            found = _first_list(v)
            if found:
                return found
    return []


def _usable(df):
    """A table is usable only if it has enough rows and at least one mostly-numeric column."""
    df = df.dropna(how="all").dropna(axis=1, how="all")
    if df.shape[0] < 3 or df.shape[1] < 2:
        return False
    for col in df.columns:
        s = df[col].astype(str).str.replace(r"[,\s%()]", "", regex=True)
        num = pd.to_numeric(s, errors="coerce")
        if num.notna().sum() >= max(3, int(0.5 * len(num))):
            return True
    return False


def acquire_datasets(candidates, data_dir, max_success=3):
    """Try to download each candidate. Returns (acquired, log_entries)."""
    data_dir = Path(data_dir)
    raw_dir = data_dir / "raw"
    parsed_dir = data_dir / "parsed"
    raw_dir.mkdir(parents=True, exist_ok=True)
    parsed_dir.mkdir(parents=True, exist_ok=True)

    acquired = []
    log = []
    for idx, c in enumerate(candidates, 1):
        url = c["download_url"]
        entry = {
            "index": idx,
            "name": c.get("name"),
            "publisher": c.get("publisher"),
            "landing_url": c.get("landing_url"),
            "download_url": url,
            "discovered_by": c.get("discovered_by"),
            "attempted_at": datetime.now(timezone.utc).isoformat(),
            "status": None,
            "error": None,
        }
        if len(acquired) >= max_success:
            entry["status"] = "skipped"
            entry["error"] = "enough datasets already acquired"
            log.append(entry)
            continue
        try:
            content, ctype, final_url = _download(url)
            sha = hashlib.sha256(content).hexdigest()
            ext = Path(final_url.split("?")[0]).suffix or ".bin"
            raw_path = raw_dir / f"{idx:02d}_{_slug(c.get('name'))}{ext}"
            raw_path.write_bytes(content)
            entry.update({"final_url": final_url, "content_type": ctype, "bytes": len(content),
                          "sha256": sha, "raw_file": str(raw_path)})
            frames = _read_tabular(content, ctype, final_url)
            frames = [(lbl, df) for lbl, df in frames if _usable(df)]
            if not frames:
                raise ValueError("downloaded file parsed but contains no usable table (needs >=3 rows, >=2 columns and a numeric column)")
            tables = []
            for lbl, df in frames:
                df = df.dropna(how="all").dropna(axis=1, how="all")
                out = parsed_dir / f"{idx:02d}_{_slug(c.get('name'))}_{_slug(lbl)}.csv"
                if df.columns.dtype != "int64":
                    df = pd.concat([pd.DataFrame([list(df.columns)], columns=range(df.shape[1])),
                                    df.set_axis(range(df.shape[1]), axis=1)], ignore_index=True)
                df.to_csv(out, index=False, header=False)
                tables.append({
                    "label": lbl,
                    "csv": str(out),
                    "rows": int(df.shape[0]),
                    "cols": int(df.shape[1]),
                    "preview": df.head(8).astype(str).values.tolist(),
                })
            entry["status"] = "acquired"
            entry["tables"] = tables
            acquired.append({**c, **entry})
        except Exception as e:
            entry["status"] = "failed"
            entry["error"] = f"{type(e).__name__}: {str(e)[:300]}"
        log.append(entry)

    (data_dir / "provenance.json").write_text(
        json.dumps({"generated_at": datetime.now(timezone.utc).isoformat(), "attempts": log},
                   indent=2, ensure_ascii=False), encoding="utf-8")
    return acquired, log


def write_acquisition_log_md(path, discovery_log, attempts, acquired):
    lines = ["# Data acquisition log", ""]
    lines.append(f"Discovery method: {discovery_log.get('method') or 'none'}")
    lines.append(f"Candidates found: {discovery_log.get('n_candidates', 0)}")
    for e in discovery_log.get("errors", []):
        lines.append(f"- discovery error: {e}")
    lines.append("")
    lines.append(f"Datasets successfully acquired and parsed: {len(acquired)}")
    lines.append("")
    lines.append("| # | Dataset | Publisher | URL | Status | Detail |")
    lines.append("|---|---------|-----------|-----|--------|--------|")
    for a in attempts:
        detail = a.get("error") or (
            f"sha256={a.get('sha256', '')[:12]}…, {sum(t['rows'] for t in a.get('tables', []))} rows"
            if a.get("status") == "acquired" else "")
        lines.append(
            f"| {a['index']} | {a.get('name') or ''} | {a.get('publisher') or ''} | {a['download_url']} | "
            f"{a['status']} | {str(detail).replace('|', '/')} |")
    lines.append("")
    if not acquired:
        lines.append("No dataset could be downloaded and parsed. No empirical results are reported; "
                     "the manuscript is a protocol that documents the attempted sources above.")
    return Path(path).write_text("\n".join(lines), encoding="utf-8")
