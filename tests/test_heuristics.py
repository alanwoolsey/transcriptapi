from app.services.extractors import HeuristicJudge
from app.services.heuristics import TranscriptHeuristicParser


SAMPLE_COLLEGE_TEXT = """
Example State University
Student Name: Jane Smith
Student ID: 123456
Fall 2024
ENG101 English Composition 3 A
MATH120 College Algebra 3 B+
HIST110 US History 3 A-
Cumulative GPA 3.76
Credits Attempted 62
Credits Earned 59
""".strip()


def test_heuristic_assessment_accepts_good_text():
    judge = HeuristicJudge()
    assessment = judge.assess(SAMPLE_COLLEGE_TEXT)
    assert assessment.acceptable is True
    assert assessment.score >= 0.65


def test_parser_extracts_student_summary_and_courses():
    parser = TranscriptHeuristicParser()
    doc_type = parser.detect_document_type(SAMPLE_COLLEGE_TEXT)
    parsed = parser.parse(SAMPLE_COLLEGE_TEXT, doc_type)

    assert parsed["document_type"] == "college_transcript"
    assert parsed["student"]["name"] == "Jane Smith"
    assert parsed["student"]["student_id"] == "123456"
    assert parsed["academic_summary"]["gpa"] == 3.76
    assert parsed["academic_summary"]["total_credits_attempted"] == 62.0
    assert parsed["academic_summary"]["total_credits_earned"] == 59.0
    assert len(parsed["terms"]) == 1
    assert len(parsed["terms"][0]["courses"]) == 3


def test_parser_merges_split_institution_name_fragments():
    parser = TranscriptHeuristicParser()
    text = """
TR
ANSCRIPT OF
ACADEMIC RECORD
Issued To:
STUDENT
OR
EGON STATE UNIVERSITY
Fall 2024
ENG101 English Composition 3 A
""".strip()

    parsed = parser.parse(text, "college_transcript")

    assert parsed["institutions"][0]["name"] == "OREGON STATE UNIVERSITY"
