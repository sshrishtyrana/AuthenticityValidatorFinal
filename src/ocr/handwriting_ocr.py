import os

os.environ["FLAGS_use_mkldnn"] = "0"

from paddleocr import PaddleOCR


class HandwritingOCR:

    def __init__(self):

        self.ocr = PaddleOCR(
            text_detection_model_name="PP-OCRv5_server_det",
            text_recognition_model_name="PP-OCRv5_server_rec",
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=True,
            enable_mkldnn=False
        )

    def recognize(self, image_path: str) -> str:

        results = self.ocr.predict(image_path)

        texts = []

        for result in results:

            data = result.json

            if callable(data):
                data = data()

            if not isinstance(data, dict):
                continue

            if "res" in data:
                data = data["res"]

            rec_texts = data.get(
                "rec_texts",
                []
            )

            for text in rec_texts:

                text = str(text).strip()

                if text:
                    texts.append(text)

        return "\n".join(texts)