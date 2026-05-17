"""
Nightingale Sandbox
Isolated execution environment with integrity verification
"""
import os
import shutil
import hashlib
import subprocess
import time
from typing import List, Tuple
from nightingale.config import config
from nightingale.types import FileDiff
from nightingale.core.logger import logger


def _compute_dir_hash(directory: str, ignore: set = None) -> str:
    """Compute a deterministic hash of all files in a directory tree."""
    if ignore is None:
        ignore = {".git", ".sandbox", "__pycache__", ".nightingale_cache"}
    # Always ignore runtime-generated files that change during a run
    _always_ignore_exts = {".db", ".log", ".pyc"}
    _always_ignore_names = {"nightingale.db", "nightingale.log"}
    hasher = hashlib.sha256()
    for root, dirs, files in sorted(os.walk(directory)):
        dirs[:] = [d for d in sorted(dirs) if d not in ignore]
        for fname in sorted(files):
            # Skip runtime-generated files that legitimately change during a run
            if fname in _always_ignore_names:
                continue
            _, ext = os.path.splitext(fname)
            if ext in _always_ignore_exts:
                continue
            fpath = os.path.join(root, fname)
            rel = os.path.relpath(fpath, directory)
            hasher.update(rel.encode())
            try:
                with open(fpath, "rb") as f:
                    hasher.update(f.read())
            except (PermissionError, OSError):
                pass
    return hasher.hexdigest()


class Sandbox:
    """
    Isolated execution environment.
    - Copies repo excluding .git / caches
    - Applies diffs
    - Runs commands
    - Verifies original repo integrity before and after
    """

    def __init__(self, repo_path: str, sandbox_id: str):
        self.original_repo_path = os.path.abspath(repo_path)
        self.sandbox_id = sandbox_id
        base = config.get("sandbox_dir", ".sandbox")
        self.sandbox_path = os.path.join(self.original_repo_path, base, sandbox_id)
        self.original_hash: str = ""

    def setup(self):
        """Create a clean copy of the repo in the sandbox directory."""
        # Snapshot original repo hash BEFORE anything
        self.original_hash = _compute_dir_hash(self.original_repo_path)
        logger.info(
            f"[SANDBOX] Original repo hash: {self.original_hash[:16]}...",
            component="sandbox"
        )

        if os.path.exists(self.sandbox_path):
            shutil.rmtree(self.sandbox_path)

        shutil.copytree(
            self.original_repo_path,
            self.sandbox_path,
            ignore=shutil.ignore_patterns(
                ".git", ".sandbox", "__pycache__", "*.pyc", ".nightingale_cache"
            )
        )
        logger.info(f"[SANDBOX] Created sandbox at {self.sandbox_path}", component="sandbox")

    def apply_diffs(self, diffs: List[FileDiff]):
        """Apply file changes to the sandboxed repo only."""
        for diff in diffs:
            file_path = os.path.join(self.sandbox_path, diff.file_path)

            if diff.change_type == "modify":
                os.makedirs(os.path.dirname(file_path), exist_ok=True)
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(diff.diff_content)
            elif diff.change_type == "add":
                os.makedirs(os.path.dirname(file_path), exist_ok=True)
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(diff.diff_content)
            elif diff.change_type == "delete":
                if os.path.exists(file_path):
                    os.remove(file_path)

        logger.info(f"[SANDBOX] Applied {len(diffs)} file change(s)", component="sandbox")

    def run_command(self, command: str, timeout: int = 60) -> Tuple[int, str, str]:
        """Run a command inside the sandbox environment."""
        try:
            result = subprocess.run(
                command,
                shell=True,
                cwd=self.sandbox_path,
                capture_output=True,
                text=True,
                timeout=timeout
            )
            return result.returncode, result.stdout, result.stderr
        except subprocess.TimeoutExpired:
            return -1, "", f"Command timed out after {timeout}s"

    def verify_original_unchanged(self) -> bool:
        """Assert that the original repository has NOT been modified."""
        if not self.original_hash:
            logger.warning("[SANDBOX] No original hash to compare – skipping integrity check", component="sandbox")
            return True

        current_hash = _compute_dir_hash(self.original_repo_path)
        if current_hash == self.original_hash:
            logger.info(
                f"[SANDBOX] Integrity OK – original repo unchanged ({current_hash[:16]}...)",
                component="sandbox"
            )
            return True
        else:
            logger.error(
                f"[SANDBOX] INTEGRITY VIOLATION – repo changed! "
                f"before={self.original_hash[:16]}... after={current_hash[:16]}...",
                component="sandbox"
            )
            return False

    def cleanup(self):
        """Remove sandbox and verify original repo integrity."""
        # Verify original repo unchanged
        self.verify_original_unchanged()

        if os.path.exists(self.sandbox_path):
            shutil.rmtree(self.sandbox_path)
            logger.info("[SANDBOX] Sandbox cleaned up", component="sandbox")
