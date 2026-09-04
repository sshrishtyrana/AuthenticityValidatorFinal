import re
import statistics
from collections import Counter


def split_sentences(text):
    """Split text into individual sentences."""
    sentences = re.split(r"[.!?]+", text)
    return [s.strip() for s in sentences if s.strip()]


def tokenize(text):
    """Extract words from text."""
    return re.findall(r"\b[a-zA-Z]+\b", text.lower())


def calculate_linguistic_features(text):
    """
    Extract linguistic features that can later be used
    by a machine-learning classifier.
    """

    words = tokenize(text)
    sentences = split_sentences(text)

    if not words:
        return {
            "word_count": 0,
            "sentence_count": 0,
            "avg_sentence_length": 0,
            "sentence_length_std": 0,
            "unique_word_ratio": 0,
            "avg_word_length": 0,
            "punctuation_density": 0,
            "stopword_ratio": 0,
            "repeated_word_ratio": 0
        }

    # Sentence lengths
    sentence_lengths = [
        len(tokenize(sentence))
        for sentence in sentences
    ]

    avg_sentence_length = (
        statistics.mean(sentence_lengths)
        if sentence_lengths
        else 0
    )

    sentence_length_std = (
        statistics.stdev(sentence_lengths)
        if len(sentence_lengths) > 1
        else 0
    )

    # Vocabulary diversity
    unique_word_ratio = len(set(words)) / len(words)

    # Average word length
    avg_word_length = statistics.mean(
        len(word) for word in words
    )

    # Punctuation
    punctuation_count = len(
        re.findall(r"[,.!?;:]", text)
    )

    punctuation_density = (
        punctuation_count / len(words)
    )

    # Basic stop-word list
    stopwords = {
        "the", "is", "a", "an", "and", "or", "but",
        "to", "of", "in", "on", "for", "with",
        "this", "that", "it", "as", "by", "from"
    }

    stopword_count = sum(
        1 for word in words
        if word in stopwords
    )

    stopword_ratio = stopword_count / len(words)

    # Repetition
    word_counts = Counter(words)

    repeated_words = sum(
        count - 1
        for count in word_counts.values()
        if count > 1
    )

    repeated_word_ratio = repeated_words / len(words)

    return {
        "word_count": len(words),
        "sentence_count": len(sentences),
        "avg_sentence_length": round(avg_sentence_length, 2),
        "sentence_length_std": round(sentence_length_std, 2),
        "unique_word_ratio": round(unique_word_ratio, 3),
        "avg_word_length": round(avg_word_length, 2),
        "punctuation_density": round(punctuation_density, 3),
        "stopword_ratio": round(stopword_ratio, 3),
        "repeated_word_ratio": round(repeated_word_ratio, 3)
    }


def detect_ai_like_patterns(text):
    """
    Baseline rule-based analysis.

    This function does NOT claim to prove AI authorship.
    It identifies writing patterns that may warrant further analysis.
    """

    features = calculate_linguistic_features(text)

    risk_score = 0
    indicators = []

    # Very uniform sentence structure
    if (
        features["sentence_count"] >= 5
        and features["sentence_length_std"] < 5
    ):
        risk_score += 1
        indicators.append(
            "Low variation in sentence length"
        )

    # Very low vocabulary diversity
    if (
        features["word_count"] >= 50
        and features["unique_word_ratio"] < 0.40
    ):
        risk_score += 1
        indicators.append(
            "Low vocabulary diversity"
        )

    # High repetition
    if features["repeated_word_ratio"] > 0.30:
        risk_score += 1
        indicators.append(
            "High word repetition"
        )

    # Extremely long sentences
    if features["avg_sentence_length"] > 35:
        risk_score += 1
        indicators.append(
            "Long average sentence length"
        )

    return {
        "risk_score": risk_score,
        "features": features,
        "indicators": indicators
    }


if __name__ == "__main__":

    sample_text = """
    Artificial intelligence is transforming many industries.
    Organizations are increasingly using machine learning
    systems to analyze data and improve decision making.
    These technologies are helping organizations automate
    complex processes and improve operational efficiency.
    Machine learning models can identify patterns in data
    and support better analytical decisions.
    """

    result = detect_ai_like_patterns(sample_text)

    print("AI Detection Analysis")
    print("=" * 30)

    print("\nRisk Score:", result["risk_score"])

    print("\nExtracted Features:")

    for feature, value in result["features"].items():
        print(f"{feature}: {value}")

    print("\nIndicators:")

    if result["indicators"]:
        for indicator in result["indicators"]:
            print("-", indicator)
    else:
        print("No significant indicators detected.")