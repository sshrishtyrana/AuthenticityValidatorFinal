from pathlib import Path

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from src.ocr.ocr_pipeline import OCRPipeline


class SimilarityChecker:

    def __init__(self):
        self.vectorizer = TfidfVectorizer(
            lowercase=True,
            stop_words="english"
        )

        # Load OCR pipeline only once.
        self.ocr_pipeline = OCRPipeline()

    def calculate_similarity(
        self,
        input_text: str,
        reference_text: str
    ) -> float:

        if not input_text.strip() or not reference_text.strip():
            return 0.0

        documents = [
            input_text,
            reference_text
        ]

        vectors = self.vectorizer.fit_transform(
            documents
        )

        score = cosine_similarity(
            vectors[0:1],
            vectors[1:2]
        )[0][0]

        return round(float(score), 4)

    def compare_with_references(
        self,
        input_text: str,
        reference_directory: str
    ) -> list:

        reference_path = Path(reference_directory)

        if not reference_path.exists():
            raise FileNotFoundError(
                f"Reference directory not found: "
                f"{reference_directory}"
            )

        reference_files = sorted(
            path
            for path in reference_path.iterdir()
            if path.is_file()
            and path.suffix.lower() == ".pdf"
        )

        results = []

        for reference_file in reference_files:

            reference_text = self._extract_text(
                reference_file
            )

            score = self.calculate_similarity(
                input_text,
                reference_text
            )

            results.append({
                "reference_file": reference_file.name,
                "similarity_score": score,
                "similarity_percentage": round(
                    score * 100,
                    2
                )
            })

        results.sort(
            key=lambda item: item["similarity_score"],
            reverse=True
        )

        return results

    def _extract_text(
        self,
        file_path: Path
    ) -> str:

        result = self.ocr_pipeline.extract(
            str(file_path)
        )

        return result.get("text", "")