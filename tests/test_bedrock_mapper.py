from app.core.config import settings
from app.services.bedrock_mapper import BEDROCK_FALLBACK_MODEL_ID, BedrockMapper


class FakeClientError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.response = {"Error": {"Code": code, "Message": message}}


class FallbackBedrockClient:
    def __init__(self):
        self.calls = []

    def converse(self, modelId: str, messages: list[dict], inferenceConfig: dict):
        self.calls.append(modelId)
        if modelId != BEDROCK_FALLBACK_MODEL_ID:
            raise FakeClientError(
                "ResourceNotFoundException",
                "This model version has reached the end of its life. Please refer to the AWS documentation for more details.",
            )
        return {
            "output": {
                "message": {
                    "content": [
                        {
                            "text": '{"document_type":"college_transcript","student":{"name":"Jane Smith","student_id":"123456","date_of_birth":null},"institutions":[{"name":"Example State University","type":"college"}],"academic_summary":{"gpa":3.76,"total_credits_attempted":62,"total_credits_earned":59,"class_rank":null},"terms":[]}'
                        }
                    ]
                }
            }
        }


def test_bedrock_mapper_retries_with_fallback_model_on_eol_error():
    client = FallbackBedrockClient()
    mapper = BedrockMapper(client=client)
    original_model_id = settings.bedrock_model_id
    settings.bedrock_model_id = "anthropic.claude-3-5-sonnet-20241022-v2:0"

    try:
        payload = mapper.refine(
            text="Example State University\nStudent Name: Jane Smith",
            heuristic_result={
                "document_type": "college_transcript",
                "student": {"name": "Jane Smith", "student_id": "123456", "date_of_birth": None},
                "institutions": [{"name": "Example State University", "type": "college"}],
                "academic_summary": {"gpa": 3.76, "total_credits_attempted": 62, "total_credits_earned": 59, "class_rank": None},
                "terms": [],
            },
        )
    finally:
        settings.bedrock_model_id = original_model_id

    assert client.calls == ["anthropic.claude-3-5-sonnet-20241022-v2:0", BEDROCK_FALLBACK_MODEL_ID]
    assert payload["document_type"] == "college_transcript"


class ValidationFallbackBedrockClient:
    def __init__(self):
        self.calls = []

    def converse(self, modelId: str, messages: list[dict], inferenceConfig: dict):
        self.calls.append(modelId)
        if modelId != BEDROCK_FALLBACK_MODEL_ID:
            raise FakeClientError(
                "ValidationException",
                "Invocation of model ID anthropic.claude-sonnet-4-6 with on-demand throughput isn't supported. Retry your request with the ID or ARN of an inference profile that contains this model.",
            )
        return {
            "output": {
                "message": {
                    "content": [
                        {
                            "text": '{"document_type":"college_transcript","student":{"name":"Jane Smith","student_id":"123456","date_of_birth":null},"institutions":[{"name":"Example State University","type":"college"}],"academic_summary":{"gpa":3.76,"total_credits_attempted":62,"total_credits_earned":59,"class_rank":null},"terms":[]}'
                        }
                    ]
                }
            }
        }


def test_bedrock_mapper_retries_with_inference_profile_on_validation_error():
    client = ValidationFallbackBedrockClient()
    mapper = BedrockMapper(client=client)
    original_model_id = settings.bedrock_model_id
    settings.bedrock_model_id = "anthropic.claude-sonnet-4-6"

    try:
        payload = mapper.refine(
            text="Example State University\nStudent Name: Jane Smith",
            heuristic_result={
                "document_type": "college_transcript",
                "student": {"name": "Jane Smith", "student_id": "123456", "date_of_birth": None},
                "institutions": [{"name": "Example State University", "type": "college"}],
                "academic_summary": {"gpa": 3.76, "total_credits_attempted": 62, "total_credits_earned": 59, "class_rank": None},
                "terms": [],
            },
        )
    finally:
        settings.bedrock_model_id = original_model_id

    assert client.calls == ["anthropic.claude-sonnet-4-6", BEDROCK_FALLBACK_MODEL_ID]
    assert payload["document_type"] == "college_transcript"
