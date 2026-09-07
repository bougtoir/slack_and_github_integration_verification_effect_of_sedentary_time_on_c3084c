import os
from pathlib import Path


class Config:
    def __init__(self, env_path=None):
        if env_path and Path(env_path).exists():
            with open(env_path) as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        key, value = line.split("=", 1)
                        os.environ.setdefault(key.strip(), value.strip())

        self.openalex_api_key = os.getenv("OPENALEX_API_KEY")
        self.perplexity_api_key = os.getenv("PERPLEXITY_API_KEY")
        self.perplexity_base_url = os.getenv("PERPLEXITY_BASE_URL", "https://api.perplexity.ai")
        self.perplexity_model = os.getenv("PERPLEXITY_MODEL", "")
        self.perplexity_preset = os.getenv("PERPLEXITY_PRESET", "pro-search")
        self.perplexity_prompt = os.getenv("PERPLEXITY_PROMPT", "")
        self.perplexity_max_steps = int(os.getenv("PERPLEXITY_MAX_STEPS", "3"))
        self.pubmed_email = os.getenv("PUBMED_EMAIL", os.getenv("NCBI_EMAIL", "sandbox@example.com"))
        self.deepseek_api_key = os.getenv("DEEPSEEK_API_KEY")
        self.deepseek_base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
        self.deepseek_model = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
        self.deepl_api_key = os.getenv("DEEPL_API_KEY")
        self.slack_webhook_url = os.getenv("SLACK_WEBHOOK_URL")
        self.slack_bot_token = os.getenv("SLACK_BOT_TOKEN")
        self.git_auto_commit = os.getenv("GIT_AUTO_COMMIT", "true").lower() == "true"
        self.git_user_name = os.getenv("GIT_USER_NAME", "Paper Sandbox")
        self.git_user_email = os.getenv("GIT_USER_EMAIL", "sandbox@example.com")
        self.language = os.getenv("LANGUAGE", "en")
        self.figure_embedded = os.getenv("FIGURE_EMBEDDED", "false").lower() == "true"

        self.workspace = Path(os.getenv("WORKSPACE", "/app/workspace"))
        self.output_dir = Path(os.getenv("OUTPUT_DIR", str(self.workspace / "output")))
        self.input_path = self.workspace / "input.json"

    def ensure_dirs(self):
        self.output_dir.mkdir(parents=True, exist_ok=True)
