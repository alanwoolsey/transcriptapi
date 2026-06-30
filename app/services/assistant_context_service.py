from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.api.dependencies import AuthenticatedTenantContext
from app.core.config import settings
from app.models.assistant_models import AssistantChatRequest, AssistantChatResponse, AssistantDocumentClassificationRequest, AssistantDocumentClassificationResponse, AssistantRetrievalInfo
from app.services.admissions_ops_service import AdmissionsOpsService
from app.services.student_360_service import Student360Service


@dataclass
class IntentPlan:
    intent: str
    confidence: float
    tools: list[str] = field(default_factory=list)


class AssistantContextService:
    def __init__(
        self,
        *,
        student_service: Student360Service | None = None,
        admissions_ops_service: AdmissionsOpsService | None = None,
    ) -> None:
        self.student_service = student_service or Student360Service()
        self.admissions_ops_service = admissions_ops_service or AdmissionsOpsService()

    def classify_document(self, payload: AssistantDocumentClassificationRequest, auth_context: AuthenticatedTenantContext) -> AssistantDocumentClassificationResponse:
        options = payload.classificationOptions or ["Application form"]
        governed_payload = {
            "message": (
                "Classify the attached student document into exactly one of the allowed options. "
                "Use visible document content if the attachment is an image. Use the filename only as a fallback. "
                "Return only compact JSON with keys: documentType, confidence, rationale. "
                f"Allowed options: {json.dumps(options)}. "
                f"Filename: {payload.fileName}. Content type: {payload.contentType}."
            ),
            "dataClassification": "confidential",
            "workspaceId": str(auth_context.tenant.id),
            "metadata": {
                "source": "crtfy_student_document_classifier",
                "tenantId": str(auth_context.tenant.id),
                "userId": str(auth_context.user.id),
            },
            "attachments": [{
                "fileName": payload.fileName,
                "contentType": payload.contentType,
                "sizeBytes": payload.sizeBytes,
                "dataBase64": payload.dataBase64,
            }],
        }
        governed_response = self.call_governed_ai(governed_payload, auth_context)
        parsed = self.parse_classification_response(governed_response.get("response", ""), options)
        return AssistantDocumentClassificationResponse(
            documentType=parsed["documentType"],
            confidence=parsed["confidence"],
            rationale=parsed["rationale"],
            policyStatus=governed_response.get("policyStatus") or "allowed",
            guardrails=list(governed_response.get("guardrails") or []),
            auditId=governed_response.get("auditId") or "",
        )

    def run_chat(self, payload: AssistantChatRequest, auth_context: AuthenticatedTenantContext) -> AssistantChatResponse:
        started = time.perf_counter()
        plan = self.plan_intent(payload)
        context_packet = self.build_context_packet(payload, auth_context, plan)
        compact_context = self.compact_context(context_packet)
        governed_payload = self.build_governed_payload(payload, compact_context, auth_context)
        governed_response = self.call_governed_ai(governed_payload, auth_context)
        retrieval = AssistantRetrievalInfo(
            intent=plan.intent,
            confidence=plan.confidence,
            toolsUsed=plan.tools,
            inputContextTokens=max(1, round(len(json.dumps(compact_context, default=str)) / 4)),
            cacheHit=False,
            sources=[citation["id"] for citation in compact_context.get("citations", [])],
        )
        latency_ms = int((time.perf_counter() - started) * 1000)
        return AssistantChatResponse(
            response=governed_response.get("response") or "The governed assistant returned an empty response.",
            policyStatus=governed_response.get("policyStatus") or "allowed",
            guardrails=list(governed_response.get("guardrails") or []),
            citations=governed_response.get("citations") or compact_context.get("citations", []),
            auditId=governed_response.get("auditId") or "",
            model=governed_response.get("model") or "",
            latencyMs=governed_response.get("latencyMs") or latency_ms,
            inputTokens=governed_response.get("inputTokens"),
            outputTokens=governed_response.get("outputTokens"),
            requiredApproval=bool(governed_response.get("requiredApproval")),
            retrieval=retrieval,
        )

    def plan_intent(self, payload: AssistantChatRequest) -> IntentPlan:
        message = payload.message.lower()
        route = (payload.route or "").lower()
        has_student = bool(payload.activeEntity and payload.activeEntity.type == "student" and payload.activeEntity.id) or "/students/" in route
        names_student = bool(self.extract_student_name(payload.message))
        if any(word in message for word in ["missing", "checklist", "required", "complete", "incomplete"]) and (has_student or names_student):
            return IntentPlan("student_checklist_question", 0.92, ["resolve_student_by_name", "get_active_student_summary", "get_student_checklist_summary", "get_student_documents_summary"])
        if any(word in message for word in ["document", "transcript", "file", "upload"]) and has_student:
            return IntentPlan("student_documents_question", 0.9, ["get_active_student_summary", "get_student_documents_summary"])
        if any(word in message for word in ["timeline", "history", "recent", "activity"]) and has_student:
            return IntentPlan("student_timeline_question", 0.86, ["get_active_student_summary", "get_student_timeline_summary"])
        if any(word in message for word in ["decision", "ready for review", "release", "blocked"]) and has_student:
            return IntentPlan("student_decision_question", 0.84, ["get_active_student_summary", "get_student_checklist_summary"])
        if any(word in message for word in ["draft", "email", "text", "message", "communicat"]) and has_student:
            return IntentPlan("student_communication_draft", 0.88, ["get_active_student_summary", "get_student_checklist_summary", "get_recent_communication_summary"])
        if any(phrase in message for phrase in ["next best", "what should i do", "what should i work", "work on next", "prioritize my", "where should i start"]):
            return IntentPlan("counselor_next_best_action", 0.88, ["get_counselor_today_work"])
        if any(word in message for word in ["which students", "students need", "who needs", "missing transcripts", "follow-up", "follow up"]):
            return IntentPlan("workflow_queue_question", 0.78, ["search_students"])
        if any(word in message for word in ["report", "how many", "count", "trend", "workload"]):
            return IntentPlan("reporting_question", 0.68, ["search_students"])
        if any(word in message for word in ["import", "csv", "template", "mapping"]) or "/utilities" in route:
            return IntentPlan("import_utility_question", 0.78, ["get_route_capabilities"])
        if any(word in message for word in ["how do i", "how to", "what can", "help"]):
            return IntentPlan("how_to_use_app", 0.72, ["get_route_capabilities"])
        if has_student:
            return IntentPlan("student_profile_question", 0.7, ["get_active_student_summary"])
        return IntentPlan("general_governed_chat", 0.55, [])

    def build_context_packet(self, payload: AssistantChatRequest, auth_context: AuthenticatedTenantContext, plan: IntentPlan) -> dict[str, Any]:
        citations: list[dict[str, Any]] = []
        retrieved: list[dict[str, Any]] = []
        packet: dict[str, Any] = {
            "contextVersion": 1,
            "tenant": {"id": str(auth_context.tenant.id), "name": auth_context.tenant.name},
            "user": {
                "id": str(auth_context.user.id),
                "displayName": auth_context.user.display_name,
                "baseRole": auth_context.authorization.base_role,
                "roles": sorted(auth_context.authorization.roles),
                "capabilities": self.assistant_capabilities(auth_context),
            },
            "route": payload.route,
            "intent": {"name": plan.intent, "confidence": plan.confidence},
            "retrieved": retrieved,
            "citations": citations,
            "restrictions": [],
        }
        active_student_id = self.resolve_active_student_id(payload)
        if not active_student_id and "resolve_student_by_name" in plan.tools and auth_context.authorization.can("view_student_360"):
            active_student_id = self.resolve_student_id_by_name(payload.message, auth_context, packet)
        if "get_active_student_summary" in plan.tools and active_student_id and auth_context.authorization.can("view_student_360"):
            student = self.student_service.get_student(auth_context.tenant.id, active_student_id, auth_context.authorization)
            if student:
                summary = self.student_summary(student)
                packet["activeEntity"] = {"type": "student", "id": active_student_id, "summary": summary}
                retrieved.append({"sourceId": f"{active_student_id}:summary", "type": "student_summary", "summary": summary})
                citations.append({"id": f"{active_student_id}:summary", "label": f"Student summary for {summary.get('name')}", "type": "student_summary", "route": f"/students/{active_student_id}"})
        if "get_student_checklist_summary" in plan.tools and active_student_id and auth_context.authorization.can("view_student_360"):
            try:
                checklist = self.admissions_ops_service.get_student_checklist(auth_context.tenant.id, active_student_id)
                summary = self.checklist_summary(checklist)
                retrieved.append({"sourceId": f"{active_student_id}:checklist", "type": "checklist_summary", "summary": summary})
                citations.append({"id": f"{active_student_id}:checklist", "label": "Student checklist", "type": "student_checklist", "route": f"/students/{active_student_id}?tab=checklist"})
                packet["answerFocus"] = self.answer_focus_for_checklist_question(packet, summary)
            except Exception:
                packet["restrictions"].append({"type": "checklist_summary", "reason": "Checklist data unavailable."})
        if "get_student_documents_summary" in plan.tools and active_student_id and auth_context.authorization.can("view_student_360"):
            student = self.student_service.get_student(auth_context.tenant.id, active_student_id, auth_context.authorization)
            if student:
                summary = self.documents_summary(student)
                retrieved.append({"sourceId": f"{active_student_id}:documents", "type": "documents_summary", "summary": summary})
                citations.append({"id": f"{active_student_id}:documents", "label": "Student documents", "type": "student_documents", "route": f"/students/{active_student_id}?tab=documents"})
        if "get_student_timeline_summary" in plan.tools and active_student_id and auth_context.authorization.can("view_student_360"):
            timeline = self.student_service.get_student_timeline(auth_context.tenant.id, active_student_id, auth_context.authorization)
            if timeline:
                events = [self.model_dump(event) for event in timeline.events[:8]]
                retrieved.append({"sourceId": f"{active_student_id}:timeline", "type": "timeline_summary", "summary": {"events": events, "count": len(timeline.events)}})
                citations.append({"id": f"{active_student_id}:timeline", "label": "Student timeline", "type": "student_timeline", "route": f"/students/{active_student_id}?tab=timeline"})
        if "get_recent_communication_summary" in plan.tools and active_student_id and auth_context.authorization.can("view_student_360"):
            student = self.student_service.get_student(auth_context.tenant.id, active_student_id, auth_context.authorization)
            interactions = list(getattr(student, "interactions", None) or []) if student else []
            communications = [item for item in interactions if item.get("type") == "communication"][:5]
            retrieved.append({"sourceId": f"{active_student_id}:communications", "type": "communication_summary", "summary": {"recent": communications, "count": len(communications)}})
            citations.append({"id": f"{active_student_id}:communications", "label": "Student communications", "type": "student_communications", "route": f"/students/{active_student_id}?tab=outreach"})
        if "search_students" in plan.tools and auth_context.authorization.can("view_student_360"):
            search = self.student_service.list_students(auth_context.tenant.id, q=None, limit=10, offset=0)
            students = [self.student_list_summary(item) for item in search.students[:10]]
            retrieved.append({"sourceId": "students:search", "type": "student_search", "summary": {"students": students, "total": search.total}})
            citations.append({"id": "students:search", "label": "Student search results", "type": "student_search", "route": "/students"})
        if "get_counselor_today_work" in plan.tools and auth_context.authorization.can("view_student_360"):
            today_work = self.admissions_ops_service.get_counselor_today_work(auth_context.tenant.id, limit=75)
            summary = self.counselor_today_work_summary(today_work, auth_context)
            retrieved.append({"sourceId": "work:counselor_today", "type": "counselor_today_work", "summary": summary})
            citations.append({"id": "work:counselor_today", "label": "Counselor today's work", "type": "work_queue", "route": "/work/counselor/today"})
            packet["answerFocus"] = self.answer_focus_for_counselor_next_action(summary)
        if "get_route_capabilities" in plan.tools:
            retrieved.append({"sourceId": "app:route_capabilities", "type": "app_help", "summary": self.route_capabilities(payload.route)})
            citations.append({"id": "app:route_capabilities", "label": "crtfy Student route capabilities", "type": "app_help", "route": payload.route})
        return packet

    def compact_context(self, packet: dict[str, Any]) -> dict[str, Any]:
        max_chars = max(1000, settings.assistant_context_max_chars)
        compact = dict(packet)
        while len(json.dumps(compact, default=str)) > max_chars and compact.get("retrieved"):
            last = compact["retrieved"][-1]
            summary = last.get("summary")
            if isinstance(summary, dict):
                for key in ("events", "students", "recent", "documents", "transcripts"):
                    if isinstance(summary.get(key), list) and len(summary[key]) > 3:
                        summary[key] = summary[key][:3]
                        break
                else:
                    compact["retrieved"].pop()
            else:
                compact["retrieved"].pop()
        return compact

    def build_governed_payload(self, payload: AssistantChatRequest, context_packet: dict[str, Any], auth_context: AuthenticatedTenantContext) -> dict[str, Any]:
        context_text = json.dumps(context_packet, default=str, separators=(",", ":"))
        message = (
            "Answer the user's crtfy Student question using only the authorized application context below. "
            "First use ANSWER_FOCUS_JSON when present; it contains the broker's best task-specific data. "
            "Use APP_CONTEXT_JSON only to support or clarify the answer. "
            "If a named student cannot be resolved or the needed data is absent, say what is missing from context. "
            "Do not reveal data that is absent from the context. Cite source labels when using context.\n\n"
            f"ANSWER_FOCUS_JSON:\n{json.dumps(context_packet.get('answerFocus') or {}, default=str, separators=(',', ':'))}\n\n"
            f"APP_CONTEXT_JSON:\n{context_text}\n\nUSER_MESSAGE:\n{payload.message}"
        )
        return {
            "message": message,
            "dataClassification": "internal",
            "workspaceId": str(auth_context.tenant.id),
            "metadata": {
                "source": "crtfy_student_context_broker",
                "intent": context_packet.get("intent", {}).get("name"),
                "route": payload.route,
                "tenantId": str(auth_context.tenant.id),
                "userId": str(auth_context.user.id),
            },
            **({"attachments": [attachment.model_dump() for attachment in payload.attachments]} if payload.attachments else {}),
        }

    @staticmethod
    def assistant_capabilities(auth_context: AuthenticatedTenantContext) -> dict[str, Any]:
        authorization = auth_context.authorization
        return {
            "canViewStudents": authorization.can("view_student_360"),
            "canViewChecklists": authorization.can("view_checklist") or authorization.can("view_student_360"),
            "canEditChecklists": authorization.can("edit_checklist"),
            "canViewDocuments": authorization.can("view_document_metadata"),
            "canUploadDocuments": authorization.can("upload_documents"),
            "canViewDecisions": authorization.can("view_decision_packet"),
            "canViewDashboards": authorization.can("view_dashboards"),
            "canViewTrustFlags": authorization.can("view_trust_flags"),
            "sensitivityAccess": {
                "basicProfile": authorization.can_access_tier("basic_profile"),
                "academicRecord": authorization.can_access_tier("academic_record"),
                "notes": authorization.can_access_tier("notes"),
                "releasedDecisions": authorization.can_access_tier("released_decisions"),
            },
        }

    def call_governed_ai(self, governed_payload: dict[str, Any], auth_context: AuthenticatedTenantContext) -> dict[str, Any]:
        base_url = (settings.governed_ai_url or settings.chat_url or "").rstrip("/")
        if not base_url:
            return {
                "response": "The governed assistant is not configured on the backend. Set GOVERNED_AI_URL to enable app-aware chat.",
                "policyStatus": "blocked",
                "guardrails": ["governed_ai_not_configured"],
                "citations": [],
            }
        with httpx.Client(timeout=settings.governed_ai_request_timeout_seconds) as client:
            headers = {"X-Tenant-Id": str(auth_context.tenant.id)}
            if auth_context.claims.get("raw_token"):
                headers["Authorization"] = f"Bearer {auth_context.claims['raw_token']}"
            response = client.post(
                f"{base_url}/api/agent/run",
                json=governed_payload,
                headers=headers,
            )
        try:
            payload = response.json()
        except ValueError:
            payload = {"response": response.text}
        if response.status_code >= 400:
            return {
                "response": payload.get("detail") or payload.get("message") or payload.get("error") or "The governed assistant rejected this request.",
                "policyStatus": "blocked",
                "guardrails": ["governed_ai_error"],
                "citations": [],
            }
        return payload

    @staticmethod
    def parse_classification_response(response_text: str, options: list[str]) -> dict[str, Any]:
        fallback = options[0] if options else "Application form"
        text = (response_text or "").strip()
        try:
            parsed = json.loads(text)
        except ValueError:
            start = text.find("{")
            end = text.rfind("}")
            if start >= 0 and end > start:
                try:
                    parsed = json.loads(text[start:end + 1])
                except ValueError:
                    parsed = {}
            else:
                parsed = {}
        requested_type = str(parsed.get("documentType") or parsed.get("document_type") or "").strip()
        matched_type = next((option for option in options if option.lower() == requested_type.lower()), "")
        if not matched_type:
            lowered = text.lower()
            matched_type = next((option for option in options if option.lower() in lowered), fallback)
        confidence = parsed.get("confidence", 0.0)
        try:
            confidence = float(confidence)
        except (TypeError, ValueError):
            confidence = 0.0
        if confidence > 1:
            confidence = confidence / 100
        return {
            "documentType": matched_type,
            "confidence": max(0.0, min(confidence, 1.0)),
            "rationale": str(parsed.get("rationale") or "Classified by governed AI.").strip(),
        }

    @staticmethod
    def resolve_active_student_id(payload: AssistantChatRequest) -> str | None:
        if payload.activeEntity and payload.activeEntity.type == "student" and payload.activeEntity.id:
            return payload.activeEntity.id
        route = payload.route or ""
        parts = [part for part in route.split("/") if part]
        if len(parts) >= 2 and parts[0] == "students":
            return parts[1]
        return None

    def resolve_student_id_by_name(self, message: str, auth_context: AuthenticatedTenantContext, packet: dict[str, Any]) -> str | None:
        student_name = self.extract_student_name(message)
        if not student_name:
            return None
        search = self.student_service.list_students(auth_context.tenant.id, q=student_name, limit=5, offset=0)
        matches = [self.student_list_summary(item) for item in search.students[:5]]
        packet["studentResolution"] = {
            "query": student_name,
            "matchCount": len(matches),
            "matches": matches,
        }
        if len(matches) == 1 and matches[0].get("id"):
            return str(matches[0]["id"])
        exact_matches = [item for item in matches if str(item.get("name", "")).lower() == student_name.lower() and item.get("id")]
        if len(exact_matches) == 1:
            return str(exact_matches[0]["id"])
        if matches:
            packet["restrictions"].append({"type": "student_resolution", "reason": "Multiple possible students matched the requested name."})
        return None

    @staticmethod
    def extract_student_name(message: str) -> str | None:
        text = " ".join((message or "").strip().split())
        patterns = [
            r"\bstudent\s+([A-Z][A-Za-z' -]+?)(?:\s+(?:missing|need|needs|required|complete|incomplete)\b|[?.!,]|$)",
            r"\bfor\s+([A-Z][A-Za-z' -]+?)(?:\s+(?:missing|need|needs|required|complete|incomplete)\b|[?.!,]|$)",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                name = match.group(1).strip(" ?.!,")
                name = re.sub(r"^(student|the student)\s+", "", name, flags=re.IGNORECASE).strip()
                if len(name.split()) >= 2:
                    return " ".join(part.capitalize() for part in name.split())
        return None

    @staticmethod
    def model_dump(value: Any) -> dict[str, Any]:
        if hasattr(value, "model_dump"):
            return value.model_dump(by_alias=True, exclude_none=True)
        if isinstance(value, dict):
            return value
        return dict(value)

    def student_summary(self, student: Any) -> dict[str, Any]:
        data = self.model_dump(student)
        return {key: data.get(key) for key in ("id", "name", "email", "program", "stage", "risk", "advisor", "nextBestAction", "lastActivity") if data.get(key) is not None}

    def student_list_summary(self, student: Any) -> dict[str, Any]:
        data = self.model_dump(student)
        return {key: data.get(key) for key in ("id", "name", "program", "stage", "risk", "advisor", "nextBestAction") if data.get(key) is not None}

    def documents_summary(self, student: Any) -> dict[str, Any]:
        data = self.model_dump(student)
        transcripts = data.get("transcripts") or []
        documents = data.get("documents") or []
        return {
            "transcriptCount": len(transcripts),
            "documentCount": len(documents) + len(transcripts),
            "transcripts": [
                {key: item.get(key) for key in ("id", "institution", "type", "status", "documentId", "documentUploadId", "documentStorageType") if item.get(key)}
                for item in transcripts[:5]
                if isinstance(item, dict)
            ],
            "documents": [
                {key: item.get(key) for key in ("id", "title", "fileName", "documentType", "status", "documentId", "department") if item.get(key)}
                for item in documents[:5]
                if isinstance(item, dict)
            ],
        }

    def checklist_summary(self, checklist: Any) -> dict[str, Any]:
        data = self.model_dump(checklist)
        items = data.get("items") or []
        missing = [item.get("label") for item in items if isinstance(item, dict) and not item.get("done")][:8]
        complete = [item.get("label") for item in items if isinstance(item, dict) and item.get("done")][:8]
        return {
            "status": data.get("status"),
            "completionPercent": data.get("completionPercent"),
            "oneItemAway": data.get("oneItemAway"),
            "missing": missing,
            "complete": complete,
            "totalItems": len(items),
        }

    def counselor_today_work_summary(self, today_work: Any, auth_context: AuthenticatedTenantContext) -> dict[str, Any]:
        data = self.model_dump(today_work)
        buckets = data.get("buckets") or []
        bucket_summaries: list[dict[str, Any]] = []
        all_items: list[dict[str, Any]] = []
        for bucket in buckets:
            if not isinstance(bucket, dict):
                continue
            items = [self.work_item_summary(item, auth_context) for item in bucket.get("items", []) if isinstance(item, dict)]
            bucket_summaries.append(
                {
                    "key": bucket.get("key"),
                    "label": bucket.get("label"),
                    "meaning": bucket.get("meaning"),
                    "count": len(items),
                    "topItems": items[:5],
                }
            )
            all_items.extend(items)
        top_items = sorted(
            all_items,
            key=lambda item: (
                not item.get("ownedByCurrentUser", False),
                -(item.get("priorityScore") or 0),
                item.get("priority") not in {"urgent", "today"},
            ),
        )[:10]
        return {
            "totalItems": len(all_items),
            "ownedByCurrentUserCount": sum(1 for item in all_items if item.get("ownedByCurrentUser")),
            "buckets": bucket_summaries,
            "recommendedTopItems": top_items,
        }

    def work_item_summary(self, item: dict[str, Any], auth_context: AuthenticatedTenantContext) -> dict[str, Any]:
        owner = item.get("owner") or {}
        owner_id = str(owner.get("id") or "") if isinstance(owner, dict) else ""
        owner_name = str(owner.get("name") or "") if isinstance(owner, dict) else ""
        user_id = str(auth_context.user.id)
        user_name = str(auth_context.user.display_name or "")
        reason = item.get("reasonToAct") or {}
        action = item.get("suggestedAction") or {}
        blocking_items = item.get("blockingItems") or []
        return {
            "studentId": item.get("studentId"),
            "studentName": item.get("studentName"),
            "stage": item.get("stage"),
            "section": item.get("section"),
            "priority": item.get("priority"),
            "priorityScore": item.get("priorityScore"),
            "owner": owner_name,
            "ownedByCurrentUser": bool((owner_id and owner_id == user_id) or (owner_name and owner_name.lower() == user_name.lower())),
            "reasonToAct": reason.get("label") if isinstance(reason, dict) else None,
            "suggestedAction": action.get("label") if isinstance(action, dict) else None,
            "blockingItems": [
                entry.get("label")
                for entry in blocking_items[:5]
                if isinstance(entry, dict) and entry.get("label")
            ],
            "nextFollowUpAt": item.get("nextFollowUpAt"),
            "routeHint": item.get("routeHint"),
        }

    @staticmethod
    def answer_focus_for_checklist_question(packet: dict[str, Any], checklist_summary: dict[str, Any]) -> dict[str, Any]:
        student_summary = (packet.get("activeEntity") or {}).get("summary") or {}
        return {
            "questionType": "student_missing_items",
            "student": {
                "id": (packet.get("activeEntity") or {}).get("id"),
                "name": student_summary.get("name"),
                "stage": student_summary.get("stage"),
                "program": student_summary.get("program"),
            },
            "checklistStatus": checklist_summary.get("status"),
            "completionPercent": checklist_summary.get("completionPercent"),
            "missingItems": checklist_summary.get("missing") or [],
            "completeItems": checklist_summary.get("complete") or [],
            "sourceIds": [
                citation["id"]
                for citation in packet.get("citations", [])
                if citation.get("type") in {"student_summary", "student_checklist"}
            ],
        }

    @staticmethod
    def answer_focus_for_counselor_next_action(work_summary: dict[str, Any]) -> dict[str, Any]:
        return {
            "questionType": "counselor_next_best_action",
            "instruction": "Recommend the highest-value next action for the current counselor. Prefer owned items, urgent/today priority, high priorityScore, overdue follow-up, and explicit suggestedAction/reasonToAct.",
            "totalWorkItems": work_summary.get("totalItems", 0),
            "ownedByCurrentUserCount": work_summary.get("ownedByCurrentUserCount", 0),
            "recommendedTopItems": work_summary.get("recommendedTopItems", []),
            "bucketCounts": [
                {"key": bucket.get("key"), "label": bucket.get("label"), "count": bucket.get("count")}
                for bucket in work_summary.get("buckets", [])
            ],
            "sourceIds": ["work:counselor_today"],
        }

    @staticmethod
    def route_capabilities(route: str | None) -> dict[str, Any]:
        route = route or "/"
        if route.startswith("/students/"):
            return {"route": route, "capabilities": ["student summary", "checklist", "documents", "timeline", "communication drafts", "decision readiness"]}
        if route.startswith("/documents"):
            return {"route": route, "capabilities": ["document queue", "upload status", "exceptions", "student links"]}
        if route.startswith("/utilities"):
            return {"route": route, "capabilities": ["CSV import wizard", "mapping templates", "validation reports", "import history"]}
        if route.startswith("/admin"):
            return {"route": route, "capabilities": ["users", "roles", "tenant settings", "permissions"]}
        return {"route": route, "capabilities": ["today's work", "student search", "workflow summaries", "general governed help"]}


assistant_context_service = AssistantContextService()
