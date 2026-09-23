from src.ocr.handwriting_ocr import HandwritingOCR


IMAGE_PATH = "data/raw/handwritten_sample.jpeg"


ocr = HandwritingOCR()

text = ocr.recognize(
    IMAGE_PATH
)

print("\n======================================")
print("       HANDWRITING OCR")
print("======================================")

print("\nRecognized Text:")
print(text)

print("\n======================================")