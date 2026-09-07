import json
import re
from pathlib import Path


def _topic_tokens(text):
    return set(re.findall(r"\w+", str(text).lower()))


JOURNALS = [
    {
        "name": "Health Policy",
        "publisher": "Elsevier",
        "if_2023": 3.4,
        "apc_usd": 3300,
        "hybrid": True,
        "topics": ["health policy", "health economics", "healthcare systems"],
    },
    {
        "name": "Social Science & Medicine",
        "publisher": "Elsevier",
        "if_2023": 5.4,
        "apc_usd": 3450,
        "hybrid": True,
        "topics": ["health", "social science", "public health"],
    },
    {
        "name": "Statistics in Medicine",
        "publisher": "Wiley",
        "if_2023": 2.0,
        "apc_usd": 4200,
        "hybrid": True,
        "topics": ["biostatistics", "clinical trials", "statistics"],
    },
    {
        "name": "Biometrical Journal",
        "publisher": "Wiley",
        "if_2023": 1.3,
        "apc_usd": 3250,
        "hybrid": True,
        "topics": ["biostatistics", "methodology"],
    },
    {
        "name": "Journal of Clinical Epidemiology",
        "publisher": "Elsevier",
        "if_2023": 4.6,
        "apc_usd": 3700,
        "hybrid": True,
        "topics": ["epidemiology", "clinical research", "methods"],
    },
    {
        "name": "BMC Health Services Research",
        "publisher": "BMC / Springer Nature",
        "if_2023": 2.7,
        "apc_usd": 2090,
        "hybrid": False,
        "topics": ["health services", "health policy"],
    },
    {
        "name": "PLOS ONE",
        "publisher": "PLOS",
        "if_2023": 2.9,
        "apc_usd": 1715,
        "hybrid": False,
        "topics": ["multidisciplinary", "science"],
    },
    {
        "name": "Scientific Reports",
        "publisher": "Springer Nature",
        "if_2023": 3.8,
        "apc_usd": 1790,
        "hybrid": False,
        "topics": ["multidisciplinary", "science"],
    },
    {
        "name": "International Journal of Health Policy and Management",
        "publisher": "Kerman University of Medical Sciences",
        "if_2023": 3.5,
        "apc_usd": 0,
        "hybrid": False,
        "topics": ["health policy", "global health"],
    },
    {
        "name": "BMJ Open",
        "publisher": "BMJ",
        "if_2023": 2.4,
        "apc_usd": 1500,
        "hybrid": False,
        "topics": ["open access", "medicine"],
    },
]


class JournalDB:
    def __init__(self, path=None):
        self.path = Path(path) if path else None
        if self.path and self.path.exists():
            with open(self.path) as f:
                self.journals = json.load(f)
        else:
            self.journals = JOURNALS

    def rank(self, topic, maximize_open_access=False):
        topic_tokens = _topic_tokens(topic)
        scored = []
        for j in self.journals:
            journal_tokens = set()
            for t in j.get("topics", []):
                journal_tokens.update(_topic_tokens(t))
            overlap = topic_tokens & journal_tokens
            match = bool(overlap)
            score = j["if_2023"]
            if match:
                score += 2.0 + len(overlap) * 0.5
            if maximize_open_access and not j.get("hybrid"):
                score += 1.0
            scored.append({**j, "score": score, "topic_match": match})
        scored.sort(key=lambda x: x["score"], reverse=True)
        matching = [s for s in scored if s["topic_match"]]
        if matching:
            return matching
        return scored[:3]

    def to_table(self, ranked):
        lines = ["| # | Journal | IF 2023 | APC USD | Hybrid | Publisher |"]
        lines.append("|---|---|---|---|---|---|")
        for i, j in enumerate(ranked[:10], start=1):
            lines.append(
                f"| {i} | {j['name']} | {j['if_2023']} | {j['apc_usd']} | "
                f"{'Yes' if j['hybrid'] else 'No'} | {j['publisher']} |"
            )
        return "\n".join(lines)
