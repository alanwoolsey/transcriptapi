import json
from pathlib import Path

from app.core.config import settings
from app.services.pipeline import TranscriptPipeline
from app.models.api_models import ParseTranscriptResponse


class DummyLocalExtractor:
    def __init__(self, text: str):
        self.text = text

    def extract(self, filename: str, content: bytes, extension: str) -> str:
        return self.text

    def extract_with_layout(self, filename: str, content: bytes, extension: str) -> dict:
        return {
            "text": self.text,
            "line_locations": [
                {
                    "text": line,
                    "normalized_text": "".join(ch.lower() for ch in line if ch.isalnum()),
                    "page_number": 1,
                    "bounding_box": {"left": 10.0, "top": 20.0, "width": 100.0, "height": 12.0},
                }
                for line in self.text.splitlines()
                if line.strip()
            ],
        }


class DummyTextract:
    def extract(self, content: bytes) -> str:
        return "Example High School\nName: John Doe\nClass Rank: 10/250\nWeighted GPA 3.9"

    def extract_with_layout(self, content: bytes) -> dict:
        return {
            "text": self.extract(content),
            "line_locations": [
                {
                    "text": "Example High School",
                    "normalized_text": "examplehighschool",
                    "page_number": 1,
                    "bounding_box": {"left": 0.1, "top": 0.1, "width": 0.3, "height": 0.05},
                },
                {
                    "text": "Name: John Doe",
                    "normalized_text": "namejohndoe",
                    "page_number": 1,
                    "bounding_box": {"left": 0.1, "top": 0.2, "width": 0.2, "height": 0.05},
                },
                {
                    "text": "Class Rank: 10/250",
                    "normalized_text": "classrank10250",
                    "page_number": 1,
                    "bounding_box": {"left": 0.1, "top": 0.3, "width": 0.2, "height": 0.05},
                },
                {
                    "text": "Weighted GPA 3.9",
                    "normalized_text": "weightedgpa39",
                    "page_number": 1,
                    "bounding_box": {"left": 0.1, "top": 0.4, "width": 0.2, "height": 0.05},
                },
            ],
        }


class DummyBedrock:
    def __init__(self):
        self.calls = 0
        self.proposal_calls = 0

    def refine(self, text: str, heuristic_result: dict) -> dict:
        self.calls += 1
        heuristic_result["student"]["name"] = heuristic_result["student"].get("name") or "John Doe"
        heuristic_result["academic_summary"]["class_rank"] = heuristic_result["academic_summary"].get("class_rank") or "10/250"
        return heuristic_result

    def propose_heuristic_rule(self, text: str, heuristic_result: dict, repaired_result: dict) -> dict:
        self.proposal_calls += 1
        return {
            "family_id": "example_high_school_v1",
            "version": 1,
            "status": "candidate",
            "match": {"all": [{"contains": "Example High School"}, {"contains": "Name: John Doe"}]},
            "strategy": {"document_type": repaired_result["document_type"], "python_parser_fallback": True, "notes": ["Low confidence heuristic parse."]},
            "field_hints": {
                "institution_name": "Example High School",
                "student_name_example": "John Doe",
                "student_id_example": None,
                "date_of_birth_example": None,
            },
        }


class MalformedBedrock:
    def __init__(self):
        self.calls = 0

    def refine(self, text: str, heuristic_result: dict) -> dict:
        from app.services.bedrock_mapper import BedrockResponseFormatError

        self.calls += 1
        raise BedrockResponseFormatError("Bedrock returned malformed JSON: Expecting ',' delimiter")


class BlankStudentBedrock:
    def __init__(self):
        self.calls = 0

    def refine(self, text: str, heuristic_result: dict) -> dict:
        self.calls += 1
        refined = dict(heuristic_result)
        refined["student"] = {"name": None, "student_id": None, "date_of_birth": None}
        refined["parser_confidence"] = 0.9
        return refined


class FailingTextract:
    def extract(self, content: bytes) -> str:
        raise RuntimeError("UnsupportedDocumentException")

    def extract_with_layout(self, content: bytes) -> dict:
        raise RuntimeError("UnsupportedDocumentException")


