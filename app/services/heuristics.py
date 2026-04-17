import re
from collections import defaultdict
from typing import Any, Dict, List, Tuple

from app.models.domain_models import TranscriptCourse
from app.utils.text_utils import TERM_PATTERN, lines, looks_like_grade


class TranscriptHeuristicParser:
    STUDENT_NAME_PATTERNS = [
        re.compile(r"\bStudent\s+Name[:\-]\s*(.+)$", re.IGNORECASE),
        re.compile(r"\bName[:\-]\s*(.+)$", re.IGNORECASE),
    ]
    STUDENT_ID_PATTERNS = [
        re.compile(r"\bStudent\s+ID[:\-]\s*([A-Z0-9\-]+)\b", re.IGNORECASE),
        re.compile(r"\bID[:\-]\s*([A-Z0-9\-]+)\b", re.IGNORECASE),
    ]
    GPA_PATTERN = re.compile(r"\b(?:Cumulative\s+)?GPA[:\s]+([0-4]\.\d{1,3})\b", re.IGNORECASE)
    EARNED_PATTERN = re.compile(r"\b(?:Credits\s+Earned|Units\s+Earned)[:\s]+([0-9]+(?:\.[0-9]+)?)\b", re.IGNORECASE)
    ATTEMPTED_PATTERN = re.compile(r"\b(?:Credits\s+Attempted|Units\s+Attempted)[:\s]+([0-9]+(?:\.[0-9]+)?)\b", re.IGNORECASE)
    HS_HINTS = ["unweighted gpa", "weighted gpa", "class rank", "high school", "graduation date"]
    COLLEGE_HINTS = ["credits attempted", "credits earned", "term gpa", "semester", "university", "college"]
    INSTITUTION_KEYWORDS = ("university", "college", "school", "academy")

    def detect_document_type(self, text: str, requested_document_type: str = "auto") -> str:
        if requested_document_type == "high_school":
            return "high_school_transcript"
        if requested_document_type == "college":
            return "college_transcript"

        lowered = text.lower()
        hs_score = sum(1 for hint in self.HS_HINTS if hint in lowered)
        college_score = sum(1 for hint in self.COLLEGE_HINTS if hint in lowered)

        if hs_score > college_score:
            return "high_school_transcript"
        if college_score > hs_score:
            return "college_transcript"
        return "unknown"

    def parse(self, text: str, document_type: str) -> Dict[str, Any]:
        text_lines = lines(text)
        student = self._parse_student(text_lines)
        institutions = self._parse_institutions(text_lines, document_type)
        terms = self._parse_terms_and_courses(text_lines)
        summary = self._parse_summary(text)

        confidence = self._estimate_confidence(student, institutions, summary, terms)
        return {
            "document_type": document_type,
            "student": student,
            "institutions": institutions,
            "academic_summary": summary,
            "terms": terms,
            "parser_confidence": confidence,
        }

    def _parse_student(self, text_lines: List[str]) -> Dict[str, Any]:
        student = {"name": None, "student_id": None, "date_of_birth": None}
        for line in text_lines[:30]:
            for pattern in self.STUDENT_NAME_PATTERNS:
                match = pattern.search(line)
                if match and not student["name"]:
                    student["name"] = match.group(1).strip()
            for pattern in self.STUDENT_ID_PATTERNS:
                match = pattern.search(line)
                if match and not student["student_id"]:
                    student["student_id"] = match.group(1).strip()
            dob_match = re.search(r"\b(?:DOB|Date of Birth)[:\-]\s*([0-9/\-]{6,10})\b", line, re.IGNORECASE)
            if dob_match and not student["date_of_birth"]:
                student["date_of_birth"] = dob_match.group(1)
        return student

    def _parse_institutions(self, text_lines: List[str], document_type: str) -> List[Dict[str, Any]]:
        institutions: List[Dict[str, Any]] = []
        inst_type = "college" if document_type == "college_transcript" else "high_school" if document_type == "high_school_transcript" else "unknown"
        normalized_lines = [line.strip() for line in text_lines[:25] if line.strip()]
        for idx, line in enumerate(normalized_lines):
            candidate = self._merge_institution_line_fragments(normalized_lines, idx)
            if any(keyword in candidate.lower() for keyword in self.INSTITUTION_KEYWORDS):
                institutions.append({"name": candidate, "type": inst_type})
                break
        return institutions

    def _merge_institution_line_fragments(self, lines_in_scope: List[str], idx: int) -> str:
        candidate = lines_in_scope[idx]
        if idx > 0:
            prev_line = lines_in_scope[idx - 1]
            if self._looks_like_institution_prefix(prev_line):
                candidate = f"{prev_line}{candidate}" if self._should_join_without_space(prev_line, candidate) else f"{prev_line} {candidate}"
        return re.sub(r"\s+", " ", candidate).strip()

    def _looks_like_institution_prefix(self, line: str) -> bool:
        compact = line.strip()
        return bool(compact) and len(compact) <= 4 and compact.isupper() and compact.isalpha()

    def _should_join_without_space(self, prefix: str, remainder: str) -> bool:
        if not prefix or not remainder:
            return False
        if " " in prefix:
            return False
        if not (prefix.isalpha() and remainder[:1].isalpha() and remainder[:1].isupper()):
            return False
        lowered = remainder.lower()
        return any(keyword in lowered for keyword in self.INSTITUTION_KEYWORDS)

    def _parse_summary(self, text: str) -> Dict[str, Any]:
        gpa = self._find_float(self.GPA_PATTERN, text)
        earned = self._find_float(self.EARNED_PATTERN, text)
        attempted = self._find_float(self.ATTEMPTED_PATTERN, text)
        rank_match = re.search(r"\bClass\s+Rank[:\s]+([A-Za-z0-9#/ ]+)\b", text, re.IGNORECASE)
        return {
            "gpa": gpa,
            "total_credits_attempted": attempted,
            "total_credits_earned": earned,
            "class_rank": rank_match.group(1).strip() if rank_match else None,
        }

    def _find_float(self, pattern: re.Pattern[str], text: str) -> float | None:
        match = pattern.search(text)
        return float(match.group(1)) if match else None

    def _parse_terms_and_courses(self, text_lines: List[str]) -> List[Dict[str, Any]]:
        current_term = "Unassigned"
        bucket: dict[str, list[TranscriptCourse]] = defaultdict(list)

        for line in text_lines:
            if TERM_PATTERN.search(line):
                current_term = line.strip()
                continue

            parsed = self._parse_course_line(line)
            if parsed:
                parsed.term = current_term
                bucket[current_term].append(parsed)

        terms: List[Dict[str, Any]] = []
        for term_name, courses in bucket.items():
            if courses:
                terms.append(
                    {
                        "term_name": term_name,
                        "courses": [
                            {
                                "course_code": c.course_code,
                                "course_title": c.course_title,
                                "credits": c.credits,
                                "grade": c.grade,
                                "term": c.term,
                            }
                            for c in courses
                        ],
                    }
                )
        return terms

    def _parse_course_line(self, line: str) -> TranscriptCourse | None:
        compact = re.sub(r"\s+", " ", line).strip()
        if len(compact) < 8:
            return None

        tokens = compact.split(" ")
        grade = tokens[-1] if tokens and looks_like_grade(tokens[-1]) else None
        credits = None
        credits_idx = None
        if len(tokens) >= 2:
            for idx in range(len(tokens) - 1, -1, -1):
                token = tokens[idx]
                if re.fullmatch(r"\d+(?:\.\d+)?", token):
                    credits = float(token)
                    credits_idx = idx
                    break

        code_match = re.match(r"^([A-Z]{2,6}[- ]?\d{2,4}[A-Z]?)\b", compact)
        if not code_match:
            return None

        course_code = code_match.group(1).replace(" ", "")
        remainder = compact[code_match.end() :].strip()

        if grade and compact.endswith(grade):
            remainder = remainder[: -len(grade)].strip()
        if credits is not None and credits_idx is not None:
            tokenized_remainder = remainder.split()
            if tokenized_remainder:
                credits_token = f"{credits:g}"
                if credits_token in tokenized_remainder:
                    tokenized_remainder.remove(credits_token)
                    remainder = " ".join(tokenized_remainder)

        title = remainder.strip(" -") or None
        return TranscriptCourse(course_code=course_code, course_title=title, credits=credits, grade=grade)

    def _estimate_confidence(
        self,
        student: Dict[str, Any],
        institutions: List[Dict[str, Any]],
        summary: Dict[str, Any],
        terms: List[Dict[str, Any]],
    ) -> float:
        score = 0.0
        if student.get("name"):
            score += 0.20
        if student.get("student_id"):
            score += 0.10
        if institutions:
            score += 0.15
        if summary.get("gpa") is not None:
            score += 0.15
        if summary.get("total_credits_attempted") is not None or summary.get("total_credits_earned") is not None:
            score += 0.10
        course_count = sum(len(term.get("courses", [])) for term in terms)
        if course_count >= 3:
            score += 0.30
        elif course_count > 0:
            score += 0.15
        return round(min(score, 1.0), 4)
