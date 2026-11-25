
import json
import requests


OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "llama3.2:3b"


def analyze_document_consistency(documents: list[dict]) -> dict:
    """
    Compare extracted information from documents believed
    to belong to the same student.

    Each document should contain:
    {
        "document_id": 1,
        "filename": "degree.pdf",
        "extracted_fields": {
            "recipient_name": "Example Student",
            "institution_name": "Example University",
            "completion_date": "2025"
        }
    }
    """

    if len(documents) < 2:
        return {
            "status": "skipped",
            "message": "At least two documents are required for comparison.",
            "findings": [],
        }

    prompt = f"""
You are assisting with academic document consistency review.

Compare the extracted fields from these documents:

{json.dumps(documents, ensure_ascii=False, indent=2)}

Identify only meaningful contradictions supported by the supplied data.

Rules:
1. Do not assume missing information is a contradiction.
2. Do not invent facts or correct extracted values.
3. Different document types may legitimately contain different fields.
4. Similar names or dates are not automatically evidence of fraud.
5. Never declare a document fake. Recommend manual review when appropriate.
6. Include the exact conflicting values and source document IDs.
7. Do not report a contradiction if the supplied values are identical.
8. Return valid JSON only, without Markdown fences.

Use this JSON structure:

{{
    "findings": [
        {{
            "field": "completion_date",
            "issue": "The documents report different completion dates.",
            "evidence": [
                {{
                    "document_id": 1,
                    "value": "2025"
                }},
                {{
                    "document_id": 2,
                    "value": "2026"
                }}
            ],
            "recommendation": "Review the original documents to confirm the correct date."
        }}
    ]
}}

If there are no meaningful contradictions, return:

{{"findings": []}}
"""

    try:
        response = requests.post(
            OLLAMA_URL,
            json={
                "model": OLLAMA_MODEL,
                "prompt": prompt,
                "stream": False,
                "format": "json",
            },
            timeout=120,
        )

        response.raise_for_status()

        result = response.json()
        raw_output = result.get("response", "").strip()

        parsed = json.loads(raw_output)
        findings = parsed.get("findings", [])

        if not isinstance(findings, list):
            raise ValueError(
                "The model returned an invalid findings list."
            )

        # Validate Ollama findings using the original extracted values.
        validated_findings = []

        for finding in findings:

            if not isinstance(finding, dict):
                continue

            field = finding.get("field")

            if not isinstance(field, str) or not field.strip():
                continue

            actual_values = []

            for document in documents:

                extracted_fields = document.get(
                    "extracted_fields", {}
                )

                if not isinstance(extracted_fields, dict):
                    continue

                value = extracted_fields.get(field)

                # Missing values are not contradictions.
                if value is None or not str(value).strip():
                    continue

                normalized_value = " ".join(
                    str(value).strip().lower().split()
                )

                actual_values.append(normalized_value)

            # Keep a finding only if at least two different
            # non-empty values actually exist.
            if len(set(actual_values)) < 2:
                continue

            validated_findings.append(finding)

        return {
            "status": "completed",
            "findings": validated_findings,
        }

    except (
        requests.RequestException,
        json.JSONDecodeError,
        ValueError,
    ) as exc:

        return {
            "status": "error",
            "message": str(exc),
            "findings": [],
        }
