import json
import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from paper_sandbox.config import Config
from paper_sandbox.pipeline import PaperPipeline


class MockAI:
    def __init__(self, *args, **kwargs):
        pass

    def chat(self, prompt, temperature=0.7):
        return f"[Mock AI response for prompt: {prompt[:80]}...]"

    def rewrite_academic(self, text, language="en"):
        return text


class MockOpenAlex:
    def __init__(self, *args, **kwargs):
        pass

    def search(self, query, limit=5):
        return [{"display_name": f"Mock paper on {query}", "publication_year": 2024, "doi": "10.1234/mock"}]

    def to_references(self, results):
        return [{"id": 1, "title": "Mock paper", "year": 2024, "doi": "10.1234/mock", "authors": ["A Smith"], "journal": "Mock Journal"}]


# Patch clients
import paper_sandbox.ai_client
import paper_sandbox.openalex
paper_sandbox.ai_client.AIClient = MockAI
paper_sandbox.openalex.OpenAlexClient = MockOpenAlex

# Also patch in stage modules
import paper_sandbox.stages.idea
import paper_sandbox.stages.draft
import paper_sandbox.stages.reviewer_review
import paper_sandbox.stages.rewrite
paper_sandbox.stages.idea.AIClient = MockAI
paper_sandbox.stages.draft.AIClient = MockAI
paper_sandbox.stages.reviewer_review.AIClient = MockAI
paper_sandbox.stages.rewrite.AIClient = MockAI


def main():
    from paper_sandbox.config import Config
    cfg = Config()
    cfg.workspace = Path("/tmp/paper-sandbox-smoke")
    cfg.output_dir = cfg.workspace / "output"
    if cfg.workspace.exists():
        shutil.rmtree(cfg.workspace)
    cfg.workspace.mkdir(parents=True, exist_ok=True)
    cfg.git_auto_commit = False
    cfg.slack_webhook_url = None

    pipeline = PaperPipeline(cfg)
    input_data = {
        "topic": "health policy simulation workflow",
        "authors": ["Sandbox Author"],
        "open_access": True,
        "language": "en",
    }
    result = pipeline.run(input_data)
    print(json.dumps({
        "chosen_journal": result["chosen_journal"]["name"],
        "zip": result["zip"],
        "package": result["package"],
        "checks": result["check_results"],
    }, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
