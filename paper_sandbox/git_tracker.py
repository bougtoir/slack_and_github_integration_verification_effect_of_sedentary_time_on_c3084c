import subprocess
from pathlib import Path


class GitTracker:
    def __init__(self, cfg, root=None):
        self.cfg = cfg
        self.root = Path(root or "/app")

    def _run(self, cmd):
        return subprocess.run(cmd, cwd=self.root, check=True, capture_output=True, text=True)

    def init(self):
        # Avoid "dubious ownership" errors when the repo is mounted from the host.
        subprocess.run(
            ["git", "config", "--global", "--add", "safe.directory", str(self.root)],
            check=False, capture_output=True, text=True,
        )
        if not (self.root / ".git").exists():
            self._run(["git", "init"])
            self._run(["git", "config", "user.name", self.cfg.git_user_name])
            self._run(["git", "config", "user.email", self.cfg.git_user_email])

    def commit(self, message, tag=None):
        if not self.cfg.git_auto_commit:
            return
        self.init()
        self._run(["git", "add", "-A"])
        try:
            self._run(["git", "commit", "-m", message])
        except subprocess.CalledProcessError:
            return
        if tag:
            self._run(["git", "tag", "-fa", tag, "-m", message])

    def tag_stage(self, stage):
        self.commit(f"Stage: {stage}", tag=f"stage/{stage}")
