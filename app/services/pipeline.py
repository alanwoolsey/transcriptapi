import logging
from typing import Any, Dict

from app.core.config import settings
from app.services.bedrock_mapper import BedrockMapper
from app.services.extractors import HeuristicJudge, LocalTextExtractor, TextractExtractor
from app.services.heuristics import TranscriptHeuristicParser
from app.services.response_mapper import TranscriptResponseMapper
from app.utils.file_utils import bytes_to_mb, validate_extension
from app.utils.text_utils import normalize_whitespace

logger = logging.getLogger(__name__)


class TranscriptPipeline:
    def __init__(
        self,
        local_extractor: LocalTextExtractor | None = None,
        heuristic_judge: HeuristicJudge | None = None,
        textract_extractor: TextractExtractor | None = None,
        parser: TranscriptHeuristicParser | None = None,
        bedrock_mapper: BedrockMapper | None = None,
        response_mapper: TranscriptResponseMapper | None = None,
    ):
        self.local_extractor = local_extractor or LocalTextExtractor()
        self.heuristic_judge = heuristic_judge or HeuristicJudge()
        self.textract_extractor = textract_extractor or TextractExtractor()
        self.parser = parser or TranscriptHeuristicParser()
        self.bedrock_mapper = bedrock_mapper or BedrockMapper()
        self.response_mapper = response_mapper or TranscriptResponseMapper()

    def process(
        self,
        filename: str,
        content: bytes,
        content_type: str | None,
        requested_document_type: str = "auto",
        use_bedrock: bool = True,
    ) -> Dict[str, Any]:
        logger.info(
            "Transcript request received filename=%s content_type=%s requested_document_type=%s use_bedrock=%s",
            filename,
            content_type,
            requested_document_type,
            use_bedrock,
        )
        if bytes_to_mb(content) > settings.max_upload_mb:
            raise ValueError(f"File exceeds max upload limit of {settings.max_upload_mb} MB.")

        ext = validate_extension(filename)
        local_text = self.local_extractor.extract(filename, content, ext)
        heuristic_assessment = self.heuristic_judge.assess(local_text)
        logger.info(
            "Heuristic extraction completed extension=%s acceptable=%s score=%.4f char_count=%s line_count=%s alpha_ratio=%.4f",
            ext,
            heuristic_assessment.acceptable,
            heuristic_assessment.score,
            heuristic_assessment.char_count,
            heuristic_assessment.line_count,
            heuristic_assessment.alpha_ratio,
        )

        warnings = list(heuristic_assessment.warnings)
        text_source = "heuristic"
        text = local_text

        if not heuristic_assessment.acceptable:
            if not settings.use_textract:
                warnings.append("Heuristic extraction was insufficient and Textract is disabled.")
                logger.info("Textract skipped because heuristic extraction was insufficient and USE_TEXTRACT=false")
            else:
                logger.info("Heuristic extraction insufficient. Falling back to Textract.")
                text = normalize_whitespace(self.textract_extractor.extract(content))
                text_source = "textract"
                logger.info("Textract extraction completed text_length=%s", len(text))
                if not text:
                    raise ValueError("No text could be extracted from the document.")
        else:
            logger.info("Using heuristic text extraction without Textract fallback.")

        document_type = self.parser.detect_document_type(text, requested_document_type=requested_document_type)
        parsed = self.parser.parse(text, document_type)
        course_count = sum(len(term.get("courses", [])) for term in parsed.get("terms", []))
        logger.info(
            "Heuristic parsing completed document_type=%s parser_confidence=%.4f terms=%s courses=%s",
            document_type,
            parsed.get("parser_confidence", 0.0),
            len(parsed.get("terms", [])),
            course_count,
        )

        bedrock_used = False
        if use_bedrock and settings.use_bedrock:
            logger.info("Bedrock second pass enabled model_id=%s", settings.bedrock_model_id)
            refined = self.bedrock_mapper.refine(text=text, heuristic_result=parsed)
            parsed = self._merge(parsed, refined)
            bedrock_used = True
            course_count = sum(len(term.get("courses", [])) for term in parsed.get("terms", []))
            logger.info(
                "Bedrock second pass applied successfully parser_confidence=%.4f courses=%s",
                parsed.get("parser_confidence", 0.0),
                course_count,
            )
        else:
            logger.info(
                "Bedrock second pass skipped use_bedrock=%s settings.use_bedrock=%s",
                use_bedrock,
                settings.use_bedrock,
            )

        metadata = {
            "text_source": text_source,
            "bedrock_used": bedrock_used,
            "heuristic_score": heuristic_assessment.score,
            "warnings": warnings,
            "parser_confidence": parsed.get("parser_confidence", 0.0),
            "document_type": parsed["document_type"],
            "raw_text_excerpt": text[:2000],
        }
        logger.info(
            "Transcript request completed text_source=%s bedrock_used=%s document_type=%s warnings=%s",
            text_source,
            bedrock_used,
            parsed["document_type"],
            len(warnings),
        )
        return self.response_mapper.map(parsed=parsed, raw_text=text, metadata=metadata)

    def _merge(self, base: Dict[str, Any], refined: Dict[str, Any]) -> Dict[str, Any]:
        merged = dict(base)
        for key in ["document_type", "student", "institutions", "academic_summary", "terms"]:
            refined_value = refined.get(key)
            if refined_value not in (None, [], {}, ""):
                merged[key] = refined_value
        merged["parser_confidence"] = max(base.get("parser_confidence", 0.0), refined.get("parser_confidence", 0.0), 0.85)
        return merged
