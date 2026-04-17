import re
from typing import Iterable, List


GRADE_PATTERN = re.compile(r"^(A\+?|A-|B\+?|B-|C\+?|C-|D\+?|D-|F|P|NP|S|U|W|I|IP|CR|NC)$", re.IGNORECASE)
TERM_PATTERN = re.compile(
    r"\b(Spring|Summer|Fall|Winter)\s+(19|20)\d{2}\b|\b(19|20)\d{2}\s+(Spring|Summer|Fall|Winter)\b",
    re.IGNORECASE,
)


def normalize_whitespace(text: str) -> str:
    text = text.replace("\x00", " ")
    text = re.sub(r"\r\n?", "\n", text)
    text = re.sub(r"[\t\f\v]+", " ", text)
    text = re.sub(r" +", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def alpha_ratio(text: str) -> float:
    if not text:
        return 0.0
    alpha = sum(1 for ch in text if ch.isalpha())
    visible = sum(1 for ch in text if not ch.isspace()) or 1
    return alpha / visible


def lines(text: str) -> List[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def looks_like_grade(token: str) -> bool:
    return bool(GRADE_PATTERN.match(token.strip()))


def find_first_matching_line(text_lines: Iterable[str], pattern: re.Pattern[str]) -> str | None:
    for line in text_lines:
        if pattern.search(line):
            return line
    return None
