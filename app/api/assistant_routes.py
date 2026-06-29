from fastapi import APIRouter, Depends

from app.api.dependencies import AuthenticatedTenantContext, get_current_tenant_context
from app.models.assistant_models import AssistantChatRequest, AssistantChatResponse, AssistantDocumentClassificationRequest, AssistantDocumentClassificationResponse
from app.services.assistant_context_service import assistant_context_service

router = APIRouter(prefix="/assistant", tags=["assistant"])


@router.post("/chat", response_model=AssistantChatResponse)
def governed_app_chat(
    payload: AssistantChatRequest,
    auth_context: AuthenticatedTenantContext = Depends(get_current_tenant_context),
) -> AssistantChatResponse:
    return assistant_context_service.run_chat(payload, auth_context)


@router.post("/classify-document", response_model=AssistantDocumentClassificationResponse)
def governed_document_classification(
    payload: AssistantDocumentClassificationRequest,
    auth_context: AuthenticatedTenantContext = Depends(get_current_tenant_context),
) -> AssistantDocumentClassificationResponse:
    return assistant_context_service.classify_document(payload, auth_context)
