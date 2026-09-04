import re
from math import sqrt
from collections import Counter


def preprocess_text(text):
    """
    Clean text before similarity calculation.
    """

    text = text.lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text)

    return text.strip()


def calculate_cosine_similarity(text1, text2):
    """
    Calculate cosine similarity between two texts.

    Returns a value between 0 and 1:
    0 = completely different
    1 = identical
    """

    text1 = preprocess_text(text1)
    text2 = preprocess_text(text2)

    if not text1 or not text2:
        return 0.0

    words1 = text1.split()
    words2 = text2.split()

    vocabulary = set(words1 + words2)

    vector1 = Counter(words1)
    vector2 = Counter(words2)

    dot_product = sum(
        vector1[word] * vector2[word]
        for word in vocabulary
    )

    magnitude1 = sqrt(
        sum(vector1[word] ** 2 for word in vocabulary)
    )

    magnitude2 = sqrt(
        sum(vector2[word] ** 2 for word in vocabulary)
    )

    if magnitude1 == 0 or magnitude2 == 0:
        return 0.0

    similarity = dot_product / (magnitude1 * magnitude2)

    return round(similarity, 3)


def analyze_similarity(text1, text2):
    """
    Analyze similarity and classify the result.
    """

    similarity = calculate_cosine_similarity(text1, text2)

    if similarity >= 0.80:
        classification = "Very High Similarity"
    elif similarity >= 0.60:
        classification = "High Similarity"
    elif similarity >= 0.40:
        classification = "Moderate Similarity"
    elif similarity >= 0.20:
        classification = "Low Similarity"
    else:
        classification = "Very Low Similarity"

    return {
        "similarity_score": similarity,
        "classification": classification
    }


if __name__ == "__main__":

    original_text = """
    Artificial intelligence is transforming many industries.
    Organizations are increasingly using machine learning
    to analyze data and automate business processes.
    """

    reference_text = """
    Artificial intelligence is transforming different industries.
    Organizations use machine learning to analyze data
    and automate various business processes.
    """

    result = analyze_similarity(
        original_text,
        reference_text
    )

    print("Similarity Analysis")
    print("-------------------")
    print("Similarity Score:", result["similarity_score"])
    print("Classification:", result["classification"])