from paddleocr import PaddleOCR


IMAGE_PATH = "data/raw/handwritten_sample.jpeg"


ocr = PaddleOCR(
    text_detection_model_name="PP-OCRv5_server_det",
    text_recognition_model_name="PP-OCRv5_server_rec",
    use_doc_orientation_classify=False,
    use_doc_unwarping=False,
    use_textline_orientation=True,
    enable_mkldnn=False
)

results = ocr.predict(
    IMAGE_PATH
)

print("\n======================================")
print("       PADDLEOCR HANDWRITING TEST")
print("======================================")

for result in results:

    data = result.json

    if callable(data):
        data = data()

    print("\nRAW RESULT:")
    print(data)

print("\n======================================")