class MergedLayoutLocalExtractor(DummyLocalExtractor):
    def extract_with_layout(self, filename: str, content: bytes, extension: str) -> dict:
        return {
            "text": self.text,
            "line_locations": [
                {
                    "text": "Academic SessionAcademic SessionAcademic Session",
                    "normalized_text": "academicsessionacademicsessionacademicsession",
                    "page_number": 1,
                    "bounding_box": {"left": 0.0, "top": 996.0, "width": 23884.2, "height": 12.0},
                },
                {
                    "text": "Course noCourse noCourse no",
                    "normalized_text": "coursenocoursenocourseno",
                    "page_number": 1,
                    "bounding_box": {"left": 0.0, "top": 980.0, "width": 22000.0, "height": 12.0},
                },
            ],
        }


class CleanLayoutTextract(DummyTextract):
    def extract(self, content: bytes) -> str:
        return "Example State University\nFall 2024\nENG101 English Composition 3 A"

    def extract_with_layout(self, content: bytes) -> dict:
        return {
            "text": self.extract(content),
            "line_locations": [
                {
                    "text": "Example State University",
                    "normalized_text": "examplestateuniversity",
                    "page_number": 1,
                    "bounding_box": {"left": 1.0, "top": 2.0, "width": 30.0, "height": 4.0},
                },
                {
                    "text": "Fall 2024",
                    "normalized_text": "fall2024",
                    "page_number": 1,
                    "bounding_box": {"left": 2.0, "top": 6.0, "width": 10.0, "height": 4.0},
                },
                {
                    "text": "ENG101 English Composition 3 A",
                    "normalized_text": "eng101englishcomposition3a",
                    "page_number": 1,
                    "bounding_box": {"left": 3.0, "top": 10.0, "width": 20.0, "height": 4.0},
                },
            ],
        }


class SourceLineParser:
    def detect_document_type(self, text: str, requested_document_type: str = "auto") -> str:
        return "high_school_transcript"

    def parse(self, text: str, document_type: str) -> dict:
        return {
            "document_type": "high_school_transcript",
            "student": {"name": "Jane Smith", "student_id": None, "date_of_birth": None, "address": {"street": None, "city": None, "state": None, "postal_code": None}},
            "institutions": [{"name": "Example High School", "type": "high_school"}],
            "academic_summary": {"gpa": None, "total_credits_attempted": None, "total_credits_earned": None, "class_rank": None},
            "terms": [
                {
                    "term_name": "2024-2025 Example High School",
                    "courses": [
                        {
                            "course_code": None,
                            "course_title": "English Composition",
                            "credits": 0.5,
                            "grade": "A",
                            "term": "2024-2025 Example High School",
                            "source_line": "English Composition 1 A 0.500",
                            "confidence_score": 0.7,
                            "confidence_reasons": ["missing course code"],
                        }
                    ],
                }
            ],
            "parser_confidence": 0.9,
            "course_confidence_summary": {"average": 0.7, "minimum": 0.7, "count": 1, "low_confidence_count": 0},
        }

    def ensure_course_confidences(self, terms):
        return terms

    def summarize_course_confidence(self, terms):
        return {"average": 0.7, "minimum": 0.7, "count": 1, "low_confidence_count": 0}


class SplitRowParser(SourceLineParser):
    def parse(self, text: str, document_type: str) -> dict:
        return {
            "document_type": "high_school_transcript",
            "student": {"name": "Jane Smith", "student_id": None, "date_of_birth": None, "address": {"street": None, "city": None, "state": None, "postal_code": None}},
            "institutions": [{"name": "Example High School", "type": "high_school"}],
            "academic_summary": {"gpa": None, "total_credits_attempted": None, "total_credits_earned": None, "class_rank": None},
            "terms": [
                {
                    "term_name": "2024-2025 Example High School",
                    "courses": [
                        {
                            "course_code": None,
                            "course_title": "Found Business & Marketing",
                            "credits": 0.25,
                            "grade": "A",
                            "term": "2024-2025 Example High School",
                            "source_line": "Found Business & Marketing 1 A 0.250",
                            "confidence_score": 0.7,
                            "confidence_reasons": ["missing course code"],
                        }
                    ],
                }
            ],
            "parser_confidence": 0.9,
            "course_confidence_summary": {"average": 0.7, "minimum": 0.7, "count": 1, "low_confidence_count": 0},
        }


