import io
import re
from typing import Any, Optional

from pypdf import PdfReader

from app.core.config import settings
from app.models.domain_models import HeuristicAssessment
from app.services.aws_client_factory import create_boto3_client
from app.utils.text_utils import alpha_ratio, lines, normalize_for_match, normalize_whitespace


class LocalTextExtractor:
    def extract(self, filename: str, content: bytes, extension: str) -> str:
        return self.extract_with_layout(filename, content, extension)["text"]

    def extract_with_layout(self, filename: str, content: bytes, extension: str) -> dict[str, Any]:
        if extension == ".txt":
            text = normalize_whitespace(content.decode("utf-8", errors="ignore"))
            line_locations = [
                self._build_line_location(
                    text=line,
                    page_number=1,
                    bounding_box={"left": 0.0, "top": 0.0, "width": 0.0, "height": 0.0},
                )
                for line in lines(text)
            ]
            return {"text": text, "line_locations": line_locations}
        if extension == ".pdf":
            return self._extract_pdf_with_layout(content)
        return {"text": "", "line_locations": []}

    def _extract_pdf_with_layout(self, content: bytes) -> dict[str, Any]:
        try:
            reader = PdfReader(io.BytesIO(content))
            page_text: list[str] = []
            line_locations: list[dict[str, Any]] = []
            for page_number, page in enumerate(reader.pages, start=1):
                page_height = float(page.mediabox.height or 0.0)
                fragments: list[dict[str, Any]] = []

                def visitor_text(text, cm, tm, font_dict, font_size):
                    if not text or not text.strip():
                        return
                    x = float(tm[4] if len(tm) > 4 else 0.0)
                    y = float(tm[5] if len(tm) > 5 else 0.0)
                    size = float(font_size or 0.0)
                    fragments.append({"text": text, "x": x, "y": y, "font_size": size})

                extracted = page.extract_text(visitor_text=visitor_text) or ""
                segmented_lines = self._split_compound_pdf_lines(extracted.splitlines())
                if segmented_lines:
                    page_text.append("\n".join(segmented_lines))
                line_locations.extend(self._group_pdf_fragments_into_lines(fragments, page_number, page_height))
            return {"text": normalize_whitespace("\n".join(page_text)), "line_locations": line_locations}
        except Exception:
            return {"text": "", "line_locations": []}

    def _split_compound_pdf_lines(self, lines_in_page: list[str]) -> list[str]:
        out: list[str] = []
        for raw_line in lines_in_page:
            stripped = raw_line.rstrip()
            if not stripped.strip():
                continue
            segments = [segment.strip() for segment in re.split(r"\s{6,}", stripped) if segment.strip()]
            if not segments:
                continue
            merged_segments: list[str] = []
            current = segments[0]
            for segment in segments[1:]:
                if self._starts_new_pdf_segment(segment):
                    merged_segments.append(current)
                    current = segment
                else:
                    current = f"{current} {segment}"
            merged_segments.append(current)
            out.extend(normalize_whitespace(segment) for segment in merged_segments if normalize_whitespace(segment))
        return out

    def _starts_new_pdf_segment(self, segment: str) -> bool:
        return bool(
            re.match(r"^[A-Z]{2,6}[- ]?\d{2,4}[A-Z]?\b", segment)
            or re.match(r"^-+\s*\([A-Z0-9]+\)\s+", segment)
            or re.match(r"^(Total\s+Park|Earned\s+Earned|ses\b|cum\b|\*\*\s+Repeated\s+\*\*|\*\*\s+Replaces)", segment, re.IGNORECASE)
        )

    def _group_pdf_fragments_into_lines(
        self, fragments: list[dict[str, Any]], page_number: int, page_height: float
    ) -> list[dict[str, Any]]:
        if not fragments:
            return []

        grouped: list[dict[str, Any]] = []
        sorted_fragments = sorted(fragments, key=lambda item: (-item["y"], item["x"]))
        tolerance = 3.0

        for fragment in sorted_fragments:
            target = None
            for line in grouped:
                if abs(line["y"] - fragment["y"]) <= tolerance:
                    target = line
                    break
            if target is None:
                target = {"y": fragment["y"], "fragments": []}
                grouped.append(target)
            target["fragments"].append(fragment)

        line_locations: list[dict[str, Any]] = []
        for line in grouped:
            ordered = sorted(line["fragments"], key=lambda item: item["x"])
            text = normalize_whitespace("".join(part["text"] for part in ordered))
            if not text:
                continue
            left = min(part["x"] for part in ordered)
            font_height = max(part["font_size"] for part in ordered) or 10.0
            top = max(page_height - line["y"] - font_height, 0.0) if page_height else 0.0
            width = max((max(part["x"] for part in ordered) - left) + self._approximate_text_width(text, font_height), 0.0)
            line_locations.append(
                self._build_line_location(
                    text=text,
                    page_number=page_number,
                    bounding_box={
                        "left": round(left, 2),
                        "top": round(top, 2),
                        "width": round(width, 2),
                        "height": round(font_height, 2),
                    },
                )
            )
        return line_locations

    def _approximate_text_width(self, text: str, font_size: float) -> float:
        return max(len(text) * max(font_size, 8.0) * 0.45, font_size)

    def _build_line_location(self, text: str, page_number: int, bounding_box: dict[str, float]) -> dict[str, Any]:
        return {
            "text": text,
            "normalized_text": normalize_for_match(text),
            "page_number": page_number,
            "bounding_box": bounding_box,
        }


