from types import SimpleNamespace
from uuid import uuid4

import pytest

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