class RepeatedTitleParser:
    def detect_document_type(self, text: str, requested_document_type: str = "auto") -> str:
        return "high_school_transcript"

    def parse(self, text: str, document_type: str) -> dict:
        return {
            "document_type": "high_school_transcript",
            "student": {"name": "Jane Smith", "student_id": None, "date_of_birth": None, "address": {"street": None, "city": None, "state": None, "postal_code": None}},
            "institutions": [{"name": "Example High School", "type": "high_school"}],
            "academic_summary": {"gpa": None, "total_credits_attempted": None, "total_credits_earned": None, "class_rank": None},
            "terms": [
                {
                    "term_name": "2024-2025 Alpha High",
                    "courses": [
                        {
                            "course_code": None,
                            "course_title": "Chemistry",
                            "credits": 0.25,
                            "grade": "A",
                            "term": "2024-2025 Alpha High",
                            "source_line": "Chemistry 1 A 0.250",
                            "source_term_line": "Alpha High 2024-2025",
                            "confidence_score": 0.7,
                            "confidence_reasons": ["missing course code"],
                        }
                    ],
                },
                {
                    "term_name": "2025-2026 Beta High",
                    "courses": [
                        {
                            "course_code": None,
                            "course_title": "Chemistry",
                            "credits": 0.5,
                            "grade": "B",
                            "term": "2025-2026 Beta High",
                            "source_line": "Chemistry 2 B 0.500",
                            "source_term_line": "Beta High 2025-2026",
                            "confidence_score": 0.7,
                            "confidence_reasons": ["missing course code"],
                        }
                    ],
                },
            ],
            "parser_confidence": 0.9,
            "course_confidence_summary": {"average": 0.7, "minimum": 0.7, "count": 2, "low_confidence_count": 0},
        }

    def ensure_course_confidences(self, terms):
        return terms

    def summarize_course_confidence(self, terms):
        return {"average": 0.7, "minimum": 0.7, "count": 2, "low_confidence_count": 0}


class RepeatedTitleTextract(DummyTextract):
    def extract(self, content: bytes) -> str:
        return "Alpha High 2024-2025\nChemistry 1 A 0.250\nBeta High 2025-2026\nChemistry 2 B 0.500"

    def extract_with_layout(self, content: bytes) -> dict:
        return {
            "text": self.extract(content),
            "line_locations": [
                {
                    "text": "Alpha High 2024-2025",
                    "normalized_text": "alphahigh20242025",
                    "page_number": 1,
                    "bounding_box": {"left": 0.05, "top": 0.10, "width": 0.20, "height": 0.01},
                },
                {
                    "text": "Chemistry 1 A 0.250",
                    "normalized_text": "chemistry1a0250",
                    "page_number": 1,
                    "bounding_box": {"left": 0.05, "top": 0.12, "width": 0.18, "height": 0.01},
                },
                {
                    "text": "Beta High 2025-2026",
                    "normalized_text": "betahigh20252026",
                    "page_number": 1,
                    "bounding_box": {"left": 0.05, "top": 0.30, "width": 0.20, "height": 0.01},
                },
                {
                    "text": "Chemistry 2 B 0.500",
                    "normalized_text": "chemistry2b0500",
                    "page_number": 1,
                    "bounding_box": {"left": 0.05, "top": 0.32, "width": 0.18, "height": 0.01},
                },
            ],
        }


