from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


class LifecycleCohortTool:
    cohort_tool_name = "load_admit_to_deposit_cohort"

    def load_admit_to_deposit_cohort(self, payload: dict[str, Any]) -> dict[str, Any]:
        students = [
            student
            for student in self._students(payload)
            if self._stage(student) in {"admitted", "deposited", "high intent", "decision ready", "decision-ready"}
        ]
        return {
            "status": "completed",
            "code": "admit_to_deposit_cohort_loaded",
            "message": "Admit-to-deposit cohort loaded.",
            "error": None,
            "metrics": {
                "studentCount": len(students),
                "highFitCount": sum(1 for student in students if self._int_value(student, "fitScore", "fit_score") >= 80),
            },
            "artifacts": {
                "cohort": "admit_to_deposit",
                "studentIds": [self._value(student, "studentId", "student_id", "id") for student in students],
                "students": [self._student_summary(student) for student in students],
            },
        }

    def as_strands_tools(self):
        try:
            from strands import tool
        except ImportError as exc:
            raise RuntimeError("Strands Agents is not installed.") from exc

        @tool
        def load_admit_to_deposit_cohort(payload: dict[str, Any]) -> dict[str, Any]:
            """Load students in the admit-to-deposit lifecycle cohort."""
            return self.load_admit_to_deposit_cohort(payload)

        return [load_admit_to_deposit_cohort]

    def _student_summary(self, student: dict[str, Any]) -> dict[str, Any]:
        return {
            "studentId": self._value(student, "studentId", "student_id", "id"),
            "studentName": self._value(student, "studentName", "student_name", "name"),
            "stage": self._value(student, "stage"),
            "fitScore": self._value(student, "fitScore", "fit_score"),
            "depositLikelihood": self._value(student, "depositLikelihood", "deposit_likelihood"),
        }

    def _stage(self, student: dict[str, Any]) -> str:
        return str(self._value(student, "stage") or "").strip().lower().replace("_", " ")

    def _students(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        students = payload.get("students")
        if not isinstance(students, list):
            return []
        return [student for student in students if isinstance(student, dict)]

    def _int_value(self, item: dict[str, Any], *keys: str) -> int:
        value = self._value(item, *keys)
        try:
            return int(value)
        except Exception:
            return 0

    def _value(self, item: dict[str, Any], *keys: str) -> Any:
        for key in keys:
            if key in item:
                return item[key]
        return None


class LifecycleScoringTool:
    deposit_tool_name = "score_deposit_likelihood"
    melt_tool_name = "score_melt_risk"

    def score_deposit_likelihood(self, payload: dict[str, Any]) -> dict[str, Any]:
        students = self._students(payload)
        scored = [self._deposit_score(student) for student in students]
        return {
            "status": "completed",
            "code": "deposit_likelihood_scored",
            "message": "Deposit likelihood scored.",
            "error": None,
            "metrics": {
                "studentCount": len(scored),
                "highLikelihoodCount": sum(1 for item in scored if item["depositLikelihood"] >= 70),
            },
            "artifacts": {
                "students": scored,
            },
        }

    def score_melt_risk(self, payload: dict[str, Any]) -> dict[str, Any]:
        students = self._students(payload)
        scored = [self._melt_score(student) for student in students]
        return {
            "status": "completed",
            "code": "melt_risk_scored",
            "message": "Melt risk scored.",
            "error": None,
            "metrics": {
                "studentCount": len(scored),
                "highRiskCount": sum(1 for item in scored if item["meltRisk"] >= 50),
            },
            "artifacts": {
                "students": scored,
            },
        }

    def as_strands_tools(self):
        try:
            from strands import tool
        except ImportError as exc:
            raise RuntimeError("Strands Agents is not installed.") from exc

        @tool
        def score_deposit_likelihood(payload: dict[str, Any]) -> dict[str, Any]:
            """Score deterministic deposit likelihood for lifecycle recommendations."""
            return self.score_deposit_likelihood(payload)

        @tool
        def score_melt_risk(payload: dict[str, Any]) -> dict[str, Any]:
            """Score deterministic melt risk for lifecycle recommendations."""
            return self.score_melt_risk(payload)

        return [score_deposit_likelihood, score_melt_risk]

    def _deposit_score(self, student: dict[str, Any]) -> dict[str, Any]:
        existing = self._optional_int(student, "depositLikelihood", "deposit_likelihood")
        if existing is not None:
            score = existing
        else:
            fit_score = self._int_value(student, "fitScore", "fit_score")
            risk = str(self._value(student, "risk") or "").lower()
            score = fit_score - 18
            if risk == "medium":
                score -= 12
            if risk == "high":
                score = 20
            score = max(10, min(85, score))
        return {
            "studentId": self._value(student, "studentId", "student_id", "id"),
            "depositLikelihood": score,
            "rationale": self._deposit_rationale(student, score),
        }

    def _melt_score(self, student: dict[str, Any]) -> dict[str, Any]:
        existing = self._optional_int(student, "meltRisk", "melt_risk")
        if existing is not None:
            score = existing
        else:
            missing = self._missing_milestones(student)
            risk = str(self._value(student, "risk") or "").lower()
            deposit = self._optional_int(student, "depositLikelihood", "deposit_likelihood")
            score = len(missing) * 18
            if risk == "medium":
                score += 12
            if risk == "high":
                score += 40
            if deposit is not None and deposit < 50:
                score += 15
            score = max(0, min(100, score))
        return {
            "studentId": self._value(student, "studentId", "student_id", "id"),
            "meltRisk": score,
            "missingMilestones": self._missing_milestones(student),
            "rationale": self._melt_rationale(student, score),
        }

    def _deposit_rationale(self, student: dict[str, Any], score: int) -> list[str]:
        rationale = [f"Deposit likelihood is {score}%."]
        fit_score = self._optional_int(student, "fitScore", "fit_score")
        if fit_score is not None:
            rationale.append(f"Fit score is {fit_score}.")
        risk = self._value(student, "risk")
        if risk:
            rationale.append(f"Risk level is {risk}.")
        return rationale

    def _melt_rationale(self, student: dict[str, Any], score: int) -> list[str]:
        rationale = [f"Melt risk is {score}%."]
        missing = self._missing_milestones(student)
        if missing:
            rationale.append(f"Missing milestones: {', '.join(missing)}.")
        else:
            rationale.append("No missing milestones are recorded.")
        return rationale

    def _students(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        students = payload.get("students")
        if not isinstance(students, list):
            return []
        return [student for student in students if isinstance(student, dict)]

    def _missing_milestones(self, student: dict[str, Any]) -> list[str]:
        value = self._value(student, "missingMilestones", "missing_milestones")
        if not isinstance(value, list):
            return []
        return [str(item) for item in value if str(item).strip()]

    def _optional_int(self, item: dict[str, Any], *keys: str) -> int | None:
        value = self._value(item, *keys)
        if value is None:
            return None
        try:
            return int(value)
        except Exception:
            return None

    def _int_value(self, item: dict[str, Any], *keys: str) -> int:
        return self._optional_int(item, *keys) or 0

    def _value(self, item: dict[str, Any], *keys: str) -> Any:
        for key in keys:
            if key in item:
                return item[key]
        return None


class LifecycleInterventionTool:
    intervention_tool_name = "log_lifecycle_intervention"
    outreach_tool_name = "log_lifecycle_outreach"

    def log_lifecycle_intervention(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._log_action(
            payload,
            code="lifecycle_intervention_logged",
            message="Lifecycle intervention logged.",
            action_type="intervention",
        )

    def log_lifecycle_outreach(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._log_action(
            payload,
            code="lifecycle_outreach_logged",
            message="Lifecycle outreach logged.",
            action_type="outreach",
        )

    def as_strands_tools(self):
        try:
            from strands import tool
        except ImportError as exc:
            raise RuntimeError("Strands Agents is not installed.") from exc

        @tool
        def log_lifecycle_intervention(payload: dict[str, Any]) -> dict[str, Any]:
            """Record a normalized lifecycle intervention action for backend persistence."""
            return self.log_lifecycle_intervention(payload)

        @tool
        def log_lifecycle_outreach(payload: dict[str, Any]) -> dict[str, Any]:
            """Record a normalized lifecycle outreach action for backend persistence."""
            return self.log_lifecycle_outreach(payload)

        return [log_lifecycle_intervention, log_lifecycle_outreach]

    def _log_action(self, payload: dict[str, Any], *, code: str, message: str, action_type: str) -> dict[str, Any]:
        student_id = payload.get("studentId") or payload.get("student_id")
        channel = payload.get("channel")
        note = payload.get("note")
        recommended_action = payload.get("recommendedAction") or payload.get("recommended_action")
        return {
            "status": "completed",
            "code": code,
            "message": message,
            "error": None,
            "metrics": {
                "hasNote": bool(note),
            },
            "artifacts": {
                "actionType": action_type,
                "studentId": student_id,
                "channel": channel,
                "recommendedAction": recommended_action,
                "note": note,
                "loggedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            },
        }
