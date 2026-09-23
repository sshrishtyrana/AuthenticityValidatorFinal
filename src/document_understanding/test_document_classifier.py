from src.document_understanding.document_classifier import (
    DocumentClassifier
)


text = """
This document contains structured information
about an academic program. The program includes
multiple subjects, examinations, assignments,
laboratory activities, project work, and academic
assessment. Students complete coursework during
the academic session and receive results after
evaluation.
"""


classifier = DocumentClassifier()

result = classifier.classify(text)

print("\n======================================")
print("       DOCUMENT CLASSIFICATION")
print("======================================")

print(
    f"\nDocument Type: "
    f"{result['document_type']}"
)

print(
    f"Confidence: "
    f"{result['confidence_percentage']}%"
)

print("\nFeatures:")

for name, value in result["features"].items():

    print(
        f"{name}: {value}"
    )

print("\n======================================")