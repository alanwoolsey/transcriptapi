from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.models import (
    AppUser,
    DocumentUpload,
    Institution,
    Program,
    Student,
    StudentChecklist,
    StudentChecklistItem,
    Tenant,
    Transcript,
    TrustFlag,
)
from app.db.session import get_session_factory
from app.services.admissions_ops_service import AdmissionsOpsService


@dataclass(frozen=True)
class DemoStudentSpec:
    external_id: str
    first_name: str
    last_name: str
    email: str
    stage: str
    risk: str
    gpa: float
    credits: float
    statuses: dict[str, str]
    trust_blocked: bool = False
    evidence_for_code: str | None = None
    parser_confidence: float = 0.82


DEMO_STUDENTS = [
    DemoStudentSpec(
        external_id="PH1-INCOMPLETE",
        first_name="Nadia",
        last_name="Brooks",
        email="phase1.incomplete@example.test",
        stage="incomplete",
        risk="medium",
        gpa=3.6,
        credits=0,
        statuses={
            "application_form": "complete",
            "official_transcript": "requested",
            "residency_form": "not_started",
            "fafsa": "not_started",
        },
    ),
    DemoStudentSpec(
        external_id="PH1-ONE-AWAY",
        first_name="Miles",
        last_name="Chen",
        email="phase1.oneaway@example.test",
        stage="close",
        risk="low",
        gpa=3.4,
        credits=12,
        statuses={
            "application_form": "complete",
            "official_transcript": "complete",
            "college_transcript": "complete",
            "residency_form": "complete",
            "fafsa": "requested",
        },
    ),
    DemoStudentSpec(
        external_id="PH1-READY-REVIEW",
        first_name="Iris",
        last_name="Patel",
        email="phase1.readyreview@example.test",
        stage="ready_for_review",
        risk="low",
        gpa=3.7,
        credits=28,
        statuses={
            "application_form": "complete",
            "official_transcript": "needs_review",
            "college_transcript": "complete",
            "residency_form": "complete",
            "fafsa": "complete",
        },
        evidence_for_code="official_transcript",
    ),
    DemoStudentSpec(
        external_id="PH1-TRUST-BLOCKED",
        first_name="Rowan",
        last_name="Silva",
        email="phase1.trustblocked@example.test",
        stage="trust_hold",
        risk="high",
        gpa=3.1,
        credits=36,
        statuses={
            "application_form": "complete",
            "official_transcript": "complete",
            "college_transcript": "complete",
            "residency_form": "complete",
            "fafsa": "complete",
        },
        trust_blocked=True,
        evidence_for_code="official_transcript",
        parser_confidence=0.96,
    ),
]


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed Phase 1 operating-core demo students for a tenant.")
    parser.add_argument("--tenant-slug", default=None, help="Tenant slug to seed. Defaults to the first active tenant.")
    args = parser.parse_args()

    session_factory = get_session_factory()
    with session_factory() as session:
        tenant = _resolve_tenant(session, args.tenant_slug)
        owner = _resolve_owner(session, tenant.id)
        institution = _ensure_institution(session, tenant.id)
        program = _ensure_program(session, tenant.id, institution.id)
        ops = AdmissionsOpsService()

        seeded: list[str] = []
        for spec in DEMO_STUDENTS:
            student = _upsert_student(session, tenant.id, owner, institution, program, spec)
            context = ops._ensure_student_state_for_student(session, tenant.id, student)
            _apply_statuses(session, context.checklist, context.items, spec)
            if spec.trust_blocked:
                _ensure_trust_block(session, tenant.id, student, owner, spec)
            context = ops._recalculate_student_state(
                session,
                tenant.id,
                student,
                context.checklist,
                context.items,
                actor_user_id=None,
                actor_type="phase1_demo_seed",
            )
            ops.work_state_projector.refresh_student_projection(session, tenant_id=tenant.id, student_id=student.id)
            seeded.append(f"{student.external_student_id}:{context.readiness.readiness_state}")

        session.commit()

    print(f"Seeded Phase 1 demo data for tenant '{tenant.slug}': {', '.join(seeded)}")


