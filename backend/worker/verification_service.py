
import json
from typing import Optional

from ..database import SessionLocal
from ..models import (
    User,
    AssignmentSubmission,
    VerificationResult,
)
from ..routes.document_routes import verify_document


def process_assignment_verification(
    document_id: int,
    student_id: int,
    file_duplicate: bool,
    duplicate_reference_id: Optional[int],
):
    db = SessionLocal()

    try:
        student = (
            db.query(User)
            .filter(User.id == student_id)
            .first()
        )

        submission = (
            db.query(AssignmentSubmission)
            .filter(
                AssignmentSubmission.document_id == document_id
            )
            .first()
        )

        if not student or not submission:
            raise RuntimeError(
                f"Student or submission not found for document {document_id}"
            )

        # Mark automated verification as running.
        submission.verification_status = "processing"
        db.commit()

        try:
            # Run the existing verification pipeline unchanged.
            verify_document(document_id, student, db)

            verification_record = (
                db.query(VerificationResult)
                .filter(
                    VerificationResult.document_id == document_id
                )
                .first()
            )

            if not verification_record:
                raise RuntimeError(
                    "Verification finished without saving a result."
                )

            # Preserve exact-file duplicate detection evidence.
            try:
                details = json.loads(
                    verification_record.details or "{}"
                )
            except (TypeError, ValueError):
                details = {}

            details["exact_file_duplicate_check"] = {
                "is_duplicate": file_duplicate,
                "reference_id": duplicate_reference_id,
                "status": (
                    "duplicate" if file_duplicate else "unique_file"
                ),
            }

            verification_record.details = json.dumps(
                details,
                default=str,
            )

            submission.verification_status = "completed"
            db.commit()

        except Exception:
            db.rollback()

            failed_submission = (
                db.query(AssignmentSubmission)
                .filter(
                    AssignmentSubmission.document_id == document_id
                )
                .first()
            )

            if failed_submission:
                failed_submission.verification_status = "failed"
                db.commit()

            raise

    finally:
        db.close()
