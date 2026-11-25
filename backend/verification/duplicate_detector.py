
"""Database-backed exact duplicate document detection."""

import hashlib
from pathlib import Path

from sqlalchemy.orm import Session

from backend.models import Document
from backend.database import BASE_DIR


def calculate_sha256(content: bytes) -> str:
    """Return the SHA-256 fingerprint of file contents."""
    return hashlib.sha256(content).hexdigest()


def get_file_bytes(file_path: str) -> bytes | None:
    """Read a stored file, handling project-relative paths."""
    path = Path(file_path)

    candidates = [path] if path.is_absolute() else [
        Path.cwd() / path,
        BASE_DIR / path,
    ]

    for candidate in candidates:
        try:
            if candidate.is_file():
                return candidate.read_bytes()
        except OSError:
            continue

    return None


def detect_duplicate(
    content: bytes,
    db: Session,
    current_user_id: int,
    exclude_document_id: int | None = None,
) -> dict:
    """
    Detect an exact file match among previously stored documents.

    Does not expose another user's filename or personal information.
    A matching file is not, by itself, evidence of fraud.
    """
    if not content:
        return {
            "is_duplicate": False,
            "status": "empty_file",
            "reference_id": None,
            "message": "No file content was supplied.",
        }

    fingerprint = calculate_sha256(content)

    query = db.query(Document)

    if exclude_document_id is not None:
        query = query.filter(Document.id != exclude_document_id)

    for document in query.yield_per(100):
        stored_content = get_file_bytes(document.file_path)

        if stored_content is None:
            continue

        if calculate_sha256(stored_content) != fingerprint:
            continue

        if document.user_id == current_user_id:
            return {
                "is_duplicate": True,
                "status": "duplicate_same_user",
                "reference_id": document.id,
                "message": (
                    "This exact file was uploaded previously "
                    "by your account."
                ),
            }

        return {
            "is_duplicate": True,
            "status": "duplicate_other_user",
            "reference_id": document.id,
            "message": (
                "An identical file exists in the system. "
                "Review the record and access permissions."
            ),
        }

    return {
        "is_duplicate": False,
        "status": "unique_file",
        "reference_id": None,
        "message": "No exact file match was found in accessible stored files.",
    }
