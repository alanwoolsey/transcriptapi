import io
from pathlib import Path
from zipfile import ZipFile


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


def extract_supported_files_from_zip(content: bytes) -> list[tuple[str, bytes]]:
    extracted: list[tuple[str, bytes]] = []
    with ZipFile(io.BytesIO(content)) as archive:
        for member in archive.infolist():
            if member.is_dir():
                continue
            filename = Path(member.filename).name
            if not filename or filename.startswith(".") or member.filename.startswith("__MACOSX/"):
                continue
            ext = get_extension(filename)
            if ext not in SUPPORTED_EXTENSIONS:
                continue
            extracted.append((filename, archive.read(member)))
    return extracted
