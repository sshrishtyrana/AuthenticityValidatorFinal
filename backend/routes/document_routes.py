import io
import zipfile
import json
from pathlib import Path
from uuid import uuid4

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    UploadFile,
    status,
)
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..database import BASE_DIR, get_db
from ..models import (
    Document,
    User,
    VerificationResult,
    AssignmentSubmission,
)
from ..verification.duplicate_detector import detect_duplicate
from ..processing.preprocessing import preprocess_document
from ..processing.ocr import run_ocr
from ..processing.information_extraction import extract_information
from ..verification.verification_engine import DocumentVerificationEngine
from ..verification.llm_analyzer import analyze_document_consistency
from ..verification.plagiarism_detector import compare_multiple_documents
from ..verification.text_extractor import extract_text

router = APIRouter(
    prefix="/documents",
    tags=["Documents"],
)

UPLOAD_DIR = BASE_DIR / "uploads"
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB

ACADEMIC_DOCUMENT_TYPES = {
    "certificate",
    "marksheet",
    "degree certificate",
    "transcript",
    "academic certificate",
    "research paper",
    "academic report",
    "assignment",
    "project report",
    "other academic document",
}

ADMISSION_DOCUMENT_TYPES = {
    "id proof",
    "transfer certificate",
    "migration certificate",
    "entrance scorecard",
    "admission form",
    "passport",
    "other admission document",
}

STUDENT_DOCUMENT_TYPES = (
        ACADEMIC_DOCUMENT_TYPES | ADMISSION_DOCUMENT_TYPES
)

ADMIN_DOCUMENT_TYPES = (
        STUDENT_DOCUMENT_TYPES | {"auto detect", "other"}
)


def _normalize_document_type(value: str | None) -> str:
    return " ".join((value or "").casefold().split())


def _require_admin(user: User) -> None:
    if (user.role or "user").casefold() != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrator access is required for this operation.",
        )


ALLOWED_EXTENSIONS = {".pdf", ".docx", ".png", ".jpg", ".jpeg"}


# ---------------------------------------------------------
# File Validation
# ---------------------------------------------------------

def validate_file_content(filename: str, content: bytes) -> None:
    """Validate the file extension and basic file signature."""

    extension = Path(filename).suffix.lower()

    if extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Only PDF, DOCX, PNG, JPG, and JPEG files are supported.",
        )

    if not content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The file is empty.",
        )

    if extension == ".pdf" and not content.startswith(b"%PDF-"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The file does not have a valid PDF signature.",
        )

    if extension == ".png" and not content.startswith(
            b"\x89PNG\r\n\x1a\n"
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The file does not have a valid PNG signature.",
        )

    if extension in {".jpg", ".jpeg"} and not content.startswith(
            b"\xff\xd8\xff"
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The file does not have a valid JPEG signature.",
        )

    if extension == ".docx":
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as docx_file:
                required_files = {
                    "[Content_Types].xml",
                    "word/document.xml",
                }

                if not required_files.issubset(set(docx_file.namelist())):
                    raise ValueError("Invalid DOCX structure.")

        except (zipfile.BadZipFile, ValueError, OSError):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="The file does not have a valid DOCX structure.",
            )


# ---------------------------------------------------------
# Upload Document
# ---------------------------------------------------------

