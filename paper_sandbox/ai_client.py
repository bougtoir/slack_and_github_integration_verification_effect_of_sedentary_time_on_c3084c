import os
import requests


class AIClient:
    def __init__(self, api_key=None, base_url=None, model=None):
        self.api_key = api_key or os.getenv("DEEPSEEK_API_KEY")
        self.base_url = base_url or os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
        self.model = model or os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

    def chat(self, prompt, temperature=0.7, json_mode=False):
        if not self.api_key:
            return f"[AI unavailable] {prompt[:200]}..."
        body = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}
            body["max_tokens"] = 8192
        try:
            r = requests.post(
                f"{self.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=body,
                timeout=300,
            )
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"]
        except requests.RequestException as e:
            return f"[AI request failed ({e})]"

    def rewrite_academic(self, text, language="en"):
        prompt = (
            f"Rewrite the following academic text in {language} in a natural, "
            "native-speaker academic style. Keep the same meaning. Avoid AI-like phrasing.\n\n"
            f"{text}"
        )
        return self.chat(prompt, temperature=0.3)
