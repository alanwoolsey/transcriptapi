import io
from typing import Optional

from pypdf import PdfReader

from app.core.config import settings
from app.models.domain_models import HeuristicAssessment
from app.services.aws_client_factory import create_boto3_client
from app.utils.text_utils import alpha_ratio, lines, normalize_whitespace


class LocalTextExtractor:
    def extract(self, filename: str, content: bytes, extension: str) -> str:
        if extension == ".txt":
            return normalize_whitespace(content.decode("utf-8", errors="ignore"))
        if extension == ".pdf":
            return self._extract_pdf(content)
        return ""

    def _extract_pdf(self, content: bytes) -> str:
        try:
            reader = PdfReader(io.BytesIO(content))
            page_text = []
            for page in reader.pages:
                extracted = page.extract_text() or ""
                if extracted:
                    page_text.append(extracted)
            return normalize_whitespace("\n".join(page_text))
        except Exception:
            return ""


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
        response = self._client().detect_document_text(Document={"Bytes": content})
        blocks = response.get("Blocks", [])
        lines_out = [block["Text"] for block in blocks if block.get("BlockType") == "LINE" and block.get("Text")]
        return normalize_whitespace("\n".join(lines_out))
