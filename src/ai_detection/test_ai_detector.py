from src.ai_detection.ai_detector import AIContentDetector


text = """
Artificial intelligence is transforming modern education.
Machine learning systems can analyze student performance
and provide personalized educational recommendations.
These systems can support teachers by identifying learning
patterns and providing useful academic insights.

However, responsible implementation requires careful
consideration of privacy, security, fairness, and data quality.
Educational institutions should evaluate automated systems
before using them for important academic decisions.
Human oversight remains an important part of responsible
artificial intelligence deployment.
"""


detector = AIContentDetector()

result = detector.analyze(text)

print("\n======================================")
print("       AI CONTENT ANALYSIS")
print("======================================")

print(
    f"\nStatus: {result['status']}"
)

print(
    f"Indicator: "
    f"{result['indicator_percentage']}%"
)

print(
    f"Assessment: "
    f"{result['assessment']}"
)

print("\nFeatures:")

for name, value in result["features"].items():

    print(
        f"{name}: {value}"
    )

print("\n======================================")