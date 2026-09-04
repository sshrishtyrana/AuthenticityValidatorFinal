import pymupdf


def extract_text_from_pdf(pdf_path):
    """
    Extract text from a PDF while preserving page information.

    Args:
        pdf_path (str): Path to the PDF file.

    Returns:
        list: A list of dictionaries containing page number and text.
    """

    document = pymupdf.open(pdf_path)

    pages = []

    for page_number, page in enumerate(document, start=1):
        text = page.get_text("text").strip()

        pages.append({
            "page_number": page_number,
            "text": text
        })

    document.close()

    return pages


if __name__ == "__main__":
    pdf_path = "../../data/raw/sample.pdf"

    pages = extract_text_from_pdf(pdf_path)

    for page in pages:
        print(f"\n--- Page {page['page_number']} ---")
        print(page["text"][:500])