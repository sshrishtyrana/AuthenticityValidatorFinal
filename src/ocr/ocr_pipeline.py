from pathlib import Path

from src.ocr.document_ocr import DocumentOCR
from src.preprocessing.ocr_text_cleaner import OCRTextCleaner


class OCRPipeline:

    def __init__(self):
        self.ocr = DocumentOCR()
        self.cleaner = OCRTextCleaner()

    def extract(self, file_path: str) -> dict:
        path = Path(file_path)

        if not path.exists():
            raise FileNotFoundError(
                f"Document not found: {file_path}"
            )

        results = self.ocr.process(str(path))

        pages = []

        for result in results:
            data = self._normalise_result(result)

            if data is None:
                continue

            pages.append(
                self._extract_page_data(data)
            )

        raw_text = self._combine_text(pages)
        cleaned_text = self.cleaner.clean(raw_text)

        return {
            "file": path.name,
            "pages": pages,
            "raw_text": raw_text,
            "text": cleaned_text,
            "page_count": len(pages)
        }

    @staticmethod
    def _normalise_result(result):
        if hasattr(result, "json"):
            data = result.json

            if callable(data):
                data = data()

        elif isinstance(result, dict):
            data = result

        else:
            return None

        if not isinstance(data, dict):
            return None

        # PaddleOCR 3.x OCRResult returns:
        # {"res": {...}}
        if "res" in data and isinstance(data["res"], dict):
            data = data["res"]

        return data

    @staticmethod
    def _extract_page_data(data: dict) -> dict:

        # PaddleOCR 3.x stores OCR output directly
        # under rec_texts and rec_scores.
        texts = data.get("rec_texts", [])
        scores = data.get("rec_scores", [])
        polygons = data.get("rec_polys", [])
        boxes = data.get("rec_boxes", [])

        cleaned_texts = []

        for text in texts:
            text = str(text).strip()

            if text:
                cleaned_texts.append(text)

        confidence = []

        for score in scores:
            try:
                confidence.append(float(score))
            except (TypeError, ValueError):
                continue

        if confidence:
            average = sum(confidence) / len(confidence)
            minimum = min(confidence)
            maximum = max(confidence)
        else:
            average = 0.0
            minimum = 0.0
            maximum = 0.0

        blocks = []

        for index, text in enumerate(cleaned_texts):

            block = {
                "type": "text",
                "text": text
            }

            if index < len(confidence):
                block["confidence"] = round(
                    confidence[index],
                    4
                )

            if index < len(polygons):
                block["polygon"] = polygons[index]

            if index < len(boxes):
                block["box"] = boxes[index]

            blocks.append(block)

        return {
            "ocr_text": cleaned_texts,

            "ocr_confidence": {
                "average": round(average, 4),
                "minimum": round(minimum, 4),
                "maximum": round(maximum, 4),
                "count": len(confidence)
            },

            "blocks": blocks,

            "document_dimensions": {
                "width": data.get("width"),
                "height": data.get("height")
            }
        }

    @staticmethod
    def _combine_text(pages: list) -> str:

        text_parts = []

        for page in pages:
            texts = page.get("ocr_text", [])

            for text in texts:
                if text:
                    text_parts.append(text)

        return "\n".join(text_parts)