import sys
from pathlib import Path

# ---------------------------------------------------------
# PROJECT PATH SETUP
# ---------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = PROJECT_ROOT / "src"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


# ---------------------------------------------------------
# IMPORT PROJECT MODULES
# ---------------------------------------------------------

from preprocessing.pdf_extractor import extract_text_from_pdf
from preprocessing.text_preprocessor import preprocess_text
from similarity.similarity_checker import calculate_tfidf_similarity


# ---------------------------------------------------------
# DOCUMENT LOADING
# ---------------------------------------------------------

def load_document(pdf_path):
    """
    Extract and preprocess text from a PDF.
    """

    if not pdf_path.exists():
        raise FileNotFoundError(
            f"PDF not found: {pdf_path}"
        )

    pages = extract_text_from_pdf(str(pdf_path))

    if not pages:
        raise ValueError(
            f"No text could be extracted from: {pdf_path.name}"
        )

    # Combine all pages into one document
    full_text = " ".join(
        page["text"]
        for page in pages
        if page.get("text")
    )

    # Clean the document
    cleaned_text = preprocess_text(full_text)

    return cleaned_text


# ---------------------------------------------------------
# SIMILARITY CLASSIFICATION
# ---------------------------------------------------------

def classify_similarity(score):
    """
    Convert similarity score into a human-readable category.
    """

    if score >= 0.80:
        return "Very High Similarity"
    elif score >= 0.60:
        return "High Similarity"
    elif score >= 0.40:
        return "Moderate Similarity"
    elif score >= 0.20:
        return "Low Similarity"
    else:
        return "Very Low Similarity"


# ---------------------------------------------------------
# DOCUMENT COMPARISON
# ---------------------------------------------------------

def compare_documents(pdf1, pdf2):
    """
    Compare two PDF documents using TF-IDF cosine similarity.
    """

    print("\nLoading Document 1...")
    text1 = load_document(pdf1)

    print("Loading Document 2...")
    text2 = load_document(pdf2)

    print("Documents loaded successfully.")

    # Calculate similarity
    similarity_score = calculate_tfidf_similarity(
        text1,
        text2
    )

    classification = classify_similarity(
        similarity_score
    )

    return similarity_score, classification


# ---------------------------------------------------------
# MAIN PROGRAM
# ---------------------------------------------------------

def main():

    # Reference documents
    pdf1 = PROJECT_ROOT / "data" / "raw" / "sample.pdf"
    pdf2 = PROJECT_ROOT / "data" / "raw" / "sample_reference.pdf"

    print("=" * 55)
    print("      ACADEMIC DOCUMENT SIMILARITY ANALYZER")
    print("=" * 55)

    print(f"\nDocument 1:")
    print(pdf1.name)

    print(f"\nDocument 2:")
    print(pdf2.name)

    # Check files
    if not pdf1.exists():
        print(f"\nERROR: {pdf1.name} not found.")
        return

    if not pdf2.exists():
        print(f"\nERROR: {pdf2.name} not found.")
        return

    try:

        score, classification = compare_documents(
            pdf1,
            pdf2
        )

        print("\n")
        print("=" * 55)
        print("             SIMILARITY RESULT")
        print("=" * 55)

        print(
            f"\nTF-IDF Similarity Score: {score}"
        )

        print(
            f"Classification: {classification}"
        )

        print("\nInterpretation:")

        if score >= 0.80:
            print(
                "The documents contain a very high degree "
                "of textual similarity."
            )

        elif score >= 0.60:
            print(
                "The documents contain substantial "
                "textual similarity."
            )

        elif score >= 0.40:
            print(
                "The documents contain a moderate level "
                "of textual similarity."
            )

        elif score >= 0.20:
            print(
                "The documents contain some overlapping "
                "textual patterns."
            )

        else:
            print(
                "The documents contain very little "
                "textual similarity."
            )

        print("\n" + "=" * 55)

    except Exception as error:

        print("\nERROR:")
        print(error)


# ---------------------------------------------------------
# PROGRAM ENTRY POINT
# ---------------------------------------------------------

if __name__ == "__main__":
    main()