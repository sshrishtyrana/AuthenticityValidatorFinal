
from backend.verification.llm_analyzer import analyze_document_consistency


sample_documents = [
    {
        "document_id": 1,
        "filename": "degree_certificate.pdf",
        "extracted_fields": {
            "recipient_name": "Aarav Sharma",
            "institution_name": "ABC University",
            "completion_date": "2025",
        },
    },
    {
        "document_id": 2,
        "filename": "academic_transcript.pdf",
        "extracted_fields": {
            "recipient_name": "Aarav Sharma",
            "institution_name": "ABC University",
            "completion_date": "2026",
        },
    },
]


result = analyze_document_consistency(sample_documents)

print("\nLLM Analysis Result:")
print(result)
