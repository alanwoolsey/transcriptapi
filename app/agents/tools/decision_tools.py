from __future__ import annotations

from typing import Any


class DecisionPacketAssemblyTool:
    action_type = "assemble_decision_context"
    tool_name = "assemble_decision_context"

    def assemble_decision_context(self, payload: dict[str, Any]) -> dict[str, Any]:
        metrics: dict[str, Any] = {}
        for source_key, target_key in [
            ("status", "status"),
            ("readiness", "readiness"),
            ("trust_status", "trustStatus"),
            ("trust_signal_count", "trustSignalCount"),
            ("active_trust_signal_count", "activeTrustSignalCount"),
            ("document_count", "documentCount"),
        ]:
            value = payload.get(source_key)
            if value is not None:
                metrics[target_key] = value

        artifacts: dict[str, Any] = {"decisionId": payload.get("decision_id")}
        for source_key, target_key in [
            ("student_id", "studentId"),
            ("transcript_id", "transcriptId"),
            ("readiness_reason", "readinessReason"),
            ("institution", "institution"),
            ("gpa", "gpa"),
            ("credits_earned", "creditsEarned"),
            ("parser_confidence", "parserConfidence"),
        ]:
            value = payload.get(source_key)
            if value is not None:
                artifacts[target_key] = value

        return {
            "status": "completed",
            "code": "decision_context_assembled",
            "message": "Decision context assembled.",
            "error": None,
            "metrics": metrics,
            "artifacts": artifacts,
        }

    def as_strands_tool(self):
        try:
            from strands import tool
        except ImportError as exc:
            raise RuntimeError("Strands Agents is not installed.") from exc

        @tool
        def assemble_decision_context(payload: dict[str, Any]) -> dict[str, Any]:
            """Assemble deterministic decision packet context for recommendation generation."""
            return self.assemble_decision_context(payload)

        return assemble_decision_context


class DecisionReadinessEvidenceTool:
    readiness_tool_name = "load_decision_readiness"
    trust_tool_name = "load_decision_trust_status"
    evidence_tool_name = "load_decision_supporting_evidence"

    def _base_artifacts(self, payload: dict[str, Any]) -> dict[str, Any]:
        artifacts: dict[str, Any] = {"decisionId": payload.get("decision_id")}
        for source_key, target_key in [
            ("student_id", "studentId"),
            ("transcript_id", "transcriptId"),
        ]:
            value = payload.get(source_key)
            if value is not None:
                artifacts[target_key] = value
        return artifacts

    def load_decision_readiness(self, payload: dict[str, Any]) -> dict[str, Any]:
        metrics: dict[str, Any] = {}
        for source_key, target_key in [
            ("status", "status"),
            ("readiness", "readiness"),
        ]:
            value = payload.get(source_key)
            if value is not None:
                metrics[target_key] = value

        artifacts = self._base_artifacts(payload)
        readiness_reason = payload.get("readiness_reason")
        if readiness_reason is not None:
            artifacts["readinessReason"] = readiness_reason

        return {
            "status": "completed",
            "code": "decision_readiness_loaded",
            "message": "Decision readiness loaded.",
            "error": None,
            "metrics": metrics,
            "artifacts": artifacts,
        }

    def load_decision_trust_status(self, payload: dict[str, Any]) -> dict[str, Any]:
        metrics: dict[str, Any] = {}
        for source_key, target_key in [
            ("trust_status", "trustStatus"),
            ("trust_signal_count", "trustSignalCount"),
            ("active_trust_signal_count", "activeTrustSignalCount"),
        ]:
            value = payload.get(source_key)
            if value is not None:
                metrics[target_key] = value

        return {
            "status": "completed",
            "code": "decision_trust_status_loaded",
            "message": "Decision trust status loaded.",
            "error": None,
            "metrics": metrics,
            "artifacts": self._base_artifacts(payload),
        }

    def load_decision_supporting_evidence(self, payload: dict[str, Any]) -> dict[str, Any]:
        metrics: dict[str, Any] = {}
        document_count = payload.get("document_count")
        if document_count is not None:
            metrics["documentCount"] = document_count

        artifacts = self._base_artifacts(payload)
        for source_key, target_key in [
            ("institution", "institution"),
            ("gpa", "gpa"),
            ("credits_earned", "creditsEarned"),
            ("parser_confidence", "parserConfidence"),
        ]:
            value = payload.get(source_key)
            if value is not None:
                artifacts[target_key] = value

        return {
            "status": "completed",
            "code": "decision_supporting_evidence_loaded",
            "message": "Decision supporting evidence loaded.",
            "error": None,
            "metrics": metrics,
            "artifacts": artifacts,
        }

    def as_strands_tools(self):
        try:
            from strands import tool
        except ImportError as exc:
            raise RuntimeError("Strands Agents is not installed.") from exc

        @tool
        def load_decision_readiness(payload: dict[str, Any]) -> dict[str, Any]:
            """Load deterministic readiness status and rationale for a decision packet."""
            return self.load_decision_readiness(payload)

        @tool
        def load_decision_trust_status(payload: dict[str, Any]) -> dict[str, Any]:
            """Load trust status signals that should constrain decision recommendation."""
            return self.load_decision_trust_status(payload)

        @tool
        def load_decision_supporting_evidence(payload: dict[str, Any]) -> dict[str, Any]:
            """Load transcript and document evidence supporting a decision recommendation."""
            return self.load_decision_supporting_evidence(payload)

        return [
            load_decision_readiness,
            load_decision_trust_status,
            load_decision_supporting_evidence,
        ]