def _resolve_tenant(session: Session, tenant_slug: str | None) -> Tenant:
    stmt = select(Tenant)
    if tenant_slug:
        stmt = stmt.where(Tenant.slug == tenant_slug)
    else:
        stmt = stmt.where(Tenant.status == "active").order_by(Tenant.created_at.asc())
    tenant = session.execute(stmt.limit(1)).scalar_one_or_none()
    if tenant is None:
        raise RuntimeError(f"Tenant not found: {tenant_slug or 'first active tenant'}")
    return tenant


def _resolve_owner(session: Session, tenant_id: UUID) -> AppUser | None:
    return session.execute(
        select(AppUser).where(AppUser.tenant_id == tenant_id, AppUser.is_active.is_(True)).order_by(AppUser.created_at.asc()).limit(1)
    ).scalar_one_or_none()


def _ensure_institution(session: Session, tenant_id: UUID) -> Institution:
    institution = session.execute(
        select(Institution).where(Institution.tenant_id == tenant_id, Institution.name == "Phase 1 Demo University").limit(1)
    ).scalar_one_or_none()
    if institution is None:
        institution = Institution(
            tenant_id=tenant_id,
            name="Phase 1 Demo University",
            external_code="PH1-DEMO",
            state="AZ",
            country="US",
            institution_type="university",
        )
        session.add(institution)
        session.flush()
    return institution


def _ensure_program(session: Session, tenant_id: UUID, institution_id: UUID) -> Program:
    program = session.execute(
        select(Program).where(Program.tenant_id == tenant_id, Program.institution_id == institution_id, Program.name == "Applied Admissions Operations").limit(1)
    ).scalar_one_or_none()
    if program is None:
        program = Program(
            tenant_id=tenant_id,
            institution_id=institution_id,
            name="Applied Admissions Operations",
            program_code="PH1-OPS",
            degree_type="BS",
            is_active=True,
        )
        session.add(program)
        session.flush()
    return program


def _upsert_student(
    session: Session,
    tenant_id: UUID,
    owner: AppUser | None,
    institution: Institution,
    program: Program,
    spec: DemoStudentSpec,
) -> Student:
    now = datetime.now(timezone.utc)
    student = session.execute(
        select(Student).where(Student.tenant_id == tenant_id, Student.external_student_id == spec.external_id).limit(1)
    ).scalar_one_or_none()
    if student is None:
        student = Student(tenant_id=tenant_id, external_student_id=spec.external_id)
        session.add(student)
    student.first_name = spec.first_name
    student.last_name = spec.last_name
    student.preferred_name = spec.first_name
    student.email = spec.email
    student.phone = "555-0100"
    student.city = "Phoenix"
    student.state = "AZ"
    student.country = "US"
    student.target_program_id = program.id
    student.target_institution_id = institution.id
    student.advisor_user_id = owner.id if owner else None
    student.current_stage = spec.stage
    student.risk_level = spec.risk
    student.latest_cumulative_gpa = spec.gpa
    student.accepted_credits = spec.credits
    student.summary = f"Phase 1 demo student seeded for {spec.external_id.lower().replace('-', ' ')}."
    student.latest_activity_at = now - timedelta(hours=DEMO_STUDENTS.index(spec) + 1)
    student.updated_at = now
    session.flush()
    return student


