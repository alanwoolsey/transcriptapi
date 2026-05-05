from __future__ import annotations

from typing import Any


class OrchestratorProjectedWorkTool:
    queue_tool_name = "load_projected_work_queue"
    ownership_tool_name = "load_work_ownership"
    priority_tool_name = "load_work_priority"

    def load_projected_work_queue(self, payload: dict[str, Any]) -> dict[str, Any]:
        items = self._items(payload)
        limit = payload.get("limit")
        if isinstance(limit, int):
            items = items[:limit]

        queue_groups = sorted({self._value(item, "queueGroup", "queue_group") for item in items if self._value(item, "queueGroup", "queue_group")})
        return {
            "status": "completed",
            "code": "projected_work_queue_loaded",
            "message": "Projected work queue loaded.",
            "error": None,
            "metrics": {
                "totalItems": len(items),
                "queueGroupCount": len(queue_groups),
            },
            "artifacts": {
                "queueGroups": queue_groups,
                "items": [self._queue_item(item) for item in items],
            },
        }

    def load_work_ownership(self, payload: dict[str, Any]) -> dict[str, Any]:
        items = self._items(payload)
        owner_agents = sorted({self._value(item, "currentOwnerAgent", "current_owner_agent") for item in items if self._value(item, "currentOwnerAgent", "current_owner_agent")})
        recommended_agents = sorted({self._value(item, "recommendedAgent", "recommended_agent") for item in items if self._value(item, "recommendedAgent", "recommended_agent")})
        return {
            "status": "completed",
            "code": "work_ownership_loaded",
            "message": "Work ownership loaded.",
            "error": None,
            "metrics": {
                "totalItems": len(items),
                "currentOwnerAgentCount": len(owner_agents),
                "recommendedAgentCount": len(recommended_agents),
            },
            "artifacts": {
                "currentOwnerAgents": owner_agents,
                "recommendedAgents": recommended_agents,
                "items": [self._ownership_item(item) for item in items],
            },
        }

    def load_work_priority(self, payload: dict[str, Any]) -> dict[str, Any]:
        items = self._items(payload)
        priority_scores = [
            int(score)
            for item in items
            for score in [self._value(item, "priorityScore", "priority_score")]
            if isinstance(score, int)
        ]
        urgent_count = sum(1 for item in items if self._value(item, "priority") == "urgent")
        return {
            "status": "completed",
            "code": "work_priority_loaded",
            "message": "Work priority loaded.",
            "error": None,
            "metrics": {
                "totalItems": len(items),
                "urgentCount": urgent_count,
                "maxPriorityScore": max(priority_scores) if priority_scores else None,
            },
            "artifacts": {
                "items": [self._priority_item(item) for item in items],
            },
        }

    def as_strands_tools(self):
        try:
            from strands import tool
        except ImportError as exc:
            raise RuntimeError("Strands Agents is not installed.") from exc

        @tool
        def load_projected_work_queue(payload: dict[str, Any]) -> dict[str, Any]:
            """Load projected work queue rows for orchestrator prioritization."""
            return self.load_projected_work_queue(payload)

        @tool
        def load_work_ownership(payload: dict[str, Any]) -> dict[str, Any]:
            """Load current and recommended owner-agent hints for projected work."""
            return self.load_work_ownership(payload)

        @tool
        def load_work_priority(payload: dict[str, Any]) -> dict[str, Any]:
            """Load priority labels and scores for projected work."""
            return self.load_work_priority(payload)

        return [load_projected_work_queue, load_work_ownership, load_work_priority]

    def _items(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        items = payload.get("items")
        if not isinstance(items, list):
            return []
        return [item for item in items if isinstance(item, dict)]

    def _queue_item(self, item: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": self._value(item, "id"),
            "studentId": self._value(item, "studentId", "student_id"),
            "studentName": self._value(item, "studentName", "student_name"),
            "section": self._value(item, "section"),
            "queueGroup": self._value(item, "queueGroup", "queue_group"),
            "recommendedAgent": self._value(item, "recommendedAgent", "recommended_agent"),
        }

    def _ownership_item(self, item: dict[str, Any]) -> dict[str, Any]:
        return {
            "studentId": self._value(item, "studentId", "student_id"),
            "currentOwnerAgent": self._value(item, "currentOwnerAgent", "current_owner_agent"),
            "currentStage": self._value(item, "currentStage", "current_stage"),
            "recommendedAgent": self._value(item, "recommendedAgent", "recommended_agent"),
        }

    def _priority_item(self, item: dict[str, Any]) -> dict[str, Any]:
        return {
            "studentId": self._value(item, "studentId", "student_id"),
            "priority": self._value(item, "priority"),
            "priorityScore": self._value(item, "priorityScore", "priority_score"),
            "reasonToActCode": self._reason_code(item, "reasonToAct", "reason_to_act_code"),
            "suggestedActionCode": self._reason_code(item, "suggestedAction", "suggested_action_code"),
        }

    def _reason_code(self, item: dict[str, Any], object_key: str, scalar_key: str) -> Any:
        value = item.get(object_key)
        if isinstance(value, dict):
            return value.get("code")
        return item.get(scalar_key)

    def _value(self, item: dict[str, Any], *keys: str) -> Any:
        for key in keys:
            if key in item:
                return item[key]
        return None
