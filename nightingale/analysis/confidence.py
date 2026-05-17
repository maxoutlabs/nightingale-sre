"""
Nightingale Confidence Scoring
Weighted multi-factor confidence calculation
"""
from typing import Optional

from nightingale.types import (
    FixPlan, VerificationResult, ConfidenceFactors, RiskLevel
)
from nightingale.analysis.blast_radius import BlastRadiusAnalyzer


class ConfidenceScorer:
    """
    Calculates confidence score using weighted factors.
    
    Formula:
    confidence = weighted(
        test_pass_ratio,      # 35% - % of tests passing
        inverse_blast_radius, # 25% - smaller change = safer
        attempt_penalty,      # 15% - fewer attempts = more confidence
        risk_modifier,        # 15% - file risk levels
        self_consistency      # 10% - model self-reported confidence
    )
    """
    
    # Weights for each factor
    WEIGHTS = {
        "test_pass_ratio": 0.35,
        "inverse_blast_radius": 0.25,
        "attempt_penalty": 0.15,
        "risk_modifier": 0.15,
        "self_consistency_score": 0.10
    }
    
    # Attempt penalties
    ATTEMPT_PENALTIES = {
        1: 1.0,   # First attempt - no penalty
        2: 0.7,   # Second attempt - 30% penalty
        3: 0.4    # Third attempt - 60% penalty
    }
    
    def __init__(self, total_files: int = 100):
        """
        Initialize scorer.
        
        Args:
            total_files: Total files in repo for blast radius calculation
        """
        self.total_files = total_files
        self.blast_analyzer = BlastRadiusAnalyzer(total_files)
    
    def calculate(
        self,
        plan: FixPlan,
        result: VerificationResult,
        attempt_number: int = 1
    ) -> tuple[float, ConfidenceFactors]:
        """
        Calculate confidence score with all factors.
        
        Args:
            plan: The fix plan
            result: Verification result
            attempt_number: Which attempt this is (1-3)
            
        Returns:
            (final_score, factors) tuple
        """
        # Factor 1: Test pass ratio
        test_pass_ratio = result.pass_ratio if result.success else 0.0
        
        # Factor 2: Inverse blast radius
        blast_result = self.blast_analyzer.analyze(plan.files_to_change)
        inverse_blast_radius = blast_result["inverse_blast_radius"]
        
        # Factor 3: Attempt penalty
        attempt_penalty = self.ATTEMPT_PENALTIES.get(attempt_number, 0.3)
        
        # Factor 4: Risk modifier
        risk_modifier = blast_result["risk_modifier"]
        
        # Factor 5: Self-consistency (model's own confidence)
        self_consistency_score = plan.confidence_score
        
        # Create factors object
        factors = ConfidenceFactors(
            test_pass_ratio=test_pass_ratio,
            inverse_blast_radius=inverse_blast_radius,
            attempt_penalty=attempt_penalty,
            risk_modifier=risk_modifier,
            self_consistency_score=self_consistency_score
        )
        
        # Calculate weighted score
        final_score = factors.weighted_score()
        
        # Clamp to [0, 1]
        final_score = max(0.0, min(1.0, final_score))
        
        return final_score, factors
    
    def calculate_simple(
        self,
        plan: FixPlan,
        result: VerificationResult
    ) -> float:
        """
        Simple confidence calculation for backward compatibility.
        
        Args:
            plan: The fix plan
            result: Verification result
            
        Returns:
            Confidence score between 0 and 1
        """
        score, _ = self.calculate(plan, result, plan.attempt_number)
        return score


class ResolutionEngine:
    """
    Decides whether to resolve autonomously or escalate to human.
    """
    
    # Thresholds
    RESOLVE_THRESHOLD = 0.85  # Above this = auto-resolve
    ESCALATE_THRESHOLD = 0.60  # Below this = definitely escalate
    
    def __init__(self, resolve_threshold: float = 0.85):
        """
        Initialize with custom threshold.
        
        Args:
            resolve_threshold: Minimum confidence to auto-resolve
        """
        self.resolve_threshold = resolve_threshold
    
    def decide(self, confidence_score: float, factors: Optional[ConfidenceFactors] = None) -> str:
        """
        Decide whether to resolve or escalate.
        
        Args:
            confidence_score: Overall confidence score
            factors: Individual factors (for additional checks)
            
        Returns:
            "resolve" or "escalate"
        """
        # Hard threshold check
        if confidence_score >= self.resolve_threshold:
            # Additional safety checks if factors provided
            if factors:
                # Never auto-resolve critical file changes with low test coverage
                if factors.test_pass_ratio < 0.5:
                    return "escalate"
                # Never auto-resolve if blast radius is too high
                if factors.inverse_blast_radius < 0.3:
                    return "escalate"
            
            return "resolve"
        
        return "escalate"
    
    def explain_decision(
        self,
        decision: str,
        confidence: float,
        factors: ConfidenceFactors
    ) -> str:
        """
        Generate explanation for the decision.
        
        Args:
            decision: The decision made
            confidence: Confidence score
            factors: Individual factors
            
        Returns:
            Human-readable explanation
        """
        explanations = []
        
        if decision == "resolve":
            explanations.append(f"Confidence {confidence:.1%} exceeds threshold {self.resolve_threshold:.1%}")
            if factors.test_pass_ratio >= 0.9:
                explanations.append("All tests passing")
            if factors.inverse_blast_radius >= 0.9:
                explanations.append("Minimal code changes")
        else:
            if confidence < self.resolve_threshold:
                explanations.append(f"Confidence {confidence:.1%} below threshold {self.resolve_threshold:.1%}")
            if factors.test_pass_ratio < 0.9:
                explanations.append(f"Test pass ratio: {factors.test_pass_ratio:.1%}")
            if factors.attempt_penalty < 0.7:
                explanations.append("Multiple attempts needed")
            if factors.risk_modifier < 0.5:
                explanations.append("High-risk files modified")
        
        return "; ".join(explanations)
