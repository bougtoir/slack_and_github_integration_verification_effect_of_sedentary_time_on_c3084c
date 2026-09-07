# Paper Sandbox

Docker sandbox based paper writing environment PoC.

## Overview

A containerized end-to-end workflow for academic manuscript preparation:

1. Interactive idea development
2. Literature search (OpenAlex)
3. Draft generation
4. Journal selection with IF / APC / hybrid / publisher table
5. Reviewer-perspective critical review
6. Validation checks
   - Fabrication check (citations, figures, numbering, real references)
   - Reproducibility check (data/code → results → manuscript)
   - Consistency check (intro → results → discussion alignment)
   - Formatting check (Word equations, no full-width characters)
   - Revision check (no "old version" wording)
7. Natural academic rewrite
8. Deliverable packaging

## Run locally

```bash
cp .env.example .env
# edit .env with your keys
docker compose up --build
```

## Usage

Put an input JSON in `workspace/input.json` and run:

```bash
docker compose exec sandbox python -m paper_sandbox.cli --input workspace/input.json
```

Or use the example:

```bash
docker compose exec sandbox python -m paper_sandbox.cli --input examples/sample_input.json
```

Outputs are written to `workspace/output/` and committed to git with stage tags.

## Configuration

See `.env.example`. Key variables:

- `OPENALEX_API_KEY` — literature search
- `DEEPSEEK_API_KEY` — drafting / rewriting
- `DEEPL_API_KEY` — academic rewriting (optional)
- `SLACK_WEBHOOK_URL` — progress / completion notifications
- `GIT_AUTO_COMMIT=true` — commit each stage

## Deliverables

After a run, `output/` contains:

- `manuscript.docx` — main text
- `cover_letter.docx` — cover letter
- `figures/` — individual PNG and TIFF figures
- `tables/` — editable table DOCX
- `package.zip` — complete submission package
