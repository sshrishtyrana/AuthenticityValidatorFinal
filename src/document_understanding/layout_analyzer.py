from paddleocr import PPStructureV3


class LayoutAnalyzer:

    def __init__(self):

        self.pipeline = PPStructureV3(
            use_doc_orientation_classify=True,
            use_doc_unwarping=True,
            use_textline_orientation=True
        )

    def analyze(self, file_path: str):

        results = self.pipeline.predict(file_path)

        output = []

        for result in results:

            if hasattr(result, "json"):
                output.append(result.json)

        return output