class ParallelColumnsParser:
    def detect_document_type(self, text: str, requested_document_type: str = "auto") -> str:
        return "high_school_transcript"

    def parse(self, text: str, document_type: str) -> dict:
        return {
            "document_type": "high_school_transcript",
            "student": {"name": "Jane Smith", "student_id": None, "date_of_birth": None, "address": {"street": None, "city": None, "state": None, "postal_code": None}},
            "institutions": [{"name": "Example High School", "type": "high_school"}],
            "academic_summary": {"gpa": None, "total_credits_attempted": None, "total_credits_earned": None, "class_rank": None},
            "terms": [
                {
                    "term_name": "2024-2025 Alpha High",
                    "courses": [
                        {
                            "course_code": None,
                            "course_title": "Chemistry",
                            "credits": 0.25,
                            "grade": "A",
                            "term": "2024-2025 Alpha High",
                            "source_line": "Chemistry 1 A 0.250",
                            "source_term_line": "Alpha High 2024-2025",
                            "confidence_score": 0.7,
                            "confidence_reasons": ["missing course code"],
                        }
                    ],
                },
                {
                    "term_name": "2023-2024 Beta High",
                    "courses": [
                        {
                            "course_code": None,
                            "course_title": "Chemistry",
                            "credits": 0.5,
                            "grade": "B",
                            "term": "2023-2024 Beta High",
                            "source_line": "Chemistry 2 B 0.500",
                            "source_term_line": "Beta High 2023-2024",
                            "confidence_score": 0.7,
                            "confidence_reasons": ["missing course code"],
                        }
                    ],
                },
                {
                    "term_name": "2025-2026 Gamma High",
                    "courses": [
                        {
                            "course_code": None,
                            "course_title": "Chemistry",
                            "credits": 0.75,
                            "grade": "A-",
                            "term": "2025-2026 Gamma High",
                            "source_line": "Chemistry 3 A- 0.750",
                            "source_term_line": "Gamma High 2025-2026",
                            "confidence_score": 0.7,
                            "confidence_reasons": ["missing course code"],
                        }
                    ],
                },
            ],
            "parser_confidence": 0.9,
            "course_confidence_summary": {"average": 0.7, "minimum": 0.7, "count": 3, "low_confidence_count": 0},
        }

    def ensure_course_confidences(self, terms):
        return terms

    def summarize_course_confidence(self, terms):
        return {"average": 0.7, "minimum": 0.7, "count": 3, "low_confidence_count": 0}


class ParallelColumnsTextract(DummyTextract):
    def extract(self, content: bytes) -> str:
        return "Alpha High 2024-2025 Beta High 2023-2024 Gamma High 2025-2026"

    def extract_with_layout(self, content: bytes) -> dict:
        return {
            "text": self.extract(content),
            "line_locations": [
                {
                    "text": "Alpha High 2024-2025",
                    "normalized_text": "alphahigh20242025",
                    "page_number": 1,
                    "bounding_box": {"left": 0.05, "top": 0.10, "width": 0.16, "height": 0.01},
                },
                {
                    "text": "Beta High 2023-2024",
                    "normalized_text": "betahigh20232024",
                    "page_number": 1,
                    "bounding_box": {"left": 0.30, "top": 0.10, "width": 0.16, "height": 0.01},
                },
                {
                    "text": "Gamma High 2025-2026",
                    "normalized_text": "gammahigh20252026",
                    "page_number": 1,
                    "bounding_box": {"left": 0.55, "top": 0.10, "width": 0.16, "height": 0.01},
                },
                {
                    "text": "Chemistry 1 A 0.250",
                    "normalized_text": "chemistry1a0250",
                    "page_number": 1,
                    "bounding_box": {"left": 0.05, "top": 0.12, "width": 0.14, "height": 0.01},
                },
                {
                    "text": "Chemistry 2 B 0.500",
                    "normalized_text": "chemistry2b0500",
                    "page_number": 1,
                    "bounding_box": {"left": 0.30, "top": 0.12, "width": 0.14, "height": 0.01},
                },
                {
                    "text": "Chemistry 3 A- 0.750",
                    "normalized_text": "chemistry3a0750",
                    "page_number": 1,
                    "bounding_box": {"left": 0.55, "top": 0.12, "width": 0.14, "height": 0.01},
                },
            ],
        }


class SourceLineTextract(DummyTextract):
    def extract(self, content: bytes) -> str:
        return "Example High School\nEnglish Composition 1 A 0.500"

    def extract_with_layout(self, content: bytes) -> dict:
        return {
            "text": self.extract(content),
            "line_locations": [
                {
                    "text": "Example High School",
                    "normalized_text": "examplehighschool",
                    "page_number": 1,
                    "bounding_box": {"left": 0.1, "top": 0.1, "width": 0.3, "height": 0.05},
                },
                {
                    "text": "English Composition 1 A 0.500",
                    "normalized_text": "englishcomposition1a0500",
                    "page_number": 1,
                    "bounding_box": {"left": 0.2, "top": 0.2, "width": 0.4, "height": 0.05},
                },
            ],
        }


