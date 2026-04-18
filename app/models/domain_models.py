from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class HeuristicAssessment:
    text: str
    score: float
    acceptable: bool
    char_count: int
    alpha_ratio: float
    line_count: int
    warnings: List[str] = field(default_factory=list)


@dataclass
class TranscriptCourse:
    course_code: Optional[str]
    course_title: Optional[str]
    credits: Optional[float]
    grade: Optional[str]
    term: Optional[str] = None
    confidence_score: float = 0.0
    confidence_reasons: List[str] = field(default_factory=list)


@dataclass
class TranscriptTerm:
    term_name: str
    courses: List[TranscriptCourse] = field(default_factory=list)
