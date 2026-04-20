from uuid import uuid4

from app.services.rbac_service import RBACService, SENSITIVITY_ACADEMIC_RECORD


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _FakeSession:
    def __init__(self, rows_by_call):
        self._rows_by_call = rows_by_call
        self._index = 0

    def execute(self, stmt):
        rows = self._rows_by_call[self._index]
        self._index += 1
        return _FakeResult(rows)


def test_resolve_profile_falls_back_to_membership_role(monkeypatch):
    service = RBACService()
    monkeypatch.setattr(service, "sync_seed_data", lambda session: None)
    session = _FakeSession([
        [],  # role assignments
        [],  # record exception grants
    ])

    profile = service.resolve_profile(
        session,
        tenant_id=uuid4(),
        user_id=uuid4(),
        membership_role="counselor",
    )

    assert "admissions_counselor" in profile.roles
    assert profile.can("edit_checklist")
    assert profile.can_access_tier(SENSITIVITY_ACADEMIC_RECORD)


def test_resolve_profile_uses_explicit_assignment_rows(monkeypatch):
    service = RBACService()
    monkeypatch.setattr(service, "sync_seed_data", lambda session: None)

    role = type("Role", (), {"system_key": "trust_analyst", "id": uuid4()})()
    assignment = type("Assignment", (), {"id": uuid4()})()
    session = _FakeSession([
        [(assignment, role)],  # assignments
        [("manage_trust_cases",), ("view_trust_flags",)],  # permissions
        [("program", "nursing")],  # scopes
        [("trust_fraud_flags",)],  # sensitivity
        [("fraud_trust",)],  # record exceptions
    ])

    profile = service.resolve_profile(
        session,
        tenant_id=uuid4(),
        user_id=uuid4(),
        membership_role=None,
    )

    assert profile.can("manage_trust_cases")
    assert "nursing" in profile.scopes["program"]
    assert "fraud_trust" in profile.record_exceptions
