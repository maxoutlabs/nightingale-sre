"""
Nightingale GitHub PR Creator
Opens a Pull Request with the fix instead of writing directly to disk.

Uses the GitHub REST API v3 via httpx (already in requirements).
Falls back gracefully if no token is configured.
"""
import os
import json
import base64
import time
from typing import Optional, List, Dict, Any
from datetime import datetime

import httpx

from nightingale.types import FixPlan, ConfidenceFactors
from nightingale.core.logger import logger
from nightingale.config import config


class GitHubPRError(Exception):
    pass


class GitHubPRCreator:
    """
    Creates a GitHub Pull Request for an auto-resolved fix.

    Workflow:
    1. Get the default branch's latest commit SHA
    2. Create a new branch: nightingale/fix-{incident_id}
    3. Commit all changed files to that branch
    4. Open a PR with a rich description
    """

    BASE_URL = "https://api.github.com"

    def __init__(self, token: str, repo: str):
        """
        Args:
            token: GitHub personal access token (repo scope)
            repo: Repository in "owner/repo" format
        """
        self.token = token
        self.repo = repo
        self.headers = {
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "Nightingale-SRE/1.0",
        }

    def _get(self, path: str) -> Dict[str, Any]:
        url = f"{self.BASE_URL}{path}"
        with httpx.Client(timeout=30) as client:
            r = client.get(url, headers=self.headers)
            r.raise_for_status()
            return r.json()

    def _post(self, path: str, data: Dict) -> Dict[str, Any]:
        url = f"{self.BASE_URL}{path}"
        with httpx.Client(timeout=30) as client:
            r = client.post(url, headers=self.headers, json=data)
            r.raise_for_status()
            return r.json()

    def _put(self, path: str, data: Dict) -> Dict[str, Any]:
        url = f"{self.BASE_URL}{path}"
        with httpx.Client(timeout=30) as client:
            r = client.put(url, headers=self.headers, json=data)
            if r.status_code not in (200, 201):
                raise GitHubPRError(f"PUT {path} failed: {r.status_code} {r.text}")
            return r.json()

    def _get_default_branch(self) -> str:
        data = self._get(f"/repos/{self.repo}")
        return data.get("default_branch", "main")

    def _get_branch_sha(self, branch: str) -> str:
        data = self._get(f"/repos/{self.repo}/git/ref/heads/{branch}")
        return data["object"]["sha"]

    def _create_branch(self, branch_name: str, from_sha: str) -> str:
        self._post(f"/repos/{self.repo}/git/refs", {
            "ref": f"refs/heads/{branch_name}",
            "sha": from_sha,
        })
        return branch_name

    def _get_file_sha(self, file_path: str, branch: str) -> Optional[str]:
        """Get the blob SHA of an existing file (needed for updates)."""
        try:
            data = self._get(f"/repos/{self.repo}/contents/{file_path}?ref={branch}")
            return data.get("sha")
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return None  # File doesn't exist yet
            raise

    def _commit_file(self, file_path: str, content: str, branch: str,
                     message: str, existing_sha: Optional[str] = None):
        """Create or update a single file in the repository."""
        encoded = base64.b64encode(content.encode("utf-8")).decode("ascii")
        payload: Dict[str, Any] = {
            "message": message,
            "content": encoded,
            "branch": branch,
        }
        if existing_sha:
            payload["sha"] = existing_sha

        self._put(f"/repos/{self.repo}/contents/{file_path}", payload)

    def create_pr(
        self,
        incident_id: str,
        plan: FixPlan,
        confidence: float,
        factors: ConfidenceFactors,
        base_branch: Optional[str] = None,
    ) -> str:
        """
        Create a Pull Request with the fix.

        Returns:
            URL of the created PR
        """
        if not base_branch:
            try:
                base_branch = self._get_default_branch()
            except Exception:
                base_branch = "main"

        # Create fix branch
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        fix_branch = f"nightingale/fix-{incident_id}-{timestamp}"

        try:
            base_sha = self._get_branch_sha(base_branch)
        except Exception as e:
            raise GitHubPRError(f"Could not get base branch SHA: {e}")

        try:
            self._create_branch(fix_branch, base_sha)
        except Exception as e:
            raise GitHubPRError(f"Could not create fix branch: {e}")

        # Commit all changed files
        for i, diff in enumerate(plan.files_to_change):
            if diff.change_type == "delete":
                logger.info(f"[GitHub PR] Skipping delete for {diff.file_path} (manual review needed)")
                continue

            existing_sha = self._get_file_sha(diff.file_path, fix_branch)
            commit_msg = f"fix({diff.file_path}): Nightingale auto-fix for {incident_id}"

            try:
                self._commit_file(
                    file_path=diff.file_path,
                    content=diff.diff_content,
                    branch=fix_branch,
                    message=commit_msg,
                    existing_sha=existing_sha,
                )
                logger.info(f"[GitHub PR] Committed {diff.file_path}", component="github")
            except Exception as e:
                raise GitHubPRError(f"Failed to commit {diff.file_path}: {e}")

        # Build PR description
        files_list = "\n".join(
            f"- `{d.file_path}` [{d.change_type}]" for d in plan.files_to_change
        )

        pr_body = f"""## 🐦 Nightingale Auto-Fix

> This PR was automatically generated by [Nightingale SRE](https://github.com/maxoutlabs/nightingale-sre), an autonomous CI/CD repair agent.

---

### 🔍 Root Cause Analysis

{plan.root_cause or plan.rationale}

---

### 🔧 Fix Summary

{plan.rationale}

**Risk Level**: `{plan.risk_level.value.upper()}`
**Attempt Number**: {plan.attempt_number}/{3}

### Files Changed

{files_list}

---

### 📊 Confidence Score: {confidence:.1%}

| Factor | Score | Weight |
|--------|-------|--------|
| Test Pass Ratio | {factors.test_pass_ratio:.2f} | 35% |
| Inverse Blast Radius | {factors.inverse_blast_radius:.2f} | 25% |
| Attempt Penalty | {factors.attempt_penalty:.2f} | 15% |
| Risk Modifier | {factors.risk_modifier:.2f} | 15% |
| Self-Consistency | {factors.self_consistency_score:.2f} | 10% |
| **Weighted Total** | **{confidence:.2f}** | |

---

### ⚠️ Review Checklist

- [ ] Verify the root cause analysis is accurate
- [ ] Review all changed files
- [ ] Run the full test suite after merging
- [ ] Check for any unintended side effects

---

*Generated by Nightingale v1.0 | Incident `{incident_id}` | {datetime.now().strftime("%Y-%m-%d %Human:%M UTC")}*
"""

        pr_title = f"[Nightingale] Auto-fix: {plan.root_cause[:80] if plan.root_cause else plan.rationale[:80]}"

        try:
            pr = self._post(f"/repos/{self.repo}/pulls", {
                "title": pr_title,
                "body": pr_body,
                "head": fix_branch,
                "base": base_branch,
            })
            pr_url = pr["html_url"]
            logger.info(f"[GitHub PR] Created: {pr_url}", component="github")
            return pr_url
        except Exception as e:
            raise GitHubPRError(f"Failed to create PR: {e}")


def create_fix_pr(
    incident_id: str,
    plan: FixPlan,
    confidence: float,
    factors: ConfidenceFactors,
) -> Optional[str]:
    """
    Attempt to create a GitHub PR for the fix.
    Returns the PR URL on success, None if not configured or on error.
    """
    token = os.getenv("GITHUB_TOKEN", "") or config.get("github.token", "")
    repo = os.getenv("GITHUB_REPO", "") or config.get("github.repo", "")

    if not token or not repo:
        logger.info(
            "GitHub PR skipped — GITHUB_TOKEN or GITHUB_REPO not configured.",
            component="github",
        )
        return None

    try:
        creator = GitHubPRCreator(token=token, repo=repo)
        pr_url = creator.create_pr(
            incident_id=incident_id,
            plan=plan,
            confidence=confidence,
            factors=factors,
        )
        return pr_url
    except Exception as e:
        logger.error(f"GitHub PR creation failed: {e}", component="github")
        return None
