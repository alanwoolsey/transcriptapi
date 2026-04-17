from pathlib import Path


SUPPORTED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".txt"}


def get_extension(filename: str) -> str:
    return Path(filename).suffix.lower()


def validate_extension(filename: str) -> str:
    ext = get_extension(filename)
    if ext not in SUPPORTED_EXTENSIONS:
        raise ValueError(
            f"Unsupported file type '{ext}'. Supported extensions: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
        )
    return ext


def bytes_to_mb(content: bytes) -> float:
    return len(content) / (1024 * 1024)
