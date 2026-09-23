import os

os.environ["FLAGS_use_mkldnn"] = "0"

from pathlib import Path

from paddleocr import PaddleOCR


class DocumentOCR:

    def __init__(self):

        self.pipeline = PaddleOCR(
            text_detection_model_name="PP-OCRv5_server_det",
            text_recognition_model_name="PP-OCRv5_server_rec",
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=True,
            enable_mkldnn=False
        )

    def process(self, file_path: str):

        path = Path(file_path)

        if not path.exists():
            raise FileNotFoundError(
                f"Document not found: {file_path}"
            )

        return self.pipeline.predict(
            str(path)
        )