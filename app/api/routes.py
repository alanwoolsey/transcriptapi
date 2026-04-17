import logging

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.models.api_models import ParseTranscriptResponse
from app.services.pipeline import TranscriptPipeline

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/transcripts", tags=["transcripts"])
pipeline = TranscriptPipeline()


@router.post("/parse", response_model=ParseTranscriptResponse)
async def parse_transcript(
    file: UploadFile = File(...),
    document_type: str = Form("auto"),
    use_bedrock: str | None = Form(None),
) -> ParseTranscriptResponse:
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    normalized_use_bedrock = _normalize_use_bedrock(use_bedrock)
    logger.info("Route normalized use_bedrock raw_value=%s normalized_value=%s", use_bedrock, normalized_use_bedrock)

    try:
        result = pipeline.process(
            filename=file.filename or "upload.bin",
            content=content,
            content_type=file.content_type,
            requested_document_type=document_type,
            use_bedrock=normalized_use_bedrock,
        )
        return ParseTranscriptResponse(**result)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover
        raise HTTPException(status_code=500, detail=f"Processing failed: {exc}") from exc


def _normalize_use_bedrock(value: str | None) -> bool:
    if value is None:
        return True
    normalized = value.strip().lower()
    if normalized == "":
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    if normalized in {"1", "true", "yes", "on"}:
        return True
    return True
