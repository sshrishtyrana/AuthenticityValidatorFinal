
from pathlib import Path

import fitz  # PyMuPDF
from docx import Document


def extract_text(file_path: str) -> str:
    """
    Extract text from PDF or DOCX files.
    Returns the extracted text as a string.
    """

    path = Path(file_path)

    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    extension = path.suffix.lower()

    if extension == ".pdf":
        text_parts = []

        with fitz.open(path) as pdf:
            for page in pdf:
                text_parts.append(page.get_text())

        extracted_text = "\n".join(text_parts)

    elif extension == ".docx":
        document = Document(path)

        paragraphs = [
            paragraph.text
            for paragraph in document.paragraphs
            if paragraph.text.strip()
        ]

        extracted_text = "\n".join(paragraphs)

        # Also extract text from tables.
        for table in document.tables:
            for row in table.rows:
                extracted_text += "\n" + " ".join(
                    cell.text for cell in row.cells
                )

    else:
        raise ValueError("Only PDF and DOCX files are supported.")

    return extracted_text.strip()