class SplitRowTextract(DummyTextract):
    def extract(self, content: bytes) -> str:
        return "Example High School\nFound Business & Marketing 1 A 0.250"

    def extract_with_layout(self, content: bytes) -> dict:
        return {
            "text": self.extract(content),
            "line_locations": [
                {
                    "text": "Found Business & Marketing 1",
                    "normalized_text": "foundbusinessmarketing1",
                    "page_number": 1,
                    "bounding_box": {"left": 0.05, "top": 0.20, "width": 0.10, "height": 0.01},
                },
                {
                    "text": "A",
                    "normalized_text": "a",
                    "page_number": 1,
                    "bounding_box": {"left": 0.18, "top": 0.20, "width": 0.01, "height": 0.01},
                },
                {
                    "text": "0.250",
                    "normalized_text": "0250",
                    "page_number": 1,
                    "bounding_box": {"left": 0.21, "top": 0.20, "width": 0.02, "height": 0.01},
                },
                {
                    "text": "Analytic Geometry",
                    "normalized_text": "analyticgeometry",
                    "page_number": 1,
                    "bounding_box": {"left": 0.29, "top": 0.20, "width": 0.06, "height": 0.01},
                },
            ],
        }


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
    assert result["metadata"]["overall_confidence"] >= 0.72
    assert result["courses"][0]["confidenceScore"] >= 0.8


def test_pipeline_fills_course_bounding_box_from_line_match():
    text = "Example State University\nStudent Name: Jane Smith\nStudent ID: 123456\nFall 2024\nENG101 English Composition 3 A\nCumulative GPA 3.76"
    local_extractor = DummyLocalExtractor(text=text)
    pipeline = TranscriptPipeline(local_extractor=local_extractor, textract_extractor=DummyTextract(), bedrock_mapper=DummyBedrock())

    result = pipeline.process("test.pdf", b"%PDF", "application/pdf", requested_document_type="college", use_bedrock=False)

    assert result["courses"][0]["pageNumber"] == 1
    assert result["courses"][0]["boundingBox"]["left"] == 10.0
    assert result["courses"][0]["boundingBox"]["width"] == 100.0


def test_pipeline_uses_textract_layout_when_local_pdf_geometry_is_merged():
    text = "\n".join(
        [
            "Example State University",
            "Student Name: Jane Smith",
            "Student ID: 123456",
            "Fall 2024",
            "ENG101 English Composition 3 A",
        ]
        + [f"Extra Line {idx}" for idx in range(30)]
    )
    local_extractor = MergedLayoutLocalExtractor(text=text)
    pipeline = TranscriptPipeline(local_extractor=local_extractor, textract_extractor=CleanLayoutTextract(), bedrock_mapper=DummyBedrock())

    result = pipeline.process("test.pdf", b"%PDF", "application/pdf", requested_document_type="college", use_bedrock=False)

    assert result["metadata"]["text_source"] == "heuristic"
    assert result["metadata"]["layout_source"] == "textract"
    assert result["courses"][0]["boundingBox"]["left"] == 3.0
    assert result["courses"][0]["boundingBox"]["width"] == 20.0


def test_pipeline_prefers_exact_source_line_match_for_bounding_box():
    local_extractor = MergedLayoutLocalExtractor(
        text="\n".join(["Example High School"] + [f"Extra Line {idx}" for idx in range(30)])
    )
    pipeline = TranscriptPipeline(
        local_extractor=local_extractor,
        textract_extractor=SourceLineTextract(),
        parser=SourceLineParser(),
        bedrock_mapper=DummyBedrock(),
    )

    result = pipeline.process("test.pdf", b"%PDF", "application/pdf", requested_document_type="high_school", use_bedrock=False)

    assert result["metadata"]["layout_source"] == "textract"
    assert result["courses"][0]["boundingBox"]["left"] == 0.2
    assert round(result["courses"][0]["boundingBox"]["width"], 6) == 0.4


