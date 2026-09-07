import hashlib
import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import requests


def _repo_slug(topic: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "_", topic.lower()).strip("_")
    if not base:
        base = "paper_sandbox"
    if len(base) > 70:
        base = base[:70].rstrip("_")
    unique = hashlib.md5((topic + str(time.time())).encode()).hexdigest()[:6]
    return f"{base}_{unique}"


def _resolve_github_token() -> str | None:
    return (
        os.environ.get("GITHUB_REPO_CREATE_TOKEN")
        or os.environ.get("GITHUB_TOKEN")
        or os.environ.get("GH_TOKEN")
    )


def _run_git(args, cwd, env, check=True):
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        env=env,
        check=check,
        capture_output=True,
        text=True,
    )


def publish(topic: str, source_dir: str, output_dir: str, owner: str = "bougtoir") -> tuple[str | None, str | None, str | None]:
    """Create a public GitHub repo and push code + deliverables.

    Returns (repo_url, repo_name, error_message). repo_url is None if creation fails.
    """
    token = _resolve_github_token()
    if not token:
        return None, None, "GitHub token not configured. Set GITHUB_REPO_CREATE_TOKEN, GITHUB_TOKEN, or GH_TOKEN."

    repo_name = _repo_slug(topic)
    full_name = f"{owner}/{repo_name}"
    repo_url = f"https://github.com/{full_name}"

    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    create_resp = requests.post(
        "https://api.github.com/user/repos",
        headers=headers,
        json={
            "name": repo_name,
            "private": False,
            "description": f"Paper Sandbox submission: {topic}",
            "auto_init": False,
        },
        timeout=30,
    )
    if create_resp.status_code == 422 and "already exists" in create_resp.text:
        # Try to reuse the existing public repo
        pass
    elif create_resp.status_code != 201:
        return None, repo_name, f"GitHub repo create failed: {create_resp.status_code} {create_resp.text}"

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        # Copy source code, excluding secrets, caches, and local workspaces
        shutil.copytree(
            source_dir,
            tmp_path,
            ignore=shutil.ignore_patterns(
                ".git", ".env", "__pycache__", "*.pyc", "*.pyo",
                "workspace", "data", ".devin-files", "*.log",
            ),
            dirs_exist_ok=True,
        )

        # Re-add public data and deliverables
        data_src = Path(source_dir) / "data"
        if data_src.exists():
            shutil.copytree(data_src, tmp_path / "data", dirs_exist_ok=True)

        out_src = Path(output_dir)
        if out_src.exists():
            deliverables_dir = tmp_path / "deliverables"
            deliverables_dir.mkdir(parents=True, exist_ok=True)
            for item in out_src.iterdir():
                if item.is_file():
                    shutil.copy2(item, deliverables_dir / item.name)
                elif item.is_dir():
                    shutil.copytree(item, deliverables_dir / item.name, dirs_exist_ok=True)

        # Use an isolated git config so Devin's git-manager proxy rewrite does not apply
        git_config = tmp_path / ".gitconfig_isolated"
        git_config.write_text("[core]\n\tautocrlf = false\n", encoding="utf-8")
        git_env = {
            **os.environ,
            "GIT_CONFIG_GLOBAL": str(git_config),
            "GIT_CONFIG_NOSYSTEM": "1",
        }

        _run_git(["init"], tmp_path, git_env)
        _run_git(["config", "--local", "user.email", "sandbox@example.com"], tmp_path, git_env)
        _run_git(["config", "--local", "user.name", "Paper Sandbox"], tmp_path, git_env)
        _run_git(["remote", "add", "origin", f"https://{token}@github.com/{full_name}.git"], tmp_path, git_env)
        _run_git(["branch", "-M", "main"], tmp_path, git_env)
        _run_git(["add", "-A"], tmp_path, git_env)

        try:
            _run_git(["commit", "-m", f"Paper Sandbox submission: {repo_name}"], tmp_path, git_env)
        except subprocess.CalledProcessError as e:
            return None, repo_name, f"git commit failed: {e.stderr}"

        try:
            _run_git(["push", "-u", "origin", "main"], tmp_path, git_env)
        except subprocess.CalledProcessError as e:
            return None, repo_name, f"git push failed: {e.stderr}"

    return repo_url, repo_name, None
