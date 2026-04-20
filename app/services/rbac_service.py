from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterable
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    AUTHZ_SCHEMA,
    AuthzPermission,
    AuthzRecordExceptionGrant,
    AuthzRole,
    AuthzRolePermission,
    AuthzScopeGrant,
    AuthzSensitivityGrant,
    AuthzUserRoleAssignment,
)

SENSITIVITY_BASIC_PROFILE = "basic_profile"
SENSITIVITY_ACADEMIC_RECORD = "academic_record"
SENSITIVITY_TRANSCRIPT_IMAGES = "transcript_images"
SENSITIVITY_TRUST_FRAUD_FLAGS = "trust_fraud_flags"
SENSITIVITY_NOTES = "notes"
SENSITIVITY_RELEASED_DECISIONS = "released_decisions"

STARTER_PERMISSIONS: list[dict[str, str]] = [
    {"code": "view_student_360", "label": "View Student 360", "category": "student"},
    {"code": "edit_student_profile", "label": "Edit Student Profile", "category": "student"},
    {"code": "merge_duplicates", "label": "Merge Duplicates", "category": "student"},
    {"code": "view_checklist", "label": "View Checklist", "category": "checklist"},
    {"code": "edit_checklist", "label": "Edit Checklist", "category": "checklist"},
    {"code": "override_checklist", "label": "Override Checklist", "category": "checklist"},
    {"code": "view_document_metadata", "label": "View Document Metadata", "category": "document"},
    {"code": "view_sensitive_docs", "label": "View Sensitive Docs", "category": "document"},
    {"code": "upload_documents", "label": "Upload Documents", "category": "document"},
    {"code": "index_documents", "label": "Index Documents", "category": "document"},
    {"code": "resolve_document_exceptions", "label": "Resolve Document Exceptions", "category": "document"},
    {"code": "view_decision_packet", "label": "View Decision Packet", "category": "decision"},
    {"code": "add_decision_rationale", "label": "Add Decision Rationale", "category": "decision"},
    {"code": "recommend_decision", "label": "Recommend Decision", "category": "decision"},
    {"code": "finalize_decision", "label": "Finalize Decision", "category": "decision"},
    {"code": "release_decision", "label": "Release Decision", "category": "decision"},
    {"code": "view_trust_flags", "label": "View Trust Flags", "category": "trust"},
    {"code": "manage_trust_cases", "label": "Manage Trust Cases", "category": "trust"},
    {"code": "quarantine_document", "label": "Quarantine Document", "category": "trust"},
    {"code": "view_deposit_status", "label": "View Deposit Status", "category": "enrollment"},
    {"code": "update_deposit_status", "label": "Update Deposit Status", "category": "enrollment"},
    {"code": "view_melt_risk", "label": "View Melt Risk", "category": "enrollment"},
    {"code": "view_dashboards", "label": "View Dashboards", "category": "reporting"},
    {"code": "manage_integrations", "label": "Manage Integrations", "category": "integration"},
    {"code": "api_access", "label": "API Access", "category": "integration"},
    {"code": "admin_users_view", "label": "View Admin Users", "category": "admin"},
    {"code": "admin_users_create", "label": "Create Admin Users", "category": "admin"},
    {"code": "admin_users_update", "label": "Update Admin Users", "category": "admin"},
    {"code": "admin_users_deactivate", "label": "Deactivate Admin Users", "category": "admin"},
    {"code": "admin_users_delete", "label": "Delete Admin Users", "category": "admin"},
    {"code": "admin_roles_view", "label": "View Admin Roles", "category": "admin"},
    {"code": "admin_scopes_manage", "label": "Manage Admin Scopes", "category": "admin"},
]

