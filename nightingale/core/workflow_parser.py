"""
Nightingale GitHub Actions Workflow Parser
Dynamically extracts test commands from workflow files
"""
import os
import yaml
from typing import List, Dict, Optional, Any
from pathlib import Path

from nightingale.core.logger import logger


class WorkflowParser:
    """
    Parses GitHub Actions workflow files to extract test commands.
    """
    
    # Common test command patterns
    FALLBACK_COMMANDS = [
        "python -m pytest",
        "pytest",
        "npm test",
        "yarn test",
        "go test ./...",
        "cargo test"
    ]
    
    # Keywords that indicate test steps
    TEST_KEYWORDS = [
        "test", "pytest", "jest", "mocha", "rspec",
        "unittest", "nose", "check", "verify", "spec"
    ]
    
    def __init__(self, repo_path: str):
        """
        Initialize with repository path.
        
        Args:
            repo_path: Path to repository root
        """
        self.repo_path = Path(repo_path)
        self.workflows_dir = self.repo_path / ".github" / "workflows"
    
    def find_workflow_files(self) -> List[Path]:
        """Find all workflow YAML files."""
        if not self.workflows_dir.exists():
            return []
        
        workflows = []
        for pattern in ["*.yml", "*.yaml"]:
            workflows.extend(self.workflows_dir.glob(pattern))
        
        return sorted(workflows)
    
    def parse_workflow(self, workflow_path: Path) -> Dict[str, Any]:
        """
        Parse a single workflow file.
        
        Args:
            workflow_path: Path to workflow YAML
            
        Returns:
            Parsed workflow dict
        """
        try:
            with open(workflow_path, 'r', encoding='utf-8') as f:
                return yaml.safe_load(f) or {}
        except Exception as e:
            logger.warning(f"Failed to parse workflow {workflow_path}: {e}")
            return {}
    
    def extract_test_commands(self, workflow: Dict[str, Any]) -> List[str]:
        """
        Extract test commands from a parsed workflow.
        
        Args:
            workflow: Parsed workflow YAML
            
        Returns:
            List of test commands
        """
        commands = []
        
        jobs = workflow.get("jobs", {})
        for job_name, job in jobs.items():
            # Check if job name suggests testing
            is_test_job = any(kw in job_name.lower() for kw in self.TEST_KEYWORDS)
            
            steps = job.get("steps", [])
            for step in steps:
                step_name = (step.get("name", "") or "").lower()
                run_cmd = step.get("run", "")
                
                if not run_cmd:
                    continue
                
                # Check if step is a test step
                is_test_step = (
                    is_test_job or
                    any(kw in step_name for kw in self.TEST_KEYWORDS) or
                    any(kw in run_cmd.lower() for kw in self.TEST_KEYWORDS)
                )
                
                if is_test_step:
                    # Handle multi-line commands
                    for line in run_cmd.strip().split('\n'):
                        line = line.strip()
                        if line and not line.startswith('#'):
                            commands.append(line)
        
        return commands
    
    def get_test_commands(self) -> List[str]:
        """
        Get all test commands from repository workflows.
        
        Returns:
            List of test commands, or fallback if none found
        """
        all_commands = []
        
        workflow_files = self.find_workflow_files()
        
        for wf_path in workflow_files:
            workflow = self.parse_workflow(wf_path)
            commands = self.extract_test_commands(workflow)
            all_commands.extend(commands)
        
        if all_commands:
            # Deduplicate while preserving order
            seen = set()
            unique_commands = []
            for cmd in all_commands:
                if cmd not in seen:
                    seen.add(cmd)
                    unique_commands.append(cmd)
            return unique_commands
        
        # Fallback: detect based on files in repo
        return self._detect_test_framework()
    
    def _detect_test_framework(self) -> List[str]:
        """Detect test framework from repository files."""
        
        # Check for Python (pytest)
        if (self.repo_path / "pyproject.toml").exists() or \
           (self.repo_path / "setup.py").exists() or \
           (self.repo_path / "requirements.txt").exists():
            return ["python -m pytest -v"]
        
        # Check for Node.js
        if (self.repo_path / "package.json").exists():
            try:
                import json
                with open(self.repo_path / "package.json") as f:
                    pkg = json.load(f)
                    scripts = pkg.get("scripts", {})
                    if "test" in scripts:
                        return ["npm test"]
            except Exception:
                pass
            return ["npm test"]
        
        # Check for Go
        if (self.repo_path / "go.mod").exists():
            return ["go test ./..."]
        
        # Check for Rust
        if (self.repo_path / "Cargo.toml").exists():
            return ["cargo test"]
        
        # Default fallback for Python
        return ["python -m pytest -v"]
    
    def get_workflow_info(self) -> Dict[str, Any]:
        """
        Get comprehensive workflow information.
        
        Returns:
            Dict with workflow metadata
        """
        workflow_files = self.find_workflow_files()
        
        info = {
            "workflows_found": len(workflow_files),
            "workflow_files": [str(wf.name) for wf in workflow_files],
            "test_commands": self.get_test_commands(),
            "has_ci": len(workflow_files) > 0
        }
        
        return info


def get_test_commands(repo_path: str) -> List[str]:
    """
    Convenience function to get test commands for a repository.
    
    Args:
        repo_path: Path to repository
        
    Returns:
        List of test commands
    """
    parser = WorkflowParser(repo_path)
    return parser.get_test_commands()
