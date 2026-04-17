from app.services.pipeline import TranscriptPipeline


class DummyTextract:
    def extract(self, content: bytes) -> str:
        return "Example High School\nName: John Doe\nClass Rank: 10/250\nWeighted GPA 3.9"


class DummyBedrock:
    def refine(self, text: str, heuristic_result: dict) -> dict:
        heuristic_result["student"]["name"] = heuristic_result["student"].get("name") or "John Doe"
        heuristic_result["academic_summary"]["class_rank"] = heuristic_result["academic_summary"].get("class_rank") or "10/250"
        return heuristic_result


def test_pipeline_process_text_file_without_textract_or_bedrock():
    pipeline = TranscriptPipeline(textract_extractor=DummyTextract(), bedrock_mapper=DummyBedrock())
    content = b"Example State University\nStudent Name: Jane Smith\nStudent ID: 123456\nFall 2024\nENG101 English Composition 3 A\nCumulative GPA 3.76"
    result = pipeline.process("test.txt", content, "text/plain", requested_document_type="college", use_bedrock=False)

    assert result["demographic"]["firstName"] == "Jane"
    assert result["demographic"]["lastName"] == "Smith"
    assert result["demographic"]["studentId"] == "123456"
    assert result["demographic"]["institutionName"] == "Example State University"
    assert result["grandGPA"]["cumulativeGPA"] == 3.76
    assert len(result["courses"]) == 1
    assert result["courses"][0]["courseId"] == "ENG101"
    assert result["courses"][0]["term"] == "Fall"
    assert result["courses"][0]["year"] == "2024"
    assert result["metadata"]["text_source"] == "heuristic"
    assert result["metadata"]["bedrock_used"] is False


def test_pipeline_always_runs_bedrock_when_enabled():
    pipeline = TranscriptPipeline(textract_extractor=DummyTextract(), bedrock_mapper=DummyBedrock())
    content = b"Example State University\nStudent Name: Jane Smith\nStudent ID: 123456\nFall 2024\nENG101 English Composition 3 A\nCumulative GPA 3.76"

    result = pipeline.process("test.txt", content, "text/plain", requested_document_type="college", use_bedrock=True)

    assert result["metadata"]["bedrock_used"] is True
    assert result["demographic"]["classRank"] == "10/250"
