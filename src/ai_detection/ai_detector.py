import re
import math
from collections import Counter


class AIContentDetector:

    def analyze(self, text: str) -> dict:

        if not text or not text.strip():
            return {
                "status": "insufficient_text",
                "indicator": 0.0,
                "assessment": "Insufficient text for analysis",
                "features": {}
            }

        cleaned_text = self._clean_text(text)

        sentences = self._split_sentences(
            cleaned_text
        )

        words = self._extract_words(
            cleaned_text
        )

        if len(words) < 20 or len(sentences) < 2:
            return {
                "status": "insufficient_text",
                "indicator": 0.0,
                "assessment": "Insufficient text for reliable analysis",
                "features": {
                    "word_count": len(words),
                    "sentence_count": len(sentences)
                }
            }

        sentence_lengths = [
            len(self._extract_words(sentence))
            for sentence in sentences
        ]

        vocabulary_ratio = (
            self._vocabulary_ratio(words)
        )

        repetition_ratio = (
            self._repetition_ratio(words)
        )

        sentence_variation = (
            self._sentence_length_variation(
                sentence_lengths
            )
        )

        punctuation_score = (
            self._punctuation_variation(
                cleaned_text
            )
        )

        complexity_score = (
            self._lexical_complexity(
                words
            )
        )

        indicator = self._calculate_indicator(
            vocabulary_ratio,
            repetition_ratio,
            sentence_variation,
            punctuation_score,
            complexity_score
        )

        assessment = self._assessment(
            indicator
        )

        return {
            "status": "success",
            "indicator": round(
                indicator,
                4
            ),
            "indicator_percentage": round(
                indicator * 100,
                2
            ),
            "assessment": assessment,
            "features": {
                "word_count": len(words),
                "sentence_count": len(sentences),
                "unique_word_count": len(set(words)),
                "vocabulary_ratio": round(
                    vocabulary_ratio,
                    4
                ),
                "repetition_ratio": round(
                    repetition_ratio,
                    4
                ),
                "sentence_length_variation": round(
                    sentence_variation,
                    4
                ),
                "punctuation_variation": round(
                    punctuation_score,
                    4
                ),
                "lexical_complexity": round(
                    complexity_score,
                    4
                )
            }
        }

    @staticmethod
    def _clean_text(text: str) -> str:

        return re.sub(
            r"\s+",
            " ",
            text
        ).strip()

    @staticmethod
    def _split_sentences(text: str) -> list:

        sentences = re.split(
            r"(?<=[.!?])\s+",
            text
        )

        return [
            sentence.strip()
            for sentence in sentences
            if sentence.strip()
        ]

    @staticmethod
    def _extract_words(text: str) -> list:

        return re.findall(
            r"\b[a-zA-Z]+\b",
            text.lower()
        )

    @staticmethod
    def _vocabulary_ratio(words: list) -> float:

        if not words:
            return 0.0

        return len(set(words)) / len(words)

    @staticmethod
    def _repetition_ratio(words: list) -> float:

        if not words:
            return 0.0

        counts = Counter(words)

        repeated_words = sum(
            count - 1
            for count in counts.values()
            if count > 1
        )

        return repeated_words / len(words)

    @staticmethod
    def _sentence_length_variation(
        sentence_lengths: list
    ) -> float:

        if len(sentence_lengths) < 2:
            return 0.0

        mean = sum(sentence_lengths) / len(
            sentence_lengths
        )

        if mean == 0:
            return 0.0

        variance = sum(
            (length - mean) ** 2
            for length in sentence_lengths
        ) / len(sentence_lengths)

        standard_deviation = math.sqrt(
            variance
        )

        return standard_deviation / mean

    @staticmethod
    def _punctuation_variation(
        text: str
    ) -> float:

        punctuation_counts = {
            mark: text.count(mark)
            for mark in ",;:!?-"
        }

        total = sum(
            punctuation_counts.values()
        )

        if total == 0:
            return 0.0

        frequencies = [
            count / total
            for count in punctuation_counts.values()
            if count > 0
        ]

        return len(frequencies) / len(
            punctuation_counts
        )

    @staticmethod
    def _lexical_complexity(
        words: list
    ) -> float:

        if not words:
            return 0.0

        long_words = sum(
            1
            for word in words
            if len(word) >= 7
        )

        return long_words / len(words)

    @staticmethod
    def _calculate_indicator(
        vocabulary_ratio: float,
        repetition_ratio: float,
        sentence_variation: float,
        punctuation_score: float,
        complexity_score: float
    ) -> float:

        # This is a linguistic-style indicator,
        # not a definitive probability of AI authorship.

        regularity = max(
            0.0,
            1.0 - min(
                sentence_variation,
                1.0
            )
        )

        repetition_component = min(
            repetition_ratio * 2,
            1.0
        )

        vocabulary_component = (
            1.0 - min(
                vocabulary_ratio,
                1.0
            )
        )

        complexity_component = min(
            complexity_score,
            1.0
        )

        punctuation_component = (
            1.0 - min(
                punctuation_score,
                1.0
            )
        )

        indicator = (
            regularity * 0.25
            + repetition_component * 0.15
            + vocabulary_component * 0.20
            + complexity_component * 0.20
            + punctuation_component * 0.20
        )

        return max(
            0.0,
            min(
                indicator,
                1.0
            )
        )

    @staticmethod
    def _assessment(
        indicator: float
    ) -> str:

        if indicator < 0.35:
            return "Lower AI-like linguistic indicators"

        if indicator < 0.65:
            return "Mixed AI-like linguistic indicators"

        return "Higher AI-like linguistic indicators"