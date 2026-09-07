import json
from pathlib import Path

import pandas as pd
import requests


def _load(path_or_url):
    path = Path(path_or_url)
    if path.exists():
        return str(path)
    # treat as URL
    try:
        r = requests.get(path_or_url, timeout=60)
        r.raise_for_status()
        suffix = Path(path_or_url).suffix.lower()
        tmp = Path(f"/tmp/data_download{suffix}")
        tmp.write_bytes(r.content)
        return str(tmp)
    except Exception as e:
        raise RuntimeError(f"Could not load data from {path_or_url}: {e}")


def _read_file(path):
    p = Path(path)
    if p.suffix.lower() in [".xlsx", ".xls"]:
        return pd.read_excel(path)
    if p.suffix.lower() == ".tsv":
        return pd.read_csv(path, sep="\t")
    return pd.read_csv(path)


def analyze_data(path_or_url, numeric_summary=True, group_column=None, value_column=None):
    file_path = _load(path_or_url)
    df = _read_file(file_path)

    summary = {
        "source": str(path_or_url),
        "rows": len(df),
        "columns": list(df.columns),
        "dtypes": {c: str(t) for c, t in df.dtypes.items()},
    }

    numeric_cols = df.select_dtypes(include="number").columns.tolist()
    if value_column:
        value_cols = [value_column] if value_column in df.columns else []
    else:
        value_cols = numeric_cols

    if group_column and group_column in df.columns:
        groups = df.groupby(group_column)
        group_stats = {}
        for col in value_cols:
            group_stats[col] = groups[col].agg(["count", "mean", "std", "median"]).to_dict()
        summary["group_stats"] = group_stats
    elif numeric_summary:
        stats = df[value_cols].describe().to_dict()
        summary["numeric_summary"] = stats

    return summary, df
