"""
Nightingale Verification Agent
Executes verification commands and parses results
"""
import re
import time
from typing import Tuple

from nightingale.types import FixPlan, VerificationResult
from nightingale.core.sandbox import Sandbox
from nightingale.core.logger import logger


class VerificationAgent:
    """
    Executes verification steps and analyzes results.
    """
    
    def __init__(self):
        pass
    
    def verify(self, sandbox: Sandbox, plan: FixPlan) -> VerificationResult:
        """
        Execute verification commands in sandbox.
        
        Args:
            sandbox: Sandbox environment
            plan: Fix plan with verification steps
            
        Returns:
            VerificationResult with detailed metrics
        """
        start_time = time.time()
        combined_logs = ""
        success = True
        total_passed = 0
        total_failed = 0
        total_tests = 0
        last_exit_code = 0
        
        for cmd in plan.verification_steps:
            code, stdout, stderr = sandbox.run_command(cmd)
            combined_logs += f"\n{'='*50}\nCMD: {cmd}\nEXIT CODE: {code}\n{'='*50}\n"
            combined_logs += f"STDOUT:\n{stdout}\n"
            if stderr:
                combined_logs += f"STDERR:\n{stderr}\n"
            
            last_exit_code = code
            
            # Parse test results
            passed, failed, total = self._parse_test_output(stdout + stderr)
            total_passed += passed
            total_failed += failed
            total_tests += total
            
            if code != 0:
                success = False
                # Log but continue to collect all verification data
                logger.verification_result(
                    incident_id="",
                    success=False,
                    passed=total_passed,
                    failed=total_failed,
                    total=total_tests
                )
        
        duration_ms = int((time.time() - start_time) * 1000)
        
        # If we couldn't parse test counts, estimate from success
        if total_tests == 0 and success:
            total_tests = 1
            total_passed = 1
        
        result = VerificationResult(
            success=success,
            input_hash=plan.content_hash(),
            output_log=combined_logs,
            duration_ms=duration_ms,
            tests_passed=total_passed,
            tests_failed=total_failed,
            tests_total=total_tests,
            exit_code=last_exit_code
        )
        
        if success:
            logger.verification_result(
                incident_id="",
                success=True,
                passed=total_passed,
                failed=total_failed,
                total=total_tests
            )
        
        return result
    
    def _parse_test_output(self, output: str) -> Tuple[int, int, int]:
        """
        Parse test output to extract pass/fail counts.
        
        Supports:
        - pytest format
        - unittest format
        - jest/mocha format
        
        Args:
            output: Test command output
            
        Returns:
            (passed, failed, total) tuple
        """
        passed = 0
        failed = 0
        
        # Pytest format: "5 passed, 2 failed"
        pytest_match = re.search(r'(\d+)\s+passed', output)
        if pytest_match:
            passed = int(pytest_match.group(1))
        
        pytest_fail = re.search(r'(\d+)\s+failed', output)
        if pytest_fail:
            failed = int(pytest_fail.group(1))
        
        # Pytest short format: "===== 5 passed in 0.5s ====="
        if passed == 0:
            short_match = re.search(r'=+\s*(\d+)\s+passed', output)
            if short_match:
                passed = int(short_match.group(1))
        
        # unittest format: "Ran X tests"
        unittest_match = re.search(r'Ran\s+(\d+)\s+test', output)
        if unittest_match and passed == 0 and failed == 0:
            total = int(unittest_match.group(1))
            if "OK" in output:
                passed = total
            elif "FAILED" in output:
                fail_match = re.search(r'failures=(\d+)', output)
                if fail_match:
                    failed = int(fail_match.group(1))
                    passed = total - failed
        
        # Jest format: "Tests: X passed, Y failed, Z total"
        jest_match = re.search(r'Tests:\s*(\d+)\s+passed.*?(\d+)\s+failed', output)
        if jest_match:
            passed = int(jest_match.group(1))
            failed = int(jest_match.group(2))
        
        total = passed + failed
        
        return passed, failed, total
