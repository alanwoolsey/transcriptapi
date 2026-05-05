from fastapi import APIRouter, Depends
from fastapi import HTTPException

from app.api.dependencies import AuthenticatedTenantContext, get_current_tenant_context
from app.models.operations_models import ActionResponse
from app.models.trust_models import TrustCaseActionRequest, TrustCaseAssignRequest, TrustCaseDetailsResponse, TrustCaseItem
from app.services.trust_service import TrustService

router = APIRouter(prefix="/trust", tags=["trust"])
trust_service = TrustService()


def _normalize_action_response(response: ActionResponse | dict) -> ActionResponse:
    if isinstance(response, ActionResponse):
        return response
    return ActionResponse(**response)


@router.get("/cases", response_model=list[TrustCaseItem])
def list_trust_cases(
    auth_context: AuthenticatedTenantContext = Depends(get_current_tenant_context),
) -> list[TrustCaseItem]:
    return trust_service.list_cases(auth_context.tenant.id)


@router.get("/transcripts/{transcript_id}/details", response_model=TrustCaseDetailsResponse)
def get_trust_case_details(
    transcript_id: str,
    auth_context: AuthenticatedTenantContext = Depends(get_current_tenant_context),
) -> TrustCaseDetailsResponse:
    response = trust_service.get_case_details(auth_context.tenant.id, transcript_id)
    if response is None:
        raise HTTPException(status_code=404, detail="Trust case not found.")
    return response


@router.post("/transcripts/{transcript_id}/resolve", response_model=ActionResponse)
def resolve_trust_case(
    transcript_id: str,
    payload: TrustCaseActionRequest,
    auth_context: AuthenticatedTenantContext = Depends(get_current_tenant_context),
) -> ActionResponse:
    response = _normalize_action_response(
        trust_service.resolve_case(auth_context.tenant.id, transcript_id, auth_context.user.id, payload.note)
    )
    if not response.success and response.status == "not_found":
        raise HTTPException(status_code=404, detail=response.detail)
    return response


@router.post("/transcripts/{transcript_id}/block", response_model=ActionResponse)
def block_trust_case(
    transcript_id: str,
    payload: TrustCaseActionRequest,
    auth_context: AuthenticatedTenantContext = Depends(get_current_tenant_context),
) -> ActionResponse:
    response = _normalize_action_response(
        trust_service.block_case(auth_context.tenant.id, transcript_id, auth_context.user.id, payload.note)
    )
    if not response.success and response.status == "not_found":
        raise HTTPException(status_code=404, detail=response.detail)
    return response


@router.post("/transcripts/{transcript_id}/unblock", response_model=ActionResponse)
def unblock_trust_case(
    transcript_id: str,
    payload: TrustCaseActionRequest,
    auth_context: AuthenticatedTenantContext = Depends(get_current_tenant_context),
) -> ActionResponse:
    response = _normalize_action_response(
        trust_service.unblock_case(auth_context.tenant.id, transcript_id, auth_context.user.id, payload.note)
    )
    if not response.success and response.status == "not_found":
        raise HTTPException(status_code=404, detail=response.detail)
    return response


@router.post("/transcripts/{transcript_id}/escalate", response_model=ActionResponse)
def escalate_trust_case(
    transcript_id: str,
    payload: TrustCaseActionRequest,
    auth_context: AuthenticatedTenantContext = Depends(get_current_tenant_context),
) -> ActionResponse:
    response = _normalize_action_response(
        trust_service.escalate_case(auth_context.tenant.id, transcript_id, auth_context.user.id, payload.note)
    )
    if not response.success and response.status == "not_found":
        raise HTTPException(status_code=404, detail=response.detail)
    return response


@router.post("/transcripts/{transcript_id}/assign", response_model=ActionResponse)
def assign_trust_case(
    transcript_id: str,
    payload: TrustCaseAssignRequest,
    auth_context: AuthenticatedTenantContext = Depends(get_current_tenant_context),
) -> ActionResponse:
    response = _normalize_action_response(
        trust_service.assign_case(auth_context.tenant.id, transcript_id, auth_context.user.id, payload.userId, payload.note)
    )
    if not response.success and response.status == "not_found":
        raise HTTPException(status_code=404, detail=response.detail)
    return response
