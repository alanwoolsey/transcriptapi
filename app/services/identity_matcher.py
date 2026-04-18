import re
from difflib import SequenceMatcher
from typing import Any, Dict, List


class IdentityMatcher:
    def compare_documents(self, left: Dict[str, Any], right: Dict[str, Any]) -> Dict[str, Any]:
        left_identity = self._extract_identity(left)
        right_identity = self._extract_identity(right)

        reasons: List[str] = []
        score = 0.0

        name_score = self._score_name(left_identity["full_name"], right_identity["full_name"])
        if name_score >= 0.95:
            score += 0.35
            reasons.append("full name matches strongly after normalization")
        elif name_score >= 0.8:
            score += 0.25
            reasons.append("name matches with minor formatting differences")
        elif name_score >= 0.65:
            score += 0.12
            reasons.append("name partially matches")

        dob_match = self._score_dob(left_identity["dob"], right_identity["dob"])
        if dob_match == "exact":
            score += 0.30
            reasons.append("date of birth matches exactly")
        elif dob_match == "month_day":
            score += 0.20
            reasons.append("date of birth matches on month and day")

        address_score = self._score_address(left_identity["address"], right_identity["address"])
        if address_score >= 0.95:
            score += 0.25
            reasons.append("address matches strongly")
        elif address_score >= 0.8:
            score += 0.18
            reasons.append("address matches with minor normalization differences")

        email_score = self._score_exact_token(left_identity["email"], right_identity["email"])
        if email_score:
            score += 0.30
            reasons.append("email matches exactly")

        ssn_score = self._score_ssn(left_identity["ssn"], right_identity["ssn"])
        if ssn_score == "exact":
            score += 0.40
            reasons.append("social security number matches exactly")
        elif ssn_score == "last4":
            score += 0.18
            reasons.append("social security number matches on last four digits")

        degree_score, degree_reasons = self._score_degree_continuity(left, right)
        if degree_score > 0:
            score += degree_score
            reasons.extend(degree_reasons)

        decision = self._decision(score=score, name_score=name_score, dob_match=dob_match)
        return {
            "same_student_confidence": round(min(score, 1.0), 4),
            "decision": decision,
            "reasons": reasons,
            "signals": {
                "name_similarity": round(name_score, 4),
                "dob_match": dob_match,
                "address_similarity": round(address_score, 4),
                "email_match": email_score,
                "ssn_match": ssn_score,
                "degree_continuity_score": round(degree_score, 4),
            },
        }

    def _extract_identity(self, document: Dict[str, Any]) -> Dict[str, str]:
        demographic = document.get("demographic", {})
        raw_text = document.get("metadata", {}).get("raw_text_excerpt", "") or ""
        fallback_name = self._extract_name_from_text(raw_text)
        fallback_dob = self._extract_dob_from_text(raw_text)
        fallback_address = self._extract_address_from_text(raw_text)
        fallback_email = self._extract_email_from_text(raw_text)
        fallback_ssn = self._extract_ssn_from_text(raw_text)
        fallback_institution = self._extract_institution_from_text(raw_text)

        full_name = self._normalize_name(
            " ".join(
                part
                for part in [
                    demographic.get("firstName", "") or fallback_name.get("first", ""),
                    demographic.get("middleName", "") or fallback_name.get("middle", ""),
                    demographic.get("lastName", "") or fallback_name.get("last", ""),
                ]
                if part
            )
        )
        address = self._normalize_address(
            " ".join(
                part
                for part in [
                    demographic.get("studentAddress", "") or fallback_address.get("street", ""),
                    demographic.get("studentCity", "") or fallback_address.get("city", ""),
                    demographic.get("studentState", "") or fallback_address.get("state", ""),
                    demographic.get("studentPostalCode", "") or fallback_address.get("postal_code", ""),
                    demographic.get("studentCountry", ""),
                ]
                if part
            )
        )
        return {
            "full_name": full_name,
            "dob": self._normalize_dob(demographic.get("dateOfBirth", "") or fallback_dob),
            "address": address,
            "email": self._normalize_email(demographic.get("studentEmail", "") or demographic.get("email", "") or fallback_email),
            "ssn": self._normalize_ssn(demographic.get("ssn", "") or fallback_ssn),
            "institution": self._normalize_name(demographic.get("institutionName", "") or fallback_institution),
        }

    def _normalize_name(self, value: str) -> str:
        text = re.sub(r"\s+", " ", (value or "").strip())
        if "," in text:
            parts = [part.strip() for part in text.split(",") if part.strip()]
            if len(parts) >= 2:
                text = f"{parts[1]} {parts[0]}"
        return re.sub(r"[^a-z0-9 ]+", "", text.lower()).strip()

    def _normalize_dob(self, value: str) -> str:
        text = (value or "").strip()
        if not text:
            return ""
        digits = re.findall(r"\d+|X+", text.upper())
        if len(digits) >= 3:
            month = digits[0].zfill(2)
            day = digits[1].zfill(2)
            year = digits[2]
            return f"{month}/{day}/{year}"
        return text

    def _normalize_address(self, value: str) -> str:
        text = re.sub(r"\s+", " ", (value or "").strip().lower())
        replacements = {
            " street": " st",
            " avenue": " ave",
            " road": " rd",
            " drive": " dr",
            " boulevard": " blvd",
            " lane": " ln",
            " court": " ct",
            " apartment": " apt",
        }
        for source, target in replacements.items():
            text = text.replace(source, target)
        return re.sub(r"[^a-z0-9 ]+", "", text).strip()

    def _normalize_email(self, value: str) -> str:
        return (value or "").strip().lower()

    def _normalize_ssn(self, value: str) -> str:
        return "".join(ch for ch in (value or "") if ch.isdigit())

    def _score_name(self, left: str, right: str) -> float:
        if not left or not right:
            return 0.0
        if left == right:
            return 1.0
        left_parts = left.split()
        right_parts = right.split()
        if left_parts and right_parts:
            first_match = self._token_initial_match(left_parts[0], right_parts[0])
            last_match = self._token_initial_match(left_parts[-1], right_parts[-1])
            middle_match = 1.0
            if len(left_parts) > 2 and len(right_parts) > 2:
                middle_match = self._token_initial_match(" ".join(left_parts[1:-1]), " ".join(right_parts[1:-1]))
            elif len(left_parts) > 1 and len(right_parts) > 1:
                middle_match = self._token_initial_match(left_parts[1], right_parts[1])
            blended = (first_match * 0.35) + (last_match * 0.45) + (middle_match * 0.20)
            return max(blended, SequenceMatcher(None, left, right).ratio())
        return SequenceMatcher(None, left, right).ratio()

    def _token_initial_match(self, left: str, right: str) -> float:
        if not left or not right:
            return 0.0
        if left == right:
            return 1.0
        if left[0] == right[0]:
            if len(left) == 1 or len(right) == 1:
                return 0.9
            return 0.75
        return SequenceMatcher(None, left, right).ratio()

    def _score_dob(self, left: str, right: str) -> str:
        if not left or not right:
            return "none"
        if left == right:
            return "exact"
        left_parts = left.split("/")
        right_parts = right.split("/")
        if len(left_parts) == 3 and len(right_parts) == 3 and left_parts[:2] == right_parts[:2]:
            return "month_day"
        return "none"

    def _score_address(self, left: str, right: str) -> float:
        if not left or not right:
            return 0.0
        if left == right:
            return 1.0
        return SequenceMatcher(None, left, right).ratio()

    def _score_exact_token(self, left: str, right: str) -> bool:
        return bool(left and right and left == right)

    def _score_ssn(self, left: str, right: str) -> str:
        if not left or not right:
            return "none"
        if left == right:
            return "exact"
        if len(left) >= 4 and len(right) >= 4 and left[-4:] == right[-4:]:
            return "last4"
        return "none"

    def _score_degree_continuity(self, left: Dict[str, Any], right: Dict[str, Any]) -> tuple[float, List[str]]:
        reasons: List[str] = []
        score = 0.0
        left_institution = self._extract_identity(left)["institution"]
        right_institution = self._extract_identity(right)["institution"]
        left_text = self._normalize_free_text(left.get("metadata", {}).get("raw_text_excerpt", ""))
        right_text = self._normalize_free_text(right.get("metadata", {}).get("raw_text_excerpt", ""))
        left_degree_date = self._normalize_degree_date(left.get("demographic", {}).get("degreeAwardedDate", "") or left.get("demographic", {}).get("graduationDate", ""))
        right_degree_date = self._normalize_degree_date(right.get("demographic", {}).get("degreeAwardedDate", "") or right.get("demographic", {}).get("graduationDate", ""))

        if left_institution and left_institution in right_text:
            score += 0.15
            reasons.append("right document references the left institution")
        if right_institution and right_institution in left_text:
            score += 0.15
            reasons.append("left document references the right institution")
        if left_degree_date and left_degree_date in right_text:
            score += 0.10
            reasons.append("right document references the left degree date")
        if right_degree_date and right_degree_date in left_text:
            score += 0.10
            reasons.append("left document references the right degree date")

        return min(score, 0.25), reasons

    def _normalize_free_text(self, value: str) -> str:
        return re.sub(r"\s+", " ", (value or "").lower())

    def _normalize_degree_date(self, value: str) -> str:
        digits = re.findall(r"\d+", value or "")
        if len(digits) >= 2:
            return "/".join(digits[:3]) if len(digits) >= 3 else "/".join(digits[:2])
        return (value or "").strip().lower()

    def _decision(self, score: float, name_score: float, dob_match: str) -> str:
        if score >= 0.85:
            return "match"
        if score >= 0.6 and name_score >= 0.8 and dob_match in {"exact", "month_day"}:
            return "match"
        if score >= 0.45:
            return "review"
        return "different"

    def _extract_name_from_text(self, text: str) -> Dict[str, str]:
        candidates = [
            re.search(r"Student Name:\s*([^\n]+)", text, re.IGNORECASE),
            re.search(r"Name:\s*([^\n]+)", text, re.IGNORECASE),
        ]
        for match in candidates:
            if not match:
                continue
            return self._split_name(match.group(1).strip())
        return {"first": "", "middle": "", "last": ""}

    def _split_name(self, value: str) -> Dict[str, str]:
        text = re.sub(r"\s+", " ", value.strip())
        if "," in text:
            last, rest = [part.strip() for part in text.split(",", 1)]
            tokens = [token for token in rest.split(" ") if token]
            return {
                "first": tokens[0] if tokens else "",
                "middle": " ".join(tokens[1:]) if len(tokens) > 1 else "",
                "last": last,
            }
        tokens = [token for token in text.split(" ") if token]
        if len(tokens) == 1:
            return {"first": tokens[0], "middle": "", "last": ""}
        if len(tokens) == 2:
            return {"first": tokens[0], "middle": "", "last": tokens[1]}
        return {"first": tokens[0], "middle": " ".join(tokens[1:-1]), "last": tokens[-1]}

    def _extract_dob_from_text(self, text: str) -> str:
        match = re.search(r"(?:Birth Date|Date of Birth)[:\s]+([0-9Xx/\-]{6,12})", text, re.IGNORECASE)
        return match.group(1).strip() if match else ""

    def _extract_email_from_text(self, text: str) -> str:
        match = re.search(r"\b[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}\b", text, re.IGNORECASE)
        return match.group(0) if match else ""

    def _extract_ssn_from_text(self, text: str) -> str:
        match = re.search(r"\b\d{3}-\d{2}-\d{4}\b", text)
        return match.group(0) if match else ""

    def _extract_address_from_text(self, text: str) -> Dict[str, str]:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        for idx, line in enumerate(lines):
            if re.search(r"\b\d{2,6}\s+\w+", line) and idx + 1 < len(lines):
                city_line = lines[idx + 1]
                city_match = re.search(r"^(.+?),\s*([A-Z]{2})\s+(\d{5}(?:-\d{4})?)$", city_line)
                if city_match:
                    return {
                        "street": line,
                        "city": city_match.group(1),
                        "state": city_match.group(2),
                        "postal_code": city_match.group(3),
                    }
        return {"street": "", "city": "", "state": "", "postal_code": ""}

    def _extract_institution_from_text(self, text: str) -> str:
        candidates = [
            re.search(r"Official Academic Transcript from\s+([^\n]+)", text, re.IGNORECASE),
            re.search(r"Degrees Awarded:\s*\n?([^\n]+)", text, re.IGNORECASE),
            re.search(r"^([^\n]+University[^\n]*)$", text, re.IGNORECASE | re.MULTILINE),
        ]
        for match in candidates:
            if match:
                return match.group(1).strip()
        return ""
