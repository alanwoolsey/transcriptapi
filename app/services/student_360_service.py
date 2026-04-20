from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session

from app.db.models import AppUser, DocumentUpload, Institution, Program, Student, Transcript, TranscriptDemographics, TranscriptParseRun
from app.db.session import get_session_factory
from app.models.student_models import (
    Student360ListRecord,
    Student360Record,
    StudentChecklistItem,
    StudentProgramSummary,
    StudentRecommendation,
    StudentTermGpa,
    StudentTimelineStep,
    StudentTranscriptCourse,
    StudentTranscriptRecord,
)
from app.services.student_resolution import StudentResolutionService


@dataclass
class _TranscriptBundle:
    transcript: Transcript
    upload: DocumentUpload
    demographics: TranscriptDemographics | None
    parse_run: TranscriptParseRun | None


class Student360Service:
    def __init__(self, session_factory=None) -> None:
        self.session_factory = session_factory or get_session_factory
        self.student_resolution = StudentResolutionService()

    def list_students(self, tenant_id: UUID, q: str | None = None) -> list[Student360ListRecord]:
        session_factory = self.session_factory()
        with session_factory() as session:
            canonical_students = self._list_canonical_students(session, tenant_id, q)
            if canonical_students:
                return canonical_students
            return self._list_transcript_derived_students(session, tenant_id, q)

    def get_student(self, tenant_id: UUID, student_id: str) -> Student360Record | None:
        session_factory = self.session_factory()
        with session_factory() as session:
            canonical_student = self._get_canonical_student(session, tenant_id, student_id)
            if canonical_student is not None:
                return canonical_student

            return self._get_transcript_derived_student(session, tenant_id, student_id)

    def _list_canonical_students(self, session: Session, tenant_id: UUID, q: str | None) -> list[Student360ListRecord]:
        transcript_stats = (
            select(
                Transcript.student_id.label("student_id"),
                func.count(Transcript.id).label("transcripts_count"),
                func.max(Transcript.parser_confidence).label("max_parser_confidence"),
            )
            .where(Transcript.tenant_id == tenant_id, Transcript.student_id.is_not(None))
            .group_by(Transcript.student_id)
            .subquery()
        )
        latest_institution_name = (
            select(TranscriptDemographics.institution_name)
            .join(Transcript, Transcript.id == TranscriptDemographics.transcript_id)
            .where(Transcript.tenant_id == tenant_id, Transcript.student_id == Student.id)
            .order_by(Transcript.created_at.desc())
            .limit(1)
            .scalar_subquery()
        )
        stmt = (
            select(
                Student,
                Program,
                Institution,
                AppUser,
                transcript_stats.c.transcripts_count,
                transcript_stats.c.max_parser_confidence,
                latest_institution_name.label("latest_institution_name"),
            )
            .outerjoin(Program, Program.id == Student.target_program_id)
            .outerjoin(Institution, Institution.id == Student.target_institution_id)
            .outerjoin(AppUser, AppUser.id == Student.advisor_user_id)
            .outerjoin(transcript_stats, transcript_stats.c.student_id == Student.id)
            .where(Student.tenant_id == tenant_id)
            .order_by(Student.latest_activity_at.desc().nullslast(), Student.created_at.desc())
        )
        stmt = self._apply_student_search(stmt, q)
        rows = session.execute(stmt).all()
        if not rows:
            return []

        records: list[Student360ListRecord] = []
        for student, program, institution, advisor, transcripts_count, max_parser_confidence, latest_institution in rows:
            institution_goal = institution.name if institution else self._safe_str(latest_institution, "Unknown institution")
            transcript_count = int(transcripts_count or 0)
            gpa_value = self._to_float(student.latest_cumulative_gpa)
            fit_score = self._estimate_fit_score_from_summary(gpa_value, transcript_count, max_parser_confidence)
            deposit_likelihood = self._estimate_deposit_likelihood_from_summary(
                student.risk_level,
                gpa_value,
                transcript_count,
                max_parser_confidence,
            )
            next_best_action = self._build_next_best_action(student.risk_level, student.current_stage, institution_goal)
            records.append(
                Student360ListRecord(
                    id=str(student.id),
                    name=self._join_name(student.first_name, student.last_name, fallback="Unknown Student"),
                    preferredName=student.preferred_name or student.first_name,
                    email=student.email,
                    phone=student.phone,
                    program=StudentProgramSummary(id=(str(program.id) if program else None), name=(program.name if program else "Transcript intake")),
                    studentType=self._student_type(student.accepted_credits),
                    institutionGoal=institution_goal,
                    stage=self._title_case(student.current_stage or "decision-ready"),
                    risk=self._title_case(student.risk_level or "low"),
                    advisor=advisor.display_name if advisor else "Unassigned",
                    city=self._format_location(student.city, student.state, student.country),
                    fitScore=fit_score,
                    depositLikelihood=deposit_likelihood,
                    summary=student.summary or self._default_summary_from_institution(institution_goal, student.risk_level),
                    gpa=gpa_value,
                    creditsAccepted=self._to_float(student.accepted_credits, 0),
                    transcriptsCount=transcript_count,
                    lastActivity=self._format_timestamp(student.latest_activity_at or student.updated_at),
                    tags=self._build_tags(program.name if program else None, student.risk_level, student.current_stage),
                    nextBestAction=next_best_action,
                )
            )
        return records

    def _list_transcript_derived_students(self, session: Session, tenant_id: UUID, q: str | None) -> list[Student360ListRecord]:
        stmt = (
            select(Transcript, TranscriptDemographics)
            .outerjoin(TranscriptDemographics, TranscriptDemographics.transcript_id == Transcript.id)
            .where(Transcript.tenant_id == tenant_id)
            .order_by(Transcript.created_at.desc())
        )
        rows = session.execute(stmt).all()
        grouped: dict[str, list[tuple[Transcript, TranscriptDemographics | None]]] = defaultdict(list)
        for transcript, demographics in rows:
            key = self._derive_student_key(transcript, demographics)
            grouped[key].append((transcript, demographics))

        records: list[Student360ListRecord] = []
        for key, transcript_rows in grouped.items():
            latest_transcript, latest_demographics = transcript_rows[0]
            name = self._demographic_name(latest_demographics)
            program = "Transcript intake"
            institution_goal = self._safe_str(latest_demographics.institution_name if latest_demographics else None, "Unknown institution")
            risk = self._derive_risk_from_transcripts([item[0] for item in transcript_rows])
            stage = self._derive_stage_from_transcripts([item[0] for item in transcript_rows])
            gpa_value = self._derive_gpa_from_demographics([item[1] for item in transcript_rows])
            transcript_count = len(transcript_rows)
            fit_score = self._estimate_fit_score_from_summary(gpa_value, transcript_count, latest_transcript.parser_confidence)
            deposit_likelihood = self._estimate_deposit_likelihood_from_summary(
                risk,
                gpa_value,
                transcript_count,
                latest_transcript.parser_confidence,
            )
            record = Student360ListRecord(
                id=key,
                name=name,
                preferredName=name.split(" ")[0] if name else None,
                email=None,
                phone=None,
                program=StudentProgramSummary(id=None, name=program),
                studentType="transfer" if self._derive_credits_from_demographics([item[1] for item in transcript_rows]) > 0 else "first_year",
                institutionGoal=institution_goal,
                stage=stage,
                risk=risk,
                advisor="Unassigned",
                city=self._format_location(None, latest_demographics.institution_state if latest_demographics else None, latest_demographics.institution_country if latest_demographics else None),
                fitScore=fit_score,
                depositLikelihood=deposit_likelihood,
                summary=self._default_summary_from_institution(institution_goal, risk),
                gpa=gpa_value,
                creditsAccepted=self._derive_credits_from_demographics([item[1] for item in transcript_rows]),
                transcriptsCount=transcript_count,
                lastActivity=self._format_timestamp(latest_transcript.updated_at),
                tags=self._build_tags(program, risk, stage),
                nextBestAction=self._build_next_best_action(risk, stage, institution_goal),
            )
            if self._matches_search(record, q):
                records.append(record)
        return records

    def _get_canonical_student(self, session: Session, tenant_id: UUID, student_id: str) -> Student360Record | None:
        try:
            student_uuid = UUID(student_id)
        except ValueError:
            return None

        stmt = (
            select(Student, Program, Institution, AppUser)
            .outerjoin(Program, Program.id == Student.target_program_id)
            .outerjoin(Institution, Institution.id == Student.target_institution_id)
            .outerjoin(AppUser, AppUser.id == Student.advisor_user_id)
            .where(Student.tenant_id == tenant_id, Student.id == student_uuid)
        )
        row = session.execute(stmt).one_or_none()
        if row is None:
            return None

        student, program, institution, advisor = row
        transcript_map = self._load_transcripts_for_students(session, tenant_id, [student.id])
        transcripts = transcript_map.get(student.id, [])
        recommendation = self._build_recommendation(transcripts, student.risk_level, student.current_stage)
        institution_goal = institution.name if institution else self._latest_institution_name(transcripts)
        return Student360Record(
            id=str(student.id),
            name=self._join_name(student.first_name, student.last_name, fallback="Unknown Student"),
            preferredName=student.preferred_name or student.first_name or "Student",
            email=student.email,
            phone=student.phone,
            program=StudentProgramSummary(id=(str(program.id) if program else None), name=(program.name if program else "Transcript intake")),
            studentType=self._student_type(student.accepted_credits),
            institutionGoal=institution_goal,
            stage=self._title_case(student.current_stage or "decision-ready"),
            risk=self._title_case(student.risk_level or "low"),
            fitScore=self._estimate_fit_score(student.latest_cumulative_gpa, transcripts),
            depositLikelihood=self._estimate_deposit_likelihood(student.risk_level, student.latest_cumulative_gpa, transcripts),
            summary=student.summary or self._default_summary(transcripts, student.risk_level),
            gpa=self._to_float(student.latest_cumulative_gpa),
            creditsAccepted=self._to_float(student.accepted_credits, 0),
            transcriptsCount=len(transcripts),
            advisor=advisor.display_name if advisor else "Unassigned",
            tags=self._build_tags(program.name if program else None, student.risk_level, student.current_stage),
            nextBestAction=recommendation.nextBestAction,
            city=self._format_location(student.city, student.state, student.country),
            lastActivity=self._format_timestamp(student.latest_activity_at or student.updated_at),
            checklist=self._build_checklist(transcripts, student.risk_level),
            transcripts=transcripts,
            termGpa=self._build_term_gpa(transcripts),
            recommendation=recommendation,
        )

    def _get_transcript_derived_student(self, session: Session, tenant_id: UUID, student_id: str) -> Student360Record | None:
        stmt = (
            select(Transcript, DocumentUpload, TranscriptDemographics, TranscriptParseRun)
            .join(DocumentUpload, DocumentUpload.id == Transcript.document_upload_id)
            .outerjoin(TranscriptDemographics, TranscriptDemographics.transcript_id == Transcript.id)
            .outerjoin(TranscriptParseRun, TranscriptParseRun.transcript_id == Transcript.id)
            .where(Transcript.tenant_id == tenant_id)
            .order_by(Transcript.created_at.desc())
        )
        grouped: dict[str, list[_TranscriptBundle]] = defaultdict(list)
        for transcript, upload, demographics, parse_run in session.execute(stmt).all():
            key = self._derive_student_key(transcript, demographics)
            grouped[key].append(_TranscriptBundle(transcript=transcript, upload=upload, demographics=demographics, parse_run=parse_run))

        bundles = grouped.get(student_id)
        if not bundles:
            return None

        latest = bundles[0]
        name = self._demographic_name(latest.demographics)
        transcripts = self._map_transcript_records(bundles)
        risk = self._derive_risk_from_bundles(bundles)
        stage = self._derive_stage_from_bundles(bundles)
        recommendation = self._build_recommendation(transcripts, risk, stage)
        return Student360Record(
            id=student_id,
            name=name,
            preferredName=(latest.demographics.student_first_name if latest.demographics and latest.demographics.student_first_name else name.split(" ")[0]),
            email=None,
            phone=None,
            program=StudentProgramSummary(id=None, name="Transcript intake"),
            studentType="transfer" if self._derive_credits_from_bundles(bundles) > 0 else "first_year",
            institutionGoal=self._safe_str(latest.demographics.institution_name if latest.demographics else None, "Unknown institution"),
            stage=stage,
            risk=risk,
            fitScore=self._estimate_fit_score(self._derive_gpa_from_bundles(bundles), transcripts),
            depositLikelihood=self._estimate_deposit_likelihood(risk, self._derive_gpa_from_bundles(bundles), transcripts),
            summary=self._default_summary(transcripts, risk),
            gpa=self._derive_gpa_from_bundles(bundles),
            creditsAccepted=self._derive_credits_from_bundles(bundles),
            transcriptsCount=len(bundles),
            advisor="Unassigned",
            tags=self._build_tags("Transcript intake", risk, stage),
            nextBestAction=recommendation.nextBestAction,
            city=self._format_location(
                None,
                latest.demographics.institution_state if latest.demographics else None,
                latest.demographics.institution_country if latest.demographics else None,
            ),
            lastActivity=self._format_timestamp(latest.transcript.updated_at),
            checklist=self._build_checklist(transcripts, risk),
            transcripts=transcripts,
            termGpa=self._build_term_gpa(transcripts),
            recommendation=recommendation,
        )

    def _load_transcripts_for_students(self, session: Session, tenant_id: UUID, student_ids: list[UUID]) -> dict[UUID, list[StudentTranscriptRecord]]:
        if not student_ids:
            return {}
        stmt = (
            select(Transcript, DocumentUpload, TranscriptDemographics, TranscriptParseRun)
            .join(DocumentUpload, DocumentUpload.id == Transcript.document_upload_id)
            .outerjoin(TranscriptDemographics, TranscriptDemographics.transcript_id == Transcript.id)
            .outerjoin(TranscriptParseRun, TranscriptParseRun.transcript_id == Transcript.id)
            .where(Transcript.tenant_id == tenant_id, Transcript.student_id.in_(student_ids))
            .order_by(Transcript.created_at.desc())
        )
        grouped: dict[UUID, list[_TranscriptBundle]] = defaultdict(list)
        for transcript, upload, demographics, parse_run in session.execute(stmt).all():
            if transcript.student_id:
                grouped[transcript.student_id].append(_TranscriptBundle(transcript, upload, demographics, parse_run))
        return {student_id: self._map_transcript_records(bundles) for student_id, bundles in grouped.items()}

    def _heal_transcript_data(self, session: Session, tenant_id: UUID) -> None:
        stmt = (
            select(Transcript, TranscriptDemographics, TranscriptParseRun)
            .outerjoin(TranscriptDemographics, TranscriptDemographics.transcript_id == Transcript.id)
            .outerjoin(TranscriptParseRun, TranscriptParseRun.transcript_id == Transcript.id)
            .where(Transcript.tenant_id == tenant_id)
            .order_by(Transcript.created_at.desc())
        )
        changed = False
        for transcript, demographics, parse_run in session.execute(stmt).all():
            previous_student_id = transcript.student_id
            student = self.student_resolution.ensure_student_for_transcript(
                session=session,
                tenant_id=tenant_id,
                transcript=transcript,
                demographics=demographics,
            )
            if student is not None and transcript.student_id != previous_student_id:
                changed = True

            payload = parse_run.response_json if parse_run and parse_run.response_json else {}
            raw_courses = payload.get("courses") or []
            if transcript.status == "completed" and not raw_courses:
                transcript.status = "failed"
                transcript.notes = "No courses were extracted from transcript. Reprocess required."
                if parse_run is not None:
                    parse_run.status = "failed"
                    parse_run.error_message = transcript.notes
                changed = True

        if changed:
            session.commit()

    def _map_transcript_records(self, bundles: list[_TranscriptBundle]) -> list[StudentTranscriptRecord]:
        records: list[StudentTranscriptRecord] = []
        for bundle in bundles:
            payload = bundle.parse_run.response_json if bundle.parse_run and bundle.parse_run.response_json else {}
            raw_courses = payload.get("courses") or []
            records.append(
                StudentTranscriptRecord(
                    id=str(bundle.transcript.id),
                    source=bundle.upload.original_filename,
                    institution=self._safe_str(bundle.demographics.institution_name if bundle.demographics else None, "Unknown institution"),
                    type=self._title_case(bundle.transcript.document_type.replace("_", " ")) if bundle.transcript.document_type else "Transcript",
                    uploadedAt=bundle.upload.uploaded_at,
                    status=self._title_case(bundle.transcript.status),
                    confidence=round(self._to_float(bundle.transcript.parser_confidence) * 100, 1),
                    credits=self._to_float(bundle.demographics.total_credits_earned if bundle.demographics else None, 0),
                    pages=bundle.transcript.page_count or 1,
                    owner=bundle.parse_run.parser_name if bundle.parse_run else "transcript_pipeline",
                    notes=self._resolve_transcript_note(bundle),
                    steps=self._build_steps(bundle),
                    courses=[StudentTranscriptCourse(**self._filter_course_fields(course)) for course in raw_courses],
                    rawDocument=payload or None,
                )
            )
        return records

    def _build_steps(self, bundle: _TranscriptBundle) -> list[StudentTimelineStep]:
        created = self._format_clock(bundle.upload.uploaded_at)
        steps = [StudentTimelineStep(label="Upload received", time=created)]
        if bundle.parse_run:
            steps.append(StudentTimelineStep(label=self._title_case(bundle.parse_run.status), time=self._format_clock(bundle.parse_run.completed_at or bundle.parse_run.started_at)))
        return steps

    def _build_term_gpa(self, transcripts: list[StudentTranscriptRecord]) -> list[StudentTermGpa]:
        for transcript in transcripts:
            raw = transcript.rawDocument or {}
            term_gpas = raw.get("termGPAs") or []
            if term_gpas:
                return [
                    StudentTermGpa(
                        term=" ".join(part for part in [item.get("term"), item.get("year")] if part).strip() or f"Term {index + 1}",
                        gpa=self._to_float(item.get("simpleGPA")),
                        credits=self._to_float(item.get("simpleUnitsEarned"), 0),
                    )
                    for index, item in enumerate(term_gpas)
                ]
        return []

    def _build_checklist(self, transcripts: list[StudentTranscriptRecord], risk_level: str | None) -> list[StudentChecklistItem]:
        has_transcripts = bool(transcripts)
        high_risk = (risk_level or "").lower() == "high"
        return [
            StudentChecklistItem(label="Identity matched", done=has_transcripts),
            StudentChecklistItem(label="Document parsed", done=has_transcripts),
            StudentChecklistItem(label="Trust scan cleared", done=not high_risk),
            StudentChecklistItem(label="Decision packet built", done=has_transcripts and not high_risk),
        ]

    def _build_recommendation(self, transcripts: list[StudentTranscriptRecord], risk_level: str | None, stage: str | None) -> StudentRecommendation:
        high_risk = (risk_level or "").lower() == "high"
        if high_risk:
            return StudentRecommendation(
                summary="Do not release outcome until trust review is resolved.",
                fitNarrative="The available records indicate document or provenance issues that require manual review before release.",
                nextBestAction="Review flagged transcript evidence and request an official replacement if needed.",
            )
        institution = self._latest_institution_name(transcripts)
        return StudentRecommendation(
            summary="Latest transcript is ready for counselor review.",
            fitNarrative=f"Current transcript evidence from {institution} was parsed successfully and is available for review.",
            nextBestAction="Open the student record and review the latest transcript outcome.",
        )

    def _default_summary(self, transcripts: list[StudentTranscriptRecord], risk_level: str | None) -> str:
        high_risk = (risk_level or "").lower() == "high"
        institution = self._latest_institution_name(transcripts)
        if high_risk:
            return f"Latest transcript from {institution} is blocked pending trust review."
        return f"Latest transcript parsed from {institution}. Outcome draft prepared for review."

    def _default_summary_from_institution(self, institution: str, risk_level: str | None) -> str:
        if (risk_level or "").lower() == "high":
            return f"Latest transcript from {institution} is blocked pending trust review."
        return f"Latest transcript parsed from {institution}. Outcome draft prepared for review."

    def _build_tags(self, program: str | None, risk_level: str | None, stage: str | None) -> list[str]:
        tags: list[str] = []
        if program and program.strip():
            tags.append(program)
        if stage and stage.strip():
            tags.append(stage)
        if risk_level and risk_level.strip():
            tags.append(f"{self._title_case(risk_level)} risk")
        return tags

    def _estimate_fit_score(self, gpa: Decimal | float | None, transcripts: list[StudentTranscriptRecord]) -> int:
        gpa_value = self._to_float(gpa)
        if gpa_value >= 3.5:
            return 92
        if gpa_value >= 3.0:
            return 84
        if gpa_value >= 2.5:
            return 72
        if transcripts:
            confidence = max((t.confidence for t in transcripts), default=70.0)
            return max(55, min(90, int(confidence)))
        return 65

    def _estimate_deposit_likelihood(self, risk_level: str | None, gpa: Decimal | float | None, transcripts: list[StudentTranscriptRecord]) -> int:
        risk = (risk_level or "").lower()
        if risk == "high":
            return 20
        base = self._estimate_fit_score(gpa, transcripts) - 18
        if risk == "medium":
            base -= 12
        return max(10, min(85, base))

    def _estimate_fit_score_from_summary(
        self,
        gpa: Decimal | float | None,
        transcripts_count: int,
        parser_confidence: Decimal | float | None,
    ) -> int:
        gpa_value = self._to_float(gpa)
        if gpa_value >= 3.5:
            return 92
        if gpa_value >= 3.0:
            return 84
        if gpa_value >= 2.5:
            return 72
        if transcripts_count > 0:
            confidence = self._to_float(parser_confidence) * 100
            fallback_confidence = confidence if confidence > 0 else 70.0
            return max(55, min(90, int(fallback_confidence)))
        return 65

    def _estimate_deposit_likelihood_from_summary(
        self,
        risk_level: str | None,
        gpa: Decimal | float | None,
        transcripts_count: int,
        parser_confidence: Decimal | float | None,
    ) -> int:
        risk = (risk_level or "").lower()
        if risk == "high":
            return 20
        base = self._estimate_fit_score_from_summary(gpa, transcripts_count, parser_confidence) - 18
        if risk == "medium":
            base -= 12
        return max(10, min(85, base))

    def _build_next_best_action(self, risk_level: str | None, stage: str | None, institution: str) -> str:
        if (risk_level or "").lower() == "high":
            return "Review flagged transcript evidence and request an official replacement if needed."
        if (stage or "").lower().replace("_", " ") in {"pending evidence", "trust hold"}:
            return f"Resolve outstanding transcript issues for {institution} before releasing an outcome."
        return "Open the student record and review the latest transcript outcome."

    def _derive_student_key(self, transcript: Transcript, demographics: TranscriptDemographics | None) -> str:
        if transcript.student_id:
            return str(transcript.student_id)
        if demographics:
            if demographics.student_external_id:
                return demographics.student_external_id
            parts = [demographics.student_first_name or "", demographics.student_last_name or "", demographics.institution_name or ""]
            key = "-".join(part.strip().lower().replace(" ", "-") for part in parts if part and part.strip())
            if key:
                return key
        return str(transcript.id)

    def _derive_stage_from_bundles(self, bundles: list[_TranscriptBundle]) -> str:
        latest = bundles[0].transcript
        if latest.is_fraudulent:
            return "Trust hold"
        if latest.status in {"failed", "processing"}:
            return "Pending evidence"
        return "Decision-ready"

    def _derive_risk_from_bundles(self, bundles: list[_TranscriptBundle]) -> str:
        latest = bundles[0].transcript
        if latest.is_fraudulent:
            return "High"
        confidence = self._to_float(latest.parser_confidence)
        if confidence and confidence < 0.8:
            return "Medium"
        return "Low"

    def _derive_stage_from_transcripts(self, transcripts: list[Transcript]) -> str:
        latest = transcripts[0]
        if latest.is_fraudulent:
            return "Trust hold"
        if latest.status in {"failed", "processing"}:
            return "Pending evidence"
        return "Decision-ready"

    def _derive_risk_from_transcripts(self, transcripts: list[Transcript]) -> str:
        latest = transcripts[0]
        if latest.is_fraudulent:
            return "High"
        confidence = self._to_float(latest.parser_confidence)
        if confidence and confidence < 0.8:
            return "Medium"
        return "Low"

    def _derive_gpa_from_bundles(self, bundles: list[_TranscriptBundle]) -> float:
        for bundle in bundles:
            if bundle.demographics and bundle.demographics.cumulative_gpa is not None:
                return self._to_float(bundle.demographics.cumulative_gpa)
        return 0.0

    def _derive_credits_from_bundles(self, bundles: list[_TranscriptBundle]) -> float:
        for bundle in bundles:
            if bundle.demographics and bundle.demographics.total_credits_earned is not None:
                return self._to_float(bundle.demographics.total_credits_earned, 0)
        return 0.0

    def _derive_gpa_from_demographics(self, demographics_rows: list[TranscriptDemographics | None]) -> float:
        for demographics in demographics_rows:
            if demographics and demographics.cumulative_gpa is not None:
                return self._to_float(demographics.cumulative_gpa)
        return 0.0

    def _derive_credits_from_demographics(self, demographics_rows: list[TranscriptDemographics | None]) -> float:
        for demographics in demographics_rows:
            if demographics and demographics.total_credits_earned is not None:
                return self._to_float(demographics.total_credits_earned, 0)
        return 0.0

    def _apply_student_search(self, stmt: Select, q: str | None) -> Select:
        if not q or not q.strip():
            return stmt
        pattern = f"%{q.strip()}%"
        return stmt.where(
            or_(
                Student.first_name.ilike(pattern),
                Student.last_name.ilike(pattern),
                Student.preferred_name.ilike(pattern),
                Student.email.ilike(pattern),
                Student.current_stage.ilike(pattern),
                Student.risk_level.ilike(pattern),
                Program.name.ilike(pattern),
                Institution.name.ilike(pattern),
                AppUser.display_name.ilike(pattern),
            )
        )

    def _matches_search(self, record: Student360ListRecord | Student360Record, q: str | None) -> bool:
        if not q or not q.strip():
            return True
        haystack = " ".join(
            [
                record.name,
                record.program,
                record.institutionGoal,
                record.advisor,
                record.risk,
                record.stage,
                record.summary,
            ]
        ).lower()
        return q.strip().lower() in haystack

    def _latest_institution_name(self, transcripts: list[StudentTranscriptRecord]) -> str:
        return transcripts[0].institution if transcripts else "Unknown institution"

    def _filter_course_fields(self, course: dict[str, Any]) -> dict[str, Any]:
        allowed = {"courseId", "courseTitle", "term", "year", "credit", "grade", "subject", "creditAttempted"}
        return {key: value for key, value in course.items() if key in allowed}

    def _default_transcript_note(self, transcript: Transcript) -> str:
        if transcript.status == "failed":
            return "Transcript processing failed."
        return "Transcript parsed and stored."

    def _resolve_transcript_note(self, bundle: _TranscriptBundle) -> str:
        if bundle.transcript.notes:
            return bundle.transcript.notes
        if bundle.parse_run and bundle.parse_run.error_message:
            return bundle.parse_run.error_message
        return self._default_transcript_note(bundle.transcript)

    def _demographic_name(self, demographics: TranscriptDemographics | None) -> str:
        if not demographics:
            return "Student record pending"
        if demographics.student_external_id:
            fallback = demographics.student_external_id
        else:
            fallback = "Student record pending"
        return self._join_name(demographics.student_first_name, demographics.student_last_name, fallback=fallback)

    def _join_name(self, first: str | None, last: str | None, fallback: str) -> str:
        name = " ".join(part for part in [first or "", last or ""] if part.strip()).strip()
        return name or fallback

    def _student_type(self, accepted_credits: Decimal | float | int | str | None) -> str:
        return "transfer" if self._to_float(accepted_credits, 0.0) > 0 else "first_year"

    def _format_location(self, city: str | None, state: str | None, country: str | None) -> str:
        parts = [part for part in [city, state, country] if part]
        return ", ".join(parts) if parts else "Location pending"

    def _safe_str(self, value: str | None, fallback: str) -> str:
        return value.strip() if value and value.strip() else fallback

    def _to_float(self, value: Decimal | float | int | str | None, fallback: float = 0.0) -> float:
        if value is None:
            return fallback
        try:
            return round(float(value), 2)
        except Exception:
            return fallback

    def _title_case(self, value: str | None) -> str:
        if not value:
            return ""
        return value.replace("_", " ").replace("-", " ").title()

    def _format_timestamp(self, value: datetime | None) -> str:
        if not value:
            return "Unknown"
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

    def _format_clock(self, value: datetime | None) -> str:
        if not value:
            return "Now"
        return value.astimezone(timezone.utc).strftime("%I:%M %p").lstrip("0")