def test_pipeline_reconstructs_row_bounding_box_from_split_textract_fragments():
    local_extractor = MergedLayoutLocalExtractor(
        text="\n".join(["Example High School"] + [f"Extra Line {idx}" for idx in range(30)])
    )
    pipeline = TranscriptPipeline(
        local_extractor=local_extractor,
        textract_extractor=SplitRowTextract(),
        parser=SplitRowParser(),
        bedrock_mapper=DummyBedrock(),
    )

    result = pipeline.process("test.pdf", b"%PDF", "application/pdf", requested_document_type="high_school", use_bedrock=False)

    assert result["metadata"]["layout_source"] == "textract"
    assert result["courses"][0]["boundingBox"]["left"] == 0.05
    assert result["courses"][0]["boundingBox"]["width"] == 0.18


def test_textract_layout_includes_synthetic_row_segments():
    base_lines = SplitRowTextract().extract_with_layout(b"%PDF")["line_locations"]
    from app.services.extractors import TextractExtractor

    synthetic_rows = TextractExtractor()._build_synthetic_textract_rows(base_lines)
    assert synthetic_rows
    merged = next(line for line in synthetic_rows if line["normalized_text"] == "foundbusinessmarketing1a0250")
    assert merged["bounding_box"]["left"] == 0.05
    assert round(merged["bounding_box"]["width"], 6) == 0.18


def test_pipeline_uses_term_header_to_disambiguate_repeated_titles():
    local_extractor = MergedLayoutLocalExtractor(
        text="\n".join(["Example High School"] + [f"Extra Line {idx}" for idx in range(30)])
    )
    pipeline = TranscriptPipeline(
        local_extractor=local_extractor,
        textract_extractor=RepeatedTitleTextract(),
        parser=RepeatedTitleParser(),
        bedrock_mapper=DummyBedrock(),
    )

    result = pipeline.process("test.pdf", b"%PDF", "application/pdf", requested_document_type="high_school", use_bedrock=False)

    assert result["metadata"]["layout_source"] == "textract"
    chemistry_rows = [course for course in result["courses"] if course["courseTitle"] == "Chemistry"]
    assert len(chemistry_rows) == 2
    assert chemistry_rows[0]["boundingBox"]["top"] == 0.12
    assert chemistry_rows[1]["boundingBox"]["top"] == 0.32


def test_pipeline_uses_header_column_band_for_parallel_term_blocks():
    local_extractor = MergedLayoutLocalExtractor(
        text="\n".join(["Example High School"] + [f"Extra Line {idx}" for idx in range(30)])
    )
    pipeline = TranscriptPipeline(
        local_extractor=local_extractor,
        textract_extractor=ParallelColumnsTextract(),
        parser=ParallelColumnsParser(),
        bedrock_mapper=DummyBedrock(),
    )

    result = pipeline.process("test.pdf", b"%PDF", "application/pdf", requested_document_type="high_school", use_bedrock=False)

    chemistry_rows = [course for course in result["courses"] if course["courseTitle"] == "Chemistry"]
    assert len(chemistry_rows) == 3
    assert chemistry_rows[0]["boundingBox"]["left"] == 0.05
    assert chemistry_rows[1]["boundingBox"]["left"] == 0.30
    assert chemistry_rows[2]["boundingBox"]["left"] == 0.55


def test_pipeline_skips_bedrock_when_heuristic_confidence_is_good():
    bedrock = DummyBedrock()
    pipeline = TranscriptPipeline(textract_extractor=DummyTextract(), bedrock_mapper=bedrock)
    content = b"Example State University\nStudent Name: Jane Smith\nStudent ID: 123456\nFall 2024\nENG101 English Composition 3 A\nCumulative GPA 3.76"

    result = pipeline.process("test.txt", content, "text/plain", requested_document_type="college", use_bedrock=True)

    assert result["metadata"]["bedrock_used"] is False
    assert result["metadata"]["ai_needed"] is False
    assert bedrock.calls == 0


def test_pipeline_falls_back_to_heuristic_parse_when_bedrock_returns_malformed_json():
    bedrock = MalformedBedrock()
    low_confidence_text = b"Example State University\nFall 2024\nENG101 3"
    pipeline = TranscriptPipeline(textract_extractor=DummyTextract(), bedrock_mapper=bedrock)

    result = pipeline.process("test.txt", low_confidence_text, "text/plain", requested_document_type="college", use_bedrock=True)

    assert result["metadata"]["bedrock_used"] is False
    assert result["metadata"]["ai_needed"] is True
    assert "Bedrock second pass returned malformed JSON; using heuristic parse." in result["metadata"]["warnings"]
    assert bedrock.calls == 1
    assert len(result["courses"]) == 1


