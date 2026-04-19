from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.models.api_models import ParseTranscriptResponse
from app.services.persistence import TranscriptPersistenceService


def test_get_tenant_requires_valid_uuid():
    service = TranscriptPersistenceService(session_factory=lambda: None)

    with pytest.raises(ValueError, match="valid tenant_id"):
        service._get_tenant(session=SimpleNamespace(), tenant_id="not-a-uuid")


def test_get_tenant_raises_when_missing():
    service = TranscriptPersistenceService(session_factory=lambda: None)

    class FakeQuery:
        def filter(self, *args, **kwargs):
            return self

        def one_or_none(self):
            return None

    class FakeSession:
        def query(self, model):
            return FakeQuery()

    with pytest.raises(ValueError, match="Tenant not found"):
        service._get_tenant(session=FakeSession(), tenant_id=str(uuid4()))


def test_validate_parsed_transcript_requires_student_identity():
    service = TranscriptPersistenceService(session_factory=lambda: None)
    parsed = ParseTranscriptResponse(
        documentId="doc-1",
        demographic={"firstName": "", "lastName": "", "studentId": "", "institutionName": "Example U"},
        courses=[{"courseId": "BIO101", "courseTitle": "Biology", "credit": "3", "grade": "A"}],
        metadata={},
    )

    with pytest.raises(ValueError, match="identify student"):
        service._validate_parsed_transcript(parsed)


def test_validate_parsed_transcript_requires_courses():
    service = TranscriptPersistenceService(session_factory=lambda: None)
    parsed = ParseTranscriptResponse(
        documentId="doc-1",
        demographic={"firstName": "Avery", "lastName": "Carter", "studentId": "", "institutionName": "Example U"},
        courses=[],
        metadata={},
    )

    with pytest.raises(ValueError, match="No courses were extracted"):
        service._validate_parsed_transcript(parsed)


def test_failure_code_maps_student_resolution_and_course_mapping():
    service = TranscriptPersistenceService(session_factory=lambda: None)

    assert service._failure_code_from_message("Could not identify student from transcript.") == "student_resolution_failed"
    assert service._failure_code_from_message("No courses were extracted from transcript.") == "course_mapping_failed"
    assert service._failure_code_from_message("Something else broke.") == "processing_failed"