@router.post(
    "/upload",
    status_code=status.HTTP_201_CREATED,
)
async def upload_document(
        file: UploadFile = File(...),
        document_type: str = Form("Auto Detect"),
        document_category: str = Form("academic"),
        current_user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
):
    """Upload a document with server-enforced role and type restrictions."""

    role = (current_user.role or "user").casefold()
    normalized_type = _normalize_document_type(document_type)
    document_category = document_category.strip().casefold()

    if document_category not in {"academic", "admission"}:
        raise HTTPException(
            status_code=400,
            detail="Invalid document category."
        )

    if role not in {"admin", "user", "student"}:
        raise HTTPException(
            status_code=403,
            detail="Unauthorized role."
        )

    if role == "admin":
        allowed_types = ADMIN_DOCUMENT_TYPES

    elif document_category == "academic":
        allowed_types = ACADEMIC_DOCUMENT_TYPES

    else:
        allowed_types = ADMISSION_DOCUMENT_TYPES

    if normalized_type not in allowed_types:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unsupported document type '{document_type}' "
                f"for {document_category} documents."
            )
        )

    original_filename = Path(file.filename or "").name

    if not original_filename or original_filename in {".", ".."}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A valid filename is required.",
        )

    try:
        content = await file.read(MAX_FILE_SIZE + 1)
    finally:
        await file.close()

    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="File exceeds the 10 MB upload limit.",
        )

    validate_file_content(original_filename, content)

    # Check for exact duplicate content.
    duplicate = detect_duplicate(
        content=content,
        db=db,
        current_user_id=current_user.id,
    )

    if duplicate["is_duplicate"]:
        same_user = duplicate["status"] == "duplicate_same_user"

        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": (
                    "This file was previously uploaded by your account."
                    if same_user
                    else "An identical file already exists and requires review."
                ),
                "code": "duplicate_document",
                "duplicate_type": (
                    "same_user" if same_user else "existing_record"
                ),
                "reference_id": (
                    duplicate.get("reference_id") if same_user else None
                ),
            },
        )
    # Prepare file storage.
    extension = Path(original_filename).suffix.lower()
    stored_filename = f"{uuid4().hex}{extension}"

    user_directory = UPLOAD_DIR / str(current_user.id)
    user_directory.mkdir(parents=True, exist_ok=True)

    file_path = user_directory / stored_filename

    document = Document(
        user_id=current_user.id,
        original_filename=original_filename,
        stored_filename=stored_filename,
        document_type=document_type.strip(),
        document_category=document_category,
        file_path=str(file_path.resolve()),
        status="uploaded",
    )

    # Save the file and database record.
    try:
        with file_path.open("xb") as output:
            output.write(content)

        db.add(document)
        db.commit()
        db.refresh(document)

    except Exception as exc:
        db.rollback()

        try:
            if file_path.exists():
                file_path.unlink()
        except OSError:
            pass

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Document upload failed. Please try again.",
        ) from exc

    return {
        "message": "Document uploaded successfully.",
        "document_id": document.id,
        "filename": document.original_filename,
        "status": document.status,
        "duplicate_check": {
            "is_duplicate": False,
            "result": "unique_file",
        },
        "document_category": document.document_category,
        "next_step": "Run the document verification pipeline.",
    }


# ---------------------------------------------------------
# Verify Uploaded Document
# ---------------------------------------------------------

