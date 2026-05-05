import re
from collections import defaultdict
from typing import Any, Dict, List, Tuple

from app.models.domain_models import TranscriptCourse
from app.utils.text_utils import TERM_PATTERN, lines, looks_like_grade


class TranscriptHeuristicParser:
    GRADE_TOKEN_PATTERN = r"A\+?|A-|AB|B\+?|B-|BC\*?|C\+?|C-|D\+?|D-|F|P|NP|S|U|W|I|IP|CR|NC|TR|PR|NR|T"
    COURSE_CODE_PATTERN = r"(?:[A-Z]{2,6}(?:\s+[A-Z]{2,6})?\s+\d{2,4}[A-Z]?|[A-Z]{2,6}[- ]?\d{2,4}[A-Z]?)"
    COURSE_LINE_PATTERN = re.compile(
        r"^"
        r"(?P<course_code>(?:[A-Z]{2,6}(?:\s+[A-Z]{2,6})?\s+\d{2,4}[A-Z]?|[A-Z]{2,6}[- ]?\d{2,4}[A-Z]?))\s+"
        r"(?P<course_title>.+?)\s+"
        r"(?P<credits>\d+(?:\.\d+)?)\s+"
        rf"(?P<grade>{GRADE_TOKEN_PATTERN})(?=\s|$)",
        re.IGNORECASE,
    )
    COURSE_LINE_PATTERN_GRADE_THEN_CREDITS = re.compile(
        r"^"
        r"(?P<course_code>(?:[A-Z]{2,6}(?:\s+[A-Z]{2,6})?\s+\d{2,4}[A-Z]?|[A-Z]{2,6}[- ]?\d{2,4}[A-Z]?))\s+"
        r"(?P<course_title>.+?)\s+"
        rf"(?P<grade>{GRADE_TOKEN_PATTERN})(?=\s)\s+"
        r"(?P<credits>\d+(?:\.\d+)?)",
        re.IGNORECASE,
    )
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
    HS_HINTS = [
        "unweighted gpa",
        "weighted gpa",
        "cum unwt gpa",
        "cum wt gpa",
        "class rank",
        "rank:",
        "high school transcript",
        "high school",
        "graduation date",
        "student number",
        "state id",
    ]
    COLLEGE_HINTS = ["credits attempted", "credits earned", "term gpa", "semester", "university", "bachelor of", "degrees awarded"]
    INSTITUTION_KEYWORDS = ("university", "college", "school", "academy")

    def detect_document_type(self, text: str, requested_document_type: str = "auto") -> str:
        if requested_document_type == "high_school":
            return "high_school_transcript"
        if requested_document_type == "college":
            return "college_transcript"

        lowered = text.lower()
        if "milwaukee area technical college" in lowered and "transcript" in lowered:
            return "college_transcript"
        hs_score = sum(1 for hint in self.HS_HINTS if hint in lowered)
        college_score = sum(1 for hint in self.COLLEGE_HINTS if hint in lowered)

        if hs_score > college_score:
            return "high_school_transcript"
        if college_score > hs_score:
            return "college_transcript"
        return "unknown"

    def parse(self, text: str, document_type: str) -> Dict[str, Any]:
        if self._looks_like_formatted_xml_transcript(text):
            return self._parse_formatted_xml_transcript(text, document_type)
        if self._looks_like_analysis_report(text):
            return self._parse_analysis_report(text, document_type)
        if self._looks_like_milwaukee_area_technical_college_transcript(text):
            return self._parse_milwaukee_area_technical_college_transcript(text, document_type)
        if self._looks_like_madison_college_transcript(text):
            return self._parse_madison_college_transcript(text, document_type)
        if self._looks_like_phoenix_transcript(text):
            return self._parse_phoenix_transcript(text, document_type)
        if self._looks_like_utah_export(text):
            return self._parse_utah_export(text, document_type)
        if self._looks_like_brandon_valley_transcript(text):
            return self._parse_brandon_valley_transcript(text, document_type)
        if self._looks_like_logan_district_transcript(text):
            return self._parse_logan_district_transcript(text, document_type)
        if self._looks_like_parchment_high_school_transcript(text):
            return self._parse_parchment_high_school_transcript(text, document_type)
        if self._looks_like_student_achievement_summary_transcript(text):
            return self._parse_student_achievement_summary_transcript(text, document_type)
        if self._looks_like_school_report_transcript(text):
            return self._parse_school_report_transcript(text, document_type)

        text_lines = lines(text)
        student = self._parse_student(text_lines)
        institutions = self._parse_institutions(text_lines, document_type)
        terms = self._parse_terms_and_courses(text_lines)
        terms = self.ensure_course_confidences(terms)
        summary = self._parse_summary(text)

        course_summary = self.summarize_course_confidence(terms)
        confidence = self._estimate_confidence(student, institutions, summary, terms, course_summary)
        return {
            "document_type": document_type,
            "student": student,
            "institutions": institutions,
            "academic_summary": summary,
            "terms": terms,
            "parser_confidence": confidence,
            "course_confidence_summary": course_summary,
        }

    def _looks_like_analysis_report(self, text: str) -> bool:
        lowered = text.lower()
        return lowered.startswith("official transcript analysis report") and "freedom quality metrics system" in lowered

    def _looks_like_utah_export(self, text: str) -> bool:
        lowered = re.sub(r"\s+", " ", text.lower())
        return "academic session" in lowered and "course no title session grade credits" in lowered and ("canyons" in lowered or "corner canyon high" in lowered)

    def _looks_like_school_report_transcript(self, text: str) -> bool:
        lowered = text.lower()
        return lowered.startswith("ricks, carter") or ("school report" in lowered and "grade 9 -" in lowered and "t1 t2 t3 t4" in lowered)

    def _looks_like_student_achievement_summary_transcript(self, text: str) -> bool:
        lowered = re.sub(r"\s+", " ", text.lower())
        return (
            "student achievement summary" in lowered
            and "student name" in lowered
            and "course title s1 s2 credits" in lowered
            and ("9th grade 10th grade" in lowered or "11th grade 12th grade" in lowered)
        )

    def _looks_like_brandon_valley_transcript(self, text: str) -> bool:
        lowered = re.sub(r"\s+", " ", text.lower())
        return "brandon valley high school" in lowered and "grade 9 grade 10" in lowered and "cumulative gpa" in lowered

    def _looks_like_parchment_high_school_transcript(self, text: str) -> bool:
        lowered = re.sub(r"\s+", " ", text.lower())
        return lowered.startswith("official transcript") and "parchment student id:" in lowered and "high school" in lowered

    def _looks_like_logan_district_transcript(self, text: str) -> bool:
        lowered = re.sub(r"\s+", " ", text.lower())
        return "academic session" in lowered and "institution academic yearacademic level" in lowered and "course no title session grade credits" in lowered

    def _looks_like_phoenix_transcript(self, text: str) -> bool:
        lowered = re.sub(r"\s+", " ", text.lower())
        return "university of phoenix" in lowered and "mo/year course id course title grade" in lowered

    def _looks_like_milwaukee_area_technical_college_transcript(self, text: str) -> bool:
        lowered = re.sub(r"\s+", " ", text.lower())
        return "milwaukee area technical college" in lowered and "id number:" in lowered and "birth date:" in lowered

    def _looks_like_madison_college_transcript(self, text: str) -> bool:
        lowered = re.sub(r"\s+", " ", text.lower())
        if "madison college" in lowered and "beginning of student record" in lowered and "course #" in lowered and "course title" in lowered:
            return True
        structural_markers = (
            "beginning of student record" in lowered
            and "course #" in lowered
            and "course title" in lowered
            and "term gpa" in lowered
            and "cum gpa" in lowered
        )
        madison_specific_markers = (
            "transfer credits" in lowered
            or "other credits" in lowered
            or "requestor:" in lowered
            or "course topic:" in lowered
        )
        return structural_markers and madison_specific_markers

    def _parse_analysis_report(self, text: str, document_type: str) -> Dict[str, Any]:
        text_lines = lines(text)
        student = {
            "name": self._extract_labeled_value(text, "First Name", "Middle Name", "Last Name"),
            "student_id": self._extract_labeled_value(text, "Student Id"),
            "date_of_birth": self._extract_labeled_value(text, "Date Of Birth", "Weighted Class Rank"),
            "address": {"street": None, "city": None, "state": None, "postal_code": None},
        }
        institution_name = self._extract_labeled_value(text, "Institution Name", "Date Of Birth")
        summary = {
            "gpa": self._safe_float(self._extract_labeled_value(text, "Gpa", "Institution Address")),
            "total_credits_attempted": self._safe_float(self._extract_labeled_value(text, "Total Credits Attempted", "Total Credits Received")),
            "total_credits_earned": self._safe_float(self._extract_labeled_value(text, "Total Credits Received", "Total Grade Points")),
            "class_rank": None,
        }
        terms = self._parse_analysis_report_courses(text_lines)
        terms = self.ensure_course_confidences(terms)
        course_summary = self.summarize_course_confidence(terms)
        confidence = self._estimate_confidence(student, [{"name": institution_name, "type": "college"}] if institution_name else [], summary, terms, course_summary)
        return {
            "document_type": "college_transcript",
            "student": student,
            "institutions": [{"name": institution_name, "type": "college"}] if institution_name else [],
            "academic_summary": summary,
            "terms": terms,
            "parser_confidence": max(confidence, 0.82),
            "course_confidence_summary": course_summary,
        }

    def _parse_phoenix_transcript(self, text: str, document_type: str) -> Dict[str, Any]:
        normalized = re.sub(r"\s+", " ", text)
        student = {
            "name": self._extract_regex_group(normalized, r"Record of:\s*([A-Z][A-Z.\s]+)Student Number", title=True),
            "student_id": self._extract_regex_group(normalized, r"Student Number:\s*([0-9]+)"),
            "date_of_birth": self._extract_regex_group(normalized, r"Birthdate:\s*([0-9/]+)"),
            "address": {"street": None, "city": None, "state": None, "postal_code": None},
        }
        summary_match = re.search(r"UOPX Cumulative:\s*([0-9.]+)\s+([0-9.]+)\s+([0-9.]+)\s+([0-9.]+)", normalized)
        summary = {
            "gpa": float(summary_match.group(1)) if summary_match else None,
            "total_credits_attempted": float(summary_match.group(2)) if summary_match else None,
            "total_credits_earned": float(summary_match.group(3)) if summary_match else None,
            "class_rank": None,
        }
        institution_name = "University of Phoenix"
        courses_by_term: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        course_pattern = re.compile(
            r"(?P<term_month>\d{2})/(?P<term_year>\d{4})\s+"
            r"(?P<course_id>[A-Z]{2,5}/\d{3})\s+"
            r"(?P<title>.+?)"
            r"(?P<grade>A\+?|A-|B\+?|B-|C\+?|C-|D\+?|D-|F|W|P|NP|S|U|IP|CR|NC|TR|PR)\s+"
            r"(?P<attempted>\d+(?:\.\d+)?)\s+"
            r"(?P<earned>\d+(?:\.\d+)?)\s+"
            r"(?P<points>\d+(?:\.\d+)?)"
            r"(?=\s*(?:\d{2}/\d{4}\s+[A-Z]{2,5}/\d{3}\s|GPA Credits|UOPX Cumulative|Total Cumulative Credits|$))",
            re.IGNORECASE,
        )
        for match in course_pattern.finditer(normalized):
            month = int(match.group("term_month"))
            year = match.group("term_year")
            season = "Spring" if month <= 5 else "Summer" if month <= 8 else "Fall"
            term_name = f"{season} {year}"
            course = {
                "course_code": match.group("course_id").replace("/", ""),
                "course_title": match.group("title").strip(),
                "credits": float(match.group("earned")),
                "grade": match.group("grade").upper(),
                "term": term_name,
            }
            self.ensure_course_confidences([{"term_name": term_name, "courses": [course]}])
            courses_by_term[term_name].append(course)
        terms = [{"term_name": term_name, "courses": courses} for term_name, courses in courses_by_term.items()]
        course_summary = self.summarize_course_confidence(terms)
        confidence = self._estimate_confidence(student, [{"name": institution_name, "type": "college"}], summary, terms, course_summary)
        return {
            "document_type": "college_transcript",
            "student": student,
            "institutions": [{"name": institution_name, "type": "college"}],
            "academic_summary": summary,
            "terms": terms,
            "parser_confidence": max(confidence, 0.82),
            "course_confidence_summary": course_summary,
        }

    def _parse_milwaukee_area_technical_college_transcript(self, text: str, document_type: str) -> Dict[str, Any]:
        normalized = re.sub(r"\s+", " ", text)
        student = {
            "name": self._extract_regex_group(
                normalized,
                r"TRANSCRIPT\s+(?:[0-9A-Za-z.]+\s+)?([A-Z][A-Za-z'.-]+(?:\s+[A-Z][A-Za-z'.-]+)+)\s+ID Number",
                title=True,
            ),
            "student_id": self._extract_regex_group(normalized, r"ID Number:\s*([0-9]+)"),
            "date_of_birth": self._extract_regex_group(normalized, r"Birth Date:\s*([0-9/]+)"),
            "address": {"street": None, "city": None, "state": None, "postal_code": None},
        }
        summary_match = re.search(
            r"TOTALS:\s*CRED ATT\s*(?P<attempted>\d+(?:\.\d+)?)\s+CRED\.?\s*CPT\s*(?P<earned>\d+(?:\.\d+)?)\s+GRADE\.?PTS\s*[-=]?\s*(?P<points>\d+(?:\.\d+)?)\s+GPA\s*(?P<gpa>\d+(?:\.\d+)?)",
            normalized,
            re.IGNORECASE,
        )
        summary = {
            "gpa": float(summary_match.group("gpa")) if summary_match else None,
            "total_credits_attempted": float(summary_match.group("attempted")) if summary_match else None,
            "total_credits_earned": float(summary_match.group("earned")) if summary_match else None,
            "class_rank": None,
        }
        institution_name = "MILWAUKEE AREA TECHNICAL COLLEGE"
        terms = self._parse_milwaukee_area_technical_college_terms(lines(text))
        terms = self.ensure_course_confidences(terms)
        course_summary = self.summarize_course_confidence(terms)
        confidence = self._estimate_confidence(student, [{"name": institution_name, "type": "college"}], summary, terms, course_summary)
        return {
            "document_type": "college_transcript",
            "student": student,
            "institutions": [{"name": institution_name, "type": "college"}],
            "academic_summary": summary,
            "terms": terms,
            "parser_confidence": max(confidence, 0.84 if terms else 0.68),
            "course_confidence_summary": course_summary,
        }

    def _parse_madison_college_transcript(self, text: str, document_type: str) -> Dict[str, Any]:
        text_lines = lines(text)
        student = {
            "name": self._extract_regex_group(text, r"Name:\s*([A-Za-z][A-Za-z'., -]+)", title=True) or self._title_case_line_after(text_lines, "Name:"),
            "student_id": self._extract_regex_group(text, r"ID:\s*([0-9]+)") or self._line_after(text_lines, "ID:"),
            "date_of_birth": None,
            "address": {"street": None, "city": None, "state": None, "postal_code": None},
        }
        institution_name = "Madison College"
        summary = self._parse_madison_college_summary(text)
        terms = self._parse_madison_college_terms(text_lines)
        terms = self.ensure_course_confidences(terms)
        course_summary = self.summarize_course_confidence(terms)
        confidence = self._estimate_confidence(student, [{"name": institution_name, "type": "college"}], summary, terms, course_summary)
        return {
            "document_type": "college_transcript",
            "student": student,
            "institutions": [{"name": institution_name, "type": "college"}],
            "academic_summary": summary,
            "terms": terms,
            "parser_confidence": max(confidence, 0.84 if terms else 0.65),
            "course_confidence_summary": course_summary,
        }

    def _parse_madison_college_summary(self, text: str) -> Dict[str, Any]:
        main_record = re.split(r"Transfer Credits", text, maxsplit=1, flags=re.IGNORECASE)[0]
        gpa_matches = list(re.finditer(r"Cum GPA\s+([0-9]+\.[0-9]+)", main_record, re.IGNORECASE))
        totals_matches = list(
            re.finditer(
                r"Cum Totals\s+([0-9]+(?:\.[0-9]+)?)\s+([0-9]+(?:\.[0-9]+)?)\s+([0-9]+(?:\.[0-9]+)?)",
                main_record,
                re.IGNORECASE,
            )
        )
        gpa = float(gpa_matches[-1].group(1)) if gpa_matches else None
        attempted = float(totals_matches[-1].group(1)) if totals_matches else None
        earned = float(totals_matches[-1].group(2)) if totals_matches else None
        return {
            "gpa": gpa,
            "total_credits_attempted": attempted,
            "total_credits_earned": earned,
            "class_rank": None,
        }

    def _parse_madison_college_terms(self, text_lines: List[str]) -> List[Dict[str, Any]]:
        terms: List[Dict[str, Any]] = []
        idx = 0
        current_term: str | None = None
        current_courses: List[Dict[str, Any]] = []
        current_section = "record"
        while idx < len(text_lines):
            line = text_lines[idx].strip()
            if not line:
                idx += 1
                continue

            if re.fullmatch(r"(Spring|Summer|Fall|Winter)\s+(19|20)\d{2}", line, re.IGNORECASE):
                if current_term and current_courses:
                    terms.append({"term_name": current_term, "courses": current_courses})
                suffix = " Transfer" if current_section == "transfer" else ""
                current_term = f"{line.title()}{suffix}"
                current_courses = []
                idx += 1
                continue

            lowered = line.lower()
            if lowered == "transfer credits":
                if current_term and current_courses:
                    terms.append({"term_name": current_term, "courses": current_courses})
                current_term = None
                current_courses = []
                current_section = "transfer"
                idx += 1
                continue
            if lowered == "other credits":
                if current_term and current_courses:
                    terms.append({"term_name": current_term, "courses": current_courses})
                current_term = "Other Credits"
                current_courses = []
                current_section = "other"
                idx += 1
                continue

            if current_term is not None:
                row_course = self._parse_madison_college_course_row(line, current_term)
                if row_course:
                    current_courses.append(row_course)
                    idx += 1
                    continue

            if self._is_madison_college_subject_line(text_lines, idx):
                if current_term is None:
                    current_term = "Unassigned"
                course, idx = self._consume_madison_college_course(text_lines, idx, current_term)
                if course:
                    current_courses.append(course)
                continue

            idx += 1

        if current_term and current_courses:
            terms.append({"term_name": current_term, "courses": current_courses})
        return terms

    def _is_madison_college_subject_line(self, text_lines: List[str], idx: int) -> bool:
        line = text_lines[idx].strip()
        if not re.fullmatch(r"[A-Z]{3,12}", line):
            return False
        if idx + 1 >= len(text_lines) or not re.fullmatch(r"\d{8}", text_lines[idx + 1].strip()):
            return False
        lowered = line.lower()
        if lowered in {"subject", "course", "grade", "earned"}:
            return False
        return True

    def _parse_madison_college_course_row(self, line: str, term_name: str) -> Dict[str, Any] | None:
        compact = re.sub(r"\s+", " ", line).strip()
        if not compact or self._should_skip_madison_college_line(compact):
            return None
        match = re.match(
            rf"^(?P<subject>[A-Z]{{3,12}})\s+"
            rf"(?P<number>\d{{8}})\s+"
            rf"(?P<title>.+?)\s+"
            rf"(?P<attempted>\d+\.\d+)"
            rf"(?:\s+(?P<earned>\d+\.\d+))?"
            rf"\s+(?P<grade>{self.GRADE_TOKEN_PATTERN})"
            rf"(?:\s+(?P<points>\d+\.\d+))?$",
            compact,
            re.IGNORECASE,
        )
        if not match:
            return None

        attempted = float(match.group("attempted"))
        earned = float(match.group("earned")) if match.group("earned") else attempted
        grade = match.group("grade").upper()
        points = float(match.group("points")) if match.group("points") else None
        title = match.group("title").strip()
        confidence_score, confidence_reasons = self._estimate_course_confidence(
            course_code=f"{match.group('subject').upper()}{match.group('number')}",
            course_title=title,
            credits=earned,
            grade=grade,
            term=term_name,
        )
        course: Dict[str, Any] = {
            "course_code": f"{match.group('subject').upper()}{match.group('number')}",
            "course_title": title,
            "credits": earned,
            "grade": grade,
            "term": term_name,
            "confidence_score": confidence_score,
            "confidence_reasons": confidence_reasons,
            "source_line": compact,
            "credits_attempted": attempted,
        }
        if points is not None:
            course["grade_points"] = points
        return course

    def _should_skip_madison_college_line(self, line: str) -> bool:
        lowered = line.lower()
        if lowered in {
            "subject course # course title attempted earned grade",
            "subject course # course title attempted earned grade points",
            "course description attempted earned grade points",
            "attempted earned points",
            "attempted earned",
            "gpa",
        }:
            return True
        prefixes = (
            "term gpa",
            "cum gpa",
            "term totals",
            "cum totals",
            "course trans gpa",
            "transfer totals",
            "course topic:",
            "repeated:",
            "request reason:",
            "requestor:",
            "applied toward ",
            "transfer credit from ",
            "advanced cna licensure",
            "transferred to term ",
            "end of student record",
            "beginning of student record",
            "madison college unofficial",
            "name:",
            "id:",
        )
        return lowered.startswith(prefixes)

    def _consume_madison_college_course(self, text_lines: List[str], start_idx: int, term_name: str) -> Tuple[Dict[str, Any] | None, int]:
        subject = text_lines[start_idx].strip().upper()
        course_number = text_lines[start_idx + 1].strip()
        idx = start_idx + 2

        title_parts: List[str] = []
        while idx < len(text_lines):
            candidate = text_lines[idx].strip()
            if re.fullmatch(r"\d+(?:\.\d+)?", candidate):
                break
            if self._is_madison_college_subject_line(text_lines, idx) or re.fullmatch(r"(Spring|Summer|Fall|Winter)\s+(19|20)\d{2}", candidate, re.IGNORECASE):
                return None, idx
            if candidate.lower() in {
                "term totals",
                "cum totals",
                "term gpa",
                "cum gpa",
                "transfer credits",
                "other credits",
                "page 2",
            }:
                return None, idx
            title_parts.append(candidate)
            idx += 1

        if idx >= len(text_lines) or not re.fullmatch(r"\d+(?:\.\d+)?", text_lines[idx].strip()):
            return None, max(idx, start_idx + 2)

        numeric_tokens: List[str] = []
        while idx < len(text_lines) and re.fullmatch(r"\d+(?:\.\d+)?", text_lines[idx].strip()):
            numeric_tokens.append(text_lines[idx].strip())
            idx += 1

        grade = text_lines[idx].strip().upper() if idx < len(text_lines) and looks_like_grade(text_lines[idx].strip()) else None
        if grade:
            idx += 1

        points = None
        if idx < len(text_lines) and re.fullmatch(r"\d+(?:\.\d+)?", text_lines[idx].strip()):
            points = float(text_lines[idx].strip())
            idx += 1

        while idx < len(text_lines):
            candidate = text_lines[idx].strip()
            if candidate.lower() == "course topic:":
                idx += 2
                continue
            break

        title = " ".join(part for part in title_parts if part).strip()
        attempted = float(numeric_tokens[0]) if numeric_tokens else None
        earned = float(numeric_tokens[1]) if len(numeric_tokens) > 1 else attempted
        if not title or grade is None:
            return None, idx

        confidence_score, confidence_reasons = self._estimate_course_confidence(
            course_code=f"{subject}{course_number}",
            course_title=title,
            credits=earned,
            grade=grade,
            term=term_name,
        )
        course: Dict[str, Any] = {
            "course_code": f"{subject}{course_number}",
            "course_title": title,
            "credits": earned,
            "grade": grade,
            "term": term_name,
            "confidence_score": confidence_score,
            "confidence_reasons": confidence_reasons,
            "source_line": f"{subject} {course_number} {title} {' '.join(numeric_tokens)} {grade}".strip(),
        }
        if attempted is not None:
            course["credits_attempted"] = attempted
        if points is not None:
            course["grade_points"] = points
        return course, idx

    def _parse_milwaukee_area_technical_college_terms(self, text_lines: List[str]) -> List[Dict[str, Any]]:
        terms: List[Dict[str, Any]] = []
        pending_lines: List[str] = []

        for raw_line in text_lines:
            line = raw_line.strip()
            if not line or self._is_milwaukee_noise_line(line):
                continue
            term_match = re.fullmatch(r"Term\s+([A-Z]{2}\d{4})", line, re.IGNORECASE)
            if term_match:
                term_name = term_match.group(1).upper()
                courses = self._parse_milwaukee_area_technical_college_course_block(pending_lines, term_name)
                if courses:
                    terms.append({"term_name": term_name, "courses": courses})
                pending_lines = []
                continue
            pending_lines.append(line)

        return terms

    def _parse_milwaukee_area_technical_college_course_block(self, block_lines: List[str], term_name: str) -> List[Dict[str, Any]]:
        cleaned_lines = [line for line in block_lines if not self._is_milwaukee_noise_line(line)]
        while cleaned_lines and not (
            self._looks_like_milwaukee_course_code_line(cleaned_lines[0])
            or self._looks_like_milwaukee_title_first_start(cleaned_lines, 0)
        ):
            cleaned_lines.pop(0)
        if not cleaned_lines:
            return []
        courses: List[Dict[str, Any]] = []
        idx = 0
        while idx < len(cleaned_lines):
            chunk, next_idx = self._consume_milwaukee_course_chunk(cleaned_lines, idx)
            if not chunk:
                idx += 1
                continue
            idx = max(next_idx, idx + 1)
            parsed = self._parse_milwaukee_course_chunk(chunk, term_name)
            if not parsed:
                continue
            course_title = parsed["course_title"]
            if not course_title or self._is_milwaukee_noise_line(course_title):
                continue
            confidence_score, confidence_reasons = self._estimate_course_confidence(
                course_code=parsed["course_code"],
                course_title=course_title,
                credits=parsed["credits"],
                grade=parsed["grade"],
                term=term_name,
            )
            courses.append(
                {
                    "course_code": parsed["course_code"],
                    "course_title": course_title,
                    "credits": parsed["credits"],
                    "grade": parsed["grade"],
                    "term": term_name,
                    "confidence_score": confidence_score,
                    "confidence_reasons": confidence_reasons,
                }
            )
        return courses

    def _consume_milwaukee_course_chunk(self, lines_in_block: List[str], start_idx: int) -> Tuple[List[str], int]:
        line = lines_in_block[start_idx].strip()
        if self._looks_like_milwaukee_course_code_line(line):
            chunk = [line]
            idx = start_idx + 1
            if re.fullmatch(r"[A-Z]{4,8}", line, re.IGNORECASE) and idx < len(lines_in_block) and re.fullmatch(r"\d{3}", lines_in_block[idx].strip()):
                chunk.append(lines_in_block[idx].strip())
                idx += 1
            while idx < len(lines_in_block):
                candidate = lines_in_block[idx].strip()
                if self._is_milwaukee_noise_line(candidate):
                    idx += 1
                    continue
                chunk.append(candidate)
                idx += 1
                if self._looks_like_milwaukee_date_line(candidate):
                    break
            if idx < len(lines_in_block) and not any(re.search(r"[A-Z]{4,8}\s+\d{3}", item, re.IGNORECASE) or re.fullmatch(r"[A-Z]{4,8}", item, re.IGNORECASE) for item in chunk):
                trailing = lines_in_block[idx].strip()
                if self._looks_like_milwaukee_course_code_line(trailing):
                    chunk.append(trailing)
                    idx += 1
            return chunk, idx

        if self._looks_like_milwaukee_title_first_start(lines_in_block, start_idx):
            chunk = [line]
            idx = start_idx + 1
            while idx < len(lines_in_block):
                candidate = lines_in_block[idx].strip()
                if self._is_milwaukee_noise_line(candidate):
                    idx += 1
                    continue
                chunk.append(candidate)
                idx += 1
                if self._looks_like_milwaukee_date_line(candidate):
                    if idx < len(lines_in_block) and self._looks_like_milwaukee_course_code_line(lines_in_block[idx].strip()):
                        chunk.append(lines_in_block[idx].strip())
                        idx += 1
                    break
            return chunk, idx

        return [], start_idx + 1

    def _parse_milwaukee_course_chunk(self, chunk_lines: List[str], term_name: str) -> Dict[str, Any] | None:
        chunk_text = "\n".join(chunk_lines)
        patterns = [
            re.compile(
                r"^(?P<code>[A-Z]{4,8})\s+(?P<num>\d{3})\s+(?P<title>.+?)\s+(?P<grade>A\+?|A-|B\+?|B-|C\+?|C-|D\+?|D-|F|P|NP|S|U|W)\s+(?P<attempted>\d+\.\d+)\s+(?P<earned>\d+\.\d+)\s+(?P<points>\d+\.\d+)\s+(?P<dates>\d{2}/\d{2}/\d{2}(?:-\d{2}/\d{2}/\d{2})?)$",
                re.IGNORECASE | re.DOTALL,
            ),
            re.compile(
                r"^(?P<code>[A-Z]{4,8})\s+(?P<title>.+?)\s+(?P<grade>A\+?|A-|B\+?|B-|C\+?|C-|D\+?|D-|F|P|NP|S|U|W)\s+(?P<attempted>\d+\.\d+)\s+(?P<earned>\d+\.\d+)\s+(?P<points>\d+\.\d+)\s+(?P<dates>\d{2}/\d{2}/\d{2}(?:-\d{2}/\d{2}/\d{2})?)\s+(?P<num>\d{3})$",
                re.IGNORECASE | re.DOTALL,
            ),
            re.compile(
                r"^(?P<title>.+?)\s+(?P<grade>A\+?|A-|B\+?|B-|C\+?|C-|D\+?|D-|F|P|NP|S|U|W)\s+(?P<attempted>\d+\.\d+)\s+(?P<earned>\d+\.\d+)\s+(?P<points>\d+\.\d+)\s+(?P<dates>\d{2}/\d{2}/\d{2}(?:-\d{2}/\d{2}/\d{2})?)\s+(?P<code>[A-Z]{4,8})\s+(?P<num>\d{3})$",
                re.IGNORECASE | re.DOTALL,
            ),
        ]
        for pattern in patterns:
            match = pattern.match(chunk_text)
            if not match:
                continue
            return {
                "course_code": f"{match.group('code').upper()}{match.group('num')}",
                "course_title": re.sub(r"\s+", " ", match.group("title")).strip(" -"),
                "credits": float(match.group("earned")),
                "grade": match.group("grade").upper(),
                "term": term_name,
            }
        return None

    def _looks_like_milwaukee_course_code_line(self, line: str) -> bool:
        return bool(re.fullmatch(r"[A-Z]{4,8}(?:\s+\d{3})?", line.strip(), re.IGNORECASE))

    def _looks_like_milwaukee_title_first_line(self, line: str) -> bool:
        compact = re.sub(r"\s+", " ", line).strip()
        return bool(compact and re.search(r"[A-Za-z]{4,}", compact) and not self._looks_like_milwaukee_course_code_line(compact))

    def _looks_like_milwaukee_date_line(self, line: str) -> bool:
        return bool(re.search(r"\d{2}/\d{2}/\d{2}(?:-\d{2}/\d{2}/\d{2})?", line))

    def _looks_like_milwaukee_title_first_start(self, lines_in_block: List[str], start_idx: int) -> bool:
        line = lines_in_block[start_idx].strip()
        if not self._looks_like_milwaukee_title_first_line(line):
            return False
        window = [candidate.strip() for candidate in lines_in_block[start_idx : min(len(lines_in_block), start_idx + 8)]]
        has_grade = any(looks_like_grade(candidate) for candidate in window[1:4])
        has_date = any(self._looks_like_milwaukee_date_line(candidate) for candidate in window[1:7])
        has_trailing_code = any(self._looks_like_milwaukee_course_code_line(candidate) for candidate in window[2:8])
        return has_grade and has_date and has_trailing_code

    def _is_milwaukee_noise_line(self, line: str) -> bool:
        compact = re.sub(r"\s+", " ", line).strip()
        if not compact:
            return True
        lowered = compact.lower()
        if lowered in {
            "milwaukee area technical college",
            "transcript",
            "credits credits",
            "grade",
            "credit",
            "course",
            "title",
            "grd",
            "repeat",
            "att",
            "cmpt",
            "points course dates",
            "type",
            "notes",
        }:
            return True
        if re.fullmatch(r"\d{1,2}", compact):
            return True
        noise_fragments = (
            "the college name appears in white print",
            "the word void will appear across the front",
            "chain-link pattern must be visible",
            "officially sealed and signed transcript",
            "official signature is white with a raised seal",
            "family educational rights and privacy act",
            "should not be accepted",
            "sarah y. adams, registrar",
            "special circumstances grades",
            "clep - college level examination program",
            "new grade information",
            "area technic",
            "college est.",
            "birth date:",
            "id number:",
        )
        if any(fragment in lowered for fragment in noise_fragments):
            return True
        if lowered.startswith("totals:") or lowered.startswith("cumulative totals:") or lowered.startswith("gpa"):
            return True
        return False

    def _parse_analysis_report_courses(self, text_lines: List[str]) -> List[Dict[str, Any]]:
        rows: List[str] = []
        collecting = False
        current = ""
        for line in text_lines:
            stripped = re.sub(r"\s+", " ", line).strip()
            if stripped == "Transcript Data":
                collecting = True
                current = ""
                continue
            if not collecting:
                continue
            if stripped.startswith("Analysis Summary"):
                if current:
                    rows.append(current.strip())
                break
            if stripped.startswith(("Subject Course ID", "CONFIDENTIAL")):
                continue
            if re.match(r"^[A-Z]{2,4}\s+[A-Z]{2,4}\s+\d{3}\b", stripped):
                if current:
                    rows.append(current.strip())
                current = stripped
            elif current:
                current = f"{current} {stripped}".strip()
        if current and current not in rows:
            rows.append(current.strip())

        courses_by_term: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        pattern = re.compile(
            r"^(?P<subject>[A-Z]{2,4})\s+"
            r"(?P<course_id>[A-Z]{2,4}\s+\d{3})\s+"
            r"(?P<title>.+?)\s+"
            r"(?P<attempted>\d+(?:\.\d+)?)\s+"
            r"(?P<earned>\d+(?:\.\d+)?)\s+"
            r"(?P<grade>A\+?|A-|B\+?|B-|C\+?|C-|D\+?|D-|F|W|P|NP|S|U|IP|CR|NC|TR|PR)\s+"
            r"(?P<points>\d+(?:\.\d+)?)\s+"
            r"(?P<term>Fall|Spring|Summer|Winter)\s+"
            r"(?P<year>\d{4})",
            re.IGNORECASE,
        )
        for row in rows:
            match = pattern.match(row)
            if not match:
                continue
            term_name = f"{match.group('term').title()} {match.group('year')}"
            course = {
                "course_code": match.group("course_id").replace(" ", ""),
                "course_title": match.group("title").strip(),
                "credits": float(match.group("earned")),
                "grade": match.group("grade").upper(),
                "term": term_name,
            }
            self.ensure_course_confidences([{"term_name": term_name, "courses": [course]}])
            courses_by_term[term_name].append(course)
        return [{"term_name": term_name, "courses": courses} for term_name, courses in courses_by_term.items()]

    def _parse_utah_export(self, text: str, document_type: str) -> Dict[str, Any]:
        text_lines = lines(text)
        student = {
            "name": self._title_case_line_after(text_lines, "Student"),
            "student_id": None,
            "date_of_birth": self._extract_after_prefix(text_lines, "DOB:"),
            "address": self._parse_inline_city_address(text_lines),
        }
        institution_name = self._utah_export_institution_name(text_lines)
        summary = {
            "gpa": self._safe_float_from_summary_line(text_lines, "All", position=2),
            "total_credits_attempted": self._safe_float_from_summary_line(text_lines, "All", position=0),
            "total_credits_earned": self._safe_float_from_summary_line(text_lines, "All", position=1),
            "class_rank": self._extract_rank_classsize_inline(text_lines),
        }
        terms = self._parse_utah_export_courses(text_lines)
        terms = self.ensure_course_confidences(terms)
        course_summary = self.summarize_course_confidence(terms)
        confidence = self._estimate_confidence(student, [{"name": institution_name, "type": "high_school"}] if institution_name else [], summary, terms, course_summary)
        return {
            "document_type": "high_school_transcript" if document_type == "unknown" else document_type,
            "student": student,
            "institutions": [{"name": institution_name, "type": "high_school"}] if institution_name else [],
            "academic_summary": summary,
            "terms": terms,
            "parser_confidence": max(confidence, 0.86),
            "course_confidence_summary": course_summary,
        }

    def _parse_utah_export_courses(self, text_lines: List[str]) -> List[Dict[str, Any]]:
        idx = 0
        current_term = "Unassigned"
        courses_by_term: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        while idx < len(text_lines):
            line = text_lines[idx]
            if line == "Academic Session" and idx + 2 < len(text_lines):
                for look in range(idx + 1, min(idx + 8, len(text_lines))):
                    m = re.match(r"^(?P<inst>.+?)\s+(?P<year>20\d{2}[\-\u00ad]20\d{2})$", text_lines[look].strip(), re.IGNORECASE)
                    if m:
                        inst = m.group("inst").replace("\u00ad", "").strip().title()
                        year = m.group("year").replace("\u00ad", "")
                        current_term = f"{year} {inst}"
                        break
                idx += 1
            match = re.match(
                r"^(?P<course_code>\d{4,6})\s+(?P<title>.+?)\s+(?P<session>\d{1,2})\s+(?P<grade>A\+?|A-|B\+?|B-|C\+?|C-|D\+?|D-|F|W|P|NP|S|U|IP|CR|NC|TR|PR)\s+(?P<credits>\d+(?:\.\d+)?)$",
                line,
                re.IGNORECASE,
            )
            if match:
                course = {
                    "course_code": match.group("course_code"),
                    "course_title": match.group("title").strip(),
                    "credits": float(match.group("credits")),
                    "grade": match.group("grade").upper(),
                    "term": current_term,
                }
                self.ensure_course_confidences([{"term_name": current_term, "courses": [course]}])
                courses_by_term[current_term].append(course)
            idx += 1
        return [{"term_name": term_name, "courses": courses} for term_name, courses in courses_by_term.items()]

    def _parse_school_report_transcript(self, text: str, document_type: str) -> Dict[str, Any]:
        text_lines = lines(text)
        student = {
            "name": self._school_report_student_name(text_lines),
            "student_id": self._extract_after_prefix(text_lines, "State ID :"),
            "date_of_birth": self._extract_after_prefix(text_lines, "DOB:"),
            "address": self._parse_school_report_address(text_lines),
        }
        institution_name = self._extract_school_report_institution(text_lines)
        summary = {
            "gpa": self._safe_float(self._extract_after_prefix(text_lines, "Cumulative GPA:")),
            "total_credits_attempted": None,
            "total_credits_earned": self._safe_float(self._extract_after_prefix(text_lines, "Cumulative Earned Credits:")),
            "class_rank": self._extract_school_report_rank(text_lines),
        }
        terms = self._parse_school_report_courses(text_lines)
        terms = self.ensure_course_confidences(terms)
        course_summary = self.summarize_course_confidence(terms)
        confidence = self._estimate_confidence(student, [{"name": institution_name, "type": "high_school"}] if institution_name else [], summary, terms, course_summary)
        return {
            "document_type": "high_school_transcript" if document_type == "unknown" else document_type,
            "student": student,
            "institutions": [{"name": institution_name, "type": "high_school"}] if institution_name else [],
            "academic_summary": summary,
            "terms": terms,
            "parser_confidence": max(confidence, 0.84),
            "course_confidence_summary": course_summary,
        }

    def _parse_student_achievement_summary_transcript(self, text: str, document_type: str) -> Dict[str, Any]:
        text_lines = lines(text)
        institution_name = self._extract_student_achievement_summary_institution(text)
        student = {
            "name": self._extract_labeled_name_value(text_lines, "Student Name")
            or self._extract_school_report_wrapper_name(text_lines)
            or self._extract_top_name(text_lines),
            "student_id": None,
            "date_of_birth": self._extract_student_achievement_summary_dob(text),
            "address": {"street": None, "city": None, "state": None, "postal_code": None},
        }
        summary = self._parse_student_achievement_summary_metrics(text)
        terms = self._parse_student_achievement_summary_courses(text_lines, institution_name)
        terms = self.ensure_course_confidences(terms)
        course_summary = self.summarize_course_confidence(terms)
        confidence = self._estimate_confidence(student, [{"name": institution_name, "type": "high_school"}] if institution_name else [], summary, terms, course_summary)
        return {
            "document_type": "high_school_transcript" if document_type == "unknown" else document_type,
            "student": student,
            "institutions": [{"name": institution_name, "type": "high_school"}] if institution_name else [],
            "academic_summary": summary,
            "terms": terms,
            "parser_confidence": max(confidence, 0.87 if terms else 0.65),
            "course_confidence_summary": course_summary,
        }

    def _extract_student_achievement_summary_institution(self, text: str) -> str:
        match = re.search(r"(20\d{2}-20\d{2})\s+([A-Za-z][A-Za-z .&'-]*High School)", text)
        if match:
            return re.sub(r"\s+", " ", match.group(2)).strip()
        match = re.search(r"\b([A-Za-z][A-Za-z .&'-]*High School)\b", text)
        return re.sub(r"\s+", " ", match.group(1)).strip() if match else ""

    def _extract_student_achievement_summary_dob(self, text: str) -> str | None:
        match = re.search(r"Date of Birth(?:\s+Current Grade\s+Gender)?\s+([0-9]{2}/[0-9]{2}/[0-9]{4})", text, re.IGNORECASE)
        return match.group(1) if match else None

    def _parse_student_achievement_summary_metrics(self, text: str) -> Dict[str, Any]:
        match = re.search(
            r"Rank\s+Out of Graduation Date\s+([0-9]+(?:\.[0-9]+)?)\s+([0-9]+(?:\.[0-9]+)?)\s+(\d+)\s+(\d+)",
            text,
            re.IGNORECASE,
        )
        return {
            "gpa": float(match.group(1)) if match else None,
            "total_credits_attempted": None,
            "total_credits_earned": None,
            "class_rank": f"{match.group(3)}/{match.group(4)}" if match else None,
        }

    def _parse_student_achievement_summary_courses(self, text_lines: List[str], institution_name: str) -> List[Dict[str, Any]]:
        courses_by_term: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        current_terms: List[str] = []
        in_course_section = False

        for idx, raw_line in enumerate(text_lines):
            line = re.sub(r"\s+", " ", raw_line.strip())
            if not line:
                continue
            if re.match(r"^(9th|10th|11th|12th) Grade\s+(9th|10th|11th|12th) Grade\b", line):
                current_terms = self._student_achievement_summary_term_names(line, text_lines[idx + 1] if idx + 1 < len(text_lines) else "", institution_name)
                in_course_section = False
                continue
            if not current_terms:
                continue
            if "Course Title S1 S2 Credits" in line:
                in_course_section = True
                continue
            if not in_course_section:
                continue
            if self._is_student_achievement_summary_stop_line(line):
                in_course_section = False
                continue

            row_courses = self._parse_student_achievement_summary_row(line, current_terms)
            if not row_courses:
                continue
            for course in row_courses:
                term_name = course.pop("_term_name")
                self.ensure_course_confidences([{"term_name": term_name, "courses": [course]}])
                courses_by_term[term_name].append(course)

        return [{"term_name": term_name, "courses": courses} for term_name, courses in courses_by_term.items() if courses]

    def _student_achievement_summary_term_names(self, grade_line: str, year_line: str, institution_name: str) -> List[str]:
        years = re.findall(r"20\d{2}-20\d{2}", year_line)
        institution_matches = re.findall(r"(20\d{2}-20\d{2})\s+([A-Za-z][A-Za-z .&'-]*High School)", year_line)
        institutions_by_year = {year: inst.strip() for year, inst in institution_matches}
        grade_labels = re.findall(r"(9th|10th|11th|12th) Grade", grade_line)
        terms: List[str] = []
        for idx, grade in enumerate(grade_labels):
            year = years[idx] if idx < len(years) else ""
            inst = institutions_by_year.get(year) or institution_name
            label = f"{grade} Grade"
            if year and inst:
                terms.append(f"{label} {year} {inst}".strip())
            elif year:
                terms.append(f"{label} {year}".strip())
            else:
                terms.append(label)
        return terms

    def _is_student_achievement_summary_stop_line(self, line: str) -> bool:
        lowered = line.lower()
        return lowered.startswith(
            (
                "annual gpa",
                "graduation requirements",
                "number of credits earned by department",
                "specialized honors courses",
                "signature / title",
            )
        )

    def _parse_student_achievement_summary_row(self, line: str, current_terms: List[str]) -> List[Dict[str, Any]]:
        if "=" in line or "grades:" in line.lower():
            line = re.split(r"\b(?:Un-weighted grades:|Weighted grades:|A =|C =|F =|S =|T =)", line, maxsplit=1, flags=re.IGNORECASE)[0].strip()
        if not line:
            return []

        remaining = line
        courses: List[Dict[str, Any]] = []
        for column_index in range(min(2, len(current_terms))):
            parsed = self._consume_student_achievement_summary_entry(remaining)
            if parsed is None:
                break
            course, remaining = parsed
            course["_term_name"] = current_terms[column_index]
            course["source_line"] = line
            course["source_term_line"] = current_terms[column_index]
            courses.append(course)
            if not remaining:
                break
        return courses

    def _consume_student_achievement_summary_entry(self, text: str) -> Tuple[Dict[str, Any], str] | None:
        compact = re.sub(r"\s+", " ", text.strip())
        if not compact:
            return None
        grade_pattern = r"A\+?|A-|B\+?|B-|C\+?|C-|D\+?|D-|F|P|W|WF|I"
        patterns = [
            re.compile(
                rf"^(?P<title>.+?)\s+(?:(?P<rigor>AP|H|S)\s+)?(?P<grade1>{grade_pattern})(?:\s+(?P<grade2>{grade_pattern}))?\s+(?P<credit>\d+\.\d+)(?:\s+(?P<rest>.*))?$",
                re.IGNORECASE,
            ),
            re.compile(
                r"^(?P<title>.+?)\s+(?:(?P<rigor>AP|H|S)\s+)?(?P<credit>\d+\.\d+)(?:\s+(?P<rest>.*))?$",
                re.IGNORECASE,
            ),
        ]
        for pattern in patterns:
            match = pattern.match(compact)
            if not match:
                continue
            title = match.group("title").strip(" -")
            if not title or self._is_student_achievement_summary_noise_title(title):
                continue
            credits = float(match.group("credit"))
            grade = (match.groupdict().get("grade2") or match.groupdict().get("grade1") or "").upper() or None
            course = {
                "course_code": None,
                "course_title": title,
                "credits": credits,
                "grade": grade,
                "term": None,
            }
            rest = re.sub(r"\s+", " ", (match.groupdict().get("rest") or "").strip())
            return course, rest
        return None

    def _is_student_achievement_summary_noise_title(self, title: str) -> bool:
        lowered = title.lower()
        if lowered in {"course title", "current grade gender", "date of birth", "student name"}:
            return True
        if any(token in lowered for token in ("gpa", "credits", "graduation requirements", "specialized honors")):
            return True
        return False

    def _parse_parchment_high_school_transcript(self, text: str, document_type: str) -> Dict[str, Any]:
        text_lines = lines(text)
        institution_name = self._parchment_high_school_institution(text_lines)
        student = {
            "name": self._normalize_name_value(self._extract_regex_group(text, r"Student Name:\s*([^\n]+)") or ""),
            "student_id": self._extract_regex_group(text, r"Parchment Student ID:\s*([A-Z0-9]+)") or self._extract_regex_group(text, r"\bID:\s*(\d+)\s+State ID:"),
            "date_of_birth": self._extract_regex_group(text, r"Birth Date:\s*([0-9/]+)"),
            "address": self._parse_parchment_high_school_address(text_lines),
        }
        summary = {
            "gpa": None,
            "total_credits_attempted": None,
            "total_credits_earned": None,
            "class_rank": None,
        }
        terms = self._parse_parchment_high_school_courses(text_lines)
        terms = self.ensure_course_confidences(terms)
        course_summary = self.summarize_course_confidence(terms)
        confidence = self._estimate_confidence(student, [{"name": institution_name, "type": "high_school"}] if institution_name else [], summary, terms, course_summary)
        return {
            "document_type": "high_school_transcript" if document_type == "unknown" else document_type,
            "student": student,
            "institutions": [{"name": institution_name, "type": "high_school"}] if institution_name else [],
            "academic_summary": summary,
            "terms": terms,
            "parser_confidence": max(confidence, 0.86),
            "course_confidence_summary": course_summary,
        }

    def _parse_parchment_high_school_courses(self, text_lines: List[str]) -> List[Dict[str, Any]]:
        courses_by_term: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        idx = 0
        current_term = "Unassigned"
        while idx < len(text_lines):
            line = text_lines[idx].strip()
            if self._looks_like_high_school_year_header(line):
                current_term = line
                idx += 1
                continue
            if self._is_parchment_course_title(line):
                course, next_idx = self._consume_parchment_course(text_lines, idx, current_term)
                if course:
                    courses_by_term[current_term].append(course)
                idx = next_idx
                continue
            idx += 1
        return [{"term_name": term_name, "courses": courses} for term_name, courses in courses_by_term.items() if courses]

    def _consume_parchment_course(self, text_lines: List[str], start_idx: int, current_term: str) -> Tuple[Dict[str, Any] | None, int]:
        title = text_lines[start_idx].strip().strip(":")
        idx = start_idx + 1
        grades: List[str] = []
        credits: List[float] = []

        while idx < len(text_lines):
            candidate = text_lines[idx].strip()
            if not candidate:
                idx += 1
                continue
            if self._looks_like_high_school_year_header(candidate) or self._is_parchment_course_title(candidate):
                break
            if self._is_parchment_skip_line(candidate):
                idx += 1
                continue

            combined_grade, combined_credit = self._parse_parchment_grade_credit_line(candidate)
            if combined_grade and combined_credit is not None:
                grades.append(combined_grade)
                credits.append(combined_credit)
                idx += 1
                continue

            parsed_grade = self._normalize_parchment_grade(candidate)
            parsed_credit = self._normalize_parchment_credit(candidate)

            if parsed_grade and parsed_credit is None and idx + 1 < len(text_lines):
                next_credit = self._normalize_parchment_credit(text_lines[idx + 1].strip())
                if next_credit is not None:
                    grades.append(parsed_grade)
                    credits.append(next_credit)
                    idx += 2
                    continue

            if parsed_grade and parsed_credit is not None:
                grades.append(parsed_grade)
                credits.append(parsed_credit)
                idx += 1
                continue

            if parsed_credit is not None:
                credits.append(parsed_credit)
                idx += 1
                continue

            idx += 1

        if not grades and not credits:
            return None, idx

        selected_grade = grades[-1] if grades else None
        total_credits = round(sum(credits), 2) if credits else None
        confidence_score, confidence_reasons = self._estimate_course_confidence(
            course_code=None,
            course_title=title,
            credits=total_credits,
            grade=selected_grade,
            term=current_term,
        )
        return {
            "course_code": None,
            "course_title": title,
            "credits": total_credits,
            "grade": selected_grade,
            "term": current_term,
            "confidence_score": confidence_score,
            "confidence_reasons": confidence_reasons,
        }, idx

    def _parse_brandon_valley_transcript(self, text: str, document_type: str) -> Dict[str, Any]:
        text_lines = lines(text)
        student = {
            "name": self._extract_after_prefix(text_lines, "Name "),
            "student_id": self._extract_after_prefix(text_lines, "State ID "),
            "date_of_birth": self._extract_after_prefix(text_lines, "Birthdate "),
            "address": self._parse_brandon_valley_address(text_lines),
        }
        if student["name"]:
            student["name"] = student["name"].title()

        summary = {
            "gpa": self._parse_spaced_decimal_value(text, r"Cumulative GPA\s+([0-9][0-9 .]+)"),
            "total_credits_attempted": self._parse_spaced_decimal_value(text, r"Cumulative GPA Credits\s+([0-9][0-9 .]+)"),
            "total_credits_earned": self._parse_spaced_decimal_value(text, r"Total Earned Credits\.?\s+([0-9][0-9 .]+)"),
            "class_rank": self._extract_brandon_valley_rank(text),
        }
        institution_name = "Brandon Valley High School"
        terms = self._parse_brandon_valley_courses(text_lines)
        terms = self.ensure_course_confidences(terms)
        course_summary = self.summarize_course_confidence(terms)
        confidence = self._estimate_confidence(student, [{"name": institution_name, "type": "high_school"}], summary, terms, course_summary)
        return {
            "document_type": "high_school_transcript" if document_type == "unknown" else document_type,
            "student": student,
            "institutions": [{"name": institution_name, "type": "high_school"}],
            "academic_summary": summary,
            "terms": terms,
            "parser_confidence": max(confidence, 0.88),
            "course_confidence_summary": course_summary,
        }

    def _parse_logan_district_transcript(self, text: str, document_type: str) -> Dict[str, Any]:
        text_lines = lines(text)
        student = {
            "name": self._line_after(text_lines, "Student"),
            "student_id": None,
            "date_of_birth": self._normalize_logan_text(self._extract_after_prefix(text_lines, "DOB:")) or None,
            "address": self._parse_logan_student_address(text_lines),
        }
        institution_name = self._extract_logan_institution(text_lines)
        summary = self._parse_logan_summary(text_lines)
        terms = self._parse_logan_terms_and_courses(text_lines)
        terms = self.ensure_course_confidences(terms)
        course_summary = self.summarize_course_confidence(terms)
        confidence = self._estimate_confidence(student, [{"name": institution_name, "type": "high_school"}] if institution_name else [], summary, terms, course_summary)
        return {
            "document_type": "high_school_transcript" if document_type == "unknown" else document_type,
            "student": student,
            "institutions": [{"name": institution_name, "type": "high_school"}] if institution_name else [],
            "academic_summary": summary,
            "terms": terms,
            "parser_confidence": max(confidence, 0.9),
            "course_confidence_summary": course_summary,
        }

    def _parse_logan_terms_and_courses(self, text_lines: List[str]) -> List[Dict[str, Any]]:
        terms: List[Dict[str, Any]] = []
        idx = 0
        while idx < len(text_lines):
            if self._normalize_logan_text(text_lines[idx]) != "Academic Session":
                idx += 1
                continue
            term_name = "Unassigned"
            courses: List[Dict[str, Any]] = []
            idx += 1
            while idx < len(text_lines):
                line = self._normalize_logan_text(text_lines[idx])
                if line == "Academic Session":
                    break
                if line == "Institution Academic YearAcademic Level" and idx + 1 < len(text_lines):
                    institution_line = self._normalize_logan_text(text_lines[idx + 1])
                    term_name = self._normalize_logan_term_name(institution_line)
                    idx += 2
                    continue
                if line == "Course no Title Session Grade Credits":
                    idx += 1
                    source_term_line = institution_line
                    while idx < len(text_lines):
                        course_line = self._normalize_logan_text(text_lines[idx])
                        if course_line.startswith("Summary TypeHours Attempted") or course_line == "Academic Session":
                            break
                        course = self._parse_logan_course_line(course_line, term_name, source_term_line)
                        if course:
                            courses.append(course)
                        idx += 1
                    continue
                idx += 1
            if courses:
                terms.append({"term_name": term_name, "courses": courses})
        return terms

    def _parse_logan_course_line(self, line: str, term_name: str, source_term_line: str | None = None) -> Dict[str, Any] | None:
        compact = self._normalize_logan_text(line)
        match = re.match(
            r"^(?P<title>.+?)(?P<session>\d{1,2})\s+(?P<grade>A\+?|A-|B\+?|B-|C\+?|C-|D\+?|D-|F|P|W)\s+(?P<credits>\d+\.\d{3})$",
            compact,
            re.IGNORECASE,
        )
        if not match:
            return None
        title = match.group("title").strip()
        grade = match.group("grade").upper()
        credits = float(match.group("credits"))
        confidence_score, confidence_reasons = self._estimate_course_confidence(
            course_code=None,
            course_title=title,
            credits=credits,
            grade=grade,
            term=term_name,
        )
        return {
            "course_code": None,
            "course_title": title,
            "credits": credits,
            "grade": grade,
            "term": term_name,
            "confidence_score": confidence_score,
            "confidence_reasons": confidence_reasons,
            "source_line": compact,
            "source_term_line": source_term_line,
        }

    def _parse_brandon_valley_courses(self, text_lines: List[str]) -> List[Dict[str, Any]]:
        courses_by_term: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        idx = 0
        term_pair: List[str] = []
        pair_position = 0

        while idx < len(text_lines):
            line = text_lines[idx].strip()
            if self._is_brandon_grade_header(line):
                term_pair = [line]
                if idx + 1 < len(text_lines) and self._is_brandon_grade_header(text_lines[idx + 1].strip()):
                    term_pair.append(text_lines[idx + 1].strip())
                    idx += 1
                pair_position = 0
                idx += 1
                continue

            if self._is_brandon_section_header(line) or self._is_brandon_summary_line(line):
                idx += 1
                continue

            if self._is_brandon_course_start(line):
                course, next_idx = self._consume_brandon_valley_course(text_lines, idx)
                if course:
                    assigned_term = term_pair[pair_position % len(term_pair)] if term_pair else "Unassigned"
                    pair_position += 1
                    year = course.pop("_year", "")
                    course["term"] = f"{assigned_term} {year}".strip() if year else assigned_term
                    courses_by_term[course["term"]].append(course)
                idx = next_idx
                continue
            idx += 1

        return [{"term_name": term_name, "courses": courses} for term_name, courses in courses_by_term.items()]

    def _consume_brandon_valley_course(self, text_lines: List[str], start_idx: int) -> Tuple[Dict[str, Any] | None, int]:
        row_lines = [text_lines[start_idx].strip()]
        idx = start_idx + 1
        while idx < len(text_lines):
            candidate = text_lines[idx].strip()
            if not candidate:
                idx += 1
                continue
            if (
                self._is_brandon_grade_header(candidate)
                or self._is_brandon_section_header(candidate)
                or self._is_brandon_summary_line(candidate)
                or self._is_brandon_course_start(candidate)
            ):
                break
            row_lines.append(candidate)
            idx += 1

        if not row_lines:
            return None, idx

        code = None
        title = row_lines[0]
        code_match = re.match(r"^(?P<code>\d{5}(?:/\d{5})?|[A-Z]{1,3}\s*\d{3})\s+(?P<title>.+)$", row_lines[0])
        if code_match:
            code = code_match.group("code").replace(" ", "")
            title = code_match.group("title").strip()

        year = ""
        credits: List[float] = []
        grades: List[str] = []
        for token in row_lines[1:]:
            compact = token.strip()
            if re.fullmatch(r"20\d{2}", compact):
                year = compact
                continue
            credit_and_grade = re.fullmatch(
                r"(?P<credit>\d[\d .]{2,})\s+(?P<grade>A\+?|A-|B\+?|B-|C\+?|C-|D\+?|D-|F|P)$",
                compact,
                re.IGNORECASE,
            )
            if credit_and_grade:
                parsed_credit = self._parse_brandon_valley_number(credit_and_grade.group("credit"))
                if parsed_credit is not None:
                    credits.append(parsed_credit)
                grades.append(credit_and_grade.group("grade").upper())
                continue
            if re.fullmatch(r"A\+?|A-|B\+?|B-|C\+?|C-|D\+?|D-|F|P", compact, re.IGNORECASE):
                grades.append(compact.upper())
                continue
            parsed_credit = self._parse_brandon_valley_number(compact)
            if parsed_credit is not None:
                credits.append(parsed_credit)
                continue

        selected_credit = credits[-1] if credits else None
        selected_grade = grades[-1] if grades else None
        if not title or (selected_credit is None and not selected_grade):
            return None, idx

        confidence_score, confidence_reasons = self._estimate_course_confidence(
            course_code=code,
            course_title=title,
            credits=selected_credit,
            grade=selected_grade,
            term=None,
        )
        return {
            "course_code": code,
            "course_title": title,
            "credits": selected_credit,
            "grade": selected_grade,
            "confidence_score": confidence_score,
            "confidence_reasons": confidence_reasons,
            "_year": year,
        }, idx

    def _parse_school_report_courses(self, text_lines: List[str]) -> List[Dict[str, Any]]:
        idx = 0
        current_term = "Unassigned"
        courses_by_term: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        current_buffer = ""
        while idx < len(text_lines):
            line = text_lines[idx]
            grade_header = re.match(r"^Grade\s+(?P<grade_level>\d+)\s+\-\s*$", line)
            if grade_header:
                if current_buffer:
                    self._append_school_report_course(current_buffer, current_term, courses_by_term)
                    current_buffer = ""
                year = ""
                for lookahead in range(idx + 1, min(idx + 25, len(text_lines))):
                    if re.fullmatch(r"20\d{2}", text_lines[lookahead].strip()):
                        year = text_lines[lookahead].strip()
                        break
                current_term = year or f"Grade {grade_header.group('grade_level')}"
                idx += 1
                continue
            if re.match(r"^\d{3}\s+", line):
                if current_buffer:
                    self._append_school_report_course(current_buffer, current_term, courses_by_term)
                current_buffer = line.strip()
            elif current_buffer and line.strip() and not line.startswith("Total Earned Credits:"):
                current_buffer = f"{current_buffer} {line.strip()}"
            elif current_buffer and line.startswith("Total Earned Credits:"):
                self._append_school_report_course(current_buffer, current_term, courses_by_term)
                current_buffer = ""
            idx += 1
        if current_buffer:
            self._append_school_report_course(current_buffer, current_term, courses_by_term)
        return [{"term_name": term_name, "courses": courses} for term_name, courses in courses_by_term.items()]

    def _extract_labeled_value(self, text: str, start_label: str, end_label: str | None = None, fallback_label: str | None = None) -> str:
        pattern = re.escape(start_label) + r":?\s*(.+)"
        match = re.search(pattern, text)
        if not match:
            return ""
        value = match.group(1)
        for stopper in [end_label, fallback_label]:
            if stopper and stopper in value:
                value = value.split(stopper, 1)[0]
        return re.sub(r"\s+", " ", value).strip(" -")

    def _safe_float(self, value: str | None) -> float | None:
        try:
            return float(value) if value not in (None, "", "-") else None
        except ValueError:
            return None

    def _title_case_line_after(self, text_lines: List[str], marker: str) -> str:
        for idx, line in enumerate(text_lines):
            if line == marker and idx + 1 < len(text_lines):
                candidate = text_lines[idx + 1].strip()
                if candidate.isdigit() and idx + 2 < len(text_lines):
                    candidate = text_lines[idx + 2].strip()
                return candidate.title()
        return ""

    def _extract_after_prefix(self, text_lines: List[str], prefix: str) -> str:
        for line in text_lines:
            if line.startswith(prefix):
                return line.split(prefix, 1)[1].strip()
        return ""

    def _parse_inline_city_address(self, text_lines: List[str]) -> Dict[str, Any]:
        address = {"street": None, "city": None, "state": None, "postal_code": None}
        for idx, line in enumerate(text_lines):
            if re.fullmatch(r"\d+\s+.+", line.strip()) and idx + 1 < len(text_lines):
                next_line = text_lines[idx + 1].strip()
                city_match = re.match(r"^([A-Z ]+),\s*([A-Z]{2})\s+(\d{5}(?:-\d{4})?)$", next_line)
                if city_match:
                    address["street"] = line.strip()
                    address["city"] = city_match.group(1).title()
                    address["state"] = city_match.group(2)
                    address["postal_code"] = city_match.group(3)
                    break
        return address

    def _safe_float_from_summary_line(self, text_lines: List[str], prefix: str, position: int = 2) -> float | None:
        for line in text_lines:
            if line.startswith(prefix + " "):
                parts = line.split()
                if len(parts) > position + 1:
                    return self._safe_float(parts[position + 1 if prefix == "All" else position])
        return None

    def _extract_rank_classsize_inline(self, text_lines: List[str]) -> str | None:
        for idx, line in enumerate(text_lines):
            if line.startswith("Summary"):
                continue
            if re.search(r"\bAll\s+\d", line):
                parts = line.split()
                if len(parts) >= 6:
                    return f"{parts[-2]}/{parts[-1]}"
        return None

    def _extract_named_line(self, text_lines: List[str], prefix: str) -> str | None:
        for idx, line in enumerate(text_lines):
            if line.startswith(prefix) and idx + 1 < len(text_lines):
                return text_lines[idx + 1].strip().title()
        return None

    def _extract_top_name(self, text_lines: List[str]) -> str | None:
        if text_lines and "," in text_lines[0]:
            return self._normalize_name_value(text_lines[0].strip())
        return None

    def _extract_labeled_name_value(self, text_lines: List[str], label: str) -> str | None:
        normalized_label = self._normalize_logan_text(label).rstrip(":").lower()
        for idx, line in enumerate(text_lines):
            compact = self._normalize_logan_text(line)
            if compact.rstrip(":").lower() != normalized_label:
                continue
            fallback_candidate = None
            for lookahead in range(idx + 1, min(idx + 6, len(text_lines))):
                candidate = self._normalize_logan_text(text_lines[lookahead])
                if not candidate:
                    continue
                if candidate.lower().startswith(("date of birth", "current grade", "gender", "student id", "id")):
                    break
                if not any(ch.isalpha() for ch in candidate):
                    continue
                if self._looks_like_person_name(candidate):
                    return self._normalize_name_value(candidate)
                if fallback_candidate is None:
                    fallback_candidate = candidate
            if fallback_candidate is not None:
                return self._normalize_name_value(fallback_candidate)
        return None

    def _extract_school_report_wrapper_name(self, text_lines: List[str]) -> str | None:
        for line in text_lines[:120]:
            match = re.search(r"\bSR\s+([A-Za-z][A-Za-z'., -]+?)\s+CEEB:", line)
            if match:
                return self._normalize_name_value(match.group(1).strip())
        return None

    def _looks_like_person_name(self, value: str) -> bool:
        compact = self._normalize_logan_text(value)
        lowered = compact.lower()
        if any(keyword in lowered for keyword in ("high school", "school", "university", "college", "academy", "district")):
            return False
        if any(char.isdigit() for char in compact):
            return False
        tokens = [token for token in re.split(r"[\s,]+", compact) if token]
        if any(token.lower() in {"high", "school", "university", "college", "academy", "district"} for token in tokens):
            return False
        if not 2 <= len(tokens) <= 5:
            return False
        alpha_tokens = [token for token in tokens if any(ch.isalpha() for ch in token)]
        return len(alpha_tokens) >= 2

    def _parse_school_report_address(self, text_lines: List[str]) -> Dict[str, Any]:
        address = {"street": None, "city": None, "state": None, "postal_code": None}
        for idx, line in enumerate(text_lines):
            if re.fullmatch(r"\d+\s+.+", line.strip()) and idx + 1 < len(text_lines):
                city_match = re.match(r"^([A-Z ]+),\s*([A-Z]{2})\s+(\d{5}(?:-\d{4})?)\s+\d+$", text_lines[idx + 1].strip(), re.IGNORECASE)
                if city_match:
                    address["street"] = line.strip()
                    address["city"] = city_match.group(1).title()
                    address["state"] = city_match.group(2)
                    address["postal_code"] = city_match.group(3)
                    break
        return address

    def _extract_school_report_institution(self, text_lines: List[str]) -> str:
        for line in text_lines:
            if line.startswith("Name ") and "High School" in line:
                return line.replace("Name ", "", 1).split(",", 1)[0].strip()
            if "High School" in line and "," in line:
                return line.split(",", 1)[0].strip()
        for line in text_lines:
            if line.endswith("High School"):
                return line.strip()
        return ""

    def _extract_school_report_rank(self, text_lines: List[str]) -> str | None:
        for line in text_lines:
            if re.fullmatch(r"\d+\s+of\s+\d+", line.strip()):
                parts = line.strip().split(" of ")
                return f"{parts[0]}/{parts[1]}"
        return None

    def _school_report_student_name(self, text_lines: List[str]) -> str | None:
        for idx, line in enumerate(text_lines):
            if re.fullmatch(r"[A-Z]+,\s*[A-Z]+", line.strip()):
                return self._normalize_name_value(line.strip())
        return self._extract_top_name(text_lines)

    def _append_school_report_course(self, row: str, current_term: str, courses_by_term: Dict[str, List[Dict[str, Any]]]) -> None:
        match = re.match(
            r"^(?P<entity>\d{3})\s+(?P<title>.+?)\s+(?P<credit>\d+(?:\.\d+)?)\s+(?P<to_be>\d+(?:\.\d+)?)\s*(?P<grades>(?:A\+?|A-|B\+?|B-|C\+?|C-|D\+?|D-|F|W|P|NP|S|U|IP|CR|NC|TR|PR|\s)+)$",
            row,
            re.IGNORECASE,
        )
        if not match:
            return
        grades = [token for token in match.group("grades").split() if looks_like_grade(token)]
        selected_grade = grades[-1] if grades else None
        course = {
            "course_code": None,
            "course_title": match.group("title").replace("\n", " ").strip(),
            "credits": float(match.group("credit")),
            "grade": selected_grade.upper() if selected_grade else None,
            "term": current_term,
        }
        self.ensure_course_confidences([{"term_name": current_term, "courses": [course]}])
        courses_by_term[current_term].append(course)

    def _extract_regex_group(self, text: str, pattern: str, title: bool = False) -> str | None:
        match = re.search(pattern, text, re.IGNORECASE)
        if not match:
            return None
        value = re.sub(r"\s+", " ", match.group(1)).strip()
        return value.title() if title else value

    def _utah_export_institution_name(self, text_lines: List[str]) -> str:
        for idx, line in enumerate(text_lines):
            if line == "Institution":
                for look in range(idx + 1, min(idx + 5, len(text_lines))):
                    candidate = text_lines[look].strip()
                    if candidate and not candidate.isdigit():
                        return candidate.title()
        return ""

    def _parse_brandon_valley_address(self, text_lines: List[str]) -> Dict[str, Any]:
        address = {"street": None, "city": None, "state": None, "postal_code": None}
        for idx, line in enumerate(text_lines):
            if line.startswith("Address "):
                address["street"] = line.split("Address ", 1)[1].strip()
                if idx + 1 < len(text_lines):
                    city_match = re.match(r"^([A-Z ]+),\s*([A-Z]{2})\s+(\d{5}(?:-\d{4})?)$", text_lines[idx + 1].strip())
                    if city_match:
                        address["city"] = city_match.group(1).title()
                        address["state"] = city_match.group(2)
                        address["postal_code"] = city_match.group(3)
                break
        return address

    def _extract_logan_institution(self, text_lines: List[str]) -> str:
        for idx, line in enumerate(text_lines):
            if self._normalize_logan_text(line) == "Institution" and idx + 2 < len(text_lines):
                primary = self._normalize_logan_text(text_lines[idx + 1])
                district = self._normalize_logan_text(text_lines[idx + 2])
                school = self._normalize_logan_text(text_lines[idx + 1]) if re.search(r"[A-Za-z]", text_lines[idx + 1]) else self._normalize_logan_text(text_lines[idx + 2])
                if school and re.search(r"[A-Za-z]", school):
                    if school.lower().endswith("district") and idx + 3 < len(text_lines):
                        fallback = self._normalize_logan_text(text_lines[idx + 3])
                        if fallback and re.search(r"[A-Za-z]", fallback):
                            return fallback
                    return school
                if primary:
                    return self._normalize_logan_text(primary)
                return self._normalize_logan_text(district)
        return ""

    def _parse_logan_student_address(self, text_lines: List[str]) -> Dict[str, Any]:
        address = {"street": None, "city": None, "state": None, "postal_code": None}
        for idx, line in enumerate(text_lines):
            if self._normalize_logan_text(line) == "Student" and idx + 3 < len(text_lines):
                street = self._normalize_logan_text(text_lines[idx + 2].strip()).rstrip(",")
                city_line = self._normalize_logan_text(text_lines[idx + 3].strip())
                city_match = re.match(r"^(.+?),\s*([A-Z]{2})\s+(\d{5}(?:-\d{4})?)$", city_line)
                address["street"] = street or None
                if city_match:
                    address["city"] = city_match.group(1).strip().title()
                    address["state"] = city_match.group(2)
                    address["postal_code"] = city_match.group(3)
                break
        return address

    def _parse_logan_summary(self, text_lines: List[str]) -> Dict[str, Any]:
        summary = {
            "gpa": None,
            "total_credits_attempted": None,
            "total_credits_earned": None,
            "class_rank": None,
        }
        for idx, line in enumerate(text_lines):
            if self._normalize_logan_text(line).startswith("Summary TypeHours Attempted") and idx + 1 < len(text_lines):
                compact = self._normalize_logan_text(text_lines[idx + 1].strip())
                match = re.match(r"^All\s+(\d+\.\d{3})\s+(\d+\.\d{3})\s+(\d+\.\d{3})\s+(\d+)\s+(\d+)$", compact)
                if match:
                    summary["total_credits_attempted"] = float(match.group(1))
                    summary["total_credits_earned"] = float(match.group(2))
                    summary["gpa"] = float(match.group(3))
                    summary["class_rank"] = f"{match.group(4)}/{match.group(5)}"
                    break
        return summary

    def _normalize_logan_term_name(self, value: str) -> str:
        compact = self._normalize_logan_text(value)
        match = re.match(r"^(?P<inst>.+?)\s*(?P<year>20\d{2}[-\u00ad]20\d{2})$", compact)
        if not match:
            return compact
        year = match.group("year").replace("\u00ad", "-")
        return f"{year} {match.group('inst').strip()}"

    def _normalize_logan_text(self, value: str) -> str:
        return re.sub(r"\s+", " ", (value or "").replace("\u00a0", " ").replace("\u00ad", "-")).strip()

    def _line_after(self, text_lines: List[str], marker: str) -> str | None:
        for idx, line in enumerate(text_lines):
            if self._normalize_logan_text(line) == marker and idx + 1 < len(text_lines):
                candidate = self._normalize_logan_text(text_lines[idx + 1].strip())
                return candidate or None
        return None

    def _parchment_high_school_institution(self, text_lines: List[str]) -> str:
        saw_student_name = False
        for line in text_lines:
            stripped = line.strip()
            if stripped.startswith("Student Name:"):
                saw_student_name = True
                continue
            if not saw_student_name:
                continue
            if stripped.endswith("High School") and "District" not in stripped and "Prepared for:" not in stripped:
                return stripped
        for line in text_lines:
            stripped = line.strip()
            if self._looks_like_high_school_year_header(stripped):
                return re.sub(r"^\d{2}-\d{2}\s+", "", stripped).strip()
        return ""

    def _parse_parchment_high_school_address(self, text_lines: List[str]) -> Dict[str, Any]:
        address = {"street": None, "city": None, "state": None, "postal_code": None}
        for idx, line in enumerate(text_lines):
            stripped = line.strip()
            if stripped.startswith("Address:"):
                address["street"] = stripped.split("Address:", 1)[1].strip()
                for look in range(idx + 1, min(idx + 4, len(text_lines))):
                    city_match = re.match(r"^(.+?),\s*([A-Z]{2})\s+(\d{5}(?:-\d{4})?)$", text_lines[look].strip())
                    if city_match:
                        address["city"] = city_match.group(1).strip().title()
                        address["state"] = city_match.group(2)
                        address["postal_code"] = city_match.group(3)
                        break
                break
        return address

    def _is_parchment_course_title(self, line: str) -> bool:
        if not line or self._is_parchment_skip_line(line):
            return False
        if self._looks_like_high_school_year_header(line):
            return False
        combined_grade, combined_credit = self._parse_parchment_grade_credit_line(line)
        if combined_grade and combined_credit is not None:
            return False
        if self._normalize_parchment_grade(line) or self._normalize_parchment_credit(line) is not None:
            return False
        if re.search(r"[A-Za-z]{3,}", line):
            return True
        return bool(re.search(r"[A-Za-z]{2,}\s+\d", line) and any(ch in line for ch in "/ "))

    def _is_parchment_skip_line(self, line: str) -> bool:
        lowered = line.lower()
        return bool(
            lowered.startswith(
                (
                    "official transcript",
                    "prepared for:",
                    "did#:",
                    "parchment student id:",
                    "page ",
                    "student name:",
                    "id:",
                    "address:",
                    "ph.",
                    "sat ",
                    "consumer est proficiency:",
                    "health proficiency:",
                    "read prof",
                    "constitution test:",
                    "college roi",
                    "attained the state",
                )
            )
            or lowered in {"sem 1", "sem 2", "ss", "self refence", "transition cod"}
            or "district 88" in lowered
            or "willowbrook high school" in lowered
        )

    def _normalize_parchment_grade(self, value: str) -> str | None:
        cleaned = re.sub(r"[^A-Za-z0-9+&]", "", value or "").upper()
        if not cleaned:
            return None
        replacements = {
            "A": "A",
            "AA": "A",
            "A1": "A",
            "B": "B",
            "8": "B",
            "3": "B",
            "33": "B",
            "C": "C",
            "6": "C",
            "P": "P",
            "PASS": "P",
            "F": "F",
            "D": "D",
            "A0": "A",
            "AO": "A",
            "&": "A",
        }
        if cleaned in replacements:
            return replacements[cleaned]
        if cleaned in {"APLUS", "A+"}:
            return "A+"
        return None

    def _normalize_parchment_credit(self, value: str) -> float | None:
        compact = re.sub(r"\s+", "", value or "")
        compact = compact.replace(":", ".").replace(",", ".")
        if compact in {":00", ".00", "100", "100."}:
            return 1.0
        if compact in {".50", "050", "0500"}:
            return 0.5
        if not re.fullmatch(r"[0-9.]+", compact):
            return None
        if re.fullmatch(r"\d+\.\d{2}", compact):
            return float(compact)
        return None

    def _parse_parchment_grade_credit_line(self, value: str) -> Tuple[str | None, float | None]:
        match = re.fullmatch(r"([A-Za-z0-9&.+]+)\s+([0-9:.,]+)", (value or "").strip())
        if not match:
            return None, None
        grade = self._normalize_parchment_grade(match.group(1))
        credit = self._normalize_parchment_credit(match.group(2))
        return grade, credit

    def _extract_brandon_valley_rank(self, text: str) -> str | None:
        match = re.search(r"Rank\.?\s+(\d+)\s+of\s+(\d+)", text, re.IGNORECASE)
        if not match:
            return None
        return f"{match.group(1)}/{match.group(2)}"

    def _parse_spaced_decimal_value(self, text: str, pattern: str) -> float | None:
        match = re.search(pattern, text, re.IGNORECASE)
        if not match:
            return None
        return self._parse_brandon_valley_number(match.group(1))

    def _parse_brandon_valley_number(self, value: str) -> float | None:
        compact = re.sub(r"\s+", "", value or "")
        if not compact:
            return None
        if re.fullmatch(r"\d+\.\d+", compact):
            return float(compact)
        if re.fullmatch(r"\d{4,5}", compact):
            return int(compact) / 1000.0
        return None

    def _is_brandon_grade_header(self, line: str) -> bool:
        return bool(re.fullmatch(r"Grade\s+(9|10|11|12)", line, re.IGNORECASE))

    def _is_brandon_section_header(self, line: str) -> bool:
        normalized = line.lower()
        return normalized in {"course", "year", "to be", "earned", "credits", "s1", "s2"}

    def _is_brandon_summary_line(self, line: str) -> bool:
        lowered = line.lower()
        return bool(
            lowered.startswith(("official", "received", "page ", "date printed", "gpa method", "endorsements", "advanced career endorsement"))
            or "total earned credits" in lowered
            or "cumulative gpa" in lowered
            or "credits required for graduation" in lowered
            or "to be earned credits" in lowered
            or "rank." in lowered
            or "graduation date" in lowered
        )

    def _is_brandon_course_start(self, line: str) -> bool:
        if not line or self._is_brandon_grade_header(line) or self._is_brandon_section_header(line) or self._is_brandon_summary_line(line):
            return False
        if re.fullmatch(r"(?:20\d{2}|\d[\d .]{2,}|A\+?|A-|B\+?|B-|C\+?|C-|D\+?|D-|F|P)", line, re.IGNORECASE):
            return False
        if re.fullmatch(r"\d[\d .]{2,}\s+(?:A\+?|A-|B\+?|B-|C\+?|C-|D\+?|D-|F|P)", line, re.IGNORECASE):
            return False
        if not re.search(r"[A-Za-z]{3,}", line):
            return False
        return bool(re.match(r"^(?:\d{5}(?:/\d{5})?|[A-Z]{1,3}\s*\d{3})\s+.+$", line) or re.match(r"^[0-9]{1,2}(?:st|nd|rd|th)\s+Grade\s+.+$", line, re.IGNORECASE))

    def _looks_like_formatted_xml_transcript(self, text: str) -> bool:
        lowered = text.lower()
        return lowered.startswith("formatted xml content") and "academicsession" in lowered and "coursetitle" in lowered

    def _parse_formatted_xml_transcript(self, text: str, document_type: str) -> Dict[str, Any]:
        text_lines = lines(text)
        student = self._parse_formatted_xml_student(text_lines)
        institutions = self._parse_formatted_xml_institutions(text_lines, document_type)
        summary = self._parse_formatted_xml_summary(text_lines)
        terms = self._parse_formatted_xml_terms_and_courses(text_lines)
        terms = self.ensure_course_confidences(terms)
        course_summary = self.summarize_course_confidence(terms)
        confidence = self._estimate_confidence(student, institutions, summary, terms, course_summary)
        return {
            "document_type": document_type,
            "student": student,
            "institutions": institutions,
            "academic_summary": summary,
            "terms": terms,
            "parser_confidence": max(confidence, 0.85),
            "course_confidence_summary": course_summary,
        }

    def _parse_formatted_xml_student(self, text_lines: List[str]) -> Dict[str, Any]:
        student = {
            "name": None,
            "student_id": None,
            "date_of_birth": None,
            "address": {"street": None, "city": None, "state": None, "postal_code": None},
        }
        in_student = False
        in_student_name = False
        in_student_contacts = False
        in_student_address = False
        for idx, line in enumerate(text_lines):
            if line == "Student":
                in_student = True
                in_student_name = False
                in_student_contacts = False
                in_student_address = False
                continue
            if in_student and line == "AcademicRecord":
                break
            if not in_student:
                continue

            if line == "Name":
                in_student_name = True
                in_student_contacts = False
                in_student_address = False
                continue
            if line == "ParentGuardianName":
                in_student_name = False
                continue
            if line == "Contacts":
                in_student_contacts = True
                in_student_name = False
                continue
            if in_student_contacts and line == "Address":
                in_student_address = True
                continue
            if in_student_contacts and line in {"Phone", "Gender", "EthnicityRace", "Language"}:
                in_student_address = False

            if line == "AgencyAssignedID" and idx + 1 < len(text_lines) and not student["student_id"]:
                student["student_id"] = text_lines[idx + 1].strip()
            elif line == "BirthDate" and idx + 1 < len(text_lines) and not student["date_of_birth"]:
                student["date_of_birth"] = text_lines[idx + 1].strip()
            elif line == "FirstName" and idx + 1 < len(text_lines) and in_student_name and not student["name"]:
                first = text_lines[idx + 1].strip().title()
                last = ""
                for look_ahead in range(idx + 2, min(idx + 8, len(text_lines) - 1)):
                    if text_lines[look_ahead] == "LastName":
                        last = text_lines[look_ahead + 1].strip().title()
                        break
                if first or last:
                    student["name"] = f"{first} {last}".strip()
            elif line == "AddressLine" and idx + 1 < len(text_lines) and in_student_address:
                if not student["address"]["street"]:
                    student["address"]["street"] = text_lines[idx + 1].strip().rstrip(",")
            elif line == "City" and idx + 1 < len(text_lines) and in_student_address and student["address"]["street"] and not student["address"]["city"]:
                student["address"]["city"] = text_lines[idx + 1].strip().title()
            elif line == "StateProvinceCode" and idx + 1 < len(text_lines) and in_student_address and student["address"]["street"] and not student["address"]["state"]:
                student["address"]["state"] = text_lines[idx + 1].strip()
            elif line == "PostalCode" and idx + 1 < len(text_lines) and in_student_address and student["address"]["street"] and not student["address"]["postal_code"]:
                student["address"]["postal_code"] = text_lines[idx + 1].strip()
        return student

    def _parse_formatted_xml_institutions(self, text_lines: List[str], document_type: str) -> List[Dict[str, Any]]:
        inst_type = "college" if document_type == "college_transcript" else "high_school" if document_type == "high_school_transcript" else "unknown"
        institutions: List[Dict[str, Any]] = []
        in_source_org = False
        for idx, line in enumerate(text_lines):
            if line == "Source":
                in_source_org = True
                continue
            if in_source_org and line == "Destination":
                break
            if in_source_org and line == "OrganizationName" and idx + 1 < len(text_lines):
                candidate = text_lines[idx + 1].strip().title()
                if candidate and candidate.lower() != "davis school district":
                    institutions.append({"name": candidate, "type": inst_type})
                    break
        return institutions

    def _parse_formatted_xml_summary(self, text_lines: List[str]) -> Dict[str, Any]:
        summary = {
            "gpa": None,
            "total_credits_attempted": None,
            "total_credits_earned": None,
            "class_rank": None,
        }
        for idx, line in enumerate(text_lines):
            if line == "CreditHoursAttempted" and idx + 1 < len(text_lines) and summary["total_credits_attempted"] is None:
                summary["total_credits_attempted"] = float(text_lines[idx + 1])
            elif line == "CreditHoursEarned" and idx + 1 < len(text_lines) and summary["total_credits_earned"] is None:
                summary["total_credits_earned"] = float(text_lines[idx + 1])
            elif line == "GradePointAverage" and idx + 1 < len(text_lines) and summary["gpa"] is None:
                summary["gpa"] = float(text_lines[idx + 1])
            elif line == "ClassRank" and idx + 1 < len(text_lines) and summary["class_rank"] is None:
                rank = text_lines[idx + 1].strip()
                size = ""
                if idx + 3 < len(text_lines) and text_lines[idx + 2] == "ClassSize":
                    size = text_lines[idx + 3].strip()
                summary["class_rank"] = f"{rank}/{size}" if size else rank
        return summary

    def _parse_formatted_xml_terms_and_courses(self, text_lines: List[str]) -> List[Dict[str, Any]]:
        terms: List[Dict[str, Any]] = []
        idx = 0
        current_term_name = "Unassigned"
        current_courses: List[Dict[str, Any]] = []

        while idx < len(text_lines):
            line = text_lines[idx]
            if line == "AcademicSession":
                if current_courses:
                    terms.append({"term_name": current_term_name, "courses": current_courses})
                    current_courses = []
                current_term_name, idx = self._consume_formatted_xml_session(text_lines, idx)
                continue
            if line == "Course":
                course, idx = self._consume_formatted_xml_course(text_lines, idx, current_term_name)
                if course:
                    current_courses.append(course)
                continue
            idx += 1

        if current_courses:
            terms.append({"term_name": current_term_name, "courses": current_courses})
        return terms

    def _consume_formatted_xml_session(self, text_lines: List[str], start_idx: int) -> Tuple[str, int]:
        session_year = ""
        school_name = ""
        idx = start_idx + 1
        while idx < len(text_lines):
            line = text_lines[idx]
            if line == "AcademicSession" or line == "Course":
                break
            if line == "SessionSchoolYear" and idx + 1 < len(text_lines):
                session_year = text_lines[idx + 1].strip()
            elif line == "OrganizationName" and idx > 0 and text_lines[idx - 1] == "School" and idx + 1 < len(text_lines):
                school_name = text_lines[idx + 1].strip().title()
            idx += 1
        term_name = f"{session_year} {school_name}".strip() or "Unassigned"
        return term_name, idx

    def _consume_formatted_xml_course(self, text_lines: List[str], start_idx: int, current_term_name: str) -> Tuple[Dict[str, Any] | None, int]:
        idx = start_idx + 1
        credits = None
        course_code = None
        course_title = None
        supplemental_grades: List[Tuple[int, str]] = []

        while idx < len(text_lines):
            line = text_lines[idx]
            if line in {"Course", "AcademicSession"}:
                break
            if line == "CourseCreditEarned" and idx + 1 < len(text_lines):
                try:
                    credits = float(text_lines[idx + 1].strip())
                except ValueError:
                    credits = None
            elif line == "AgencyCourseID" and idx + 1 < len(text_lines):
                course_code = text_lines[idx + 1].strip()
            elif line == "CourseTitle" and idx + 1 < len(text_lines):
                course_title = text_lines[idx + 1].strip()
            elif line == "SupplementalGradeSubSession" and idx + 3 < len(text_lines) and text_lines[idx + 2] == "Grade":
                try:
                    sub = int(text_lines[idx + 1].strip())
                except ValueError:
                    sub = 0
                supplemental_grades.append((sub, text_lines[idx + 3].strip().upper()))
            idx += 1

        if not course_title:
            return None, idx
        selected_grade = ""
        if supplemental_grades:
            selected_grade = sorted(supplemental_grades, key=lambda item: item[0])[-1][1]
        confidence_score, confidence_reasons = self._estimate_course_confidence(
            course_code=course_code,
            course_title=course_title,
            credits=credits,
            grade=selected_grade,
            term=current_term_name,
        )
        course = {
            "course_code": course_code,
            "course_title": course_title,
            "credits": credits,
            "grade": selected_grade or None,
            "term": current_term_name,
            "confidence_score": confidence_score,
            "confidence_reasons": confidence_reasons,
        }
        return course, idx

    def _parse_student(self, text_lines: List[str]) -> Dict[str, Any]:
        student = {
            "name": None,
            "student_id": None,
            "date_of_birth": None,
            "address": {"street": None, "city": None, "state": None, "postal_code": None},
        }
        for line in text_lines[:30]:
            for pattern in self.STUDENT_NAME_PATTERNS:
                match = pattern.search(line)
                if match and not student["name"]:
                    student["name"] = self._normalize_name_value(match.group(1).strip())
            for pattern in self.STUDENT_ID_PATTERNS:
                match = pattern.search(line)
                if match and not student["student_id"]:
                    student["student_id"] = match.group(1).strip()
            dob_match = re.search(r"\b(?:DOB|Date of Birth|Birth Date)[:\-]?\s*([0-9Xx/\-]{6,12})\b", line, re.IGNORECASE)
            if dob_match and not student["date_of_birth"]:
                student["date_of_birth"] = dob_match.group(1)
        if not student["name"]:
            student["name"] = self._extract_labeled_name_value(text_lines, "Student Name")
        if not student["name"] and text_lines:
            first_line = text_lines[0].strip()
            if 2 <= len(first_line.split()) <= 5 and "course name" in first_line.lower():
                student["name"] = self._normalize_name_value(first_line.split("Course Name")[0].strip())
        if not student["name"]:
            student["name"] = self._extract_top_name(text_lines)
        if not student["name"]:
            student["name"] = self._extract_school_report_wrapper_name(text_lines)
        student = self._parse_trailing_student_fields(text_lines, student)
        for idx, line in enumerate(text_lines[:40]):
            if re.search(r"(Permanent Address|Address as of)", line, re.IGNORECASE) and idx + 2 < len(text_lines):
                street = text_lines[idx + 1].strip()
                city_line = text_lines[idx + 2].strip()
                city_match = re.search(r"^(.+?),\s*([A-Z]{2})\s+(\d{5}(?:-\d{4})?)$", city_line)
                if street:
                    student["address"]["street"] = street
                if city_match:
                    student["address"]["city"] = city_match.group(1)
                    student["address"]["state"] = city_match.group(2)
                    student["address"]["postal_code"] = city_match.group(3)
                break
        return student

    def _parse_institutions(self, text_lines: List[str], document_type: str) -> List[Dict[str, Any]]:
        institutions: List[Dict[str, Any]] = []
        inst_type = "college" if document_type == "college_transcript" else "high_school" if document_type == "high_school_transcript" else "unknown"
        preferred = self._preferred_institution_line(text_lines, document_type)
        if preferred:
            return [{"name": preferred, "type": inst_type}]
        normalized_lines = [line.strip() for line in text_lines[:25] if line.strip()]
        for idx, line in enumerate(normalized_lines):
            candidate = self._merge_institution_line_fragments(normalized_lines, idx)
            if any(keyword in candidate.lower() for keyword in self.INSTITUTION_KEYWORDS) and not self._looks_like_courseish_institution_candidate(candidate):
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

    def _normalize_name_value(self, value: str) -> str:
        text = re.sub(r"\s+", " ", value.strip())
        if "," not in text:
            return text
        parts = [part.strip() for part in text.split(",", 1)]
        if len(parts) != 2:
            return text
        return f"{parts[1]} {parts[0]}".strip()

    def _parse_terms_and_courses(self, text_lines: List[str]) -> List[Dict[str, Any]]:
        current_term = "Unassigned"
        bucket: dict[str, list[TranscriptCourse]] = defaultdict(list)

        for line in text_lines:
            if TERM_PATTERN.search(line):
                current_term = line.strip()
                continue
            if self._looks_like_high_school_year_header(line):
                current_term = line.strip()
                continue

            if line.strip().startswith("-") and bucket.get(current_term):
                previous = bucket[current_term][-1]
                previous.course_title = f"{previous.course_title or ''} {line.strip().lstrip('-').strip()}".strip()
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
                                "confidence_score": c.confidence_score,
                                "confidence_reasons": c.confidence_reasons,
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

        if self._should_skip_non_course_line(compact):
            return None

        pattern_match = self.COURSE_LINE_PATTERN.match(compact) or self.COURSE_LINE_PATTERN_GRADE_THEN_CREDITS.match(compact)
        if pattern_match:
            course_code = pattern_match.group("course_code").replace(" ", "")
            if course_code.upper().startswith("TOTAL"):
                return None
            course_title = pattern_match.group("course_title").strip(" -")
            credits = float(pattern_match.group("credits"))
            grade = pattern_match.group("grade").upper()
            confidence_score, confidence_reasons = self._estimate_course_confidence(
                course_code=course_code,
                course_title=course_title,
                credits=credits,
                grade=grade,
                term=None,
            )
            return TranscriptCourse(
                course_code=course_code,
                course_title=course_title or None,
                credits=credits,
                grade=grade,
                confidence_score=confidence_score,
                confidence_reasons=confidence_reasons,
            )

        hs_course = self._parse_high_school_course_line(compact)
        if hs_course:
            return hs_course

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

        code_match = re.match(rf"^({self.COURSE_CODE_PATTERN})\b", compact)
        if not code_match:
            return None

        course_code = code_match.group(1).replace(" ", "")
        if course_code.upper().startswith("TOTAL"):
            return None
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
        if title and title.startswith("(") and credits is None and grade is None:
            return None
        confidence_score, confidence_reasons = self._estimate_course_confidence(
            course_code=course_code,
            course_title=title,
            credits=credits,
            grade=grade,
            term=None,
        )
        return TranscriptCourse(
            course_code=course_code,
            course_title=title,
            credits=credits,
            grade=grade,
            confidence_score=confidence_score,
            confidence_reasons=confidence_reasons,
        )

    def _parse_high_school_course_line(self, compact: str) -> TranscriptCourse | None:
        match = re.match(
            r"^(?P<title>.+?)\s+(?P<grade_level>9|10|11|12)\s+(?P<grade>A\+?|A-|B\+?|B-|C\+?|C-|D\+?|D-|F|P|NP|S|U|W|I|IP|CR|NC|TR|PR)\s+(?P<credits>\d+(?:\.\d+)?)\b",
            compact,
            re.IGNORECASE,
        )
        if not match:
            return None
        course_title = match.group("title").strip(" -")
        if not course_title or len(course_title) < 3:
            return None
        confidence_score, confidence_reasons = self._estimate_course_confidence(
            course_code=None,
            course_title=course_title,
            credits=float(match.group("credits")),
            grade=match.group("grade").upper(),
            term=None,
        )
        return TranscriptCourse(
            course_code=None,
            course_title=course_title,
            credits=float(match.group("credits")),
            grade=match.group("grade").upper(),
            confidence_score=confidence_score,
            confidence_reasons=confidence_reasons,
        )

    def _looks_like_high_school_year_header(self, line: str) -> bool:
        return bool(re.match(r"^\d{2}-\d{2}\s+.+(?:High School|Junior High School|Digital Learning Alliance)\s*$", line.strip(), re.IGNORECASE))

    def _should_skip_non_course_line(self, compact: str) -> bool:
        lowered = compact.lower()
        skip_prefixes = (
            "test scores",
            "grading scale",
            "gpa summary",
            "school official",
            "date printed:",
            "accredited by",
            "official transcript",
            "prepared for:",
            "page ",
            "student number:",
            "state id:",
            "birth date:",
            "graduation date:",
            "cum wt gpa:",
            "cum unwt gpa:",
            "total credits earned:",
            "rank:",
            "civics test",
            "senior project",
        )
        if lowered.startswith(skip_prefixes):
            return True
        if compact in {"P", "0.25", "00/00/0000"}:
            return True
        if re.fullmatch(r"\d{9,}", compact):
            return True
        return False

    def _preferred_institution_line(self, text_lines: List[str], document_type: str) -> str | None:
        for line in text_lines[:25]:
            lowered = line.strip().lower()
            if "madison college unofficial" in lowered or lowered == "madison college":
                return "Madison College"
        if document_type == "high_school_transcript":
            for idx, line in enumerate(text_lines):
                if line.strip().lower() == "gpa summary":
                    for candidate in text_lines[idx : min(idx + 10, len(text_lines))]:
                        if re.search(r"high school", candidate, re.IGNORECASE):
                            return candidate.strip()
        for idx, line in enumerate(text_lines):
            if re.search(r"high school transcript", line, re.IGNORECASE):
                window = text_lines[max(0, idx - 5) : idx + 2]
                for candidate in window:
                    if (
                        re.search(r"(high school|university|college)", candidate, re.IGNORECASE)
                        and "transcript" not in candidate.lower()
                        and not self._looks_like_courseish_institution_candidate(candidate)
                    ):
                        return candidate.strip()
        return None

    def _looks_like_courseish_institution_candidate(self, candidate: str) -> bool:
        compact = re.sub(r"\s+", " ", (candidate or "").strip())
        if not compact:
            return False
        if re.search(r"\b[A-Z]{2,12}\s+\d{4,8}\b", compact):
            return True
        if re.search(r"\b\d+\.\d{2}\b", compact):
            return True
        if looks_like_grade(compact.split()[-1]):
            return True
        if re.search(r"\b(Attempted|Earned|Grade|Points|Term GPA|Cum GPA|Totals|Course Topic|Repeated:)\b", compact, re.IGNORECASE):
            return True
        return False

    def _parse_trailing_student_fields(self, text_lines: List[str], student: Dict[str, Any]) -> Dict[str, Any]:
        for idx, line in enumerate(text_lines):
            if line.strip().lower() == "student number:" and idx + 1 < len(text_lines) and not student["student_id"]:
                if re.fullmatch(r"\d+", text_lines[idx + 1].strip()):
                    student["student_id"] = text_lines[idx + 1].strip()
            if line.strip().lower() == "birth date:" and idx + 1 < len(text_lines) and not student["date_of_birth"]:
                if re.fullmatch(r"[0-9Xx/\-]{6,12}", text_lines[idx + 1].strip()):
                    student["date_of_birth"] = text_lines[idx + 1].strip()
        labels = [line.strip().lower() for line in text_lines]
        try:
            student_number_idx = max(idx for idx, label in enumerate(labels) if label == "student number:")
            state_id_idx = max(idx for idx, label in enumerate(labels) if label == "state id:")
            birth_date_idx = max(idx for idx, label in enumerate(labels) if label == "birth date:")
            graduation_idx = max(idx for idx, label in enumerate(labels) if label == "graduation date:")
            if student_number_idx < state_id_idx < birth_date_idx < graduation_idx:
                trailing_values = [line.strip() for line in text_lines[graduation_idx + 1 : graduation_idx + 8] if line.strip()]
                if len(trailing_values) >= 3:
                    candidate_student_number = trailing_values[0]
                    candidate_birth_date = trailing_values[2]
                    if not student["student_id"] and re.fullmatch(r"\d+", candidate_student_number):
                        student["student_id"] = candidate_student_number
                    if not student["date_of_birth"] and re.fullmatch(r"[0-9Xx/\-]{6,12}", candidate_birth_date):
                        student["date_of_birth"] = candidate_birth_date
        except ValueError:
            pass
        return student

    def _estimate_confidence(
        self,
        student: Dict[str, Any],
        institutions: List[Dict[str, Any]],
        summary: Dict[str, Any],
        terms: List[Dict[str, Any]],
        course_summary: Dict[str, Any],
    ) -> float:
        score = 0.0
        if student.get("name"):
            score += 0.12
        if student.get("student_id"):
            score += 0.08
        if institutions:
            score += 0.10
        if summary.get("gpa") is not None:
            score += 0.10
        if summary.get("total_credits_attempted") is not None or summary.get("total_credits_earned") is not None:
            score += 0.08
        if summary.get("class_rank"):
            score += 0.05

        term_count = len(terms)
        if term_count > 0:
            score += 0.10

        course_count = sum(len(term.get("courses", [])) for term in terms)
        if course_count >= 3:
            score += 0.12
        elif course_count > 0:
            score += 0.06

        assigned_courses = sum(
            1
            for term in terms
            if term.get("term_name") and term.get("term_name") != "Unassigned"
            for _ in term.get("courses", [])
        )
        if course_count and assigned_courses / course_count >= 0.6:
            score += 0.10

        score += min(float(course_summary.get("average", 0.0)) * 0.25, 0.25)
        return round(min(score, 1.0), 4)

    def ensure_course_confidences(self, terms: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        for term in terms:
            term_name = term.get("term_name")
            for course in term.get("courses", []):
                score = course.get("confidence_score")
                reasons = course.get("confidence_reasons")
                if isinstance(score, (int, float)) and score > 0:
                    if reasons is None:
                        course["confidence_reasons"] = []
                    continue
                confidence_score, confidence_reasons = self._estimate_course_confidence(
                    course_code=course.get("course_code"),
                    course_title=course.get("course_title"),
                    credits=course.get("credits"),
                    grade=course.get("grade"),
                    term=course.get("term") or term_name,
                )
                course["confidence_score"] = confidence_score
                course["confidence_reasons"] = confidence_reasons
        return terms

    def summarize_course_confidence(self, terms: List[Dict[str, Any]]) -> Dict[str, Any]:
        scores: List[float] = []
        low_confidence_count = 0
        for term in terms:
            for course in term.get("courses", []):
                score = float(course.get("confidence_score") or 0.0)
                scores.append(score)
                if score < 0.7:
                    low_confidence_count += 1
        total = len(scores)
        average = round(sum(scores) / total, 4) if total else 0.0
        minimum = round(min(scores), 4) if scores else 0.0
        return {
            "average": average,
            "minimum": minimum,
            "count": total,
            "low_confidence_count": low_confidence_count,
        }

    def _estimate_course_confidence(
        self,
        course_code: Any,
        course_title: Any,
        credits: Any,
        grade: Any,
        term: Any,
    ) -> Tuple[float, List[str]]:
        score = 0.0
        reasons: List[str] = []

        normalized_code = str(course_code or "").strip()
        normalized_title = str(course_title or "").strip()
        normalized_grade = str(grade or "").strip()
        normalized_term = str(term or "").strip()

        if normalized_code:
            score += 0.35
        else:
            reasons.append("missing course code")

        if normalized_title and len(normalized_title) >= 4 and any(ch.isalpha() for ch in normalized_title):
            score += 0.25
        else:
            reasons.append("weak course title")

        if credits is not None:
            score += 0.15
        else:
            reasons.append("missing credits")

        if normalized_grade and looks_like_grade(normalized_grade):
            score += 0.15
        else:
            reasons.append("missing or invalid grade")

        if normalized_term and normalized_term != "Unassigned":
            score += 0.10
        else:
            reasons.append("term not assigned")

        if normalized_title and re.search(r"[A-Za-z]{3,}", normalized_title):
            score += 0.05

        return round(min(score, 1.0), 4), reasons
