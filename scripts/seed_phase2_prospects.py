from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from app.db.models import AppUser, Tenant
from app.db.session import get_session_factory
from app.models.prospect_models import ProspectInquiryRequest
from app.services.prospect_service import ProspectService


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed Phase 2 prospect portal demo data.")
    parser.add_argument("--tenant-slug", default="test1", help="Tenant slug to seed.")
    args = parser.parse_args()

    session_factory = get_session_factory()
    service = ProspectService()
    with session_factory() as session:
        tenant = session.execute(select(Tenant).where(Tenant.slug == args.tenant_slug).limit(1)).scalar_one_or_none()
        if tenant is None:
            raise RuntimeError(f"Tenant not found: {args.tenant_slug}")
        actor = session.execute(select(AppUser).where(AppUser.tenant_id == tenant.id, AppUser.is_active.is_(True)).limit(1)).scalar_one_or_none()
        if actor is None:
            raise RuntimeError(f"No active user found for tenant: {args.tenant_slug}")

        upload = service.create_transcript_upload(
            session,
            tenant_id=tenant.id,
            actor_user_id=actor.id,
            email="phase2.transcript@example.test",
            population="transfer",
            program_interest="BS Nursing Transfer",
            term_interest="Fall 2026",
            filename="phase2-transfer-transcript.pdf",
            content_type="application/pdf",
            content=b"Phase 2 seeded transcript preview",
        )

        payloads = [
            ProspectInquiryRequest(
                firstName="Avery",
                lastName="Manual",
                email="phase2.manual@example.test",
                phone="555-0201",
                population="first_year",
                programInterest="BS Business",
                termInterest="Fall 2026",
                source="manual_entry",
                sourceCategory="direct",
                campaign="phase2-demo",
                consent=True,
            ),
            ProspectInquiryRequest(
                firstName="Taylor",
                lastName="Transcript",
                email="phase2.transcript@example.test",
                phone="555-0202",
                population="transfer",
                programInterest="BS Nursing Transfer",
                termInterest="Fall 2026",
                priorInstitution="River County College",
                source="prospect_portal",
                sourceCategory="transcript_first",
                campaign="phase2-demo",
                consent=True,
                transcriptUploadId=upload.uploadId,
            ),
            ProspectInquiryRequest(
                firstName="Jordan",
                lastName="Question",
                email="phase2.question@example.test",
                phone="555-0203",
                population="transfer",
                programInterest="BS Psychology",
                termInterest="Spring 2027",
                priorInstitution="Coastal Community College",
                source="prospect_portal",
                sourceCategory="direct",
                campaign="phase2-demo",
                consent=True,
                question="Can someone explain how my credits apply?",
            ),
            ProspectInquiryRequest(
                firstName="Rowan",
                lastName="Duplicate",
                email="phase1.trustblocked@example.test",
                phone="555-0204",
                population="transfer",
                programInterest="BS Nursing Transfer",
                termInterest="Fall 2026",
                source="manual_entry",
                sourceCategory="direct",
                campaign="phase2-demo",
                consent=True,
                externalReferenceId="PH2-DUPLICATE",
            ),
            ProspectInquiryRequest(
                firstName="Casey",
                lastName="Converted",
                email="phase2.converted@example.test",
                phone="555-0205",
                population="transfer",
                programInterest="BS Computer Science",
                termInterest="Fall 2026",
                priorInstitution="North Valley College",
                source="prospect_portal",
                sourceCategory="direct",
                campaign="phase2-demo",
                consent=True,
            ),
        ]

        created = []
        for payload in payloads:
            response = service.create_inquiry(session, tenant_id=tenant.id, actor_user_id=actor.id, payload=payload)
            created.append(f"{payload.email}:{response.prospect.status}")
            if payload.email == "phase2.converted@example.test":
                service.convert_application(
                    session,
                    tenant_id=tenant.id,
                    actor_user_id=actor.id,
                    prospect_id=response.prospect.prospectId,
                )
                created[-1] = f"{payload.email}:converted"

    print(f"Seeded Phase 2 prospects for tenant '{args.tenant_slug}': {', '.join(created)}")


if __name__ == "__main__":
    main()
