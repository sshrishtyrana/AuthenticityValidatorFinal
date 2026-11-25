
"""
Document Verification Engine
Authenticity Validator for Academia

This module evaluates document consistency and available evidence.
It does not independently prove that a document is authentic.
"""

from dataclasses import dataclass, asdict
from typing import Any, Optional
import hashlib
import json
import re


@dataclass
class VerificationCheck:
    name: str
    status: str
    message: str
    points: int = 0
    evidence: Optional[str] = None


@dataclass
class VerificationReport:
    document_score: int
    verdict: str
    checks: list[VerificationCheck]
    summary: str

    def to_dict(self) -> dict:
        return {
            "document_score": self.document_score,
            "verdict": self.verdict,
            "summary": self.summary,
            "checks": [asdict(check) for check in self.checks],
        }


class DocumentVerificationEngine:
    """Rule-based consistency and evidence checks."""

    REQUIRED_FIELDS = (
        "recipient_name",
        "institution_name",
    )

    def verify(
        self,
        extracted_info: Any,
        document_text: str = "",
        document_bytes: bytes = b"",
        known_identifiers: Optional[set] = None,
        issuer_verified: bool = False,
    ) -> VerificationReport:

        checks = []
        known_identifiers = known_identifiers or set()

        # Support either the extraction result or its document_info.
        info = getattr(
            extracted_info, "document_info", extracted_info
        )

        def get_value(field_name):
            field = (
                info.get(field_name)
                if isinstance(info, dict)
                else getattr(info, field_name, None)
            )

            if isinstance(field, dict):
                value = field.get("value")
            else:
                value = getattr(field, "value", field)

            if value is None:
                return None

            value = str(value).strip()
            return value or None

        # 1. Required-field completeness
        missing = [
            field for field in self.REQUIRED_FIELDS
            if not get_value(field)
        ]

        if missing:
            checks.append(VerificationCheck(
                name="required_fields",
                status="warning",
                message="Some important fields could not be extracted.",
                points=0,
                evidence=", ".join(missing),
            ))
        else:
            checks.append(VerificationCheck(
                name="required_fields",
                status="pass",
                message="Recipient and institution fields are present.",
                points=20,
            ))

        # 2. Identifier format and duplicate checks
        identifier = (
            get_value("certificate_number")
            or get_value("student_id")
        )

        if not identifier:
            checks.append(VerificationCheck(
                name="identifier",
                status="review",
                message="No certificate or student identifier was found.",
                evidence="An identifier may not be required for every document.",
            ))
        elif len(identifier) < 3 or len(identifier) > 100:
            checks.append(VerificationCheck(
                name="identifier",
                status="warning",
                message="The extracted identifier has an unusual length.",
                evidence=identifier,
            ))
        elif identifier.casefold() in {
            str(item).strip().casefold()
            for item in known_identifiers
        }:
            checks.append(VerificationCheck(
                name="duplicate_identifier",
                status="warning",
                message="This identifier already exists in the comparison set.",
                evidence=identifier,
            ))
        else:
            checks.append(VerificationCheck(
                name="identifier",
                status="pass",
                message="An identifier was extracted and passed basic checks.",
                points=15,
                evidence=identifier,
            ))

        # 3. Date consistency
        start = get_value("start_date")
        completion = get_value("completion_date")
        issue = get_value("issue_date")

        def parse_date(value):
            if not value:
                return None

            from datetime import datetime

            formats = (
                "%d/%m/%Y", "%d-%m-%Y",
                "%Y-%m-%d", "%d.%m.%Y",
                "%B %d, %Y", "%d %B %Y",
                "%b %d, %Y", "%d %b %Y",
            )

            for fmt in formats:
                try:
                    return datetime.strptime(value, fmt).date()
                except ValueError:
                    continue

            return None

        dates = {
            "start_date": parse_date(start),
            "completion_date": parse_date(completion),
            "issue_date": parse_date(issue),
        }

        invalid_order = False

        if dates["start_date"] and dates["completion_date"]:
            invalid_order = (
                dates["start_date"] > dates["completion_date"]
            )

        if (
            dates["completion_date"]
            and dates["issue_date"]
            and dates["issue_date"] < dates["completion_date"]
        ):
            invalid_order = True

        if invalid_order:
            checks.append(VerificationCheck(
                name="date_consistency",
                status="warning",
                message="Extracted dates appear inconsistent.",
                evidence=f"Start: {start}; completion: {completion}; issue: {issue}",
            ))
        elif any(dates.values()):
            checks.append(VerificationCheck(
                name="date_consistency",
                status="pass",
                message="No date-order conflict was detected among parseable dates.",
                points=15,
            ))
        else:
            checks.append(VerificationCheck(
                name="date_consistency",
                status="review",
                message="Dates could not be reliably compared.",
            ))

        # 4. Repeated document content
        if document_bytes:
            digest = hashlib.sha256(document_bytes).hexdigest()
            checks.append(VerificationCheck(
                name="document_fingerprint",
                status="info",
                message="A SHA-256 fingerprint was generated for comparison.",
                evidence=digest,
            ))
        elif document_text.strip():
            digest = hashlib.sha256(
                document_text.encode("utf-8")
            ).hexdigest()
            checks.append(VerificationCheck(
                name="document_fingerprint",
                status="info",
                message="A fingerprint of the extracted text was generated.",
                evidence=digest,
            ))
        else:
            checks.append(VerificationCheck(
                name="document_fingerprint",
                status="review",
                message="No document content was supplied for fingerprinting.",
            ))

        # 5. Basic text-quality indicators
        if document_text.strip():
            text = document_text.strip()
            alphanumeric = sum(char.isalnum() for char in text)
            replacement_chars = text.count("\ufffd")

            if len(text) < 30 or alphanumeric < 15:
                checks.append(VerificationCheck(
                    name="text_quality",
                    status="warning",
                    message="Very little readable text was available.",
                ))
            elif replacement_chars:
                checks.append(VerificationCheck(
                    name="text_quality",
                    status="review",
                    message="OCR or text decoding produced replacement characters.",
                    evidence=f"Count: {replacement_chars}",
                ))
            else:
                checks.append(VerificationCheck(
                    name="text_quality",
                    status="pass",
                    message="Readable text was available for consistency checks.",
                    points=10,
                ))

        # Score measures consistency evidence, not authenticity probability.
        score = min(
            100,
            sum(check.points for check in checks)
        )

        warning_found = any(
            check.status == "warning"
            for check in checks
        )

        if warning_found:
            verdict = "Flagged"
            summary = (
                "Potential inconsistencies were found. "
                "Review the evidence before making a decision."
            )
        elif issuer_verified:
            verdict = "Verified"
            summary = (
                "The issuer verification was reported as successful. "
                "Review the supporting evidence and verification record."
            )
        else:
            verdict = "Manual Review"
            summary = (
                "No decisive warning was found, but authenticity has "
                "not been established by an authoritative issuer."
            )

        return VerificationReport(
            document_score=score,
            verdict=verdict,
            checks=checks,
            summary=summary,
        )
