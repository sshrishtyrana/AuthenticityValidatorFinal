from src.ocr.handwriting_preprocessor import (
    HandwritingPreprocessor
)


IMAGE_PATH = "data/raw/handwritten_sample.jpeg"


preprocessor = HandwritingPreprocessor()

line_paths = preprocessor.detect_lines(
    IMAGE_PATH
)

print("\n======================================")
print("       HANDWRITING LINE DETECTION")
print("======================================")

print(
    f"\nDetected lines: {len(line_paths)}"
)

for index, path in enumerate(
    line_paths,
    start=1
):
    print(
        f"Line {index}: {path}"
    )

print("\n======================================")