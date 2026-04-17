import json
import re
from typing import Any, Dict, List, Tuple
from uuid import uuid4

from app.models.api_models import AuditModel


GRADE_POINTS = {
    "A+": 4.0,
    "A": 4.0,
    "A-": 3.7,
    "B+": 3.3,
    "B": 3.0,
    "B-": 2.7,
    "C+": 2.3,
    "C": 2.0,
    "C-": 1.7,
    "D+": 1.3,
    "D": 1.0,
    "D-": 0.7,
    "F": 0.0,
    "P": 0.0,
    "S": 0.0,
}

TERM_YEAR_PATTERN = re.compile(
    r"(?:(Spring|Summer|Fall|Winter)\s+)?((?:19|20)\d{2}(?:\s*-\s*(?:19|20)\d{2})?)",
    re.IGNORECASE,
)


class TranscriptResponseMapper:
    def map(self, parsed: Dict[str, Any], raw_text: str, metadata: Dict[str, Any]) -> Dict[str, Any]:
        document_id = str(uuid4())
        student = parsed.get("student", {})
        institutions = parsed.get("institutions", [])
        institution_name = institutions[0].get("name", "") if institutions else ""
        summary = parsed.get("academic_summary", {})
        courses = self._map_courses(parsed, institution_name, metadata)
        grade_point_map = self._build_grade_point_map(raw_text)
        grand_gpa = self._build_grand_gpa(summary, courses)
        term_gpas = self._build_term_gpas(courses)

        first_name, middle_name, last_name = self._split_name(student.get("name") or "")
        demographic = {
            "firstName": first_name,
            "lastName": last_name,
            "middleName": middle_name,
            "studentId": student.get("student_id") or "",
            "institutionId": "",
            "dateOfBirth": student.get("date_of_birth") or "",
            "ssn": "",
            "institutionName": institution_name,
            "institutionAddress": "",
            "institutionCity": "",
            "institutionState": "",
            "institutionPostalCode": "",
            "institutionCountry": "",
            "ceebCode": "",
            "official": "true" if institution_name else "",
            "accredited": "",
            "accreditationAgency": "",
            "cumulativeGpa": self._stringify(summary.get("gpa")),
            "weightedGpa": "",
            "unweightedGpa": self._stringify(summary.get("gpa")),
            "totalCreditsAttempted": self._stringify(summary.get("total_credits_attempted")),
            "totalCreditsEarned": self._stringify(summary.get("total_credits_earned")),
            "totalGradePoints": self._stringify(grand_gpa["simpleGPA"]),
            "classRank": summary.get("class_rank") or "",
            "weightedClassRank": "",
            "classSize": self._extract_class_size(summary.get("class_rank")),
            "weightedClassSize": "",
            "degreeAwarded": "",
            "degreeAwardedDate": "",
            "degreeAwarded2": "",
            "degreeAwardedDate2": "",
            "graduationDate": "",
            "studentAddress": "",
            "studentCity": "",
            "studentState": "",
            "studentPostalCode": "",
            "studentCountry": "",
            "actEnglishScore": "",
            "actEnglishDate": "",
            "actMathScore": "",
            "actMathDate": "",
            "actReadingScore": "",
            "actReadingDate": "",
            "actSciencesScore": "",
            "actSciencesDate": "",
            "actStemScore": "",
            "actStemDate": "",
            "actCompositeScore": "",
            "actCompositeDate": "",
            "satMathScore": "",
            "satMathDate": "",
            "satReadingScore": "",
            "satReadingDate": "",
            "satTotalScore": "",
            "satTotalDate": "",
        }

        audit_payload = {"workflowState": "Ready", "taskStatus": "Completed", "durationMs": 0}
        audit = [
            AuditModel(
                entityId=document_id,
                payloadJson=json.dumps(audit_payload, separators=(",", ":")),
            ).model_dump()
        ]

        return {
            "documentId": document_id,
            "demographic": demographic,
            "courses": courses,
            "gradePointMap": grade_point_map,
            "grandGPA": grand_gpa,
            "termGPAs": term_gpas,
            "audit": audit,
            "isOfficial": bool(institution_name),
            "isFinalized": False,
            "finalizedAt": None,
            "finalizedBy": None,
            "isFraudulent": False,
            "fraudFlaggedAt": None,
            "metadata": metadata,
        }

    def _map_courses(self, parsed: Dict[str, Any], institution_name: str, metadata: Dict[str, Any]) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        parser_confidence = float(metadata.get("parser_confidence", 0.0) or 0.0)
        for term_block in parsed.get("terms", []):
            term_name = term_block.get("term_name") or ""
            term, year = self._split_term_year(term_name)
            for course in term_block.get("courses", []):
                course_id = course.get("course_code") or ""
                grade = course.get("grade") or ""
                credits = course.get("credits")
                out.append(
                    {
                        "subject": self._subject_from_course_id(course_id),
                        "courseId": course_id,
                        "courseTitle": course.get("course_title") or "",
                        "credit": self._stringify(credits),
                        "grade": grade,
                        "gradePoints": self._stringify(GRADE_POINTS.get(grade)),
                        "term": term or term_name,
                        "year": year,
                        "startDate": "",
                        "endDate": "",
                        "transfer": "",
                        "repeat": "",
                        "courseType": "",
                        "rigor": "",
                        "confidenceScore": round(max(parser_confidence, 0.5), 4),
                        "notes": f"Extracted from {metadata.get('text_source', 'heuristic')} parsing flow.",
                        "tenantCourseCodes": None,
                        "equivalencyId": None,
                        "mappingStatus": "mapped" if course_id or course.get("course_title") else "unmapped",
                        "transferGrade": "",
                        "transferStatus": "",
                        "ruleApplied": "heuristic_parser",
                        "boundingBox": {
                            "left": 0.0,
                            "top": 0.0,
                            "width": 0.0,
                            "height": 0.0,
                        },
                        "pageNumber": 1,
                        "courseGpa": GRADE_POINTS.get(grade),
                        "institution": institution_name,
                        "equlCourseCode": None,
                        "equlCoreCode": None,
                        "creditAttempted": self._stringify(credits),
                        "courseLevel": self._course_level(course_id),
                        "equlSubject": None,
                        "equlDescription": None,
                        "equlCredit": None,
                        "equlTerm": None,
                        "equlYear": None,
                    }
                )
        return out

    def _build_grade_point_map(self, raw_text: str) -> List[Dict[str, Any]]:
        found = []
        if any(token in raw_text for token in ["A-", "B+", "C+"]):
            for grade, points in GRADE_POINTS.items():
                if grade in {"P", "S"}:
                    continue
                found.append(
                    {
                        "gradeAlpha": grade,
                        "gradePoints": points,
                        "gradePointsNumericRange": {"min": None, "max": None},
                    }
                )
        return found

    def _build_grand_gpa(self, summary: Dict[str, Any], courses: List[Dict[str, Any]]) -> Dict[str, Any]:
        units_earned = float(summary.get("total_credits_earned") or 0.0)
        simple_points = 0.0
        simple_units = 0.0
        for course in courses:
            if course["courseGpa"] is None:
                continue
            credit = self._to_float(course.get("credit"))
            if credit is None:
                continue
            simple_units += credit
            simple_points += credit * float(course["courseGpa"])

        simple_gpa = round(simple_points / simple_units, 4) if simple_units else 0.0
        return {
            "unitsEarned": units_earned,
            "simpleGPA": round(simple_points, 4),
            "cumulativeGPA": float(summary.get("gpa") or 0.0),
            "weightedGPA": 0.0,
        }

    def _build_term_gpas(self, courses: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        buckets: Dict[Tuple[str, str], Dict[str, float]] = {}
        for course in courses:
            term = course.get("term") or ""
            year = course.get("year") or ""
            key = (year, term)
            if key not in buckets:
                buckets[key] = {"units": 0.0, "points": 0.0}
            course_gpa = course.get("courseGpa")
            credit = self._to_float(course.get("credit"))
            if course_gpa is None or credit is None:
                continue
            buckets[key]["units"] += credit
            buckets[key]["points"] += credit * float(course_gpa)

        out: List[Dict[str, Any]] = []
        for idx, ((year, term), totals) in enumerate(buckets.items()):
            units = round(totals["units"], 4)
            points = round(totals["points"], 4)
            out.append(
                {
                    "uniqueRowId": idx,
                    "year": year,
                    "term": term,
                    "simpleUnitsEarned": units,
                    "simplePoints": points,
                    "simpleGPA": round(points / units, 4) if units else 0.0,
                }
            )
        return out

    def _split_name(self, full_name: str) -> Tuple[str, str, str]:
        parts = [part for part in full_name.split() if part]
        if not parts:
            return "", "", ""
        if len(parts) == 1:
            return parts[0], "", ""
        if len(parts) == 2:
            return parts[0], "", parts[1]
        return parts[0], " ".join(parts[1:-1]), parts[-1]

    def _split_term_year(self, term_name: str) -> Tuple[str, str]:
        match = TERM_YEAR_PATTERN.search(term_name)
        if not match:
            return term_name, ""
        term = (match.group(1) or "").title()
        year = re.sub(r"\s+", "", match.group(2) or "")
        return term, year

    def _subject_from_course_id(self, course_id: str) -> str:
        match = re.match(r"([A-Z]{2,6})", course_id or "")
        return match.group(1) if match else ""

    def _course_level(self, course_id: str) -> str:
        match = re.search(r"(\d{3,4})", course_id or "")
        if not match:
            return ""
        digits = match.group(1)
        return digits[0] + "00" if len(digits) >= 3 else digits

    def _extract_class_size(self, class_rank: str | None) -> str:
        if not class_rank:
            return ""
        match = re.search(r"/\s*(\d+)", class_rank)
        return match.group(1) if match else ""

    def _stringify(self, value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, float):
            return f"{value:g}"
        return str(value)

    def _to_float(self, value: Any) -> float | None:
        try:
            if value in (None, ""):
                return None
            return float(value)
        except (TypeError, ValueError):
            return None