STARTER_ROLES: dict[str, dict[str, object]] = {
    "admissions_counselor": {
        "name": "Admissions Counselor",
        "permissions": {"view_student_360", "view_checklist", "edit_checklist", "view_document_metadata", "view_deposit_status", "view_melt_risk", "view_dashboards"},
        "sensitivities": {SENSITIVITY_BASIC_PROFILE, SENSITIVITY_ACADEMIC_RECORD},
    },
    "admissions_processor": {
        "name": "Admissions Processor",
        "permissions": {"view_student_360", "view_checklist", "edit_checklist", "view_document_metadata", "view_sensitive_docs", "upload_documents", "index_documents", "resolve_document_exceptions"},
        "sensitivities": {SENSITIVITY_BASIC_PROFILE, SENSITIVITY_ACADEMIC_RECORD, SENSITIVITY_TRANSCRIPT_IMAGES},
    },
    "reviewer_evaluator": {
        "name": "Reviewer / Evaluator",
        "permissions": {"view_student_360", "view_checklist", "view_document_metadata", "view_sensitive_docs", "view_decision_packet", "add_decision_rationale", "recommend_decision", "view_trust_flags"},
        "sensitivities": {SENSITIVITY_BASIC_PROFILE, SENSITIVITY_ACADEMIC_RECORD, SENSITIVITY_TRANSCRIPT_IMAGES, SENSITIVITY_NOTES},
    },
    "decision_releaser_director": {
        "name": "Decision Releaser / Director",
        "permissions": {p["code"] for p in STARTER_PERMISSIONS if p["code"] != "api_access"},
        "sensitivities": {
            SENSITIVITY_BASIC_PROFILE,
            SENSITIVITY_ACADEMIC_RECORD,
            SENSITIVITY_TRANSCRIPT_IMAGES,
            SENSITIVITY_TRUST_FRAUD_FLAGS,
            SENSITIVITY_NOTES,
            SENSITIVITY_RELEASED_DECISIONS,
        },
    },
    "trust_analyst": {
        "name": "Trust Analyst",
        "permissions": {"view_document_metadata", "view_sensitive_docs", "view_trust_flags", "manage_trust_cases", "quarantine_document"},
        "sensitivities": {SENSITIVITY_BASIC_PROFILE, SENSITIVITY_TRANSCRIPT_IMAGES, SENSITIVITY_TRUST_FRAUD_FLAGS},
    },
    "registrar_transfer_specialist": {
        "name": "Registrar / Transfer Specialist",
        "permissions": {"view_student_360", "view_checklist", "view_document_metadata", "view_sensitive_docs", "view_decision_packet"},
        "sensitivities": {SENSITIVITY_BASIC_PROFILE, SENSITIVITY_ACADEMIC_RECORD, SENSITIVITY_TRANSCRIPT_IMAGES},
    },
    "financial_aid": {
        "name": "Financial Aid",
        "permissions": {"view_student_360", "view_deposit_status", "update_deposit_status", "view_dashboards"},
        "sensitivities": {SENSITIVITY_BASIC_PROFILE, SENSITIVITY_ACADEMIC_RECORD},
    },
    "read_only_leadership": {
        "name": "Read Only Leadership",
        "permissions": {"view_student_360", "view_checklist", "view_document_metadata", "view_decision_packet", "view_trust_flags", "view_dashboards", "view_deposit_status", "view_melt_risk"},
        "sensitivities": {SENSITIVITY_BASIC_PROFILE, SENSITIVITY_ACADEMIC_RECORD, SENSITIVITY_RELEASED_DECISIONS},
    },
    "integration_service": {
        "name": "Integration Service",
        "permissions": {"api_access", "manage_integrations", "view_document_metadata"},
        "sensitivities": {SENSITIVITY_BASIC_PROFILE},
    },
}

MEMBERSHIP_ROLE_FALLBACKS = {
    "counselor": "admissions_counselor",
    "processor": "admissions_processor",
    "reviewer": "reviewer_evaluator",
    "director": "decision_releaser_director",
    "registrar": "registrar_transfer_specialist",
    "financial aid": "financial_aid",
    "read only": "read_only_leadership",
    "service": "integration_service",
}


@dataclass
class AuthorizationProfile:
    base_role: str | None = None
    roles: set[str] = field(default_factory=set)
    permissions: set[str] = field(default_factory=set)
    scopes: dict[str, set[str]] = field(default_factory=dict)
    record_exceptions: set[str] = field(default_factory=set)
    sensitivity_tiers: set[str] = field(default_factory=set)

    def can(self, permission_code: str) -> bool:
        return permission_code in self.permissions

    def can_access_tier(self, tier: str) -> bool:
        return tier in self.sensitivity_tiers