@router.post("/{document_id}/verify")
def verify_document(
        document_id: int,
        current_user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
):
    """Process an uploaded document with checks appropriate to the user's role."""

    role = (current_user.role or "user").casefold()

    # 1. Find the document and confirm ownership.
    document = (
        db.query(Document)
        .filter(
            Document.id == document_id,
            Document.user_id == current_user.id,
        )
        .first()
    )

    if document is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found.",
        )

    stored_type = _normalize_document_type(document.document_type)
    if role != "admin" and stored_type not in STUDENT_DOCUMENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This document type can only be verified by an administrator.",
        )

    file_path = Path(document.file_path)

    if not file_path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="The uploaded document file could not be found.",
        )

    try:
        # 2. Preprocess the document.
        processing_dir = (
                BASE_DIR / "processed_documents" / str(current_user.id)
        )

        metadata = preprocess_document(
            input_path=file_path,
            output_dir=processing_dir,
        )

        # 3. Extract text and use OCR when required.
        ocr_result = run_ocr(
            document_metadata=metadata,
            original_document_path=file_path,
            save_output=True,
        )

        document_text = (ocr_result.combined_text or "").strip()

        if not document_text:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="No readable text could be extracted from the document.",
            )

        # 4. Extract structured information.
        extraction = extract_information(document_text)
        info = extraction.document_info

        # 5. Run the existing verification engine.
        engine = DocumentVerificationEngine()

        report = engine.verify(
            extracted_info=extraction,
            document_text=document_text,
            document_bytes=file_path.read_bytes(),
            issuer_verified=False,
        )

        report_data = report.to_dict()

        # 6. Prepare extracted fields for LLM comparison.
        current_llm_document = {
            "document_id": document.id,
            "filename": document.original_filename,
            "extracted_fields": {},
        }

        llm_field_names = (
            "recipient_name",
            "student_id",
            "institution_name",
            "university_name",
            "certificate_number",
            "course_name",
            "degree_name",
            "issue_date",
            "completion_date",
            "grade",
            "percentage",
            "cgpa",
        )

        for field_name in llm_field_names:
            field = getattr(info, field_name, None)

            if field is not None:
                value = getattr(field, "value", field)

                if value is not None and str(value).strip():
                    current_llm_document["extracted_fields"][
                        field_name
                    ] = str(value).strip()

        # 7. Check whether this document belongs to an assignment submission.
        assignment_submission = (
            db.query(AssignmentSubmission)
            .filter(AssignmentSubmission.document_id == document.id)
            .first()
        )

        is_assignment_submission = assignment_submission is not None

        # 7A. Find documents belonging to the correct comparison group.
        if is_assignment_submission:
            previous_documents_query = (
                db.query(Document)
                .join(
                    AssignmentSubmission,
                    AssignmentSubmission.document_id == Document.id,
                )
                .filter(
                    AssignmentSubmission.assignment_id
                    == assignment_submission.assignment_id,
                    Document.id != document.id,
                    Document.status == "processed",
                )
            )

            previous_documents = previous_documents_query.all()

        elif stored_type == "research paper":
            previous_documents = (
                db.query(Document)
                .filter(
                    Document.id != document.id,
                    Document.status == "processed",
                    Document.document_category == "academic",
                )
                .all()
            )

            previous_documents = [
                previous_document
                for previous_document in previous_documents
                if _normalize_document_type(
                    previous_document.document_type
                ) == "research paper"
            ]

        else:
            previous_documents = []

        # 7B. Extract previous document text and compare.
        documents_for_similarity = []

        for previous_document in previous_documents:
            try:
                previous_text = extract_text(previous_document.file_path)

                if previous_text.strip():
                    documents_for_similarity.append({
                        "document_id": previous_document.id,
                        "filename": previous_document.original_filename,
                        "text": previous_text,
                    })

            except Exception:
                # Skip documents whose text cannot be extracted.
                continue
        similarity_results = []

        if documents_for_similarity:
            similarity_results = compare_multiple_documents(
                current_text=document_text,
                previous_documents=documents_for_similarity,
            )

        previous_results_query = (
            db.query(Document, VerificationResult)
            .join(
                VerificationResult,
                VerificationResult.document_id == Document.id,
            )
            .filter(
                Document.id != document.id,
                Document.status == "processed",
            )
        )

        # Admins compare against the institution-wide processed record set;
        # students are restricted to records belonging to their own account.
        if role != "admin" and not is_assignment_submission:
            previous_results_query = previous_results_query.filter(
                Document.user_id == current_user.id
            )

        previous_results = previous_results_query.all()

        def normalize_identity(value):
            if value is None:
                return ""
            return " ".join(str(value).casefold().split())

        current_fields = current_llm_document["extracted_fields"]

        current_student_id = normalize_identity(
            current_fields.get("student_id")
        )
        current_name = normalize_identity(
            current_fields.get("recipient_name")
        )
        current_institution = normalize_identity(
            current_fields.get("institution_name")
            or current_fields.get("university_name")
        )

        comparable_documents = []

        for previous_document, previous_result in previous_results:
            try:
                previous_details = json.loads(
                    previous_result.details or "{}"
                )
            except (json.JSONDecodeError, TypeError):
                continue

            previous_fields = previous_details.get(
                "extracted_fields", {}
            )

            if not isinstance(previous_fields, dict):
                continue

            previous_student_id = normalize_identity(
                previous_fields.get("student_id")
            )
            previous_name = normalize_identity(
                previous_fields.get("recipient_name")
            )
            previous_institution = normalize_identity(
                previous_fields.get("institution_name")
                or previous_fields.get("university_name")
            )

            # Prefer an exact student-ID match.
            same_student = (
                    bool(current_student_id)
                    and bool(previous_student_id)
                    and current_student_id == previous_student_id
            )

            # If either ID is missing, require both name and
            # institution to match.
            if not current_student_id or not previous_student_id:
                same_student = (
                        bool(current_name)
                        and bool(current_institution)
                        and current_name == previous_name
                        and current_institution == previous_institution
                )

            if same_student:
                comparable_documents.append({
                    "document_id": previous_document.id,
                    "filename": previous_document.original_filename,
                    "extracted_fields": previous_fields,
                })

        # 8. Run the LLM only when matching prior documents exist.
        llm_analysis = {
            "status": "skipped",
            "message": "No matching prior documents were found.",
            "findings": [],
        }

        if comparable_documents:
            documents_to_compare = comparable_documents + [
                current_llm_document
            ]

            try:
                llm_analysis = analyze_document_consistency(
                    documents_to_compare
                )
            except Exception:
                # LLM failure should not prevent ordinary verification.
                llm_analysis = {
                    "status": "error",
                    "message": "LLM analysis could not be completed.",
                    "findings": [],
                }

        # Include the LLM findings in the report.
        report_data["llm_consistency_analysis"] = llm_analysis

        # 9. Collect fields to save in the database.
        field_names = (
            "document_title",
            "document_type",
            "recipient_name",
            "student_id",
            "certificate_number",
            "institution_name",
            "university_name",
            "issuer_name",
            "course_name",
            "degree_name",
            "issue_date",
            "completion_date",
            "grade",
            "marks",
            "percentage",
            "cgpa",
        )

        extracted_fields = {}

        for field_name in field_names:
            field_value = getattr(info, field_name, None)

            if field_value is not None:
                value = getattr(field_value, "value", field_value)

                if value is None or isinstance(
                        value, (str, int, float, bool)
                ):
                    extracted_fields[field_name] = value
                else:
                    extracted_fields[field_name] = str(value)

        # Certificate-code matching is restricted to administrators.
        def normalize_certificate_code(value):
            if value is None:
                return ""
            return "".join(
                char for char in str(value).upper()
                if char.isalnum()
            )

        current_certificate_code = (
            normalize_certificate_code(
                extracted_fields.get("certificate_number")
            )
            if role == "admin" or is_assignment_submission else ""
        )

        certificate_code_check = {
            "status": "code_not_found",
            "certificate_number": extracted_fields.get("certificate_number"),
            "message": (
                "No certificate number could be extracted from this document."
            ),
            "matches": [],
        }

        if current_certificate_code:
            matching_codes = []

            for previous_document, previous_result in previous_results:
                try:
                    previous_details = json.loads(
                        previous_result.details or "{}"
                    )
                except (json.JSONDecodeError, TypeError):
                    continue

                previous_fields = previous_details.get(
                    "extracted_fields", {}
                )

                if not isinstance(previous_fields, dict):
                    continue

                previous_code = normalize_certificate_code(
                    previous_fields.get("certificate_number")
                )

                if previous_code != current_certificate_code:
                    continue

                previous_name = normalize_identity(
                    previous_fields.get("recipient_name")
                )
                previous_student_id = normalize_identity(
                    previous_fields.get("student_id")
                )
                previous_institution = normalize_identity(
                    previous_fields.get("institution_name")
                    or previous_fields.get("university_name")
                )

                matching_codes.append({
                    "document_id": previous_document.id,
                    "filename": previous_document.original_filename,
                    "recipient_name": previous_name,
                    "student_id": previous_student_id,
                    "institution": previous_institution,
                })

            if matching_codes:
                certificate_code_check = {
                    "status": "duplicate_code_found",
                    "certificate_number": extracted_fields.get(
                        "certificate_number"
                    ),
                    "message": (
                        "The certificate number matches an existing record."
                    ),
                    "matches": matching_codes,
                }
            else:
                certificate_code_check = {
                    "status": "unique_code",
                    "certificate_number": extracted_fields.get(
                        "certificate_number"
                    ),
                    "message": (
                        "No matching certificate number was found."
                    ),
                    "matches": [],
                }
        # Include the certificate-code check in the verification report.
        if role == "admin" or is_assignment_submission:
            report_data["certificate_code_check"] = certificate_code_check
        else:
            report_data.pop("certificate_code_check", None)

        # 9A. Prepare similarity analysis for database storage.
        similarity_score = (
            similarity_results[0]["similarity_percentage"]
            if similarity_results
            else None
        )

        similarity_analysis = {
            "status": (
                "completed" if similarity_results else "no_comparisons"
            ),
            "comparison_group": (
                "assignment"
                if is_assignment_submission
                else "research_paper"
                if stored_type == "research paper"
                else "not_applicable"
            ),
            "highest_similarity": similarity_score,
            "label": (
                similarity_results[0]["label"]
                if similarity_results
                else "Not available"
            ),
            "compared_documents": similarity_results,
        }

        report_data["similarity_analysis"] = similarity_analysis

        # 10. Save a new result or update the existing result.
        result = (
            db.query(VerificationResult)
            .filter(
                VerificationResult.document_id == document.id
            )
            .first()
        )

        if result is None:
            result = VerificationResult(document_id=document.id)
            db.add(result)

        result.overall_score = report.document_score
        result.verdict = report.verdict

        # These scores are not yet calibrated by the current engine.
        result.authenticity_score = None
        result.similarity_score = similarity_score
        result.ocr_confidence = ocr_result.average_confidence

        result.details = json.dumps(
            {
                "verification_report": report_data,
                "llm_consistency_analysis": llm_analysis,
                "similarity_analysis": similarity_analysis,
                "extraction_status": extraction.status,
                "extraction_warnings": extraction.warnings,
                "extraction_errors": extraction.errors,
                "extracted_fields": extracted_fields,
                "ocr_warnings": ocr_result.warnings,
                "ocr_processing_status": ocr_result.processing_status,
            },
            default=str,
        )

        document.status = "processed"

        db.commit()
        db.refresh(result)

        # 11. Return the verification result and LLM analysis.
        return {
            "message": "Document processing completed.",
            "document_id": document.id,
            "filename": document.original_filename,
            "status": document.status,
            "verification_result": {
                "result_id": result.id,
                "overall_score": result.overall_score,
                "verdict": result.verdict,
                "authenticity_score": result.authenticity_score,
                "similarity_score": result.similarity_score,
                "ocr_confidence": result.ocr_confidence,
                "ocr_text": document_text,
                "extracted_fields": extracted_fields,
                "report": report_data,
                "llm_consistency_analysis": llm_analysis,
            },
        }

    except HTTPException:
        db.rollback()
        raise

    except Exception as exc:
        db.rollback()

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Document verification failed: {exc}",
        ) from exc


@router.get("/admin/plagiarism-documents")
def get_plagiarism_documents(
        current_user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
):
    if (current_user.role or "").casefold() != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrator access required.",
        )

    documents = (
        db.query(Document)
        .filter(
            Document.document_category == "academic"
        )
        .order_by(Document.id.desc())
        .all()
    )

    results = []

    for document in documents:
        verification = (
            db.query(VerificationResult)
            .filter(
                VerificationResult.document_id == document.id
            )
            .order_by(VerificationResult.id.desc())
            .first()
        )

        details = {}

        if verification and verification.details:
            try:
                details = (
                    json.loads(verification.details)
                    if isinstance(verification.details, str)
                    else verification.details
                )
            except (ValueError, TypeError):
                details = {}

        results.append({
            "document_id": document.id,
            "filename": document.original_filename,
            "document_type": document.document_type,
            "category": document.document_category,
            "status": document.status,
            "similarity_score": (
                verification.similarity_score
                if verification else None
            ),
            "similarity_analysis": details.get(
                "similarity_analysis", {}
            ),
        })

    return {
        "total_documents": len(results),
        "documents": results,
    }

