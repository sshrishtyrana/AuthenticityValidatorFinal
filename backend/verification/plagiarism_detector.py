
import re

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from sentence_transformers import SentenceTransformer, util


# Load Sentence-BERT only once.
_model = None


def get_semantic_model():
    global _model

    if _model is None:
        _model = SentenceTransformer("all-MiniLM-L6-v2")

    return _model


def clean_text(text: str) -> str:
    """Clean extracted text before comparison."""

    if not text:
        return ""

    text = text.lower()
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"[^a-z0-9\s]", " ", text)

    return text.strip()


def get_similarity_label(score: float) -> str:
    """Classify TF-IDF similarity using project thresholds."""

    if score <= 20:
        return "Low"
    elif score <= 50:
        return "Moderate"

    return "High"


def calculate_semantic_similarity(text1: str, text2: str) -> float:
    """Compare two documents using Sentence-BERT embeddings."""

    if not text1.strip() or not text2.strip():
        return 0.0

    model = get_semantic_model()

    embeddings = model.encode(
        [text1, text2],
        convert_to_tensor=True,
        normalize_embeddings=True
    )

    similarity = util.cos_sim(
        embeddings[0],
        embeddings[1]
    ).item()

    percentage = max(0.0, min(100.0, similarity * 100))

    return round(percentage, 2)


def compare_documents(text1: str, text2: str) -> dict:
    """Compare two documents using TF-IDF and Sentence-BERT."""

    original_text1 = text1
    original_text2 = text2

    text1 = clean_text(text1)
    text2 = clean_text(text2)

    if not text1 or not text2:
        raise ValueError("Both documents must contain readable text.")

    # TF-IDF comparison
    vectorizer = TfidfVectorizer(
        stop_words="english",
        ngram_range=(1, 2),
        sublinear_tf=True,
    )

    matrix = vectorizer.fit_transform([text1, text2])

    similarity = cosine_similarity(
        matrix[0:1],
        matrix[1:2]
    )[0][0]

    tfidf_percentage = round(float(similarity) * 100, 2)

    # Sentence-BERT semantic comparison
    semantic_percentage = calculate_semantic_similarity(
        original_text1,
        original_text2
    )

    # Experimental combined indicator
    combined_percentage = round(
        (tfidf_percentage + semantic_percentage) / 2,
        2
    )

    return {
        "similarity_percentage": tfidf_percentage,
        "semantic_similarity_percentage": semantic_percentage,
        "combined_similarity_percentage": combined_percentage,
        "label": get_similarity_label(tfidf_percentage),
        "matching_sections": find_matching_sections(
            original_text1,
            original_text2,
        ),
    }


def find_matching_sections(
    text1: str,
    text2: str,
    threshold: float = 0.50,
) -> list:
    """Find similar sentence pairs using TF-IDF."""

    def split_sentences(text):
        return [
            sentence.strip()
            for sentence in re.split(r"(?<=[.!?])\s+", text)
            if len(sentence.split()) >= 5
        ]

    sentences1 = split_sentences(text1)
    sentences2 = split_sentences(text2)

    if not sentences1 or not sentences2:
        return []

    try:
        vectorizer = TfidfVectorizer(
            stop_words="english",
            ngram_range=(1, 2),
        )

        matrix = vectorizer.fit_transform(sentences1 + sentences2)

        first_matrix = matrix[:len(sentences1)]
        second_matrix = matrix[len(sentences1):]

        scores = cosine_similarity(first_matrix, second_matrix)

    except ValueError:
        return []

    matches = []

    for i, sentence1 in enumerate(sentences1):
        for j, sentence2 in enumerate(sentences2):
            score = float(scores[i][j])

            if score >= threshold:
                matches.append({
                    "document_1_text": sentence1,
                    "document_2_text": sentence2,
                    "similarity_percentage": round(score * 100, 2),
                })

    matches.sort(
        key=lambda item: item["similarity_percentage"],
        reverse=True,
    )

    return matches[:10]


def compare_multiple_documents(
    current_text: str,
    previous_documents: list,
) -> list:
    """Compare current document against previous documents."""

    results = []

    for document in previous_documents:
        previous_text = document.get("text", "")

        if not previous_text.strip():
            continue

        comparison = compare_documents(
            current_text,
            previous_text
        )

        results.append({
            "document_id": document.get("document_id"),
            "filename": document.get("filename"),
            **comparison,
        })

    results.sort(
        key=lambda item: item["similarity_percentage"],
        reverse=True,
    )

    return results
