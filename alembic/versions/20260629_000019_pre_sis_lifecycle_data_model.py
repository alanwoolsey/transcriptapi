"""pre sis lifecycle data model

Revision ID: 20260629_000019
Revises: 20260627_000018
Create Date: 2026-06-29
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260629_000019"
down_revision = "20260627_000018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'campuses',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('campus_code', sa.Text(), nullable=False),
        sa.Column('name', sa.Text(), nullable=False),
        sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('metadata_json', postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.UniqueConstraint('tenant_id', 'campus_code', name='uq_campuses_tenant_code'),
    )

    op.create_table(
        'communication_templates',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.Text(), nullable=False),
        sa.Column('channel', sa.Text(), nullable=False),
        sa.Column('subject', sa.Text(), nullable=True),
        sa.Column('body', sa.Text(), nullable=False),
        sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('metadata_json', postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('now()')),
    )
    op.create_index('ix_communication_templates_tenant_channel', 'communication_templates', ['tenant_id', 'channel'])

    op.create_table(
        'external_system_identifiers',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('system_name', sa.Text(), nullable=False),
        sa.Column('entity_type', sa.Text(), nullable=False),
        sa.Column('entity_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('external_id', sa.Text(), nullable=False),
        sa.Column('external_id_type', sa.Text(), nullable=True),
        sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('metadata_json', postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.UniqueConstraint('tenant_id', 'system_name', 'entity_type', 'entity_id', name='uq_external_identifiers_entity'),
    )
    op.create_index('ix_external_identifiers_tenant_external', 'external_system_identifiers', ['tenant_id', 'system_name', 'external_id'])

    op.create_table(
        'reference_values',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('category', sa.Text(), nullable=False),
        sa.Column('code', sa.Text(), nullable=False),
        sa.Column('label', sa.Text(), nullable=False),
        sa.Column('sort_order', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('metadata_json', postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.UniqueConstraint('tenant_id', 'category', 'code', name='uq_reference_values_tenant_category_code'),
    )
    op.create_index('ix_reference_values_tenant_category', 'reference_values', ['tenant_id', 'category', 'active'])

    op.create_table(
        'sis_connections',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('sis_system', sa.Text(), nullable=False),
        sa.Column('name', sa.Text(), nullable=False),
        sa.Column('status', sa.Text(), nullable=False, server_default=sa.text("'active'")),
        sa.Column('config_json', postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('now()')),
    )
    op.create_index('ix_sis_connections_tenant_system', 'sis_connections', ['tenant_id', 'sis_system'])

    op.create_table(
        'sis_field_mappings',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('sis_system', sa.Text(), nullable=False),
        sa.Column('source_entity', sa.Text(), nullable=False),
        sa.Column('source_field', sa.Text(), nullable=False),
        sa.Column('target_entity', sa.Text(), nullable=False),
        sa.Column('target_field', sa.Text(), nullable=False),
        sa.Column('transform_rule_json', postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column('required', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('now()')),
    )
    op.create_index('ix_sis_field_mappings_tenant_system_source', 'sis_field_mappings', ['tenant_id', 'sis_system', 'source_entity'])

    op.create_table(
        'teams',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.Text(), nullable=False),
        sa.Column('team_type', sa.Text(), nullable=True),
        sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.UniqueConstraint('tenant_id', 'name', name='uq_teams_tenant_name'),
    )
    op.create_index('ix_teams_tenant_type', 'teams', ['tenant_id', 'team_type'])

    op.create_table(
        'terms',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('term_code', sa.Text(), nullable=False),
        sa.Column('name', sa.Text(), nullable=False),
        sa.Column('start_date', sa.Date(), nullable=True),
        sa.Column('end_date', sa.Date(), nullable=True),
        sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('metadata_json', postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.UniqueConstraint('tenant_id', 'term_code', name='uq_terms_tenant_code'),
    )

    op.create_table(
        'team_memberships',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('team_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('teams.id', ondelete='CASCADE'), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('app_users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('role', sa.Text(), nullable=True),
        sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.UniqueConstraint('tenant_id', 'team_id', 'user_id', name='uq_team_memberships_team_user'),
    )
    op.create_index('ix_team_memberships_tenant_user', 'team_memberships', ['tenant_id', 'user_id'])

    op.create_table(
        'form_submissions',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('student_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('students.id', ondelete='SET NULL'), nullable=True),
        sa.Column('external_form_id', sa.Text(), nullable=True),
        sa.Column('form_name', sa.Text(), nullable=False),
        sa.Column('status', sa.Text(), nullable=False),
        sa.Column('submitted_at', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('payload_json', postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('now()')),
    )
    op.create_index('ix_form_submissions_tenant_student', 'form_submissions', ['tenant_id', 'student_id'])

    op.create_table(
        'student_addresses',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('student_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('students.id', ondelete='CASCADE'), nullable=False),
        sa.Column('address_type', sa.Text(), nullable=False),
        sa.Column('line1', sa.Text(), nullable=True),
        sa.Column('line2', sa.Text(), nullable=True),
        sa.Column('city', sa.Text(), nullable=True),
        sa.Column('state', sa.Text(), nullable=True),
        sa.Column('postal_code', sa.Text(), nullable=True),
        sa.Column('country', sa.Text(), nullable=True),
        sa.Column('is_primary', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('source', sa.Text(), nullable=True),
        sa.Column('metadata_json', postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('now()')),
    )
    op.create_index('ix_student_addresses_tenant_student', 'student_addresses', ['tenant_id', 'student_id'])

    op.create_table(
        'student_communication_preferences',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('student_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('students.id', ondelete='CASCADE'), nullable=False),
        sa.Column('channel', sa.Text(), nullable=False),
        sa.Column('opted_in', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('preference_json', postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('now()')),
    )
    op.create_index('ix_student_communication_preferences_tenant_student', 'student_communication_preferences', ['tenant_id', 'student_id'])

    op.create_table(
        'student_contact_methods',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('student_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('students.id', ondelete='CASCADE'), nullable=False),
        sa.Column('contact_type', sa.Text(), nullable=False),
        sa.Column('value', sa.Text(), nullable=False),
        sa.Column('is_primary', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('is_verified', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('allows_sms', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('allows_email', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('opt_out', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('source', sa.Text(), nullable=True),
        sa.Column('metadata_json', postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('now()')),
    )
    op.create_index('ix_student_contact_methods_tenant_student', 'student_contact_methods', ['tenant_id', 'student_id'])
    op.create_index('ix_student_contact_methods_tenant_value', 'student_contact_methods', ['tenant_id', 'value'])

    op.create_table(
        'student_profile_facts',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('student_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('students.id', ondelete='CASCADE'), nullable=False),
        sa.Column('field_name', sa.Text(), nullable=False),
        sa.Column('field_value', sa.Text(), nullable=True),
        sa.Column('source_type', sa.Text(), nullable=False),
        sa.Column('source_id', sa.Text(), nullable=True),
        sa.Column('confidence', sa.Numeric(5, 4), nullable=True),
        sa.Column('verified', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('effective_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('metadata_json', postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('now()')),
    )
    op.create_index('ix_student_profile_facts_tenant_student_field', 'student_profile_facts', ['tenant_id', 'student_id', 'field_name'])

    op.create_table(
        'student_program_interests',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('student_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('students.id', ondelete='CASCADE'), nullable=False),
        sa.Column('program_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('programs.id', ondelete='SET NULL'), nullable=True),
        sa.Column('program_name_raw', sa.Text(), nullable=True),
        sa.Column('interest_rank', sa.Integer(), nullable=True),
        sa.Column('interest_status', sa.Text(), nullable=False, server_default=sa.text("'active'")),
        sa.Column('source', sa.Text(), nullable=False),
        sa.Column('captured_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('metadata_json', postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
    )
    op.create_index('ix_student_program_interests_tenant_program', 'student_program_interests', ['tenant_id', 'program_id'])
    op.create_index('ix_student_program_interests_tenant_student', 'student_program_interests', ['tenant_id', 'student_id'])

    op.create_table(
        'student_relationships',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('student_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('students.id', ondelete='CASCADE'), nullable=False),
        sa.Column('related_person_name', sa.Text(), nullable=False),
        sa.Column('relationship_type', sa.Text(), nullable=False),
        sa.Column('email', sa.Text(), nullable=True),
        sa.Column('phone', sa.Text(), nullable=True),
        sa.Column('organization', sa.Text(), nullable=True),
        sa.Column('is_emergency_contact', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('has_proxy_access', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('ferpa_release_status', sa.Text(), nullable=True),
        sa.Column('metadata_json', postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('now()')),
    )
    op.create_index('ix_student_relationships_tenant_student', 'student_relationships', ['tenant_id', 'student_id'])

    op.create_table(
        'student_test_scores',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('student_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('students.id', ondelete='CASCADE'), nullable=False),
        sa.Column('test_type', sa.Text(), nullable=False),
        sa.Column('test_date', sa.Date(), nullable=True),
        sa.Column('score_name', sa.Text(), nullable=False),
        sa.Column('score_value', sa.Text(), nullable=False),
        sa.Column('percentile', sa.Integer(), nullable=True),
        sa.Column('source', sa.Text(), nullable=True),
        sa.Column('official_status', sa.Text(), nullable=False, server_default=sa.text("'unknown'")),
        sa.Column('document_upload_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('document_uploads.id', ondelete='SET NULL'), nullable=True),
        sa.Column('metadata_json', postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('now()')),
    )
    op.create_index('ix_student_test_scores_tenant_student', 'student_test_scores', ['tenant_id', 'student_id'])
    op.create_index('ix_student_test_scores_tenant_type', 'student_test_scores', ['tenant_id', 'test_type'])

    op.create_table(
        'applications',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('student_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('students.id', ondelete='CASCADE'), nullable=False),
        sa.Column('prospect_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('prospects.id', ondelete='SET NULL'), nullable=True),
        sa.Column('application_number', sa.Text(), nullable=False),
        sa.Column('application_type', sa.Text(), nullable=False),
        sa.Column('student_type', sa.Text(), nullable=True),
        sa.Column('population', sa.Text(), nullable=True),
        sa.Column('admit_term_code', sa.Text(), nullable=True),
        sa.Column('entry_term_code', sa.Text(), nullable=True),
        sa.Column('program_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('programs.id', ondelete='SET NULL'), nullable=True),
        sa.Column('campus_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('campuses.id', ondelete='SET NULL'), nullable=True),
        sa.Column('modality', sa.Text(), nullable=True),
        sa.Column('status', sa.Text(), nullable=False, server_default=sa.text("'draft'")),
        sa.Column('submitted_at', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('completed_at', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('decision_status', sa.Text(), nullable=True),
        sa.Column('decision_at', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.UniqueConstraint('tenant_id', 'application_number', name='uq_applications_tenant_application_number'),
    )
    op.create_index('ix_applications_tenant_program_term', 'applications', ['tenant_id', 'program_id', 'entry_term_code'])
    op.create_index('ix_applications_tenant_status', 'applications', ['tenant_id', 'status'])
    op.create_index('ix_applications_tenant_student', 'applications', ['tenant_id', 'student_id'])

    op.create_table(
        'form_submission_answers',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('form_submission_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('form_submissions.id', ondelete='CASCADE'), nullable=False),
        sa.Column('question_key', sa.Text(), nullable=False),
        sa.Column('question_label', sa.Text(), nullable=True),
        sa.Column('answer_value', sa.Text(), nullable=True),
        sa.Column('answer_json', postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('now()')),
    )
    op.create_index('ix_form_submission_answers_tenant_submission', 'form_submission_answers', ['tenant_id', 'form_submission_id'])

    op.create_table(
        'student_education_history',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('student_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('students.id', ondelete='CASCADE'), nullable=False),
        sa.Column('institution_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('institutions.id', ondelete='SET NULL'), nullable=True),
        sa.Column('institution_name', sa.Text(), nullable=False),
        sa.Column('institution_type', sa.Text(), nullable=True),
        sa.Column('ceeb_code', sa.Text(), nullable=True),
        sa.Column('start_date', sa.Date(), nullable=True),
        sa.Column('end_date', sa.Date(), nullable=True),
        sa.Column('graduation_date', sa.Date(), nullable=True),
        sa.Column('degree_earned', sa.Text(), nullable=True),
        sa.Column('gpa_self_reported', sa.Numeric(5, 3), nullable=True),
        sa.Column('transcript_required', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('transcript_received', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('transcript_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('transcripts.id', ondelete='SET NULL'), nullable=True),
        sa.Column('source', sa.Text(), nullable=True),
        sa.Column('metadata_json', postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('now()')),
    )
    op.create_index('ix_student_education_history_tenant_institution', 'student_education_history', ['tenant_id', 'institution_id'])
    op.create_index('ix_student_education_history_tenant_student', 'student_education_history', ['tenant_id', 'student_id'])

    op.create_table(
        'application_documents',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('application_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('applications.id', ondelete='CASCADE'), nullable=False),
        sa.Column('student_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('students.id', ondelete='CASCADE'), nullable=False),
        sa.Column('document_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('document_uploads.id', ondelete='CASCADE'), nullable=False),
        sa.Column('document_role', sa.Text(), nullable=False),
        sa.Column('match_status', sa.Text(), nullable=False, server_default=sa.text("'linked'")),
        sa.Column('match_confidence', sa.Numeric(5, 4), nullable=True),
        sa.Column('linked_by', sa.Text(), nullable=False),
        sa.Column('linked_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('metadata_json', postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.UniqueConstraint('tenant_id', 'application_id', 'document_id', name='uq_application_documents_application_document'),
    )
    op.create_index('ix_application_documents_tenant_application', 'application_documents', ['tenant_id', 'application_id'])
    op.create_index('ix_application_documents_tenant_student', 'application_documents', ['tenant_id', 'student_id'])

    op.create_table(
        'application_form_submissions',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('application_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('applications.id', ondelete='CASCADE'), nullable=False),
        sa.Column('form_submission_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('form_submissions.id', ondelete='CASCADE'), nullable=False),
        sa.Column('link_type', sa.Text(), nullable=False, server_default=sa.text("'application'")),
        sa.Column('linked_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.UniqueConstraint('tenant_id', 'application_id', 'form_submission_id', name='uq_application_form_submissions_application_form'),
    )
    op.create_index('ix_application_form_submissions_tenant_application', 'application_form_submissions', ['tenant_id', 'application_id'])

    op.create_table(
        'application_readiness',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('application_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('applications.id', ondelete='CASCADE'), nullable=False),
        sa.Column('student_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('students.id', ondelete='CASCADE'), nullable=False),
        sa.Column('readiness_state', sa.Text(), nullable=False),
        sa.Column('reason_code', sa.Text(), nullable=False),
        sa.Column('reason_label', sa.Text(), nullable=False),
        sa.Column('blocking_item_count', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.Column('trust_blocked', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('computed_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('readiness_json', postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
    )
    op.create_index('ix_application_readiness_tenant_application', 'application_readiness', ['tenant_id', 'application_id'], unique=True)
    op.create_index('ix_application_readiness_tenant_state', 'application_readiness', ['tenant_id', 'readiness_state'])

    op.create_table(
        'application_status_history',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('application_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('applications.id', ondelete='CASCADE'), nullable=False),
        sa.Column('student_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('students.id', ondelete='CASCADE'), nullable=False),
        sa.Column('from_status', sa.Text(), nullable=True),
        sa.Column('to_status', sa.Text(), nullable=False),
        sa.Column('reason', sa.Text(), nullable=True),
        sa.Column('actor_user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('app_users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('changed_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('metadata_json', postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
    )
    op.create_index('ix_application_status_history_tenant_application_changed', 'application_status_history', ['tenant_id', 'application_id', sa.text('changed_at DESC')])

    op.create_table(
        'communication_messages',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('student_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('students.id', ondelete='CASCADE'), nullable=False),
        sa.Column('application_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('applications.id', ondelete='SET NULL'), nullable=True),
        sa.Column('template_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('communication_templates.id', ondelete='SET NULL'), nullable=True),
        sa.Column('channel', sa.Text(), nullable=False),
        sa.Column('direction', sa.Text(), nullable=False),
        sa.Column('subject', sa.Text(), nullable=True),
        sa.Column('body', sa.Text(), nullable=True),
        sa.Column('status', sa.Text(), nullable=False),
        sa.Column('provider_message_id', sa.Text(), nullable=True),
        sa.Column('sent_at', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('metadata_json', postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
    )
    op.create_index('ix_communication_messages_tenant_application', 'communication_messages', ['tenant_id', 'application_id'])
    op.create_index('ix_communication_messages_tenant_student', 'communication_messages', ['tenant_id', 'student_id', sa.text('created_at DESC')])

    op.create_table(
        'sis_exports',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('student_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('students.id', ondelete='CASCADE'), nullable=False),
        sa.Column('application_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('applications.id', ondelete='SET NULL'), nullable=True),
        sa.Column('sis_system', sa.Text(), nullable=False),
        sa.Column('export_type', sa.Text(), nullable=False),
        sa.Column('status', sa.Text(), nullable=False, server_default=sa.text("'queued'")),
        sa.Column('payload_json', postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column('response_json', postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('external_person_id', sa.Text(), nullable=True),
        sa.Column('external_application_id', sa.Text(), nullable=True),
        sa.Column('attempted_at', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('completed_at', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('now()')),
    )
    op.create_index('ix_sis_exports_tenant_application', 'sis_exports', ['tenant_id', 'application_id'])
    op.create_index('ix_sis_exports_tenant_status', 'sis_exports', ['tenant_id', 'status'])
    op.create_index('ix_sis_exports_tenant_student_created', 'sis_exports', ['tenant_id', 'student_id', sa.text('created_at DESC')])

    op.create_table(
        'student_deposits',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('student_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('students.id', ondelete='CASCADE'), nullable=False),
        sa.Column('application_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('applications.id', ondelete='SET NULL'), nullable=True),
        sa.Column('amount', sa.Numeric(10, 2), nullable=True),
        sa.Column('status', sa.Text(), nullable=False),
        sa.Column('paid_at', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('waived', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('metadata_json', postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('now()')),
    )
    op.create_index('ix_student_deposits_tenant_application', 'student_deposits', ['tenant_id', 'application_id'])
    op.create_index('ix_student_deposits_tenant_student', 'student_deposits', ['tenant_id', 'student_id'])

    op.create_table(
        'student_financial_aid_status',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('student_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('students.id', ondelete='CASCADE'), nullable=False),
        sa.Column('application_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('applications.id', ondelete='SET NULL'), nullable=True),
        sa.Column('fafsa_status', sa.Text(), nullable=True),
        sa.Column('verification_status', sa.Text(), nullable=True),
        sa.Column('award_status', sa.Text(), nullable=True),
        sa.Column('affordability_risk', sa.Text(), nullable=True),
        sa.Column('metadata_json', postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('now()')),
    )
    op.create_index('ix_student_financial_aid_status_tenant_application', 'student_financial_aid_status', ['tenant_id', 'application_id'])
    op.create_index('ix_student_financial_aid_status_tenant_student', 'student_financial_aid_status', ['tenant_id', 'student_id'])

    op.create_table(
        'student_scholarships',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('student_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('students.id', ondelete='CASCADE'), nullable=False),
        sa.Column('application_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('applications.id', ondelete='SET NULL'), nullable=True),
        sa.Column('scholarship_name', sa.Text(), nullable=False),
        sa.Column('amount', sa.Numeric(10, 2), nullable=True),
        sa.Column('status', sa.Text(), nullable=False),
        sa.Column('source', sa.Text(), nullable=True),
        sa.Column('metadata_json', postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('now()')),
    )
    op.create_index('ix_student_scholarships_tenant_application', 'student_scholarships', ['tenant_id', 'application_id'])
    op.create_index('ix_student_scholarships_tenant_student', 'student_scholarships', ['tenant_id', 'student_id'])

    op.create_table(
        'student_score_history',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('student_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('students.id', ondelete='CASCADE'), nullable=False),
        sa.Column('application_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('applications.id', ondelete='SET NULL'), nullable=True),
        sa.Column('score_type', sa.Text(), nullable=False),
        sa.Column('score_value', sa.Integer(), nullable=False),
        sa.Column('reason_code', sa.Text(), nullable=True),
        sa.Column('reason_json', postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column('computed_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('now()')),
    )
    op.create_index('ix_student_score_history_tenant_student_type', 'student_score_history', ['tenant_id', 'student_id', 'score_type', sa.text('computed_at DESC')])

    op.create_table(
        'admissions_decisions',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('student_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('students.id', ondelete='CASCADE'), nullable=False),
        sa.Column('application_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('applications.id', ondelete='CASCADE'), nullable=False),
        sa.Column('decision_packet_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('decision_packets.id', ondelete='SET NULL'), nullable=True),
        sa.Column('decision_code', sa.Text(), nullable=False),
        sa.Column('decision_reason', sa.Text(), nullable=True),
        sa.Column('decided_by_user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('app_users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('decided_at', sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column('effective_term', sa.Text(), nullable=True),
        sa.Column('conditions_json', postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column('letter_template_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('released_to_student_at', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('now()')),
    )
    op.create_index('ix_admissions_decisions_tenant_application', 'admissions_decisions', ['tenant_id', 'application_id'])
    op.create_index('ix_admissions_decisions_tenant_student_decided', 'admissions_decisions', ['tenant_id', 'student_id', sa.text('decided_at DESC')])

    op.create_table(
        'communication_events',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('message_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('communication_messages.id', ondelete='CASCADE'), nullable=False),
        sa.Column('event_type', sa.Text(), nullable=False),
        sa.Column('payload_json', postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column('occurred_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('now()')),
    )
    op.create_index('ix_communication_events_tenant_message', 'communication_events', ['tenant_id', 'message_id', sa.text('occurred_at DESC')])

    op.create_table(
        'sis_export_events',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('sis_export_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('sis_exports.id', ondelete='CASCADE'), nullable=False),
        sa.Column('event_type', sa.Text(), nullable=False),
        sa.Column('status', sa.Text(), nullable=True),
        sa.Column('message', sa.Text(), nullable=True),
        sa.Column('payload_json', postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column('occurred_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('now()')),
    )
    op.create_index('ix_sis_export_events_tenant_export', 'sis_export_events', ['tenant_id', 'sis_export_id', sa.text('occurred_at DESC')])

    op.add_column("decision_packets", sa.Column("application_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("applications.id", ondelete="SET NULL"), nullable=True))
    op.create_index("ix_decision_packets_tenant_application_created_at", "decision_packets", ["tenant_id", "application_id", sa.text("created_at DESC")])
    op.add_column("student_checklists", sa.Column("application_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("applications.id", ondelete="CASCADE"), nullable=True))
    op.add_column("student_checklists", sa.Column("checklist_type", sa.Text(), nullable=False, server_default=sa.text("'application'")))
    op.drop_index("ix_student_checklists_tenant_student", table_name="student_checklists")
    op.create_index("ix_student_checklists_tenant_student", "student_checklists", ["tenant_id", "student_id"])
    op.create_index("uq_student_checklists_tenant_student_application_type", "student_checklists", ["tenant_id", "student_id", "application_id", "checklist_type"], unique=True, postgresql_where=sa.text("application_id IS NOT NULL"))


def downgrade() -> None:
    op.drop_index("uq_student_checklists_tenant_student_application_type", table_name="student_checklists")
    op.drop_index("ix_student_checklists_tenant_student", table_name="student_checklists")
    op.create_index("ix_student_checklists_tenant_student", "student_checklists", ["tenant_id", "student_id"], unique=True)
    op.drop_column("student_checklists", "checklist_type")
    op.drop_column("student_checklists", "application_id")
    op.drop_index("ix_decision_packets_tenant_application_created_at", table_name="decision_packets")
    op.drop_column("decision_packets", "application_id")
    op.drop_index('ix_sis_export_events_tenant_export', table_name='sis_export_events')
    op.drop_table('sis_export_events')
    op.drop_index('ix_communication_events_tenant_message', table_name='communication_events')
    op.drop_table('communication_events')
    op.drop_index('ix_admissions_decisions_tenant_student_decided', table_name='admissions_decisions')
    op.drop_index('ix_admissions_decisions_tenant_application', table_name='admissions_decisions')
    op.drop_table('admissions_decisions')
    op.drop_index('ix_student_score_history_tenant_student_type', table_name='student_score_history')
    op.drop_table('student_score_history')
    op.drop_index('ix_student_scholarships_tenant_student', table_name='student_scholarships')
    op.drop_index('ix_student_scholarships_tenant_application', table_name='student_scholarships')
    op.drop_table('student_scholarships')
    op.drop_index('ix_student_financial_aid_status_tenant_student', table_name='student_financial_aid_status')
    op.drop_index('ix_student_financial_aid_status_tenant_application', table_name='student_financial_aid_status')
    op.drop_table('student_financial_aid_status')
    op.drop_index('ix_student_deposits_tenant_student', table_name='student_deposits')
    op.drop_index('ix_student_deposits_tenant_application', table_name='student_deposits')
    op.drop_table('student_deposits')
    op.drop_index('ix_sis_exports_tenant_student_created', table_name='sis_exports')
    op.drop_index('ix_sis_exports_tenant_status', table_name='sis_exports')
    op.drop_index('ix_sis_exports_tenant_application', table_name='sis_exports')
    op.drop_table('sis_exports')
    op.drop_index('ix_communication_messages_tenant_student', table_name='communication_messages')
    op.drop_index('ix_communication_messages_tenant_application', table_name='communication_messages')
    op.drop_table('communication_messages')
    op.drop_index('ix_application_status_history_tenant_application_changed', table_name='application_status_history')
    op.drop_table('application_status_history')
    op.drop_index('ix_application_readiness_tenant_state', table_name='application_readiness')
    op.drop_index('ix_application_readiness_tenant_application', table_name='application_readiness')
    op.drop_table('application_readiness')
    op.drop_index('ix_application_form_submissions_tenant_application', table_name='application_form_submissions')
    op.drop_table('application_form_submissions')
    op.drop_index('ix_application_documents_tenant_student', table_name='application_documents')
    op.drop_index('ix_application_documents_tenant_application', table_name='application_documents')
    op.drop_table('application_documents')
    op.drop_index('ix_student_education_history_tenant_student', table_name='student_education_history')
    op.drop_index('ix_student_education_history_tenant_institution', table_name='student_education_history')
    op.drop_table('student_education_history')
    op.drop_index('ix_form_submission_answers_tenant_submission', table_name='form_submission_answers')
    op.drop_table('form_submission_answers')
    op.drop_index('ix_applications_tenant_student', table_name='applications')
    op.drop_index('ix_applications_tenant_status', table_name='applications')
    op.drop_index('ix_applications_tenant_program_term', table_name='applications')
    op.drop_table('applications')
    op.drop_index('ix_student_test_scores_tenant_type', table_name='student_test_scores')
    op.drop_index('ix_student_test_scores_tenant_student', table_name='student_test_scores')
    op.drop_table('student_test_scores')
    op.drop_index('ix_student_relationships_tenant_student', table_name='student_relationships')
    op.drop_table('student_relationships')
    op.drop_index('ix_student_program_interests_tenant_student', table_name='student_program_interests')
    op.drop_index('ix_student_program_interests_tenant_program', table_name='student_program_interests')
    op.drop_table('student_program_interests')
    op.drop_index('ix_student_profile_facts_tenant_student_field', table_name='student_profile_facts')
    op.drop_table('student_profile_facts')
    op.drop_index('ix_student_contact_methods_tenant_value', table_name='student_contact_methods')
    op.drop_index('ix_student_contact_methods_tenant_student', table_name='student_contact_methods')
    op.drop_table('student_contact_methods')
    op.drop_index('ix_student_communication_preferences_tenant_student', table_name='student_communication_preferences')
    op.drop_table('student_communication_preferences')
    op.drop_index('ix_student_addresses_tenant_student', table_name='student_addresses')
    op.drop_table('student_addresses')
    op.drop_index('ix_form_submissions_tenant_student', table_name='form_submissions')
    op.drop_table('form_submissions')
    op.drop_index('ix_team_memberships_tenant_user', table_name='team_memberships')
    op.drop_table('team_memberships')
    op.drop_table('terms')
    op.drop_index('ix_teams_tenant_type', table_name='teams')
    op.drop_table('teams')
    op.drop_index('ix_sis_field_mappings_tenant_system_source', table_name='sis_field_mappings')
    op.drop_table('sis_field_mappings')
    op.drop_index('ix_sis_connections_tenant_system', table_name='sis_connections')
    op.drop_table('sis_connections')
    op.drop_index('ix_reference_values_tenant_category', table_name='reference_values')
    op.drop_table('reference_values')
    op.drop_index('ix_external_identifiers_tenant_external', table_name='external_system_identifiers')
    op.drop_table('external_system_identifiers')
    op.drop_index('ix_communication_templates_tenant_channel', table_name='communication_templates')
    op.drop_table('communication_templates')
    op.drop_table('campuses')
