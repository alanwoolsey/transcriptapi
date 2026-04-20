from datetime import datetime, timedelta, timezone
from statistics import median
from uuid import UUID

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.db.models import AuditEvent, Student, Transcript, TranscriptParseRun, TrustFlag, WorkflowCase
from app.db.session import get_session_factory
from app.models.dashboard_models import (
    DashboardActivityItem,
    DashboardAgentItem,
    DashboardFunnelItem,
    DashboardResponse,
    DashboardRoutingMixItem,
    DashboardStat,
)


class DashboardService:
    def __init__(self, session_factory=None) -> None:
        self.session_factory = session_factory or get_session_factory

    def get_dashboard(self, tenant_id: UUID) -> DashboardResponse:
        return DashboardResponse(
            stats=self.get_stats(tenant_id),
            funnel=self.get_funnel(tenant_id),
            routing_mix=self.get_routing_mix(tenant_id),
            agents=self.get_agents(tenant_id),
            activity=self.get_activity(tenant_id),
        )

    def get_stats(self, tenant_id: UUID) -> list[DashboardStat]:
        session_factory = self.session_factory()
        with session_factory() as session:
            now = datetime.now(timezone.utc)
            last_30_days = now - timedelta(days=30)
            previous_30_days = last_30_days - timedelta(days=30)
            student_summaries = self._load_student_summaries(session, tenant_id)
            return self._build_stats(session, tenant_id, student_summaries, last_30_days, previous_30_days)

    def get_funnel(self, tenant_id: UUID) -> list[DashboardFunnelItem]:
        session_factory = self.session_factory()
        with session_factory() as session:
            student_summaries = self._load_student_summaries(session, tenant_id)
            return self._build_funnel(session, tenant_id, student_summaries)

    def get_routing_mix(self, tenant_id: UUID) -> list[DashboardRoutingMixItem]:
        session_factory = self.session_factory()
        with session_factory() as session:
            return self._build_routing_mix(session, tenant_id)

    def get_agents(self, tenant_id: UUID) -> list[DashboardAgentItem]:
        session_factory = self.session_factory()
        with session_factory() as session:
            now = datetime.now(timezone.utc)
            last_30_days = now - timedelta(days=30)
            student_summaries = self._load_student_summaries(session, tenant_id)
            return self._build_agents(session, tenant_id, student_summaries, last_30_days)

    def get_activity(self, tenant_id: UUID) -> list[DashboardActivityItem]:
        session_factory = self.session_factory()
        with session_factory() as session:
            now = datetime.now(timezone.utc)
            last_7_days = now - timedelta(days=7)
            return self._build_activity(session, tenant_id, last_7_days, now)

    def _build_stats(
        self,
        session: Session,
        tenant_id: UUID,
        student_summaries: list[dict[str, str | int | float]],
        last_30_days: datetime,
        previous_30_days: datetime,
    ) -> list[DashboardStat]:
        prospect_count = len(student_summaries)
        current_transcripts = self._count_transcripts(session, tenant_id, last_30_days, None)
        previous_transcripts = self._count_transcripts(session, tenant_id, previous_30_days, last_30_days)
        current_parse_runs = self._count_parse_runs(session, tenant_id, last_30_days, None, status="completed")
        decision_ready_count = self._count_decision_ready_files(session, tenant_id)
        high_risk_holds = self._count_high_risk_holds(session, tenant_id)
        auto_certified_rate = self._auto_certified_rate(session, tenant_id)

        return [
            DashboardStat(
                label="Prospects in motion",
                value=str(prospect_count),
                delta=self._format_delta(current_transcripts, previous_transcripts, suffix="vs prior 30 days"),
                tone="indigo",
            ),
            DashboardStat(
                label="Instant evaluations",
                value=str(current_parse_runs),
                delta=self._format_parse_latency(session, tenant_id, last_30_days),
                tone="teal",
            ),
            DashboardStat(
                label="Decision-ready files",
                value=str(decision_ready_count),
                delta=f"{auto_certified_rate}% auto-certified",
                tone="violet",
            ),
            DashboardStat(
                label="High-risk holds",
                value=str(high_risk_holds),
                delta=f"{high_risk_holds} active holds",
                tone="rose",
            ),
        ]

    def _build_funnel(self, session: Session, tenant_id: UUID, student_summaries: list[dict[str, str | int | float]]) -> list[DashboardFunnelItem]:
        prospects = len(student_summaries)
        transcript_evaluated = sum(1 for student in student_summaries if int(student["transcriptsCount"]) > 0)
        best_fit = sum(1 for student in student_summaries if int(student["fitScore"]) >= 75)
        application_started = sum(1 for student in student_summaries if int(student["depositLikelihood"]) >= 50)
        admitted = sum(1 for student in student_summaries if str(student["stage"]).lower() in {"decision-ready", "high intent"})
        deposited = sum(1 for student in student_summaries if int(student["depositLikelihood"]) >= 70)

        return [
            DashboardFunnelItem(step="Prospects", count=prospects),
            DashboardFunnelItem(step="Transcript evaluated", count=transcript_evaluated),
            DashboardFunnelItem(step="Best-fit program found", count=best_fit),
            DashboardFunnelItem(step="Application started", count=application_started),
            DashboardFunnelItem(step="Admitted", count=admitted),
            DashboardFunnelItem(step="Deposited", count=deposited),
        ]

    def _build_routing_mix(self, session: Session, tenant_id: UUID) -> list[DashboardRoutingMixItem]:
        total = session.execute(
            select(func.count()).select_from(Transcript).where(Transcript.tenant_id == tenant_id)
        ).scalar_one()
        if not total:
            return []

        auto_certified = session.execute(
            select(func.count()).select_from(Transcript).where(
                Transcript.tenant_id == tenant_id,
                Transcript.is_fraudulent.is_(False),
                Transcript.status.in_(["parsed", "completed"]),
                Transcript.parser_confidence >= 0.85,
            )
        ).scalar_one()
        human_review = session.execute(
            select(func.count()).select_from(Transcript).where(
                Transcript.tenant_id == tenant_id,
                Transcript.is_fraudulent.is_(False),
                Transcript.status.in_(["parsed", "completed"]),
                Transcript.parser_confidence < 0.85,
            )
        ).scalar_one()
        awaiting_student = session.execute(
            select(func.count()).select_from(Transcript).where(
                Transcript.tenant_id == tenant_id,
                Transcript.status == "processing",
            )
        ).scalar_one()
        trust_hold = self._count_high_risk_holds(session, tenant_id)

        items = [
            ("Auto-certified", auto_certified),
            ("Human review", human_review),
            ("Awaiting student", awaiting_student),
            ("Trust hold", trust_hold),
        ]
        return [
            DashboardRoutingMixItem(name=name, value=round((value / total) * 100))
            for name, value in items
            if value > 0
        ]

    def _build_agents(self, session: Session, tenant_id: UUID, student_summaries: list[dict[str, str | int | float]], last_30_days: datetime) -> list[DashboardAgentItem]:
        high_fit = sum(1 for student in student_summaries if int(student["fitScore"]) >= 80)
        likely_deposit = sum(1 for student in student_summaries if int(student["depositLikelihood"]) >= 70)
        recruiter_rate = round((likely_deposit / high_fit) * 100) if high_fit else 0

        parse_durations = []
        stmt = select(TranscriptParseRun.started_at, TranscriptParseRun.completed_at).where(
            TranscriptParseRun.tenant_id == tenant_id,
            TranscriptParseRun.status == "completed",
            TranscriptParseRun.started_at >= last_30_days,
            TranscriptParseRun.completed_at.is_not(None),
        )
        for started_at, completed_at in session.execute(stmt).all():
            parse_durations.append((completed_at - started_at).total_seconds() / 60)
        median_minutes = round(median(parse_durations), 1) if parse_durations else 0.0

        completed = self._count_transcripts(session, tenant_id, None, None)
        held = self._count_high_risk_holds(session, tenant_id)
        clear_rate = round(((completed - held) / completed) * 100, 1) if completed else 0.0

        return [
            DashboardAgentItem(
                name="Recruiter Agent",
                objective="Convert high-fit prospects before they ghost",
                metric=f"{recruiter_rate}% likely deposit",
                summary="Uses tenant-scoped fit and likelihood signals from student records to surface likely converters.",
            ),
            DashboardAgentItem(
                name="Decision Agent",
                objective="Package files for rapid admit",
                metric=f"{median_minutes} min median packaging",
                summary="Measures transcript parse and packaging time from completed parse runs for this tenant.",
            ),
            DashboardAgentItem(
                name="Trust Agent",
                objective="Keep bad documents out",
                metric=f"{clear_rate}% clear rate",
                summary="Tracks fraudulent transcripts and trust holds before outcomes are released.",
            ),
        ]

    def _load_student_summaries(self, session: Session, tenant_id: UUID) -> list[dict[str, str | int | float]]:
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
        stmt = (
            select(
                Student.current_stage,
                Student.risk_level,
                Student.latest_cumulative_gpa,
                transcript_stats.c.transcripts_count,
                transcript_stats.c.max_parser_confidence,
            )
            .outerjoin(transcript_stats, transcript_stats.c.student_id == Student.id)
            .where(Student.tenant_id == tenant_id)
        )
        rows = session.execute(stmt).all()
        summaries: list[dict[str, str | int | float]] = []
        for stage, risk_level, gpa, transcripts_count, max_parser_confidence in rows:
            transcript_count = int(transcripts_count or 0)
            fit_score = self._estimate_fit_score_from_summary(gpa, transcript_count, max_parser_confidence)
            deposit_likelihood = self._estimate_deposit_likelihood_from_summary(
                risk_level,
                gpa,
                transcript_count,
                max_parser_confidence,
            )
            summaries.append(
                {
                    "stage": self._title_case(stage or "decision-ready"),
                    "fitScore": fit_score,
                    "depositLikelihood": deposit_likelihood,
                    "transcriptsCount": transcript_count,
                }
            )
        return summaries

    def _build_activity(self, session: Session, tenant_id: UUID, last_7_days: datetime, now: datetime) -> list[DashboardActivityItem]:
        items: list[DashboardActivityItem] = []
        stmt = (
            select(AuditEvent.category, AuditEvent.action, AuditEvent.source, AuditEvent.occurred_at)
            .where(AuditEvent.tenant_id == tenant_id, AuditEvent.occurred_at >= last_7_days)
            .order_by(AuditEvent.occurred_at.desc())
            .limit(10)
        )
        for category, action, source, occurred_at in session.execute(stmt).all():
            items.append(
                DashboardActivityItem(
                    title=f"{action} event recorded",
                    detail=f"{source or 'System'} recorded {action.lower()} for category {category}.",
                    when=self._relative_time(occurred_at, now),
                    category=category or "Activity",
                )
            )

        trust_stmt = (
            select(TrustFlag.reason, TrustFlag.severity, TrustFlag.detected_at)
            .where(TrustFlag.tenant_id == tenant_id, TrustFlag.detected_at >= last_7_days)
            .order_by(TrustFlag.detected_at.desc())
            .limit(3)
        )
        for reason, severity, detected_at in session.execute(trust_stmt).all():
            items.append(
                DashboardActivityItem(
                    title=f"{self._title_case(severity)} trust review opened",
                    detail=reason,
                    when=self._relative_time(detected_at, now),
                    category="Trust",
                )
            )

        workflow_stmt = (
            select(WorkflowCase.reason, WorkflowCase.status, WorkflowCase.created_at)
            .where(WorkflowCase.tenant_id == tenant_id, WorkflowCase.created_at >= last_7_days)
            .order_by(WorkflowCase.created_at.desc())
            .limit(3)
        )
        for reason, status, created_at in session.execute(workflow_stmt).all():
            items.append(
                DashboardActivityItem(
                    title=f"Workflow case {status}",
                    detail=reason or "Workflow item updated.",
                    when=self._relative_time(created_at, now),
                    category="Workflow",
                )
            )

        items.sort(key=lambda item: self._parse_relative_order(item.when))
        return items[:8]

    def _count_transcripts(self, session: Session, tenant_id: UUID, start: datetime | None, end: datetime | None) -> int:
        conditions = [Transcript.tenant_id == tenant_id]
        if start:
            conditions.append(Transcript.created_at >= start)
        if end:
            conditions.append(Transcript.created_at < end)
        return session.execute(select(func.count()).select_from(Transcript).where(*conditions)).scalar_one()

    def _count_parse_runs(self, session: Session, tenant_id: UUID, start: datetime | None, end: datetime | None, status: str | None = None) -> int:
        conditions = [TranscriptParseRun.tenant_id == tenant_id]
        if start:
            conditions.append(TranscriptParseRun.started_at >= start)
        if end:
            conditions.append(TranscriptParseRun.started_at < end)
        if status:
            conditions.append(TranscriptParseRun.status == status)
        return session.execute(select(func.count()).select_from(TranscriptParseRun).where(*conditions)).scalar_one()

    def _count_decision_ready_files(self, session: Session, tenant_id: UUID) -> int:
        return session.execute(
            select(func.count()).select_from(Transcript).where(
                Transcript.tenant_id == tenant_id,
                Transcript.is_fraudulent.is_(False),
                Transcript.status.in_(["parsed", "completed"]),
            )
        ).scalar_one()

    def _count_high_risk_holds(self, session: Session, tenant_id: UUID) -> int:
        trust_holds = session.execute(
            select(func.count()).select_from(TrustFlag).where(
                TrustFlag.tenant_id == tenant_id,
                TrustFlag.severity == "high",
                TrustFlag.status != "closed",
            )
        ).scalar_one()
        transcript_holds = session.execute(
            select(func.count()).select_from(Transcript).where(
                Transcript.tenant_id == tenant_id,
                Transcript.is_fraudulent.is_(True),
            )
        ).scalar_one()
        return trust_holds + transcript_holds

    def _auto_certified_rate(self, session: Session, tenant_id: UUID) -> int:
        total_completed = session.execute(
            select(func.count()).select_from(Transcript).where(
                Transcript.tenant_id == tenant_id,
                Transcript.status.in_(["parsed", "completed"]),
            )
        ).scalar_one()
        if not total_completed:
            return 0
        auto_certified = session.execute(
            select(func.count()).select_from(Transcript).where(
                Transcript.tenant_id == tenant_id,
                Transcript.status.in_(["parsed", "completed"]),
                Transcript.is_fraudulent.is_(False),
                Transcript.parser_confidence >= 0.85,
            )
        ).scalar_one()
        return round((auto_certified / total_completed) * 100)

    def _format_delta(self, current: int, previous: int, suffix: str) -> str:
        if previous == 0:
            if current == 0:
                return f"0% {suffix}"
            return f"+100% {suffix}"
        change = round(((current - previous) / previous) * 100)
        prefix = "+" if change > 0 else ""
        return f"{prefix}{change}% {suffix}"

    def _format_parse_latency(self, session: Session, tenant_id: UUID, since: datetime) -> str:
        stmt = select(TranscriptParseRun.started_at, TranscriptParseRun.completed_at).where(
            TranscriptParseRun.tenant_id == tenant_id,
            TranscriptParseRun.status == "completed",
            TranscriptParseRun.started_at >= since,
            TranscriptParseRun.completed_at.is_not(None),
        )
        durations = [
            (completed_at - started_at).total_seconds() / 60
            for started_at, completed_at in session.execute(stmt).all()
        ]
        if not durations:
            return "No completed runs yet"
        return f"{round(median(durations), 1)} min median"

    def _relative_time(self, occurred_at: datetime, now: datetime) -> str:
        delta = now - occurred_at
        minutes = int(delta.total_seconds() // 60)
        if minutes < 60:
            return f"{minutes} min ago"
        hours = int(minutes // 60)
        if hours < 24:
            return f"{hours} hr ago"
        days = int(hours // 24)
        return f"{days} day ago"

    def _parse_relative_order(self, when: str) -> int:
        try:
            return int(when.split()[0])
        except Exception:
            return 999999

    def _title_case(self, value: str | None) -> str:
        if not value:
            return ""
        return value.replace("_", " ").title()

    def _estimate_fit_score_from_summary(
        self,
        gpa: float | int | str | None,
        transcripts_count: int,
        parser_confidence: float | int | str | None,
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
        gpa: float | int | str | None,
        transcripts_count: int,
        parser_confidence: float | int | str | None,
    ) -> int:
        risk = (risk_level or "").lower()
        if risk == "high":
            return 20
        base = self._estimate_fit_score_from_summary(gpa, transcripts_count, parser_confidence) - 18
        if risk == "medium":
            base -= 12
        return max(10, min(85, base))

    def _to_float(self, value: float | int | str | None, fallback: float = 0.0) -> float:
        if value is None:
            return fallback
        try:
            return round(float(value), 2)
        except Exception:
            return fallback
