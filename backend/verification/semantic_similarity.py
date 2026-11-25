
from sentence_transformers import SentenceTransformer, util


# Load the model once and reuse it.
_model = None


def get_model():
    global _model

    if _model is None:
        _model = SentenceTransformer("all-MiniLM-L6-v2")

    return _model


def calculate_semantic_similarity(text1: str, text2: str) -> float:
    """
    Compare two documents based on their meaning.
    Returns a similarity percentage between 0 and 100.
    """

    if not text1.strip() or not text2.strip():
        return 0.0

    model = get_model()

    embeddings = model.encode(
        [text1, text2],
        convert_to_tensor=True,
        normalize_embeddings=True
    )

    similarity = util.cos_sim(
        embeddings[0],
        embeddings[1]
    ).item()

    # Convert cosine similarity into a percentage.
    percentage = max(0.0, min(100.0, similarity * 100))

    return round(percentage, 2)


def compare_semantic_documents(
    current_text: str,
    previous_documents: list
) -> list:
    """
    Compare one document against multiple previous documents.
    """

    results = []

    for document in previous_documents:
        previous_text = document.get("text", "")

        semantic_score = calculate_semantic_similarity(
            current_text,
            previous_text
        )

        results.append({
            "document_id": document.get("document_id"),
            "filename": document.get("filename"),
            "semantic_similarity_percentage": semantic_score
        })

    return sorted(
        results,
        key=lambda item: item["semantic_similarity_percentage"],
        reverse=True
    )
