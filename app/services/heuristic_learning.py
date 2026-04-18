import json
import logging
import re
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict
from uuid import uuid4

from app.core.config import heuristic_learning_path

logger = logging.getLogger(__name__)


class HeuristicLearningService:
    def __init__(self, base_dir: str | Path | None = None):
        self.base_dir = Path(base_dir) if base_dir else heuristic_learning_path()
        self.candidates_dir = self.base_dir / "candidates"
        self.active_dir = self.base_dir / "active"
        self.shadow_dir = self.base_dir / "shadow"

    def capture_candidate(
        self,
        filename: str,
        text: str,
        document_type: str,
        heuristic_result: Dict[str, Any],
        repaired_result: Dict[str, Any],
        metadata: Dict[str, Any],
        bedrock_mapper: Any | None = None,
    ) -> Dict[str, Any]:
        candidate_id = self._candidate_id(filename)
        self._ensure_dirs()

        proposal = None
        proposal_source = "stub"
        if bedrock_mapper and hasattr(bedrock_mapper, "propose_heuristic_rule"):
            try:
                proposal = bedrock_mapper.propose_heuristic_rule(
                    text=text,
                    heuristic_result=heuristic_result,
                    repaired_result=repaired_result,
                )
                proposal_source = "ai"
            except Exception:
                logger.exception("Heuristic learning proposal generation failed; falling back to deterministic stub.")

        if proposal is None:
            proposal = self._build_rule_stub(
                filename=filename,
                text=text,
                document_type=document_type,
                heuristic_result=heuristic_result,
                repaired_result=repaired_result,
            )

        payload = {
            "schema_version": "1.0",
            "candidate_id": candidate_id,
            "status": "candidate",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "source_document": {
                "filename": filename,
                "document_type": document_type,
            },
            "metrics": {
                "text_source": metadata.get("text_source"),
                "ocr_used": metadata.get("ocr_used"),
                "bedrock_used": metadata.get("bedrock_used"),
                "overall_confidence": metadata.get("overall_confidence"),
                "parser_confidence": metadata.get("parser_confidence"),
                "course_confidence_summary": metadata.get("course_confidence_summary"),
            },
            "proposal_source": proposal_source,
            "proposal": proposal,
            "heuristic_result": deepcopy(heuristic_result),
            "repaired_result": deepcopy(repaired_result),
            "raw_text_excerpt": text[:4000],
        }

        candidate_path = self.candidates_dir / f"{candidate_id}.json"
        candidate_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return {
            "candidate_id": candidate_id,
            "status": "candidate",
            "path": str(candidate_path),
            "proposal_source": proposal_source,
        }

    def _ensure_dirs(self) -> None:
        self.candidates_dir.mkdir(parents=True, exist_ok=True)
        self.active_dir.mkdir(parents=True, exist_ok=True)
        self.shadow_dir.mkdir(parents=True, exist_ok=True)

    def _candidate_id(self, filename: str) -> str:
        stem = Path(filename).stem.lower()
        slug = re.sub(r"[^a-z0-9]+", "-", stem).strip("-")[:48] or "transcript"
        return f"{slug}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{uuid4().hex[:8]}"

    def _build_rule_stub(
        self,
        filename: str,
        text: str,
        document_type: str,
        heuristic_result: Dict[str, Any],
        repaired_result: Dict[str, Any],
    ) -> Dict[str, Any]:
        institutions = repaired_result.get("institutions") or heuristic_result.get("institutions") or []
        institution_name = institutions[0].get("name") if institutions else ""
        top_lines = [line.strip() for line in text.splitlines()[:20] if line.strip()]
        matchers = []
        if institution_name:
            matchers.append({"contains": institution_name})
        if "Parchment Student ID:" in text:
            matchers.append({"contains": "Parchment Student ID:"})
        elif "Official Transcript" in text:
            matchers.append({"contains": "Official Transcript"})
        for line in top_lines[:3]:
            if len(line) >= 8 and not line.lower().startswith(("prepared for:", "page ")):
                matchers.append({"contains": line})
        unique_matchers = []
        seen = set()
        for item in matchers:
            key = item["contains"].lower()
            if key in seen:
                continue
            seen.add(key)
            unique_matchers.append(item)

        student = repaired_result.get("student", {})
        return {
            "family_id": re.sub(r"[^a-z0-9]+", "_", Path(filename).stem.lower()).strip("_")[:64] or "transcript_family",
            "version": 1,
            "status": "candidate",
            "match": {"all": unique_matchers[:4]},
            "strategy": {
                "document_type": document_type,
                "python_parser_fallback": True,
                "notes": [
                    "Candidate rule captured from low-confidence request.",
                    "Promote only after replay against regression corpus.",
                ],
            },
            "field_hints": {
                "institution_name": institution_name or None,
                "student_name_example": student.get("name"),
                "student_id_example": student.get("student_id"),
                "date_of_birth_example": student.get("date_of_birth"),
            },
        }
