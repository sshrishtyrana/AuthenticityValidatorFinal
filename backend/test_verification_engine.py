
from types import SimpleNamespace

from verification.verification_engine import (
    DocumentVerificationEngine,
)


def field(value):
    if value is None:
        return None
    return SimpleNamespace(value=value)


def test_missing_required_fields():
    info = SimpleNamespace(
        recipient_name=None,
        institution_name=None,
        certificate_number=None,
        student_id=None,
        start_date=None,
        completion_date=None,
        issue_date=None,
    )

    report = DocumentVerificationEngine().verify(
        info,
        document_text="Sample academic document text.",
    )

    assert report.verdict == "Flagged"
    assert report.document_score >= 0
    assert report.document_score <= 100
    assert report.to_dict()["checks"]


def test_complete_but_unverified_document():
    info = SimpleNamespace(
        recipient_name=field("Sample Student"),
        institution_name=field("Example University"),
        certificate_number=field("CERT-12345"),
        student_id=None,
        start_date=field("01/01/2024"),
        completion_date=field("01/06/2024"),
        issue_date=field("15/06/2024"),
    )

    report = DocumentVerificationEngine().verify(
        info,
        document_text=(
            "Academic completion certificate for Sample Student "
            "issued by Example University."
        ),
    )

    # Consistent text alone must not prove authenticity.
    assert report.verdict == "Manual Review"


if __name__ == "__main__":
    test_missing_required_fields()
    test_complete_but_unverified_document()
    print("All verification engine tests passed!")
