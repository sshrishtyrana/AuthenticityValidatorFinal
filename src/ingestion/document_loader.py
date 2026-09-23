from pathlib import Path


SUPPORTED_EXTENSIONS = {
    ".pdf",
    ".png",
    ".jpg",
    ".jpeg",
    ".bmp",
    ".tif",
    ".tiff",
    ".webp"
}


def validate_document(file_path: str) -> Path:
    """
    Validate an uploaded document without making assumptions
    about its document type.
    """

    path = Path(file_path)

    if not path.exists():
        raise FileNotFoundError(f"Document not found: {path}")

    if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise ValueError(
            f"Unsupported document format: {path.suffix}"
        )

    return path


def get_document_metadata(file_path: str) -> dict:
    path = validate_document(file_path)

    return {
        "filename": path.name,
        "extension": path.suffix.lower(),
        "size_bytes": path.stat().st_size
    }