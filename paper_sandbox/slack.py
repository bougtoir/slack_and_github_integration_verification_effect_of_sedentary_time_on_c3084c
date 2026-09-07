import json
import os
import re

import requests


class SlackNotifier:
    def __init__(self, webhook_url=None, bot_token=None, channel_name=None):
        self.webhook_url = webhook_url or os.getenv("SLACK_WEBHOOK_URL")
        self.bot_token = bot_token or os.getenv("SLACK_BOT_TOKEN")
        self.channel_name = channel_name
        self._channel_ids: dict[str, str] = {}

    def _clean_channel_name(self, name: str) -> str:
        name = name.lower()
        name = re.sub(r"[^a-z0-9_-]", "_", name)
        name = name.strip("_-")
        if len(name) > 80:
            name = name[:80].rstrip("_-")
        return name or "paper-sandbox"

    def _unique_channel_name(self, base: str) -> str:
        import secrets
        cleaned = self._clean_channel_name(base)
        suffix = secrets.token_hex(3)
        max_base = 80 - len(suffix) - 1
        if len(cleaned) > max_base:
            cleaned = cleaned[:max_base].rstrip("_-")
        return f"{cleaned}-{suffix}"

    def _post_to_channel(self, channel_id: str, message: str) -> None:
        headers = {
            "Authorization": f"Bearer {self.bot_token}",
            "Content-Type": "application/json",
        }
        requests.post(
            "https://slack.com/api/conversations.join",
            headers=headers,
            json={"channel": channel_id},
            timeout=30,
        )
        post = requests.post(
            "https://slack.com/api/chat.postMessage",
            headers=headers,
            json={"channel": channel_id, "text": message, "unfurl_links": True},
            timeout=30,
        )
        post.raise_for_status()

    def create_and_post(self, channel_name: str, message: str) -> str | None:
        if not self.bot_token:
            return None
        base = self._clean_channel_name(channel_name)
        if base in self._channel_ids:
            self._post_to_channel(self._channel_ids[base], message)
            return self._channel_ids[base]

        cleaned = base
        headers = {
            "Authorization": f"Bearer {self.bot_token}",
            "Content-Type": "application/json",
        }
        for _ in range(5):
            create = requests.post(
                "https://slack.com/api/conversations.create",
                headers=headers,
                json={"name": cleaned, "is_private": False},
                timeout=30,
            )
            body = create.json()
            channel_id = body.get("channel", {}).get("id")
            if channel_id:
                self._channel_ids[base] = channel_id
                self._channel_ids[cleaned] = channel_id
                self._post_to_channel(channel_id, message)
                return channel_id
            if body.get("error") == "name_taken":
                cleaned = self._unique_channel_name(channel_name)
                continue
            break
        return None

    def send(self, message, blocks=None, channel_name=None):
        target = channel_name or self.channel_name or "paper-sandbox-notifications"
        if self.webhook_url:
            payload = {"text": message}
            if blocks:
                payload["blocks"] = blocks
            r = requests.post(
                self.webhook_url,
                data=json.dumps(payload),
                headers={"Content-Type": "application/json"},
                timeout=30,
            )
            r.raise_for_status()
        if self.bot_token:
            self.create_and_post(target, message)
        if not self.webhook_url and not self.bot_token:
            print(f"[Slack skipped] {message}")

    def stage_done(self, stage, status="done", channel_name=None):
        target = channel_name or self.channel_name or "paper-sandbox-notifications"
        self.send(f"Paper Sandbox: stage `{stage}` {status}", channel_name=target)
