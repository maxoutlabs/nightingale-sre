import json
from nightingale.types import IncidentEvent, IncidentType, PipelineStep
# Assuming we will use a file or stdin as input for the listener
from typing import Optional, Dict, Any

class IncidentListener:
    def __init__(self):
        pass

    def parse_event(self, raw_data: str) -> IncidentEvent:
        """Parses raw incident data (e.g., JSON payload from webhook) into an IncidentEvent."""
        try:
            data = json.loads(raw_data)
        except json.JSONDecodeError:
            raise ValueError("Invalid JSON format for incident data.")
        
        # Simplified parsing logic for demo purposes
        # In a real scenario, this would map webhook payloads from GitHub/GitLab
        steps = []
        for step_data in data.get("steps", []):
            steps.append(PipelineStep(
                name=step_data.get("name"),
                status=step_data.get("status"),
                logs=step_data.get("logs"),
                duration_ms=step_data.get("duration_ms")
            ))

        return IncidentEvent(
            id=data.get("id"),
            type=IncidentType(data.get("type", IncidentType.PIPELINE_FAILURE)),
            repository_path=data.get("repository_path"),
            commit_sha=data.get("commit_sha"),
            branch=data.get("branch"),
            failed_steps=steps,
            metadata=data.get("metadata", {})
        )

    def listen(self, source: str = "stdin") -> Optional[IncidentEvent]:
        # Placeholder for actual listening logic (e.g. HTTP server or polling)
        # For this prototype we will read from a file or stdin
        # To be implemented based on demo requirements
        pass
