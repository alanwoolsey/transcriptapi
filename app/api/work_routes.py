from fastapi import APIRouter, BackgroundTasks, Depends, Query, status

from app.api.dependencies import AuthenticatedTenantContext, get_current_tenant_context
from app.db import get_db
from app.models.ops_models import (
    WorkItemsResponse,
    WorkProjectionJobResponse,
    WorkProjectionJobsResponse,
    WorkProjectionRebuildResponse,
    WorkProjectionStatusResponse,
    WorkSummaryResponse,
    WorkTodayBoardResponse,
    WorkTodayOrchestrationResponse,
    WorkTodayRecommendationResponse,
    WorkTodayRouteRequest,
    WorkTodayRouteResponse,
    WorkTodayResponse,
)
from app.services.admissions_ops_service import AdmissionsOpsNotFoundError, AdmissionsOpsService, AdmissionsOpsValidationError
from app.services.work_state_projector import WorkStateProjector

router = APIRouter(prefix="/work", tags=["work"])
admissions_ops_service = AdmissionsOpsService()
work_state_projector = WorkStateProjector()


def _run_projection_job(tenant_id: str, job_id: str) -> None:
    from uuid import UUID

    work_state_projector.run_projection_job_until_complete(UUID(tenant_id), job_id=job_id)


@router.get("/summary", response_model=WorkSummaryResponse)
def get_work_summary(
    auth_context: AuthenticatedTenantContext = Depends(get_current_tenant_context),
) -> WorkSummaryResponse:
    return admissions_ops_service.get_work_summary(auth_context.tenant.id)


@router.get("/items", response_model=WorkItemsResponse)
def get_work_items(
    section: str | None = Query(default=None),
    population: str | None = Query(default=None),
    owner: str | None = Query(default=None),
    ownerId: str | None = Query(default=None),
    priority: str | None = Query(default=None),
    aging_bucket: str | None = Query(default=None),
    q: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    page: int | None = Query(default=None, ge=1),
    pageSize: int | None = Query(default=None, ge=1, le=200),
    auth_context: AuthenticatedTenantContext = Depends(get_current_tenant_context),
) -> WorkItemsResponse:
    resolved_limit = pageSize or limit
    resolved_offset = ((page - 1) * resolved_limit) if page else offset
    return admissions_ops_service.get_work_items(
        auth_context.tenant.id,
        section=section,
        population=population,
        owner=(ownerId or owner),
        priority=priority,
        aging_bucket=aging_bucket,
        q=q,
        limit=resolved_limit,
        offset=resolved_offset,
    )


@router.get("/today", response_model=WorkTodayResponse)
def get_today_work(
    limit: int = Query(default=25, ge=1, le=100),
    auth_context: AuthenticatedTenantContext = Depends(get_current_tenant_context),
) -> WorkTodayResponse:
    return admissions_ops_service.get_today_work(auth_context.tenant.id, limit=limit)


@router.get("/today/board", response_model=WorkTodayBoardResponse)
def get_today_work_board(
    limit: int = Query(default=50, ge=1, le=100),
    auth_context: AuthenticatedTenantContext = Depends(get_current_tenant_context),
) -> WorkTodayBoardResponse:
    return admissions_ops_service.get_today_work_board(auth_context.tenant.id, limit=limit)


@router.post("/today/orchestrate", response_model=WorkTodayOrchestrationResponse)
def orchestrate_today_work(
    limit: int = Query(default=50, ge=1, le=100),
    auth_context: AuthenticatedTenantContext = Depends(get_current_tenant_context),
    db=Depends(get_db),
) -> WorkTodayOrchestrationResponse:
    return admissions_ops_service.orchestrate_today_work(
        db=db,
        tenant_id=auth_context.tenant.id,
        actor_user_id=auth_context.user.id,
        limit=limit,
    )


@router.get("/today/orchestrations/latest", response_model=WorkTodayOrchestrationResponse)
def get_latest_today_work_orchestration(
    studentId: str | None = Query(default=None),
    auth_context: AuthenticatedTenantContext = Depends(get_current_tenant_context),
) -> WorkTodayOrchestrationResponse:
    try:
        return admissions_ops_service.get_latest_today_work_orchestration(
            auth_context.tenant.id,
            student_id=studentId,
        )
    except AdmissionsOpsNotFoundError as exc:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/today/{student_id}/recommendation", response_model=WorkTodayRecommendationResponse)
def get_today_work_recommendation(
    student_id: str,
    auth_context: AuthenticatedTenantContext = Depends(get_current_tenant_context),
) -> WorkTodayRecommendationResponse:
    try:
        return admissions_ops_service.get_today_work_recommendation(
            auth_context.tenant.id,
            student_id=student_id,
        )
    except AdmissionsOpsNotFoundError as exc:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AdmissionsOpsValidationError as exc:
        from fastapi import HTTPException

        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/today/{student_id}/route", response_model=WorkTodayRouteResponse)
def route_today_work(
    student_id: str,
    payload: WorkTodayRouteRequest,
    auth_context: AuthenticatedTenantContext = Depends(get_current_tenant_context),
    db=Depends(get_db),
) -> WorkTodayRouteResponse:
    try:
        return admissions_ops_service.route_today_work(
            db=db,
            tenant_id=auth_context.tenant.id,
            actor_user_id=auth_context.user.id,
            student_id=student_id,
            payload=payload,
        )
    except AdmissionsOpsNotFoundError as exc:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AdmissionsOpsValidationError as exc:
        from fastapi import HTTPException

        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/projection/status", response_model=WorkProjectionStatusResponse)
