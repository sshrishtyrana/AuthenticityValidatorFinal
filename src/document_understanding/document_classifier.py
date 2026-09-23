import re
from collections import Counter


class DocumentClassifier:

    def classify(self, text: str) -> dict:

        if not text or not text.strip():

            return {
                "document_type": "Unknown",
                "confidence": 0.0,
                "features": {}
            }

        cleaned_text = self._clean_text(text)

        features = self._extract_features(
            cleaned_text
        )

        document_type, confidence = (
            self._classify(features)
        )

        return {
            "document_type": document_type,
            "confidence": round(
                confidence,
                4
            ),
            "confidence_percentage": round(
                confidence * 100,
                2
            ),
            "features": features
        }

    @staticmethod
    def _clean_text(text: str) -> str:

        return re.sub(
            r"\s+",
            " ",
            text
        ).strip()

    @staticmethod
    def _extract_features(text: str) -> dict:

        words = re.findall(
            r"\b[a-zA-Z]+\b",
            text.lower()
        )

        numbers = re.findall(
            r"\b\d+(?:[.,]\d+)?\b",
            text
        )

        dates = re.findall(
            r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b",
            text
        )

        uppercase_words = re.findall(
            r"\b[A-Z]{3,}\b",
            text
        )

        lines = [
            line.strip()
            for line in text.splitlines()
            if line.strip()
        ]

        return {
            "word_count": len(words),
            "number_count": len(numbers),
            "date_count": len(dates),
            "uppercase_word_count": len(
                uppercase_words
            ),
            "line_count": len(lines),
            "average_word_length": (
                round(
                    sum(
                        len(word)
                        for word in words
                    ) / len(words),
                    2
                )
                if words
                else 0
            )
        }

    @staticmethod
    def _classify(features: dict) -> tuple:

        word_count = features["word_count"]
        number_count = features["number_count"]
        date_count = features["date_count"]
        line_count = features["line_count"]

        if word_count == 0:

            return "Unknown", 0.0

        # General document structure categories.
        if number_count > word_count * 0.20:

            return (
                "Data-Heavy Document",
                0.55
            )

        if date_count >= 2:

            return (
                "Date-Oriented Document",
                0.50
            )

        if line_count > 20 and word_count > 100:

            return (
                "Structured Text Document",
                0.50
            )

        if word_count > 150:

            return (
                "Long-Form Text Document",
                0.50
            )

        return (
            "General Document",
            0.40
        )