def test_pipeline_preserves_heuristic_student_when_bedrock_returns_blank_student(monkeypatch):
    monkeypatch.setattr(settings, "use_bedrock", True)
    monkeypatch.setattr(settings, "heuristic_parse_min_confidence", 0.99)
    bedrock = BlankStudentBedrock()
    text = """
    Davis School District
    Bountiful High
    TURPIN, PATRICK JEFFREYTranscript For:
    Cumulative GPA: 3.740
    BOUNTIFUL HIGH SCHOOHonors English 10 A 25 BOUNTIFUL HIGH SCHOOAP World History A- .25
    """.strip()
    pipeline = TranscriptPipeline(
        local_extractor=DummyLocalExtractor(text),
        textract_extractor=DummyTextract(),
        bedrock_mapper=bedrock,
    )

    result = pipeline.process("turpin.pdf", b"%PDF", "application/pdf", requested_document_type="auto", use_bedrock=True)

    assert bedrock.calls == 1
    assert result["demographic"]["firstName"] == "PATRICK"
    assert result["demographic"]["middleName"] == "JEFFREY"
    assert result["demographic"]["lastName"] == "TURPIN"
    assert len(result["courses"]) == 2


def test_pipeline_uses_ocr_when_pdf_text_is_not_readable():
    local_extractor = DummyLocalExtractor(text="")
    bedrock = DummyBedrock()
    pipeline = TranscriptPipeline(local_extractor=local_extractor, textract_extractor=DummyTextract(), bedrock_mapper=bedrock)

    result = pipeline.process("scan.pdf", b"%PDF", "application/pdf", requested_document_type="auto", use_bedrock=True)

    assert result["metadata"]["ocr_needed"] is True
    assert result["metadata"]["ocr_used"] is True
    assert result["metadata"]["text_source"] == "textract"


def test_pipeline_falls_back_to_local_layout_when_textract_layout_fails():
    local_extractor = MergedLayoutLocalExtractor(
        text="Formatted XML Content\nHighSchoolTranscript\nStudent\nPerson\nAgencyAssignedID\n0002270247\nBirthDate\n2008-04-14\nFirstName\nAlyssa\nLastName\nMcCulley\nAcademicRecord\nAcademicSummary\nCreditHoursAttempted\n38.000\nCreditHoursEarned\n38.000\nGradePointAverage\n4.000\nAcademicSession\nSessionSchoolYear\n2025-2026\nSchool\nOrganizationName\nGrantsville High School\nCourse\nCourseCreditEarned\n1.000\nCourseSupplementalGrade\nSupplementalGradeSubSession\n1\nGrade\nA\nAgencyCourseID\n34010000176\nCourseTitle\nBaking/Pastry CLC**"
    )
    pipeline = TranscriptPipeline(local_extractor=local_extractor, textract_extractor=FailingTextract(), bedrock_mapper=DummyBedrock())

    result = pipeline.process("formatted.pdf", b"%PDF", "application/pdf", requested_document_type="auto", use_bedrock=False)

    assert result["metadata"]["text_source"] == "heuristic"
    assert result["metadata"]["ocr_used"] is False
    assert any("Textract layout fallback unavailable; using local layout instead." in warning for warning in result["metadata"]["warnings"])
    assert result["demographic"]["studentId"] == "0002270247"
    assert result["courses"][0]["courseTitle"] == "Baking/Pastry CLC**"


def test_pipeline_result_validates_when_optional_address_parts_are_missing():
    pipeline = TranscriptPipeline(textract_extractor=DummyTextract(), bedrock_mapper=DummyBedrock())
    content = b"Example State University\nStudent Name: Jane Smith\nStudent ID: 123456\nFall 2024\nENG101 English Composition 3 A\nCumulative GPA 3.76"

    result = pipeline.process("test.txt", content, "text/plain", requested_document_type="college", use_bedrock=False)
    parsed = ParseTranscriptResponse(**result)

    assert parsed.demographic.studentAddress == ""
    assert parsed.demographic.studentCity == ""
    assert parsed.demographic.studentState == ""
    assert parsed.demographic.studentPostalCode == ""


