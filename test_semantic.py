
from backend.verification.semantic_similarity import (
    calculate_semantic_similarity
)

text1 = """
Urban trees improve air quality and reduce temperature.
Satellite images help researchers identify green spaces.
"""

text2 = """
Trees in cities make the air cleaner and help control heat.
Researchers use satellite imagery to locate vegetation.
"""

score = calculate_semantic_similarity(text1, text2)

print("Semantic Similarity:", score, "%")
