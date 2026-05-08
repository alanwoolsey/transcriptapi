import logging
from copy import deepcopy
import re
from typing import Any, Dict

from app.core.config import settings
from app.services.bedrock_mapper import BedrockMapper, BedrockResponseFormatError
from app.services.extractors import HeuristicJudge, LocalTextExtractor, TextractExtractor
from app.services.heuristics import TranscriptHeuristicParser
from app.services.heuristic_learning import HeuristicLearningService
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
        learning_service: HeuristicLearningService | None = None,
    ):
        self.local_extractor = local_extractor or LocalTextExtractor()
        self.heuristic_judge = heuristic_judge or HeuristicJudge()
        self.textract_extractor = textract_extractor or TextractExtractor()
        self.parser = parser or TranscriptHeuristicParser()
        self.bedrock_mapper = bedrock_mapper or BedrockMapper()
        self.response_mapper = response_mapper or TranscriptResponseMapper()
        self.learning_service = learning_service or HeuristicLearningService()

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
        local_extraction = self._extract_local_with_layout(filename=filename, content=content, extension=ext)
        local_text = local_extraction["text"]
        line_locations = list(local_extraction.get("line_locations", []))
        local_text_assessment = self.heuristic_judge.assess(local_text)
        logger.info(
            "Heuristic extraction completed extension=%s acceptable=%s score=%.4f char_count=%s line_count=%s alpha_ratio=%.4f",
            ext,
            local_text_assessment.acceptable,
            local_text_assessment.score,
            local_text_assessment.char_count,
            local_text_assessment.line_count,
            local_text_assessment.alpha_ratio,
        )

        warnings = list(local_text_assessment.warnings)
        text_source = "heuristic"
        layout_source = "heuristic"
        text = local_text
        ocr_needed = self._needs_ocr(extension=ext, assessment=local_text_assessment)
        ocr_used = False

        if ocr_needed:
            if not settings.use_textract:
                warnings.append("OCR appears necessary but Textract is disabled.")
                logger.info("Textract skipped because OCR appears necessary and USE_TEXTRACT=false")
            else:
                logger.info("Local extraction appears insufficient. Falling back to Textract OCR.")
                try:
                    textract_extraction = self._extract_textract_with_layout(content)
                    text = normalize_whitespace(textract_extraction["text"])
                    line_locations = list(textract_extraction.get("line_locations", []))
                    text_source = "textract"
                    layout_source = "textract"
                    ocr_used = True
                    logger.info("Textract extraction completed text_length=%s", len(text))
                    if not text:
                        raise ValueError("No text could be extracted from the document.")
                except Exception as exc:
                    if local_text:
                        warnings.append(f"Textract OCR unavailable; using local extraction instead. {exc}")
                        logger.warning("Textract OCR failed; falling back to local extraction: %s", exc)
                        text = local_text
                        line_locations = list(local_extraction.get("line_locations", []))
                        text_source = "heuristic"
                        layout_source = "heuristic"
                        ocr_used = False
                    else:
                        raise
        else:
            logger.info("Using local text extraction without OCR fallback.")
            if settings.use_textract and self._needs_layout_ocr(extension=ext, text=text, line_locations=line_locations):
                logger.info("Local text extraction is acceptable, but layout appears merged. Fetching Textract layout for line geometry.")
                try:
                    textract_extraction = self._extract_textract_with_layout(content)
                    textract_lines = list(textract_extraction.get("line_locations", []))
                    if textract_lines:
                        line_locations = textract_lines
                        layout_source = "textract"
                    else:
                        warnings.append("Textract layout fallback did not return line geometry.")
                except Exception as exc:
                    warnings.append(f"Textract layout fallback unavailable; using local layout instead. {exc}")
                    logger.warning("Textract layout fallback failed; keeping local layout: %s", exc)

        text_assessment = self.heuristic_judge.assess(text)

        parse_text = self._augment_text_with_layout_rows(text=text, line_locations=line_locations)
        document_type = self.parser.detect_document_type(parse_text, requested_document_type=requested_document_type)
        parsed = self.parser.parse(parse_text, document_type)
        parsed["terms"] = self.parser.ensure_course_confidences(parsed.get("terms", []))
        parsed["course_confidence_summary"] = self.parser.summarize_course_confidence(parsed.get("terms", []))
        heuristic_parsed = deepcopy(parsed)
        overall_confidence = self._estimate_overall_confidence(text_assessment.score, parsed)
        course_count = sum(len(term.get("courses", [])) for term in parsed.get("terms", []))
        logger.info(
            "Heuristic parsing completed document_type=%s parser_confidence=%.4f overall_confidence=%.4f terms=%s courses=%s",
            document_type,
            parsed.get("parser_confidence", 0.0),
            overall_confidence,
            len(parsed.get("terms", [])),
            course_count,
        )

        bedrock_used = False
        visible_course_rows_estimate = self._estimate_visible_course_rows(text)
        ai_needed = self._needs_ai(
            text_assessment=text_assessment,
            parsed=parsed,
            overall_confidence=overall_confidence,
            visible_course_rows_estimate=visible_course_rows_estimate,
        )
        if use_bedrock and settings.use_bedrock and ai_needed:
            logger.info("Bedrock second pass enabled model_id=%s", settings.bedrock_model_id)
            try:
                refined = self.bedrock_mapper.refine(text=text, heuristic_result=parsed)
                parsed = self._merge(parsed, refined)
                parsed["terms"] = self.parser.ensure_course_confidences(parsed.get("terms", []))
                parsed["course_confidence_summary"] = self.parser.summarize_course_confidence(parsed.get("terms", []))
                overall_confidence = self._estimate_overall_confidence(text_assessment.score, parsed)
                bedrock_used = True
                course_count = sum(len(term.get("courses", [])) for term in parsed.get("terms", []))
                logger.info(
                    "Bedrock second pass applied successfully parser_confidence=%.4f overall_confidence=%.4f courses=%s",
                    parsed.get("parser_confidence", 0.0),
                    overall_confidence,
                    course_count,
                )
            except BedrockResponseFormatError as exc:
                logger.warning("Bedrock second pass skipped due to malformed JSON response: %s", exc)
                warnings.append("Bedrock second pass returned malformed JSON; using heuristic parse.")
        elif use_bedrock and settings.use_bedrock:
            logger.info("Skipping Bedrock second pass because heuristic confidence is sufficient.")
        else:
            logger.info(
                "Bedrock second pass skipped use_bedrock=%s settings.use_bedrock=%s",
                use_bedrock,
                settings.use_bedrock,
            )

        metadata = {
            "text_source": text_source,
            "ocr_needed": ocr_needed,
            "ocr_used": ocr_used,
            "layout_source": layout_source,
            "bedrock_used": bedrock_used,
            "ai_needed": ai_needed,
            "text_extraction_confidence": text_assessment.score,
            "heuristic_score": text_assessment.score,
            "warnings": warnings,
            "parser_confidence": parsed.get("parser_confidence", 0.0),
            "overall_confidence": overall_confidence,
            "course_confidence_summary": parsed.get("course_confidence_summary", {}),
            "visible_course_rows_estimate": visible_course_rows_estimate,
            "document_type": parsed["document_type"],
            "line_locations": line_locations,
            "raw_text_excerpt": text[:2000],
        }
        self._capture_learning_candidate(
            filename=filename,
            text=text,
            document_type=parsed["document_type"],
            heuristic_result=heuristic_parsed,
            repaired_result=parsed,
            metadata=metadata,
            ai_needed=ai_needed,
            bedrock_used=bedrock_used,
        )
        logger.info(
            "Transcript request completed text_source=%s bedrock_used=%s document_type=%s warnings=%s",
            text_source,
            bedrock_used,
            parsed["document_type"],
            len(warnings),
        )
        return self.response_mapper.map(parsed=parsed, raw_text=parse_text, metadata=metadata)

    def _capture_learning_candidate(
        self,
        filename: str,
        text: str,
        document_type: str,
        heuristic_result: Dict[str, Any],
        repaired_result: Dict[str, Any],
        metadata: Dict[str, Any],
        ai_needed: bool,
        bedrock_used: bool,
    ) -> None:
        if not settings.heuristic_learning_enabled or not ai_needed:
            return
        try:
            event = self.learning_service.capture_candidate(
                filename=filename,
                text=text,
                document_type=document_type,
                heuristic_result=heuristic_result,
                repaired_result=repaired_result,
                metadata=metadata,
                bedrock_mapper=self.bedrock_mapper if bedrock_used else None,
            )
            metadata["learning_candidate_id"] = event.get("candidate_id")
            metadata["learning_status"] = event.get("status")
            metadata["learning_path"] = event.get("path")
            metadata["learning_proposal_source"] = event.get("proposal_source")
        except Exception:
            logger.exception("Failed to capture heuristic learning candidate.")
            metadata["learning_status"] = "failed"

    def _merge(self, base: Dict[str, Any], refined: Dict[str, Any]) -> Dict[str, Any]:
        merged = dict(base)
        for key in ["document_type", "student", "institutions", "academic_summary", "terms"]:
            refined_value = refined.get(key)
            if refined_value not in (None, [], {}, ""):
                merged[key] = refined_value
        merged["parser_confidence"] = max(base.get("parser_confidence", 0.0), refined.get("parser_confidence", 0.0), 0.85)
        return merged

    def _needs_ocr(self, extension: str, assessment) -> bool:
        if extension != ".pdf":
            return False
        return not assessment.acceptable

    def _needs_layout_ocr(self, extension: str, text: str, line_locations: list[dict[str, Any]]) -> bool:
        if extension != ".pdf":
            return False
        text_line_count = len([line for line in text.splitlines() if line.strip()])
        layout_line_count = len(line_locations or [])
        if text_line_count < 20 or layout_line_count == 0:
            return False
        if layout_line_count < max(int(text_line_count * 0.55), 8):
            return True
        merged_header_count = sum(
            1
            for line in (line_locations or [])
            if (
                "academicsessionacademicsession" in (line.get("normalized_text") or "")
                or "coursenocourseno" in (line.get("normalized_text") or "")
                or "institutionacademiclevelinstitutionacademiclevel" in (line.get("normalized_text") or "")
            )
        )
        return merged_header_count > 0

    def _augment_text_with_layout_rows(self, text: str, line_locations: list[dict[str, Any]]) -> str:
        if not line_locations:
            return text
        layout_rows: list[str] = []
        seen: set[str] = set()
        for line in line_locations:
            row_text = normalize_whitespace((line.get("text") or "").replace("\n", " "))
            if not row_text or row_text in seen or row_text in text:
                continue
            seen.add(row_text)
            layout_rows.append(row_text)
        if not layout_rows:
            return text
        return f"{text}\n" + "\n".join(layout_rows)

    def _needs_ai(self, text_assessment, parsed: Dict[str, Any], overall_confidence: float, visible_course_rows_estimate: int = 0) -> bool:
        if not text_assessment.acceptable:
            return True
        parser_confidence = float(parsed.get("parser_confidence", 0.0) or 0.0)
        course_summary = parsed.get("course_confidence_summary", {})
        average_course_confidence = float(course_summary.get("average", 0.0) or 0.0)
        low_confidence_count = int(course_summary.get("low_confidence_count", 0) or 0)
        course_count = int(course_summary.get("count", 0) or 0)

        if parser_confidence < settings.heuristic_parse_min_confidence:
            return True
        if overall_confidence < settings.heuristic_overall_min_confidence:
            return True
        if course_count > 0 and average_course_confidence < settings.heuristic_course_min_confidence:
            return True
        if course_count > 0 and low_confidence_count / course_count > 0.35:
            return True
        if visible_course_rows_estimate >= 4 and course_count < visible_course_rows_estimate:
            return True
        return False

    def _estimate_visible_course_rows(self, text: str) -> int:
        normalized = re.sub(r"\s+", " ", text)
        return len(
            re.findall(
                r"\d{2}/\d{4}\s+[A-Z]{2,5}/\d{3}\s+.+?(?:A\+?|A-|B\+?|B-|C\+?|C-|D\+?|D-|F|W|P|NP|S|U|IP|CR|NC|TR|PR)\s+\d+(?:\.\d+)?\s+\d+(?:\.\d+)?\s+\d+(?:\.\d+)?(?=\s*(?:\d{2}/\d{4}\s+[A-Z]{2,5}/\d{3}\s|GPA Credits|UOPX Cumulative|Total Cumulative Credits|$))",
                normalized,
                re.IGNORECASE,
            )
        )

    def _estimate_overall_confidence(self, text_confidence: float, parsed: Dict[str, Any]) -> float:
        parser_confidence = float(parsed.get("parser_confidence", 0.0) or 0.0)
        course_summary = parsed.get("course_confidence_summary", {})
        average_course_confidence = float(course_summary.get("average", 0.0) or 0.0)
        return round(
            (text_confidence * 0.35) + (parser_confidence * 0.40) + (average_course_confidence * 0.25),
            4,
        )

    def _extract_local_with_layout(self, filename: str, content: bytes, extension: str) -> Dict[str, Any]:
        if hasattr(self.local_extractor, "extract_with_layout"):
            return self.local_extractor.extract_with_layout(filename, content, extension)
        return {"text": self.local_extractor.extract(filename, content, extension), "line_locations": []}

    def _extract_textract_with_layout(self, content: bytes) -> Dict[str, Any]:
        if hasattr(self.textract_extractor, "extract_with_layout"):
            return self.textract_extractor.extract_with_layout(content)
        return {"text": self.textract_extractor.extract(content), "line_locations": []}
