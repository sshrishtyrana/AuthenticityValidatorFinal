from src.similarity.similarity_checker import SimilarityChecker
from src.ocr.ocr_pipeline import OCRPipeline


input_file = "data/raw/sample.pdf"

ocr = OCRPipeline()

input_result = ocr.extract(
    input_file
)

input_text = input_result["text"]

checker = SimilarityChecker()

results = checker.compare_with_references(
    input_text,
    "data/references"
)

print("\n======================================")
print("       DOCUMENT SIMILARITY")
print("======================================")

for result in results:

    print(
        f"\nReference: {result['reference_file']}"
    )

    print(
        f"Similarity: "
        f"{result['similarity_percentage']}%"
    )

print("\n======================================")