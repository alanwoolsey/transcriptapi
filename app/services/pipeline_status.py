CANONICAL_PIPELINE_STATUSES = {
    "inquiry": "Inquiry",
    "prospect": "Prospect",
    "applicant": "Applicant",
    "incomplete": "Incomplete",
    "complete": "Complete",
    "admitted": "Admitted",
    "deposited/committed": "Deposited/Committed",
    "registered": "Registered",
}

LEGACY_PIPELINE_STATUS_MAP = {
    "qualified_inquiry": "Prospect",
    "high_intent": "Prospect",
    "application_started": "Applicant",
    "application_submitted": "Applicant",
    "pending_evidence": "Incomplete",
    "missing_items": "Incomplete",
    "trust_hold": "Incomplete",
    "nearly_complete": "Incomplete",
    "decision_ready": "Complete",
    "ready_for_review": "Complete",
    "in_review": "Complete",
    "decision_pending": "Complete",
    "deposited": "Deposited/Committed",
    "committed": "Deposited/Committed",
    "class_ready": "Registered",
    "enrolled": "Registered",
    "registered": "Registered",
}


def canonical_pipeline_status(value: str | None) -> str:
    if not value:
        return "Incomplete"
    normalized = value.strip().lower().replace("-", "_").replace(" ", "_")
    slash_normalized = normalized.replace("_/_", "/").replace("_", " ")
    if normalized in LEGACY_PIPELINE_STATUS_MAP:
        return LEGACY_PIPELINE_STATUS_MAP[normalized]
    if normalized in CANONICAL_PIPELINE_STATUSES:
        return CANONICAL_PIPELINE_STATUSES[normalized]
    if slash_normalized in CANONICAL_PIPELINE_STATUSES:
        return CANONICAL_PIPELINE_STATUSES[slash_normalized]
    return value.strip().replace("_", " ").replace("-", " ").title()
