import os
import git
from typing import List, Optional
from nightingale.types import IncidentEvent

class RepositoryContextLoader:
    def __init__(self, repo_path: str):
        self.repo_path = repo_path
        self.repo = git.Repo(repo_path, search_parent_directories=True)

    def get_file_content(self, file_path: str, commit_sha: str = "HEAD") -> str:
        try:
            return self.repo.git.show(f"{commit_sha}:{file_path}")
        except git.GitCommandError:
            return ""

    def get_diff(self, commit_sha: str) -> str:
        try:
            # Get diff of the commit against its parent
            return self.repo.git.show(commit_sha)
        except git.GitCommandError:
            return ""

    def get_recent_commits(self, n: int = 5) -> List[str]:
        return [str(c) for c in self.repo.iter_commits(max_count=n)]

    def list_files(self) -> List[str]:
        files = []
        for blob in self.repo.head.commit.tree.traverse():
            if blob.type == 'blob':
               files.append(blob.path)
        return files
