"""
Nightingale Blast Radius Analyzer
Calculates impact scope of proposed changes
"""
from typing import List, Dict, Set
from pathlib import Path

from nightingale.types import FileDiff, RiskLevel


class BlastRadiusAnalyzer:
    """
    Analyzes the blast radius (impact scope) of proposed changes.
    
    Factors:
    - Number of files changed vs total files
    - Types of files changed (test vs core)
    - Criticality of file paths
    """
    
    # File type risk classifications
    RISK_PATTERNS = {
        RiskLevel.LOW: [
            "test_", "_test.py", "tests/", "spec/",
            ".md", ".txt", ".rst",
            "README", "LICENSE", "CHANGELOG"
        ],
        RiskLevel.MEDIUM: [
            "utils/", "helpers/", "tools/",
            "config.", "settings."
        ],
        RiskLevel.HIGH: [
            "core/", "main.", "app.",
            "__init__.py", "base.", "models/"
        ],
        RiskLevel.CRITICAL: [
            "auth", "security", "password", "secret",
            "database", "migration", "deploy",
            ".env", "credentials"
        ]
    }
    
    def __init__(self, total_files: int):
        """
        Initialize with total file count for ratio calculation.
        
        Args:
            total_files: Total number of files in repository
        """
        self.total_files = max(total_files, 1)  # Avoid division by zero
    
    def analyze(self, changes: List[FileDiff]) -> Dict:
        """
        Analyze blast radius of proposed changes.
        
        Args:
            changes: List of proposed file changes
            
        Returns:
            Dict with metrics and scores
        """
        if not changes:
            return {
                "files_changed": 0,
                "ratio": 0.0,
                "inverse_blast_radius": 1.0,
                "risk_levels": {},
                "highest_risk": RiskLevel.LOW,
                "risk_modifier": 1.0
            }
        
        files_changed = len(changes)
        ratio = files_changed / self.total_files
        
        # Classify each file's risk
        risk_levels = {}
        for change in changes:
            risk = self._classify_file_risk(change.file_path)
            risk_levels[change.file_path] = risk
        
        # Find highest risk level
        risk_priority = [RiskLevel.LOW, RiskLevel.MEDIUM, RiskLevel.HIGH, RiskLevel.CRITICAL]
        risks = list(risk_levels.values())
        highest_risk = max(risks, key=lambda r: risk_priority.index(r))
        
        # Calculate inverse blast radius (higher = safer)
        inverse_blast_radius = 1.0 - min(ratio, 1.0)
        
        # Calculate risk modifier (higher = safer)
        risk_modifier = self._calculate_risk_modifier(risks)
        
        return {
            "files_changed": files_changed,
            "ratio": ratio,
            "inverse_blast_radius": inverse_blast_radius,
            "risk_levels": {k: v.value for k, v in risk_levels.items()},
            "highest_risk": highest_risk,
            "risk_modifier": risk_modifier
        }
    
    def _classify_file_risk(self, file_path: str) -> RiskLevel:
        """Classify risk level of a file based on its path."""
        path_lower = file_path.lower()
        
        # Check from highest to lowest risk
        for risk_level in [RiskLevel.CRITICAL, RiskLevel.HIGH, RiskLevel.MEDIUM, RiskLevel.LOW]:
            patterns = self.RISK_PATTERNS.get(risk_level, [])
            for pattern in patterns:
                if pattern in path_lower:
                    return risk_level
        
        return RiskLevel.MEDIUM  # Default
    
    def _calculate_risk_modifier(self, risks: List[RiskLevel]) -> float:
        """
        Calculate risk modifier score.
        Higher = safer (more test files, fewer critical files)
        """
        if not risks:
            return 1.0
        
        # Score each risk level
        risk_scores = {
            RiskLevel.LOW: 1.0,
            RiskLevel.MEDIUM: 0.7,
            RiskLevel.HIGH: 0.4,
            RiskLevel.CRITICAL: 0.1
        }
        
        total_score = sum(risk_scores.get(r, 0.5) for r in risks)
        return total_score / len(risks)


def calculate_inverse_blast_radius(
    changes: List[FileDiff],
    total_files: int
) -> float:
    """
    Convenience function to get inverse blast radius score.
    
    Args:
        changes: Proposed file changes
        total_files: Total files in repo
        
    Returns:
        Score between 0 and 1 (higher = smaller blast radius = safer)
    """
    analyzer = BlastRadiusAnalyzer(total_files)
    result = analyzer.analyze(changes)
    return result["inverse_blast_radius"]


def calculate_risk_modifier(
    changes: List[FileDiff],
    total_files: int
) -> float:
    """
    Convenience function to get risk modifier score.
    
    Args:
        changes: Proposed file changes
        total_files: Total files in repo
        
    Returns:
        Score between 0 and 1 (higher = safer changes)
    """
    analyzer = BlastRadiusAnalyzer(total_files)
    result = analyzer.analyze(changes)
    return result["risk_modifier"]
