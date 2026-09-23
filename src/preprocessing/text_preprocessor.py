import re


def clean_text(text):
    """
    Clean extracted academic text while preserving meaningful content.

    Steps:
    1. Remove non-printable characters
    2. Normalize whitespace
    3. Remove unnecessary spaces before punctuation
    4. Normalize repeated punctuation
    """

    if not text:
        return ""

    # Remove non-printable characters
    text = "".join(char for char in text if char.isprintable())

    # Replace multiple spaces, tabs, and line breaks with one space
    text = re.sub(r"\s+", " ", text)

    # Remove spaces before punctuation
    text = re.sub(r"\s+([,.!?;:])", r"\1", text)

    # Remove excessive repeated punctuation
    text = re.sub(r"([.!?]){2,}", r"\1", text)

    return text.strip()


def preprocess_text(text):
    """
    Preprocess a single text document.

    Args:
        text (str): Raw text extracted from a document.

    Returns:
        str: Cleaned text.
    """

    return clean_text(text)


def preprocess_pages(pages):
    """
    Preprocess page-wise extracted PDF text.

    Args:
        pages (list): Output from pdf_extractor.py

    Returns:
        list: Cleaned page-wise text
    """

    processed_pages = []

    for page in pages:

        cleaned = clean_text(page["text"])

        if cleaned:
            processed_pages.append({
                "page_number": page["page_number"],
                "text": cleaned
            })

    return processed_pages


if __name__ == "__main__":

    from pdf_extractor import extract_text_from_pdf

    pdf_path = "../../data/raw/sample.pdf"

    pages = extract_text_from_pdf(pdf_path)

    processed_pages = preprocess_pages(pages)

    for page in processed_pages:

        print(f"\n--- Cleaned Page {page['page_number']} ---")
        print(page["text"][:500])