class HeuristicJudge:
    def assess(self, text: str) -> HeuristicAssessment:
        clean = normalize_whitespace(text)
        char_count = len(clean)
        line_count = len(lines(clean))
        a_ratio = alpha_ratio(clean)

        char_component = min(char_count / max(settings.heuristic_min_char_count, 1), 1.0)
        line_component = min(line_count / max(settings.heuristic_min_line_count, 1), 1.0)
        alpha_component = min(a_ratio / max(settings.heuristic_min_alpha_ratio, 0.01), 1.0)
        score = round((char_component * 0.45) + (line_component * 0.25) + (alpha_component * 0.30), 4)

        warnings: list[str] = []
        if char_count < settings.heuristic_min_char_count:
            warnings.append("Low character count from heuristic extraction.")
        if line_count < settings.heuristic_min_line_count:
            warnings.append("Low line count from heuristic extraction.")
        if a_ratio < settings.heuristic_min_alpha_ratio:
            warnings.append("Low alphabetic ratio from heuristic extraction.")

        return HeuristicAssessment(
            text=clean,
            score=score,
            acceptable=score >= settings.heuristic_min_score,
            char_count=char_count,
            alpha_ratio=round(a_ratio, 4),
            line_count=line_count,
            warnings=warnings,
        )


class TextractExtractor:
    def __init__(self, client=None):
        self.client = client

    def _client(self):
        if self.client is None:
            self.client = create_boto3_client("textract")
        return self.client

    def extract(self, content: bytes) -> str:
        return self.extract_with_layout(content)["text"]

    def extract_with_layout(self, content: bytes) -> dict[str, Any]:
        try:
            response = self._client().detect_document_text(Document={"Bytes": content})
        except Exception as exc:
            if self._is_unsupported_document_error(exc) and self._looks_like_pdf(content):
                return self._extract_pdf_pages_as_images(content)
            raise
        blocks = response.get("Blocks", [])
        line_locations = []
        lines_out = []
        for block in blocks:
            if block.get("BlockType") != "LINE" or not block.get("Text"):
                continue
            text = block["Text"]
            lines_out.append(text)
            bbox = block.get("Geometry", {}).get("BoundingBox", {})
            line_locations.append(
                {
                    "text": text,
                    "normalized_text": normalize_for_match(text),
                    "page_number": int(block.get("Page", 1) or 1),
                    "bounding_box": {
                        "left": float(bbox.get("Left", 0.0) or 0.0),
                        "top": float(bbox.get("Top", 0.0) or 0.0),
                        "width": float(bbox.get("Width", 0.0) or 0.0),
                        "height": float(bbox.get("Height", 0.0) or 0.0),
                    },
                }
            )
        synthetic_rows = self._build_synthetic_textract_rows(line_locations)
        return {"text": normalize_whitespace("\n".join(lines_out)), "line_locations": synthetic_rows + line_locations}

    def _extract_pdf_pages_as_images(self, content: bytes) -> dict[str, Any]:
        try:
            import fitz
        except Exception:
            raise

        lines_out: list[str] = []
        line_locations: list[dict[str, Any]] = []
        document = fitz.open(stream=content, filetype="pdf")
        try:
            for page_index, page in enumerate(document, start=1):
                pixmap = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
                response = self._client().detect_document_text(Document={"Bytes": pixmap.tobytes("png")})
                page_result = self._response_to_layout(response, page_number_override=page_index)
                lines_out.extend(lines(page_result["text"]))
                line_locations.extend(page_result["line_locations"])
        finally:
            document.close()

        synthetic_rows = self._build_synthetic_textract_rows(line_locations)
        return {"text": normalize_whitespace("\n".join(lines_out)), "line_locations": synthetic_rows + line_locations}

    def _response_to_layout(self, response: dict[str, Any], page_number_override: int | None = None) -> dict[str, Any]:
        blocks = response.get("Blocks", [])
        line_locations = []
        lines_out = []
        for block in blocks:
            if block.get("BlockType") != "LINE" or not block.get("Text"):
                continue
            text = block["Text"]
            lines_out.append(text)
            bbox = block.get("Geometry", {}).get("BoundingBox", {})
            line_locations.append(
                {
                    "text": text,
                    "normalized_text": normalize_for_match(text),
                    "page_number": page_number_override or int(block.get("Page", 1) or 1),
                    "bounding_box": {
                        "left": float(bbox.get("Left", 0.0) or 0.0),
                        "top": float(bbox.get("Top", 0.0) or 0.0),
                        "width": float(bbox.get("Width", 0.0) or 0.0),
                        "height": float(bbox.get("Height", 0.0) or 0.0),
                    },
                }
            )
        return {"text": normalize_whitespace("\n".join(lines_out)), "line_locations": line_locations}

    def _looks_like_pdf(self, content: bytes) -> bool:
        return content[:5] == b"%PDF-"

    def _is_unsupported_document_error(self, exc: Exception) -> bool:
        message = str(exc)
        return "UnsupportedDocumentException" in message or exc.__class__.__name__ == "UnsupportedDocumentException"

    def _build_synthetic_textract_rows(self, line_locations: list[dict[str, Any]]) -> list[dict[str, Any]]:
        grouped: dict[tuple[int, int], list[dict[str, Any]]] = {}
        for line in line_locations:
            page_number = int(line.get("page_number", 1) or 1)
            top = float(line.get("bounding_box", {}).get("top", 0.0) or 0.0)
            key = (page_number, round(top / 0.006))
            grouped.setdefault(key, []).append(line)

        synthetic: list[dict[str, Any]] = []
        for (_, _), row_lines in grouped.items():
            ordered = sorted(row_lines, key=lambda item: float(item.get("bounding_box", {}).get("left", 0.0) or 0.0))
            title_indexes = [idx for idx, line in enumerate(ordered) if self._is_title_like_textract_fragment(line.get("text") or "")]
            if len(title_indexes) <= 1:
                continue
            for position, start_idx in enumerate(title_indexes):
                end_idx = title_indexes[position + 1] if position + 1 < len(title_indexes) else len(ordered)
                fragments = ordered[start_idx:end_idx]
                if len(fragments) <= 1:
                    continue
                synthetic_line = self._merge_textract_fragments(fragments)
                if synthetic_line:
                    synthetic.append(synthetic_line)
        return synthetic

    def _is_title_like_textract_fragment(self, text: str) -> bool:
        lowered = normalize_whitespace(text).lower()
        if not lowered:
            return False
        if lowered in {
            "course no title",
            "session",
            "grade",
            "credits",
            "session grade credits",
            "institution",
            "academic session",
            "academic year academic level",
        }:
            return False
        return bool(re.search(r"[a-z]{3,}", lowered))

    def _merge_textract_fragments(self, fragments: list[dict[str, Any]]) -> dict[str, Any] | None:
        texts = [(fragment.get("text") or "").strip() for fragment in fragments if (fragment.get("text") or "").strip()]
        if len(texts) <= 1:
            return None
        left = min(float(fragment.get("bounding_box", {}).get("left", 0.0) or 0.0) for fragment in fragments)
        top = min(float(fragment.get("bounding_box", {}).get("top", 0.0) or 0.0) for fragment in fragments)
        right = max(
            float(fragment.get("bounding_box", {}).get("left", 0.0) or 0.0)
            + float(fragment.get("bounding_box", {}).get("width", 0.0) or 0.0)
            for fragment in fragments
        )
        bottom = max(
            float(fragment.get("bounding_box", {}).get("top", 0.0) or 0.0)
            + float(fragment.get("bounding_box", {}).get("height", 0.0) or 0.0)
            for fragment in fragments
        )
        merged_text = " ".join(texts)
        return {
            "text": merged_text,
            "normalized_text": normalize_for_match(merged_text),
            "page_number": int(fragments[0].get("page_number", 1) or 1),
            "bounding_box": {
                "left": left,
                "top": top,
                "width": max(right - left, 0.0),
                "height": max(bottom - top, 0.0),
            },
            "synthetic_row": True,
        }
