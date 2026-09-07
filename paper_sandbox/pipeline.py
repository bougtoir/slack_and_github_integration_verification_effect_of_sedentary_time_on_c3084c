import json
from pathlib import Path

from paper_sandbox.config import Config
from paper_sandbox.data_analyzer import analyze_data
from paper_sandbox.git_tracker import GitTracker
from paper_sandbox.slack import SlackNotifier
from paper_sandbox.figure_generator import FigureGenerator
from paper_sandbox.stages import idea, literature, draft, journal_select
from paper_sandbox.stages import reviewer_review, checks, rewrite, deliverables
from paper_sandbox.stages import data_discovery, data_acquisition, analysis_code, figure_digitize
from paper_sandbox.ai_client import AIClient


class PaperPipeline:
    def __init__(self, cfg):
        self.cfg = cfg
        self.slack = SlackNotifier(cfg.slack_webhook_url, cfg.slack_bot_token)
        self.git = GitTracker(cfg, root=str(cfg.workspace))
        self.figures_dir = cfg.output_dir / "figures"

    def _acquire_and_analyze(self, topic, idea_text, protocol=""):
        """Discover public data, download it, run generated analysis. Never invents data."""
        out = self.cfg.output_dir
        data_dir = out / "data"
        candidates, disc_log = data_discovery.discover_datasets(self.cfg, topic, idea_text, protocol=protocol)
        (out / "dataset_candidates.json").write_text(
            json.dumps({"log": disc_log, "candidates": candidates}, indent=2, ensure_ascii=False), encoding="utf-8")
        self.slack.send(f"Data discovery: {len(candidates)} candidate sources ({disc_log.get('method')})")

        ai = AIClient(self.cfg.deepseek_api_key, self.cfg.deepseek_base_url, self.cfg.deepseek_model)
        requirements = disc_log.get("requirements") or {}

        def digitizer(pmcid, idx):
            return figure_digitize.digitize_article(ai, pmcid, requirements, data_dir, idx)

        acquired, attempts = data_acquisition.acquire_datasets(candidates, data_dir, figure_digitizer=digitizer)
        data_acquisition.write_acquisition_log_md(out / "data_acquisition_log.md", disc_log, attempts, acquired)
        self.git.tag_stage("data-acquisition")
        self.slack.stage_done(f"data-acquisition ({len(acquired)} acquired / {len(attempts)} attempted)")

        attempted = [
            {
                "name": a.get("name"), "publisher": a.get("publisher"), "url": a["download_url"],
                "final_url": a.get("final_url"), "attempted_at_utc": a.get("attempted_at"),
                "status": a["status"], "error": a.get("error"), "sha256": a.get("sha256"),
                "bytes": a.get("bytes"), "content_type": a.get("content_type"),
                "tables": [{"label": t["label"], "rows": t["rows"], "cols": t["cols"]} for t in a.get("tables", [])],
            }
            for a in attempts
        ]
        if not acquired:
            return {
                "error": "No public dataset could be downloaded and parsed.",
                "attempted_sources": attempted,
                "discovery": disc_log,
            }

        results, alog = analysis_code.run_generated_analysis(self.cfg, topic, idea_text, acquired, out)
        (out / "analysis_log.json").write_text(json.dumps(alog, indent=2, ensure_ascii=False), encoding="utf-8")
        self.git.tag_stage("analysis")
        datasets = [
            {k: a.get(k) for k in ("name", "publisher", "landing_url", "download_url", "final_url",
                                    "sha256", "bytes", "attempted_at", "raw_file", "license", "years")}
            | {"tables": [{k: t[k] for k in ("csv", "rows", "cols")} for t in a.get("tables", [])]}
            for a in acquired
        ]
        if results is None:
            reason = alog.get("unusable_reason")
            msg = (
                f"Datasets were downloaded but do not contain data that can answer the question: {reason}"
                if reason else "Datasets were acquired but the analysis script failed."
            )
            self.slack.send(f"{msg} No empirical results.")
            return {
                "error": msg,
                "attempted_sources": attempted,
                "datasets": datasets,
                "analysis_attempts": alog["attempts"],
            }
        self.slack.stage_done(f"analysis ({len(results.get('findings', []))} findings)")
        summary = {
            "source": "public data acquired automatically; see data/provenance.json",
            "datasets": datasets,
            "analysis": results,
            "attempted_sources": attempted,
        }
        (out / "data_summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
        return summary

    def _data_summary(self, input_data, topic=None, idea_text=""):
        data_url = input_data.get("data_url") or input_data.get("data_file")
        if not data_url:
            if input_data.get("skip_data_acquisition"):
                return None
            return self._acquire_and_analyze(
                topic or input_data.get("topic", ""), idea_text,
                protocol=input_data.get("protocol") or input_data.get("background") or "",
            )
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

        # Stage 2: literature pool (20-30 verified records found from the plan via Perplexity + PubMed/
        # Crossref/OpenAlex). The draft cites from this pool; only cited records become the reference list.
        refs = literature.collect_literature(
            self.cfg, topic, limit=literature.POOL_MAX, verify_with_crossref=True, idea_text=idea_text
        )
        (self.cfg.output_dir / "references_pool.json").write_text(
            json.dumps(refs, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        self.git.tag_stage("literature")
        self.slack.stage_done("literature")

        # Stage 3: data (user-supplied file, or discover -> acquire -> analyze public data)
        data_summary = self._data_summary(input_data, topic=topic, idea_text=idea_text)

        # Stage 4: draft (tailored to chosen journal)
        manuscript = draft.generate_draft(
            self.cfg, research_idea, refs, data_summary=data_summary, chosen_journal=chosen_journal
        )
        manuscript["authors"] = input_data.get("authors", ["Sandbox Author"])
        (self.cfg.output_dir / "references.json").write_text(
            json.dumps(manuscript.get("references", []), indent=2, ensure_ascii=False), encoding="utf-8"
        )
        self.git.tag_stage("draft")
        self.slack.stage_done("draft")

        # Stage 5: journal selection / confirmation
        ranked, table_md = journal_select.select_journals(
            self.cfg, topic=topic, maximize_open_access=input_data.get("open_access", False),
            background=input_data.get("background") or input_data.get("protocol", ""), manuscript=manuscript,
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
        if data_summary and "error" not in data_summary and data_summary.get("analysis"):
            for fig in data_summary["analysis"].get("figures", []):
                src = self.cfg.output_dir / fig.get("file", "")
                if src.exists():
                    png, tiff, pptx = fg.from_png(src, fig.get("caption", ""), name=f"figure_{fig.get('id', 1)}")
                    figure_paths.extend([png, tiff, pptx])
        elif data_summary and "error" not in data_summary:
            fig1_png, fig1_tiff, pptx_path = fg.from_data_summary(data_summary, "figure_1")
            figure_paths.extend([fig1_png, fig1_tiff, pptx_path])
        else:
            if data_summary and "error" in data_summary:
                (self.cfg.output_dir / "data_error.txt").write_text(
                    json.dumps(data_summary, indent=2, ensure_ascii=False), encoding="utf-8")
            for fig in manuscript.get("figures", []):
                name = f"figure_{fig.get('id', 1)}"
                png, tiff, pptx = fg.demo_figure(fig.get("caption", "Figure"), name=name)
                figure_paths.extend([png, tiff, pptx])

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
            self.cfg, topic=topic, maximize_open_access=input_data.get("open_access", False),
            background=input_data.get("background") or input_data.get("protocol", ""),
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
            self.cfg, topic=topic, maximize_open_access=input_data.get("open_access", False),
            background=input_data.get("background") or input_data.get("protocol", ""),
        )
        chosen_journal = ranked[0]
        return self._core_stages(input_data, chosen_journal)
