import json
import re
from typing import Any, Dict, List, Tuple
from uuid import uuid4

from app.models.api_models import AuditModel
from app.utils.text_utils import normalize_for_match


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
    r"(?:(Spring|Summer|Fall|Winter|Spng)(?:\s+(I|II|III|IV))?\s+)?((?:19|20)\d{2}(?:\s*-\s*(?:19|20)\d{2})?)",
    re.IGNORECASE,
)


class TranscriptResponseMapper:
    def map(self, parsed: Dict[str, Any], raw_text: str, metadata: Dict[str, Any]) -> Dict[str, Any]:
        document_id = str(uuid4())
        student = parsed.get("student", {})
        institutions = parsed.get("institutions", [])
        institution_name = institutions[0].get("name", "") if institutions else ""
        institution_name = self._preferred_institution_name(institution_name, metadata)
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
            "studentAddress": student.get("address", {}).get("street") or "",
            "studentCity": student.get("address", {}).get("city") or "",
            "studentState": student.get("address", {}).get("state") or "",
            "studentPostalCode": student.get("address", {}).get("postal_code") or "",
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
        line_locations = metadata.get("line_locations", []) or []
        used_line_indexes: set[int] = set()
        for term_block in parsed.get("terms", []):
            term_name = term_block.get("term_name") or ""
            term, year = self._split_term_year(term_name)
            for course in term_block.get("courses", []):
                course_id = course.get("course_code") or ""
                grade = course.get("grade") or ""
                credits = course.get("credits")
                course_confidence = round(float(course.get("confidence_score", parser_confidence) or parser_confidence), 4)
                confidence_reasons = course.get("confidence_reasons") or []
                matched_line = self._match_course_line(
                    course=course,
                    term_name=term_name,
                    line_locations=line_locations,
                    used_line_indexes=used_line_indexes,
                )
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
                        "confidenceScore": course_confidence,
                        "notes": self._build_course_note(metadata.get("text_source", "heuristic"), confidence_reasons),
                        "tenantCourseCodes": None,
                        "equivalencyId": None,
                        "mappingStatus": self._mapping_status(course_id=course_id, course_title=course.get("course_title"), confidence_score=course_confidence),
                        "transferGrade": "",
                        "transferStatus": "",
                        "ruleApplied": "heuristic_parser",
                        "boundingBox": {
                            "left": float(matched_line.get("bounding_box", {}).get("left", 0.0)) if matched_line else 0.0,
                            "top": float(matched_line.get("bounding_box", {}).get("top", 0.0)) if matched_line else 0.0,
                            "width": float(matched_line.get("bounding_box", {}).get("width", 0.0)) if matched_line else 0.0,
                            "height": float(matched_line.get("bounding_box", {}).get("height", 0.0)) if matched_line else 0.0,
                        },
                        "pageNumber": int(matched_line.get("page_number", 1)) if matched_line else 1,
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
        if "," in full_name:
            parts = [part.strip() for part in full_name.split(",", 1)]
            if len(parts) == 2:
                tokens = [token for token in parts[1].split() if token]
                first = tokens[0] if tokens else ""
                middle = " ".join(tokens[1:]) if len(tokens) > 1 else ""
                return first, middle, parts[0]
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
        session = (match.group(2) or "").upper()
        if term and session:
            term = f"{term} {session}"
        year = re.sub(r"\s+", "", match.group(3) or "")
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

    def _build_course_note(self, text_source: str, confidence_reasons: List[str]) -> str:
        note = f"Extracted from {text_source} parsing flow."
        if confidence_reasons:
            note += f" Review signals: {', '.join(confidence_reasons)}."
        return note

    def _mapping_status(self, course_id: str, course_title: Any, confidence_score: float) -> str:
        if not (course_id or course_title):
            return "unmapped"
        if confidence_score < 0.7:
            return "review"
        return "mapped"

    def _preferred_institution_name(self, parsed_name: str, metadata: Dict[str, Any]) -> str:
        if parsed_name and not any(flag in parsed_name.lower() for flag in ("statement of authenticity", "prepared for:")):
            return parsed_name
        header_name = self._institution_from_line_locations(metadata.get("line_locations", []) or [])
        if header_name:
            return header_name
        return self._institution_from_raw_text(metadata.get("raw_text_excerpt", "") or "") or parsed_name

    def _institution_from_line_locations(self, line_locations: List[Dict[str, Any]]) -> str:
        candidates = []
        for line in line_locations:
            if int(line.get("page_number", 0) or 0) != 1:
                continue
            bbox = line.get("bounding_box", {})
            if float(bbox.get("top", 9999.0) or 9999.0) > 80.0:
                continue
            text = (line.get("text") or "").strip()
            lowered = text.lower()
            if "university" in lowered or "college" in lowered or "school" in lowered:
                if "statement of authenticity" in lowered or "prepared for:" in lowered:
                    continue
                candidates.append(text)
        if not candidates:
            return ""
        best = candidates[0]
        return re.sub(r"^[A-Z]{1,3}\s+", "", best).strip()

    def _institution_from_raw_text(self, raw_text: str) -> str:
        patterns = [
            r"Official Academic Transcript from\s+([^\n]+)",
            r"SS\s+([^\n]+University[^\n]+)",
            r"^([^\n]+University[^\n]*)$",
        ]
        for pattern in patterns:
            match = re.search(pattern, raw_text, re.IGNORECASE | re.MULTILINE)
            if match:
                return match.group(1).strip()
        return ""

    def _match_course_line(
        self,
        course: Dict[str, Any],
        term_name: str,
        line_locations: List[Dict[str, Any]],
        used_line_indexes: set[int],
    ) -> Dict[str, Any] | None:
        candidate_indexes = self._candidate_indexes_for_course(course=course, term_name=term_name, line_locations=line_locations)
        source_line = normalize_for_match(course.get("source_line") or "")
        if source_line:
            exact_index = self._match_source_line(
                source_line=source_line,
                line_locations=line_locations,
                used_line_indexes=used_line_indexes,
                candidate_indexes=candidate_indexes,
            )
            if exact_index is not None:
                return self._build_row_match_from_index(
                    matched_index=exact_index,
                    line_locations=line_locations,
                    used_line_indexes=used_line_indexes,
                )

        best_index = None
        best_score = 0
        course_code = normalize_for_match(course.get("course_code") or "")
        course_title = normalize_for_match(course.get("course_title") or "")
        grade = normalize_for_match(course.get("grade") or "")
        term = normalize_for_match(course.get("term") or term_name or "")
        credits = normalize_for_match(self._stringify(course.get("credits")))

        for idx, line in enumerate(line_locations):
            if candidate_indexes is not None and idx not in candidate_indexes:
                continue
            if idx in used_line_indexes:
                continue
            normalized_line = line.get("normalized_text") or normalize_for_match(line.get("text") or "")
            score = 0
            if course_code and course_code in normalized_line:
                score += 5
            if course_title and course_title in normalized_line:
                score += 4
            elif course_title:
                title_tokens = [token for token in re.findall(r"[a-z0-9]+", (course.get("course_title") or "").lower()) if len(token) >= 4]
                matches = sum(1 for token in title_tokens if token in (line.get("text") or "").lower())
                score += min(matches, 3)
            if grade and grade in normalized_line:
                score += 2
            if credits and credits in normalized_line:
                score += 2
            if term and term in normalized_line:
                score += 1
            if score > best_score:
                best_score = score
                best_index = idx

        if best_index is None or best_score < 5:
            return None

        return self._build_row_match_from_index(
            matched_index=best_index,
            line_locations=line_locations,
            used_line_indexes=used_line_indexes,
        )

    def _match_source_line(
        self,
        source_line: str,
        line_locations: List[Dict[str, Any]],
        used_line_indexes: set[int],
        candidate_indexes: set[int] | None = None,
    ) -> int | None:
        exact_matches: list[int] = []
        for idx, line in enumerate(line_locations):
            if candidate_indexes is not None and idx not in candidate_indexes:
                continue
            if idx in used_line_indexes:
                continue
            normalized_line = line.get("normalized_text") or normalize_for_match(line.get("text") or "")
            if normalized_line == source_line:
                exact_matches.append(idx)
        if exact_matches:
            return max(exact_matches, key=lambda idx: len(line_locations[idx].get("normalized_text") or ""))

        containment_matches: list[int] = []
        for idx, line in enumerate(line_locations):
            if candidate_indexes is not None and idx not in candidate_indexes:
                continue
            if idx in used_line_indexes:
                continue
            normalized_line = line.get("normalized_text") or normalize_for_match(line.get("text") or "")
            if source_line in normalized_line or normalized_line in source_line:
                containment_matches.append(idx)
        if containment_matches:
            return max(containment_matches, key=lambda idx: len(line_locations[idx].get("normalized_text") or ""))
        return None

    def _candidate_indexes_for_course(
        self,
        course: Dict[str, Any],
        term_name: str,
        line_locations: List[Dict[str, Any]],
    ) -> set[int] | None:
        source_term_line = normalize_for_match(course.get("source_term_line") or "")
        if not source_term_line:
            return None
        header_index = self._match_header_line(source_term_line=source_term_line, line_locations=line_locations)
        if header_index is None:
            return None

        header_line = line_locations[header_index]
        page_number = int(header_line.get("page_number", 1) or 1)
        header_top = float(header_line.get("bounding_box", {}).get("top", 0.0) or 0.0)
        header_left = float(header_line.get("bounding_box", {}).get("left", 0.0) or 0.0)
        header_height = float(header_line.get("bounding_box", {}).get("height", 0.0) or 0.0)
        next_header_min_gap = max(header_height * 2.0, 0.01)
        next_header_top = None
        column_left, column_right = self._column_bounds_for_header(
            header_index=header_index,
            line_locations=line_locations,
            page_number=page_number,
            header_top=header_top,
            header_left=header_left,
            header_height=header_height,
        )
        for idx, line in enumerate(line_locations):
            if idx == header_index:
                continue
            if int(line.get("page_number", 1) or 1) != page_number:
                continue
            top = float(line.get("bounding_box", {}).get("top", 0.0) or 0.0)
            if top <= header_top + next_header_min_gap:
                continue
            if self._looks_like_term_header(line.get("text") or ""):
                if next_header_top is None or top < next_header_top:
                    next_header_top = top

        candidates = set()
        for idx, line in enumerate(line_locations):
            if int(line.get("page_number", 1) or 1) != page_number:
                continue
            top = float(line.get("bounding_box", {}).get("top", 0.0) or 0.0)
            left = float(line.get("bounding_box", {}).get("left", 0.0) or 0.0)
            if top < header_top:
                continue
            if next_header_top is not None and top >= next_header_top:
                continue
            if column_left is not None and left + 0.0001 < column_left:
                continue
            if column_right is not None and left >= column_right:
                continue
            candidates.add(idx)
        return candidates

    def _column_bounds_for_header(
        self,
        header_index: int,
        line_locations: List[Dict[str, Any]],
        page_number: int,
        header_top: float,
        header_left: float,
        header_height: float,
    ) -> Tuple[float | None, float | None]:
        same_band_tolerance = max(header_height * 1.5, 0.01)
        same_band_headers: list[Tuple[int, float]] = []
        for idx, line in enumerate(line_locations):
            if int(line.get("page_number", 1) or 1) != page_number:
                continue
            top = float(line.get("bounding_box", {}).get("top", 0.0) or 0.0)
            if abs(top - header_top) > same_band_tolerance:
                continue
            if not self._looks_like_term_header(line.get("text") or ""):
                continue
            left = float(line.get("bounding_box", {}).get("left", 0.0) or 0.0)
            same_band_headers.append((idx, left))

        if len(same_band_headers) <= 1:
            return None, None

        same_band_headers.sort(key=lambda item: item[1])
        current_pos = next((pos for pos, (idx, _) in enumerate(same_band_headers) if idx == header_index), None)
        if current_pos is None:
            return None, None

        left_bound = None
        right_bound = None
        if current_pos > 0:
            left_bound = same_band_headers[current_pos - 1][1] + 0.01
        if current_pos + 1 < len(same_band_headers):
            right_bound = same_band_headers[current_pos + 1][1] - 0.01
        return left_bound, right_bound

    def _match_header_line(self, source_term_line: str, line_locations: List[Dict[str, Any]]) -> int | None:
        exact_matches: list[int] = []
        containment_matches: list[int] = []
        for idx, line in enumerate(line_locations):
            normalized_line = line.get("normalized_text") or normalize_for_match(line.get("text") or "")
            if normalized_line == source_term_line:
                exact_matches.append(idx)
            elif source_term_line in normalized_line or normalized_line in source_term_line:
                containment_matches.append(idx)
        if exact_matches:
            return max(exact_matches, key=lambda idx: len(line_locations[idx].get("normalized_text") or ""))
        if containment_matches:
            return max(containment_matches, key=lambda idx: len(line_locations[idx].get("normalized_text") or ""))
        return None

    def _build_row_match_from_index(
        self,
        matched_index: int,
        line_locations: List[Dict[str, Any]],
        used_line_indexes: set[int],
    ) -> Dict[str, Any]:
        matched_line = line_locations[matched_index]
        if matched_line.get("synthetic_row"):
            used_line_indexes.add(matched_index)
            return matched_line
        row_indexes = self._row_fragment_indexes(matched_index=matched_index, line_locations=line_locations)
        if not row_indexes:
            used_line_indexes.add(matched_index)
            return matched_line

        for idx in row_indexes:
            used_line_indexes.add(idx)

        fragments = [line_locations[idx] for idx in row_indexes]
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
        return {
            "text": " ".join((fragment.get("text") or "").strip() for fragment in fragments if (fragment.get("text") or "").strip()),
            "normalized_text": normalize_for_match(" ".join((fragment.get("text") or "").strip() for fragment in fragments)),
            "page_number": matched_line.get("page_number", 1),
            "bounding_box": {
                "left": left,
                "top": top,
                "width": max(right - left, 0.0),
                "height": max(bottom - top, 0.0),
            },
        }

    def _row_fragment_indexes(self, matched_index: int, line_locations: List[Dict[str, Any]]) -> List[int]:
        matched_line = line_locations[matched_index]
        matched_bbox = matched_line.get("bounding_box", {})
        matched_left = float(matched_bbox.get("left", 0.0) or 0.0)
        matched_top = float(matched_bbox.get("top", 0.0) or 0.0)
        page_number = int(matched_line.get("page_number", 1) or 1)
        top_tolerance = max(float(matched_bbox.get("height", 0.0) or 0.0) * 1.5, 0.01)

        same_row_indexes = [
            idx
            for idx, line in enumerate(line_locations)
            if int(line.get("page_number", 1) or 1) == page_number
            and abs(float(line.get("bounding_box", {}).get("top", 0.0) or 0.0) - matched_top) <= top_tolerance
        ]
        same_row_indexes.sort(key=lambda idx: float(line_locations[idx].get("bounding_box", {}).get("left", 0.0) or 0.0))

        title_like_indexes = [idx for idx in same_row_indexes if self._is_title_like_fragment(line_locations[idx])]
        next_title_left = None
        for idx in title_like_indexes:
            left = float(line_locations[idx].get("bounding_box", {}).get("left", 0.0) or 0.0)
            if left > matched_left + 0.005:
                next_title_left = left
                break

        selected = []
        for idx in same_row_indexes:
            bbox = line_locations[idx].get("bounding_box", {})
            left = float(bbox.get("left", 0.0) or 0.0)
            if left + 0.0001 < matched_left:
                continue
            if next_title_left is not None and left >= next_title_left - 0.002:
                continue
            selected.append(idx)
        return selected or [matched_index]

    def _is_title_like_fragment(self, line: Dict[str, Any]) -> bool:
        text = (line.get("text") or "").strip()
        lowered = text.lower()
        if not text:
            return False
        if lowered in {"course no title", "session", "grade", "credits", "session grade credits"}:
            return False
        alpha_tokens = re.findall(r"[A-Za-z]{3,}", text)
        return bool(alpha_tokens)

    def _looks_like_term_header(self, text: str) -> bool:
        normalized = normalize_for_match(text or "")
        if not normalized:
            return False
        return bool(re.search(r"20\d{2}20\d{2}", normalized) and re.search(r"[a-z]{4,}", normalized))

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
