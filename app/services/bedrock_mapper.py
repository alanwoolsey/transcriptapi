import json
import logging
from typing import Any, Dict

from app.core.config import settings
from app.services.aws_client_factory import create_boto3_client

logger = logging.getLogger(__name__)
BEDROCK_FALLBACK_MODEL_ID = "us.anthropic.claude-haiku-4-5-20251001-v1:0"


class BedrockResponseFormatError(ValueError):
    pass


class BedrockMapper:
    def __init__(self, client=None):
        self.client = client

    def _client(self):
        if self.client is None:
            self.client = create_boto3_client("bedrock-runtime")
        return self.client

    def refine(self, text: str, heuristic_result: Dict[str, Any]) -> Dict[str, Any]:
        prompt = self._build_prompt(text=text, heuristic_result=heuristic_result)
        return self._invoke_json_prompt(prompt=prompt, log_label="transcript refinement")

    def propose_heuristic_rule(self, text: str, heuristic_result: Dict[str, Any], repaired_result: Dict[str, Any]) -> Dict[str, Any]:
        prompt = self._build_rule_prompt(text=text, heuristic_result=heuristic_result, repaired_result=repaired_result)
        return self._invoke_json_prompt(prompt=prompt, log_label="heuristic rule proposal")

    def _invoke_json_prompt(self, prompt: str, log_label: str) -> Dict[str, Any]:
        model_id = settings.bedrock_model_id
        logger.info(
            "Calling Bedrock model=%s for %s",
            model_id,
            log_label,
        )
        try:
            response = self._converse(model_id=model_id, prompt=prompt)
            output_text = response["output"]["message"]["content"][0]["text"]
            payload = self._extract_json(output_text)
            logger.info(
                "Bedrock %s parsed successfully output_chars=%s",
                log_label,
                len(output_text),
            )
            return payload
        except Exception as exc:
            if self._should_retry_with_fallback_model(exc, model_id):
                logger.warning(
                    "Configured Bedrock model=%s is unavailable for direct invocation. Retrying with fallback model=%s",
                    model_id,
                    BEDROCK_FALLBACK_MODEL_ID,
                )
                response = self._converse(model_id=BEDROCK_FALLBACK_MODEL_ID, prompt=prompt)
                output_text = response["output"]["message"]["content"][0]["text"]
                payload = self._extract_json(output_text)
                logger.info(
                    "Bedrock fallback %s parsed successfully output_chars=%s",
                    log_label,
                    len(output_text),
                )
                return payload
            logger.exception("Bedrock call failed")
            raise

    def _converse(self, model_id: str, prompt: str) -> Dict[str, Any]:
        return self._client().converse(
            modelId=model_id,
            messages=[
                {
                    "role": "user",
                    "content": [{"text": prompt}],
                }
            ],
            inferenceConfig={"maxTokens": 1800, "temperature": 0.0},
        )

    def _should_retry_with_fallback_model(self, exc: Exception, model_id: str) -> bool:
        if model_id == BEDROCK_FALLBACK_MODEL_ID:
            return False
        response = getattr(exc, "response", None)
        if not isinstance(response, dict):
            return False
        error = response.get("Error", {})
        code = error.get("Code")
        message = (error.get("Message") or "").lower()
        if code == "ResourceNotFoundException" and "end of its life" in message:
            return True
        if code == "ValidationException" and "inference profile" in message:
            return True
        return False

    def _build_prompt(self, text: str, heuristic_result: Dict[str, Any]) -> str:
        return f"""
You are normalizing transcript data into a strict JSON schema.
Only return valid JSON. Do not wrap it in markdown.
This is a second-pass improvement step after a deterministic parser.
Your job is to preserve deterministic values unless the transcript text clearly supports a correction, and fill missing or weak fields using the transcript text.
Be conservative with sensitive fields. If a value is not supported by the transcript text, return null instead of inventing it.
Prefer completeness for course rows, terms, GPA, credits, class rank, institution, student identity, degree, graduation date, and test scores when present.

Rules:
- Keep every course that already appears in the heuristic result unless the transcript text clearly shows it is invalid.
- Add missing courses that are visible in the transcript text.
- Normalize course codes, titles, credits, grades, and terms.
- If the transcript appears to have transfer or repeated courses, preserve that distinction only when explicit in the text.
- For GPA and credits, use transcript totals over inferred totals when both exist.
- Return numbers as numbers, not strings.
- Return null for unknown values.
- Do not include any keys outside the schema.

Schema:
{{
  "document_type": "college_transcript|high_school_transcript|unknown",
  "student": {{"name": string|null, "student_id": string|null, "date_of_birth": string|null}},
  "institutions": [{{"name": string|null, "type": "college|high_school|unknown"}}],
  "academic_summary": {{
    "gpa": number|null,
    "total_credits_attempted": number|null,
    "total_credits_earned": number|null,
    "class_rank": string|null
  }},
  "terms": [{{
    "term_name": string,
    "courses": [{{
      "course_code": string|null,
      "course_title": string|null,
      "credits": number|null,
      "grade": string|null,
      "term": string|null
    }}]
  }}]
}}

Heuristic extraction result:
{json.dumps(heuristic_result, indent=2)}

Transcript text:
{text[:18000]}
""".strip()

    def _build_rule_prompt(self, text: str, heuristic_result: Dict[str, Any], repaired_result: Dict[str, Any]) -> str:
        return f"""
You are proposing a JSON heuristic candidate for a transcript parser.
Only return valid JSON. Do not wrap it in markdown.
The candidate must be conservative and declarative. It is not executable code.
It will be validated later against a regression corpus before promotion.

Return this schema only:
{{
  "family_id": string,
  "version": 1,
  "status": "candidate",
  "match": {{
    "all": [{{"contains": string}}]
  }},
  "strategy": {{
    "document_type": "college_transcript|high_school_transcript|unknown",
    "python_parser_fallback": true,
    "notes": [string]
  }},
  "field_hints": {{
    "institution_name": string|null,
    "student_name_example": string|null,
    "student_id_example": string|null,
    "date_of_birth_example": string|null
  }}
}}

Rules:
- Include 2 to 4 stable match conditions from the transcript header.
- Avoid personal identifiers in match conditions unless they are institution-level boilerplate.
- Prefer institution names, vendor markers, and durable layout labels.
- Keep python_parser_fallback=true.
- Notes should briefly explain why the deterministic parser missed this family.

Heuristic result before AI repair:
{json.dumps(heuristic_result, indent=2)}

Repaired result returned to the caller:
{json.dumps(repaired_result, indent=2)}

Transcript text:
{text[:12000]}
""".strip()

    def _extract_json(self, raw_text: str) -> Dict[str, Any]:
        raw_text = raw_text.strip()
        if raw_text.startswith("```"):
            raw_text = raw_text.strip("`")
            raw_text = raw_text.replace("json", "", 1).strip()
        start = raw_text.find("{")
        end = raw_text.rfind("}")
        if start == -1 or end == -1:
            raise BedrockResponseFormatError("Bedrock response did not contain JSON.")
        try:
            return json.loads(raw_text[start : end + 1])
        except json.JSONDecodeError as exc:
            logger.warning(
                "Bedrock returned malformed JSON at line=%s column=%s position=%s",
                exc.lineno,
                exc.colno,
                exc.pos,
            )
            raise BedrockResponseFormatError(f"Bedrock returned malformed JSON: {exc}") from exc
