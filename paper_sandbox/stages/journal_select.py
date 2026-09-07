from pathlib import Path

from paper_sandbox.journal_db import JournalDB


def select_journals(cfg, topic, maximize_open_access=False):
    db_path = Path("/app/data/journals.json")
    if not db_path.exists():
        db_path = cfg.workspace / "data" / "journals.json"
    db = JournalDB(db_path if db_path.exists() else None)
    ranked = db.rank(topic, maximize_open_access=maximize_open_access)
    table = db.to_table(ranked)
    return ranked, table
