import argparse
import json

from paper_sandbox.config import Config
from paper_sandbox.pipeline import PaperPipeline


def main():
    parser = argparse.ArgumentParser(description="Paper Sandbox CLI")
    parser.add_argument("--input", required=True, help="Path to input JSON")
    parser.add_argument("--env", default="/app/.env", help="Path to .env file")
    parser.add_argument("--mode", default="run", choices=["run", "candidates", "continue"], help="Pipeline mode")
    parser.add_argument("--output-summary", default=None, help="Path to write summary JSON")
    args = parser.parse_args()

    cfg = Config(args.env)
    with open(args.input, encoding="utf-8") as f:
        input_data = json.load(f)

    pipeline = PaperPipeline(cfg)
    if args.mode == "candidates":
        result = pipeline.journal_candidates(input_data)
    elif args.mode == "continue":
        result = pipeline.run_from_selection(input_data)
    else:
        result = pipeline.run(input_data)

    summary_path = args.output_summary or str(cfg.output_dir / "summary.json")
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    print(f"Done. Summary: {summary_path}")
    print(f"Output directory: {cfg.output_dir}")
    if "chosen_journal" in result:
        print(f"Chosen journal: {result['chosen_journal']['name']}")


if __name__ == "__main__":
    main()
