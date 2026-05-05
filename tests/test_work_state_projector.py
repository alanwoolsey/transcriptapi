from uuid import uuid4

from app.services.work_state_projector import WorkStateProjector


def test_ensure_tenant_projection_does_not_rebuild_synchronously():
    projector = WorkStateProjector(session_factory=lambda: None)

    def fail_rebuild(tenant_id):
        raise AssertionError("ensure_tenant_projection must not rebuild during reads")

    projector.rebuild_tenant_projection = fail_rebuild

    projector.ensure_tenant_projection(uuid4())