class RBACService:
    def sync_seed_data(self, session: Session) -> None:
        roles_by_key = {
            role.system_key: role
            for role in session.execute(select(AuthzRole)).scalars().all()
        }
        permissions_by_code = {
            permission.code: permission
            for permission in session.execute(select(AuthzPermission)).scalars().all()
        }

        changed = False
        for role_key, role_def in STARTER_ROLES.items():
            role = roles_by_key.get(role_key)
            if role is None:
                role = AuthzRole(system_key=role_key, name=str(role_def["name"]), description=f"System role: {role_def['name']}", active=True)
                session.add(role)
                session.flush()
                roles_by_key[role_key] = role
                changed = True

        for permission_def in STARTER_PERMISSIONS:
            permission = permissions_by_code.get(permission_def["code"])
            if permission is None:
                permission = AuthzPermission(
                    code=permission_def["code"],
                    label=permission_def["label"],
                    category=permission_def["category"],
                    description=permission_def["label"],
                    active=True,
                )
                session.add(permission)
                session.flush()
                permissions_by_code[permission.code] = permission
                changed = True

        existing_role_permissions = {
            (str(item.role_id), str(item.permission_id))
            for item in session.execute(select(AuthzRolePermission)).scalars().all()
        }
        for role_key, role_def in STARTER_ROLES.items():
            role = roles_by_key[role_key]
            for permission_code in role_def["permissions"]:
                permission = permissions_by_code[permission_code]
                pair = (str(role.id), str(permission.id))
                if pair not in existing_role_permissions:
                    session.add(AuthzRolePermission(role_id=role.id, permission_id=permission.id))
                    changed = True

        if changed:
            session.flush()

    def resolve_profile(
        self,
        session: Session,
        *,
        tenant_id: UUID,
        user_id: UUID,
        membership_role: str | None,
    ) -> AuthorizationProfile:
        self.sync_seed_data(session)
        profile = AuthorizationProfile()

        assignment_rows = session.execute(
            select(AuthzUserRoleAssignment, AuthzRole)
            .join(AuthzRole, AuthzRole.id == AuthzUserRoleAssignment.role_id)
            .where(
                AuthzUserRoleAssignment.tenant_id == tenant_id,
                AuthzUserRoleAssignment.user_id == user_id,
                AuthzUserRoleAssignment.active.is_(True),
            )
        ).all()

        if assignment_rows:
            for assignment, role in assignment_rows:
                profile.roles.add(role.system_key)
            assignment_ids = [assignment.id for assignment, _ in assignment_rows]
            permission_rows = session.execute(
                select(AuthzPermission.code)
                .join(AuthzRolePermission, AuthzRolePermission.permission_id == AuthzPermission.id)
                .join(AuthzRole, AuthzRole.id == AuthzRolePermission.role_id)
                .where(AuthzRole.id.in_([role.id for _, role in assignment_rows]))
            ).all()
            profile.permissions.update(code for (code,) in permission_rows)
            self._load_scopes(session, tenant_id, user_id, assignment_ids, profile)
            self._load_sensitivity_tiers(session, tenant_id, user_id, profile)
        else:
            fallback_key = self._fallback_role_key(membership_role)
            if fallback_key:
                role_def = STARTER_ROLES[fallback_key]
                profile.base_role = fallback_key
                profile.roles.add(fallback_key)
                profile.permissions.update(role_def["permissions"])
                profile.sensitivity_tiers.update(role_def["sensitivities"])

        profile.scopes.setdefault("tenant", set()).add(str(tenant_id))
        profile.record_exceptions.update(
            code for (code,) in session.execute(
                select(AuthzRecordExceptionGrant.exception_code).where(
                    AuthzRecordExceptionGrant.tenant_id == tenant_id,
                    AuthzRecordExceptionGrant.user_id == user_id,
                    AuthzRecordExceptionGrant.active.is_(True),
                )
            ).all()
        )

        if not profile.sensitivity_tiers and profile.roles:
            for role_key in list(profile.roles):
                role_def = STARTER_ROLES.get(role_key)
                if role_def:
                    profile.sensitivity_tiers.update(role_def["sensitivities"])
        return profile

    def require_permission(self, profile: AuthorizationProfile, permission_code: str) -> None:
        if not profile.can(permission_code):
            raise PermissionError(f"Missing permission: {permission_code}")

    def require_sensitivity(self, profile: AuthorizationProfile, tier: str) -> None:
        if not profile.can_access_tier(tier):
            raise PermissionError(f"Missing sensitivity tier: {tier}")

    def _load_scopes(
        self,
        session: Session,
        tenant_id: UUID,
        user_id: UUID,
        assignment_ids: Iterable[UUID],
        profile: AuthorizationProfile,
    ) -> None:
        rows = session.execute(
            select(AuthzScopeGrant.scope_type, AuthzScopeGrant.scope_value).where(
                AuthzScopeGrant.tenant_id == tenant_id,
                AuthzScopeGrant.user_id == user_id,
                AuthzScopeGrant.active.is_(True),
            )
        ).all()
        for scope_type, scope_value in rows:
            profile.scopes.setdefault(scope_type, set()).add(scope_value)

    def _load_sensitivity_tiers(self, session: Session, tenant_id: UUID, user_id: UUID, profile: AuthorizationProfile) -> None:
        rows = session.execute(
            select(AuthzSensitivityGrant.sensitivity_tier).where(
                AuthzSensitivityGrant.tenant_id == tenant_id,
                AuthzSensitivityGrant.user_id == user_id,
                AuthzSensitivityGrant.active.is_(True),
            )
        ).all()
        profile.sensitivity_tiers.update(tier for (tier,) in rows)

    def _fallback_role_key(self, membership_role: str | None) -> str | None:
        if not membership_role:
            return None
        normalized = membership_role.strip().lower()
        return MEMBERSHIP_ROLE_FALLBACKS.get(normalized)
