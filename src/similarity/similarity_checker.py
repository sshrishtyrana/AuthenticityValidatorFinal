from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


def calculate_tfidf_similarity(text1, text2):
    """
    Calculate TF-IDF cosine similarity between two documents.

    Returns a value between 0 and 1.
    """

    if not text1.strip() or not text2.strip():
        return 0.0

    documents = [text1, text2]

    vectorizer = TfidfVectorizer(
        lowercase=True,
        stop_words="english",
        ngram_range=(1, 2)
    )

    tfidf_matrix = vectorizer.fit_transform(documents)

    similarity_matrix = cosine_similarity(tfidf_matrix)

    similarity_score = similarity_matrix[0][1]

    return round(float(similarity_score), 3)


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


def analyze_similarity(text1, text2):
    """
    Perform complete similarity analysis.
    """

    score = calculate_tfidf_similarity(
        text1,
        text2
    )

    classification = classify_similarity(score)

    return {
        "similarity_score": score,
        "classification": classification
    }


if __name__ == "__main__":

    original_text = """
    Artificial intelligence is transforming many industries.
    Organizations are increasingly using machine learning
    to analyze data and improve decision making.
    """

    reference_text = """
    Artificial intelligence is transforming different industries.
    Organizations use machine learning to analyze data
    and improve business decision making.
    """

    result = analyze_similarity(
        original_text,
        reference_text
    )

    print("TF-IDF Similarity Analysis")
    print("=" * 30)

    print("Similarity Score:",
          result["similarity_score"])

    print("Classification:",
          result["classification"])