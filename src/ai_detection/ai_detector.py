import re
from collections import Counter


def calculate_text_features(text):
    """
    Extract basic linguistic features from text.
    These features can later be used by an ML model.
    """

    if not text or not text.strip():
        return {
            "word_count": 0,
            "sentence_count": 0,
            "avg_sentence_length": 0,
            "unique_word_ratio": 0
        }

    words = re.findall(r"\b\w+\b", text.lower())
    sentences = re.split(r"[.!?]+", text)

    words = [word for word in words if word]
    sentences = [sentence.strip() for sentence in sentences if sentence.strip()]

    word_count = len(words)
    sentence_count = len(sentences)

    avg_sentence_length = (
        word_count / sentence_count
        if sentence_count > 0
        else 0
    )

    unique_word_ratio = (
        len(set(words)) / word_count
        if word_count > 0
        else 0
    )

    return {
        "word_count": word_count,
        "sentence_count": sentence_count,
        "avg_sentence_length": round(avg_sentence_length, 2),
        "unique_word_ratio": round(unique_word_ratio, 3)
    }


def detect_ai_like_patterns(text):
    """
    Basic rule-based analysis of writing patterns.

    This is a baseline detector, not a definitive AI detector.
    """

    features = calculate_text_features(text)

    score = 0
    indicators = []

    if features["word_count"] > 100:
        if features["unique_word_ratio"] < 0.35:
            score += 1
            indicators.append("Low vocabulary diversity")

    if features["avg_sentence_length"] > 30:
        score += 1
        indicators.append("Long average sentence length")

    repetitive_words = Counter(
        re.findall(r"\b\w+\b", text.lower())
    )

    common_words = [
        word for word, count in repetitive_words.items()
        if count >= 5 and len(word) > 4
    ]

    if common_words:
        score += 1
        indicators.append("Repeated vocabulary patterns")

    return {
        "score": score,
        "features": features,
        "indicators": indicators
    }


if __name__ == "__main__":

    sample_text = """
    Artificial intelligence is transforming many industries.
    Organizations are increasingly using machine learning systems
    to analyze data, automate processes, and improve decision making.
    """

    result = detect_ai_like_patterns(sample_text)

    print("AI Detection Analysis")
    print("---------------------")
    print("Score:", result["score"])
    print("Features:", result["features"])
    print("Indicators:", result["indicators"])