def get_work_projection_status(
    auth_context: AuthenticatedTenantContext = Depends(get_current_tenant_context),
) -> WorkProjectionStatusResponse:
    status_payload = work_state_projector.get_projection_status(auth_context.tenant.id)
    if status_payload["lastProjectedAt"] is not None and not isinstance(status_payload["lastProjectedAt"], str):
        status_payload["lastProjectedAt"] = admissions_ops_service._isoformat(status_payload["lastProjectedAt"])
    current_job = status_payload.get("currentJob")
    if isinstance(current_job, dict):
        _normalize_job_timestamps(current_job)
    return WorkProjectionStatusResponse(**status_payload)


@router.get("/projection/jobs", response_model=WorkProjectionJobsResponse)
def list_work_projection_jobs(
    limit: int = Query(default=20, ge=1, le=100),
    auth_context: AuthenticatedTenantContext = Depends(get_current_tenant_context),
) -> WorkProjectionJobsResponse:
    items = work_state_projector.list_projection_jobs(auth_context.tenant.id, limit=limit)
    for item in items:
        _normalize_job_timestamps(item)
    return WorkProjectionJobsResponse(items=[WorkProjectionJobResponse(**item) for item in items])


@router.get("/projection/jobs/{job_id}", response_model=WorkProjectionJobResponse)
def get_work_projection_job(
    job_id: str,
    auth_context: AuthenticatedTenantContext = Depends(get_current_tenant_context),
) -> WorkProjectionJobResponse:
    item = work_state_projector.get_projection_job(auth_context.tenant.id, job_id=job_id)
    if item is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="Projection job not found.")
    _normalize_job_timestamps(item)
    return WorkProjectionJobResponse(**item)


@router.post("/projection/rebuild", response_model=WorkProjectionRebuildResponse, status_code=status.HTTP_202_ACCEPTED)
def rebuild_work_projection(
    reset: bool = Query(default=False),
    limit: int = Query(default=100, ge=1, le=500),
    cursor: str | None = Query(default=None),
    auth_context: AuthenticatedTenantContext = Depends(get_current_tenant_context),
) -> WorkProjectionRebuildResponse:
    if reset:
        work_state_projector.reset_tenant_projection(auth_context.tenant.id)
    chunk_result = work_state_projector.rebuild_tenant_projection_chunk(
        auth_context.tenant.id,
        limit=limit,
        cursor=cursor,
    )
    return WorkProjectionRebuildResponse(
        status="ready" if chunk_result["remainingStudents"] == 0 else "partial",
        detail="Work-state projection rebuild chunk completed.",
        processedStudents=int(chunk_result["processedStudents"]),
        nextCursor=chunk_result["nextCursor"],
        remainingStudents=int(chunk_result["remainingStudents"]),
    )


@router.post("/projection/rebuild-all", response_model=WorkProjectionRebuildResponse, status_code=status.HTTP_202_ACCEPTED)
def rebuild_all_work_projection(
    background_tasks: BackgroundTasks,
    reset: bool = Query(default=False),
    limit: int = Query(default=100, ge=1, le=500),
    auth_context: AuthenticatedTenantContext = Depends(get_current_tenant_context),
) -> WorkProjectionRebuildResponse:
    job_id = work_state_projector.create_projection_job(auth_context.tenant.id, reset=reset, limit=limit)
    background_tasks.add_task(_run_projection_job, str(auth_context.tenant.id), job_id)
    return WorkProjectionRebuildResponse(
        status="queued",
        detail="Full work-state projection rebuild queued.",
        jobId=job_id,
        processedStudents=0,
        nextCursor=None,
        remainingStudents=0,
    )


@router.post("/projection/jobs/{job_id}/retry", response_model=WorkProjectionRebuildResponse, status_code=status.HTTP_202_ACCEPTED)
def retry_work_projection_job(
    job_id: str,
    background_tasks: BackgroundTasks,
    auth_context: AuthenticatedTenantContext = Depends(get_current_tenant_context),
) -> WorkProjectionRebuildResponse:
    retried_job_id = work_state_projector.retry_projection_job(auth_context.tenant.id, job_id=job_id)
    if retried_job_id is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="Projection job not found.")
    background_tasks.add_task(_run_projection_job, str(auth_context.tenant.id), retried_job_id)
    return WorkProjectionRebuildResponse(
        status="queued",
        detail="Projection job retry queued.",
        jobId=retried_job_id,
        processedStudents=0,
        nextCursor=None,
        remainingStudents=0,
    )


@router.post("/projection/jobs/{job_id}/cancel", response_model=WorkProjectionJobResponse)
def cancel_work_projection_job(
    job_id: str,
    auth_context: AuthenticatedTenantContext = Depends(get_current_tenant_context),
) -> WorkProjectionJobResponse:
    item = work_state_projector.cancel_projection_job(auth_context.tenant.id, job_id=job_id)
    if item is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="Projection job not found.")
    _normalize_job_timestamps(item)
    return WorkProjectionJobResponse(**item)


def _normalize_job_timestamps(item: dict[str, object]) -> None:
    for key in ("startedAt", "completedAt", "createdAt", "updatedAt"):
        value = item.get(key)
        if value is not None and not isinstance(value, str):
            item[key] = admissions_ops_service._isoformat(value)