def test_pipeline_captures_learning_candidate_when_ai_path_is_needed(tmp_path):
    original_learning_enabled = settings.heuristic_learning_enabled
    original_learning_dir = settings.heuristic_learning_dir
    settings.heuristic_learning_enabled = True
    settings.heuristic_learning_dir = str(tmp_path)
    bedrock = DummyBedrock()
    pipeline = TranscriptPipeline(textract_extractor=DummyTextract(), bedrock_mapper=bedrock)

    try:
        result = pipeline.process("scan.pdf", b"%PDF", "application/pdf", requested_document_type="auto", use_bedrock=True)
    finally:
        settings.heuristic_learning_enabled = original_learning_enabled
        settings.heuristic_learning_dir = original_learning_dir

    assert result["metadata"]["learning_status"] == "candidate"
    assert result["metadata"]["learning_candidate_id"]
    assert result["metadata"]["learning_proposal_source"] == "ai"
    assert bedrock.proposal_calls == 1

    candidate_path = Path(result["metadata"]["learning_path"])
    assert candidate_path.exists()
    payload = json.loads(candidate_path.read_text(encoding="utf-8"))
    assert payload["proposal"]["family_id"] == "example_high_school_v1"
    assert payload["metrics"]["bedrock_used"] is True


def test_pipeline_marks_ai_needed_when_visible_course_rows_exceed_parsed_courses():
    class IncompletePhoenixParser:
        def detect_document_type(self, text: str, requested_document_type: str = "auto") -> str:
            return "college_transcript"

        def parse(self, text: str, document_type: str) -> dict:
            return {
                "document_type": "college_transcript",
                "student": {"name": "Andrayus J. Fluellen", "student_id": "9054839836", "date_of_birth": "10/12/1986", "address": {"street": None, "city": None, "state": None, "postal_code": None}},
                "institutions": [{"name": "University of Phoenix", "type": "college"}],
                "academic_summary": {"gpa": 2.17, "total_credits_attempted": 12.0, "total_credits_earned": 12.0, "class_rank": None},
                "terms": [
                    {
                        "term_name": "Spring 2015",
                        "courses": [
                            {"course_code": "GEN127", "course_title": "University Studies for Success", "credits": 3.0, "grade": "C+", "term": "Spring 2015", "confidence_score": 1.0, "confidence_reasons": []}
                        ],
                    }
                ],
                "parser_confidence": 1.0,
                "course_confidence_summary": {"average": 1.0, "minimum": 1.0, "count": 1, "low_confidence_count": 0},
            }

        def ensure_course_confidences(self, terms):
            return terms

        def summarize_course_confidence(self, terms):
            return {"average": 1.0, "minimum": 1.0, "count": 1, "low_confidence_count": 0}

    bedrock = DummyBedrock()
    phoenix_text = b"""UNIVERSITY OF PHOENIX\nMo/Year Course ID Course Title Grade Credits Credits Quality Rep\n05/2015 GEN/127 University Studies for Success C+ 3.00 3.00 6.99\n06/2015 ENG/147 University Writing Essentials C- 3.00 3.00 5.01\n08/2015 HUM/115 Critical Thinking in Everyday Life C+ 3.00 3.00 6.99\n09/2015 CJS/201 Introduction to Criminal Justice C+ 3.00 3.00 6.99\n12/2015 CJS/205 Composition for Communication in the Criminal Justice System W 0.00 0.00 0.00\n01/2016 IT/200 Digital Skills for the 21st Century W 0.00 0.00 0.00\nUOPX Cumulative: 2.17 12.00 12.00 25.98\nRecord of: ANDRAYUS J. FLUELLEN Student Number: 9054839836\nBirthdate: 10/12/1986"""
    pipeline = TranscriptPipeline(local_extractor=DummyLocalExtractor(phoenix_text.decode("utf-8")), textract_extractor=DummyTextract(), parser=IncompletePhoenixParser(), bedrock_mapper=bedrock)

    result = pipeline.process("phoenix.txt", phoenix_text, "text/plain", requested_document_type="college", use_bedrock=True)

    assert result["metadata"]["visible_course_rows_estimate"] == 6
    assert result["metadata"]["ai_needed"] is True
    assert bedrock.calls == 1