def _apply_statuses(
    session: Session,
    checklist: StudentChecklist,
    items: list[StudentChecklistItem],
    spec: DemoStudentSpec,
) -> None:
    now = datetime.now(timezone.utc)
    evidence_document = None
    if spec.evidence_for_code:
        evidence_document = _ensure_document(session, checklist.tenant_id, checklist.student_id, spec)
    for item in items:
        target_status = spec.statuses.get(item.code)
        if target_status is None:
            continue
        item.status = target_status
        item.updated_by_system = True
        item.updated_at = now
        item.needs_review = target_status == "needs_review"
        item.completed_at = now if target_status in {"complete", "waived"} else None
        item.received_at = now if target_status in {"received", "needs_review", "complete"} else None
        if evidence_document is not None and item.code == spec.evidence_for_code:
            item.source_document_id = evidence_document.id
            item.source_confidence = spec.parser_confidence
    session.flush()


def _ensure_document(session: Session, tenant_id: UUID, student_id: UUID, spec: DemoStudentSpec) -> DocumentUpload:
    now = datetime.now(timezone.utc)
    storage_key = f"phase1-demo/{spec.external_id.lower()}.pdf"
    document = session.execute(
        select(DocumentUpload).where(DocumentUpload.tenant_id == tenant_id, DocumentUpload.storage_key == storage_key).limit(1)
    ).scalar_one_or_none()
    if document is None:
        document = DocumentUpload(
            tenant_id=tenant_id,
            original_filename=f"{spec.external_id.lower()}-transcript.pdf",
            mime_type="application/pdf",
            file_size_bytes=1024,
            storage_bucket="phase1-demo",
            storage_key=storage_key,
            checksum_sha256=f"phase1-demo-{spec.external_id.lower()}",
            upload_status="completed",
            uploaded_at=now,
        )
        session.add(document)
        session.flush()
    transcript = session.execute(
        select(Transcript).where(Transcript.tenant_id == tenant_id, Transcript.document_upload_id == document.id).limit(1)
    ).scalar_one_or_none()
    if transcript is None:
        transcript = Transcript(
            tenant_id=tenant_id,
            document_upload_id=document.id,
            student_id=student_id,
            document_type="transcript",
            status="completed",
            is_official=True,
            is_finalized=True,
            finalized_at=now,
            is_fraudulent=spec.trust_blocked,
            fraud_flagged_at=now if spec.trust_blocked else None,
            matched_at=now,
            matched_by="phase1_demo_seed",
            parser_confidence=spec.parser_confidence,
            page_count=2,
            notes="Seeded Phase 1 demo transcript.",
        )
        session.add(transcript)
    else:
        transcript.student_id = student_id
        transcript.status = "completed"
        transcript.is_fraudulent = spec.trust_blocked
        transcript.fraud_flagged_at = now if spec.trust_blocked else None
        transcript.parser_confidence = spec.parser_confidence
    session.flush()
    return document


def _ensure_trust_block(
    session: Session,
    tenant_id: UUID,
    student: Student,
    owner: AppUser | None,
    spec: DemoStudentSpec,
) -> None:
    document = _ensure_document(session, tenant_id, student.id, spec)
    transcript = session.execute(
        select(Transcript).where(Transcript.tenant_id == tenant_id, Transcript.document_upload_id == document.id).limit(1)
    ).scalar_one()
    flag = session.execute(
        select(TrustFlag)
        .where(
            TrustFlag.tenant_id == tenant_id,
            TrustFlag.student_id == student.id,
            TrustFlag.flag_type == "phase1_demo_trust_hold",
        )
        .limit(1)
    ).scalar_one_or_none()
    if flag is None:
        flag = TrustFlag(
            tenant_id=tenant_id,
            transcript_id=transcript.id,
            student_id=student.id,
            flag_type="phase1_demo_trust_hold",
            severity="high",
            status="open",
            reason="Seeded trust hold for Phase 1 demo queue coverage.",
            detected_by="phase1_demo_seed",
            detected_at=datetime.now(timezone.utc),
            assigned_to_user_id=owner.id if owner else None,
        )
        session.add(flag)
    else:
        flag.transcript_id = transcript.id
        flag.status = "open"
        flag.severity = "high"
        flag.resolved_at = None
        flag.resolution_notes = None
    session.flush()


if __name__ == "__main__":
    main()
