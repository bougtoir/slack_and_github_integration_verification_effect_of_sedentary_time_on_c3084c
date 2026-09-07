import json
from pathlib import Path

from paper_sandbox.config import Config
from paper_sandbox.data_analyzer import analyze_data
from paper_sandbox.git_tracker import GitTracker
from paper_sandbox.slack import SlackNotifier
from paper_sandbox.figure_generator import FigureGenerator
from paper_sandbox.stages import idea, literature, draft, journal_select
from paper_sandbox.stages import reviewer_review, checks, rewrite, deliverables


class PaperPipeline:
    def __init__(self, cfg):
        self.cfg = cfg
        self.slack = SlackNotifier(cfg.slack_webhook_url, cfg.slack_bot_token)
        self.git = GitTracker(cfg, root=str(cfg.workspace))
        self.figures_dir = cfg.output_dir / "figures"

    def _data_summary(self, input_data):
        data_url = input_data.get("data_url") or input_data.get("data_file")
        if not data_url:
            return None
        try:
            summary, df = analyze_data(
                data_url,
                group_column=input_data.get("group_column"),
                value_column=input_data.get("value_column"),
            )
            data_path = self.cfg.output_dir / "data_summary.json"
            data_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
            return summary
        except Exception as e:
            self.slack.send(f"Data analysis failed: {e}")
            return {"error": str(e)}

    def _prepare_idea(self, input_data):
        topic = input_data.get("topic", "Untitled")
        protocol = input_data.get("protocol", "")
        research_idea = topic
        if protocol:
            research_idea = f"Protocol / plan:\n{protocol}\n\nResearch idea:\n{topic}"
        return topic, research_idea

    def _core_stages(self, input_data, chosen_journal):
        topic, research_idea = self._prepare_idea(input_data)
        self.slack.channel_name = self.slack._clean_channel_name(topic)
        self.slack.send(f"Starting Paper Sandbox for: {topic}")

        # Stage 1: deepen idea
        idea_text = idea.deepen_idea(self.cfg, research_idea, protocol=input_data.get("protocol", ""))
        (self.cfg.output_dir / "idea.md").write_text(idea_text, encoding="utf-8")
        self.git.tag_stage("idea")
        self.slack.stage_done("idea")

        # Stage 2: literature (multi-source + Crossref verification)
        refs = literature.collect_literature(self.cfg, topic)
        (self.cfg.output_dir / "references.json").write_text(
            json.dumps(refs, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        self.git.tag_stage("literature")
        self.slack.stage_done("literature")

        # Stage 3: optional data analysis
        data_summary = self._data_summary(input_data)

        # Stage 4: draft (tailored to chosen journal)
        manuscript = draft.generate_draft(
            self.cfg, research_idea, refs, data_summary=data_summary, chosen_journal=chosen_journal
        )
        manuscript["authors"] = input_data.get("authors", ["Sandbox Author"])
        self.git.tag_stage("draft")
        self.slack.stage_done("draft")

        # Stage 5: journal selection / confirmation
        ranked, table_md = journal_select.select_journals(
            self.cfg, topic=topic, maximize_open_access=input_data.get("open_access", False)
        )
        (self.cfg.output_dir / "journal_table.md").write_text(table_md, encoding="utf-8")
        self.git.tag_stage("journal-select")
        self.slack.stage_done("journal-select")

        # Stage 6: reviewer review
        review_report = reviewer_review.reviewer_review(self.cfg, manuscript, chosen_journal)
        (self.cfg.output_dir / "reviewer_review.md").write_text(review_report, encoding="utf-8")
        self.git.tag_stage("reviewer-review")
        self.slack.stage_done("reviewer-review")

        # Stage 7: checks
        check_results = checks.run_all_checks(manuscript, language=self.cfg.language)
        check_report = json.dumps(check_results, indent=2, ensure_ascii=False)
        (self.cfg.output_dir / "checks.json").write_text(check_report, encoding="utf-8")
        self.git.tag_stage("checks")
        self.slack.stage_done("checks")

        # Stage 8: rewrite
        manuscript = rewrite.rewrite_sections(self.cfg, manuscript)
        draft._check_for_placeholders(manuscript)
        self.git.tag_stage("rewrite")
        self.slack.stage_done("rewrite")

        # Stage 9: generate figures and tables
        fg = FigureGenerator(self.figures_dir)
        figure_paths = []
        if data_summary and "error" not in data_summary:
            fig1_png, fig1_tiff, pptx_path = fg.from_data_summary(data_summary, "figure_1")
            figure_paths.extend([fig1_png, fig1_tiff, pptx_path])
        elif data_summary and "error" in data_summary:
            (self.cfg.output_dir / "data_error.txt").write_text(data_summary["error"], encoding="utf-8")

        tables_path, table_pptx = fg.table_docx(manuscript.get("tables", []))
        if table_pptx:
            figure_paths.append(table_pptx)
        self.git.tag_stage("figures")
        self.slack.stage_done("figures")

        # Stage 10: deliverables
        check_report_text = "\n".join(f"{k}: {v}" for k, v in check_results.items())
        packaged, zip_path = deliverables.build_deliverables(
            self.cfg, manuscript, chosen_journal, figure_paths, tables_path,
            check_report_text, review_report, data_summary=data_summary
        )
        self.git.tag_stage("deliverables")
        self.slack.send(
            f"Paper Sandbox complete. Outputs in {self.cfg.output_dir}. Package: {zip_path}"
        )

        return {
            "idea": idea_text,
            "references": refs,
            "manuscript": manuscript,
            "journal_table": table_md,
            "chosen_journal": chosen_journal,
            "review_report": review_report,
            "check_results": check_results,
            "data_summary": data_summary,
            "package": packaged,
            "zip": str(zip_path),
        }

    def journal_candidates(self, input_data):
        topic = input_data.get("topic", "Untitled")
        ranked, table_md = journal_select.select_journals(
            self.cfg, topic=topic, maximize_open_access=input_data.get("open_access", False)
        )
        (self.cfg.output_dir / "journal_candidates.md").write_text(table_md, encoding="utf-8")
        return {"candidates": ranked[:10], "markdown": table_md}

    def run_from_selection(self, input_data):
        self.cfg.ensure_dirs()
        self.git.init()
        chosen_journal = input_data.get("chosen_journal")
        if not chosen_journal:
            raise ValueError("chosen_journal is required for run_from_selection")
        return self._core_stages(input_data, chosen_journal)

    def run(self, input_data):
        self.cfg.ensure_dirs()
        self.git.init()
        topic = input_data.get("topic", "Untitled")
        ranked, table_md = journal_select.select_journals(
            self.cfg, topic=topic, maximize_open_access=input_data.get("open_access", False)
        )
        chosen_journal = ranked[0]
        return self._core_stages(input_data, chosen_journal)
