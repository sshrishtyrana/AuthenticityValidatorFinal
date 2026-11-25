from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List
from uuid import uuid4

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    UploadFile,
    File,
    BackgroundTasks,
)
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session, joinedload

from ..auth import get_current_user
from ..database import get_db, BASE_DIR, SessionLocal
from ..models import (
    User,
    Assignment,
    AssignmentTarget,
    AssignmentSubmission,
    Document,
    VerificationResult,
)
from ..verification.duplicate_detector import detect_duplicate
from .document_routes import (
    validate_file_content,
    verify_document,
)
import json

router = APIRouter(
    prefix="/assignments",
    tags=["Assignments"],
)

UPLOAD_DIR = BASE_DIR / "uploads"
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB

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
            return

        # Mark automated verification as running.
        submission.verification_status = "processing"
        db.commit()

        try:
            # Keep the existing verification pipeline unchanged.
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

            # Preserve the exact-file duplicate detection evidence.
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

            # Automated processing completed successfully.
            submission.verification_status = "completed"
            db.commit()

        except Exception as error:
            db.rollback()

            # Processing failure must not change the admin's decision.
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

            print(
                f"Verification failed for document {document_id}: "
                f"{error}"
            )

    except Exception:
        db.rollback()
        raise

    finally:
        db.close()


# ---------------------------------------------------------
# ACCESS CONTROL
# ---------------------------------------------------------

def require_admin(user: User):
    if (user.role or "").casefold() != "admin":
        raise HTTPException(
            status_code=403,
            detail="Administrator access is required.",
        )


def require_student(user: User):
    if (user.role or "").casefold() not in {"user", "student"}:
        raise HTTPException(
            status_code=403,
            detail="Student access is required.",
        )


# ---------------------------------------------------------
# DATETIME HELPER
# ---------------------------------------------------------

def _as_utc_naive(value):
    if value is None:
        return None

    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    return value


# ---------------------------------------------------------
# REQUEST SCHEMA
# ---------------------------------------------------------

class AssignmentCreate(BaseModel):
    title: str = Field(min_length=3, max_length=255)
    instructions: Optional[str] = None

    category: str
    document_type: str

    eligibility_type: str = "all"
    student_ids: List[int] = Field(default_factory=list)

    course: Optional[str] = None
    department: Optional[str] = None
    academic_year: Optional[str] = None
    semester: Optional[str] = None
    admission_batch: Optional[str] = None

    start_at: Optional[datetime] = None
    due_at: Optional[datetime] = None

    status: str = "draft"
class AdminReviewUpdate(BaseModel):
 decision: str
 notes: Optional[str] = None


# ---------------------------------------------------------
# SERIALIZATION
# ---------------------------------------------------------

def assignment_data(assignment, student_id=None):
    target_count = len(assignment.targets)
    submissions = assignment.submissions

    if student_id is not None:
        submissions = [
            submission
            for submission in submissions
            if submission.student_id == student_id
        ]

    return {
        "id": assignment.id,
        "title": assignment.title,
        "instructions": assignment.instructions,
        "category": assignment.category,
        "document_type": assignment.document_type,
        "eligibility_type": assignment.eligibility_type,
        "course": assignment.course,
        "department": assignment.department,
        "academic_year": assignment.academic_year,
        "semester": assignment.semester,
        "admission_batch": assignment.admission_batch,
        "start_at": assignment.start_at,
        "due_at": assignment.due_at,
        "status": assignment.status,
        "created_at": assignment.created_at,
        "assigned_students": target_count,
        "submission_count": len(submissions),
        "submissions": [
            {
                "id": submission.id,
                "student_id": submission.student_id,
                "document_id": submission.document_id,
                "submitted_at": submission.submitted_at,
                "verification_status": (
                    submission.verification_status
                    if student_id is None
                    else None
                ),
                "review_status": (
                    submission.review_status
                    if student_id is None
                    else None
                ),
                "review_notes": (
                    submission.review_notes
                    if student_id is None
                    else None
                ),
                "reviewed_by": (
                    submission.reviewed_by
                    if student_id is None
                    else None
                ),
                "reviewed_at": (
                    submission.reviewed_at
                    if student_id is None
                    else None
                ),
            }
            for submission in submissions
        ],
    }


# ---------------------------------------------------------
# CREATE ASSIGNMENT (ADMIN)
# ---------------------------------------------------------

@router.post("/", status_code=201)
def create_assignment(
    data: AssignmentCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_admin(current_user)

    category = data.category.strip().casefold()
    eligibility = data.eligibility_type.strip().casefold()
    assignment_status = data.status.strip().casefold()

    if category not in {"academic", "admission"}:
        raise HTTPException(400, "Invalid assignment category.")

    if assignment_status not in {"draft", "published"}:
        raise HTTPException(400, "Status must be draft or published.")

    allowed_eligibility = {
        "all",
        "individual",
        "selected",
        "course",
        "department",
        "semester",
        "academic_year",
        "admission_batch",
    }

    if eligibility not in allowed_eligibility:
        raise HTTPException(400, "Invalid eligibility type.")

    start_at = _as_utc_naive(data.start_at)
    due_at = _as_utc_naive(data.due_at)

    if start_at and due_at and due_at <= start_at:
        raise HTTPException(
            400,
            "The deadline must be later than the start date.",
        )

    students_query = db.query(User).filter(
        User.is_active == True,
        User.role.in_(["user", "student"]),
    )

    if eligibility in {"individual", "selected"}:
        if not data.student_ids:
            raise HTTPException(
                400,
                "Select at least one student.",
            )

        students_query = students_query.filter(
            User.id.in_(data.student_ids)
        )

    elif eligibility == "course":
        if not data.course:
            raise HTTPException(400, "Course is required.")

        students_query = students_query.filter(
            User.course == data.course
        )

    elif eligibility == "department":
        if not data.department:
            raise HTTPException(400, "Department is required.")

        students_query = students_query.filter(
            User.department == data.department
        )

    elif eligibility == "semester":
        if not data.semester:
            raise HTTPException(400, "Semester is required.")

        students_query = students_query.filter(
            User.semester == data.semester
        )

    elif eligibility == "academic_year":
        if not data.academic_year:
            raise HTTPException(400, "Academic year is required.")

        students_query = students_query.filter(
            User.academic_year == data.academic_year
        )

    elif eligibility == "admission_batch":
        if not data.admission_batch:
            raise HTTPException(400, "Admission batch is required.")

        students_query = students_query.filter(
            User.admission_batch == data.admission_batch
        )

    students = students_query.all()

    if not students:
        raise HTTPException(
            400,
            "No eligible active students were found.",
        )

    if eligibility in {"individual", "selected"}:
        found_ids = {student.id for student in students}
        missing_ids = set(data.student_ids) - found_ids

        if missing_ids:
            raise HTTPException(
                400,
                f"Invalid or inactive student IDs: {sorted(missing_ids)}",
            )

    assignment = Assignment(
        title=data.title.strip(),
        instructions=data.instructions,
        category=category,
        document_type=data.document_type.strip(),
        created_by=current_user.id,
        eligibility_type=eligibility,
        course=data.course,
        department=data.department,
        academic_year=data.academic_year,
        semester=data.semester,
        admission_batch=data.admission_batch,
        start_at=start_at,
        due_at=due_at,
        status=assignment_status,
    )

    db.add(assignment)
    db.flush()

    for student in students:
        db.add(
            AssignmentTarget(
                assignment_id=assignment.id,
                student_id=student.id,
            )
        )

    db.commit()
    db.refresh(assignment)

    return {
        "message": "Assignment created successfully.",
        "assignment": assignment_data(assignment),
    }
# ---------------------------------------------------------
# ADMIN: DELETE ASSIGNMENT
# ---------------------------------------------------------

@router.delete("/{assignment_id}")
def delete_assignment(
    assignment_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_admin(current_user)

    assignment = (
        db.query(Assignment)
        .filter(Assignment.id == assignment_id)
        .first()
    )

    if assignment is None:
        raise HTTPException(
            status_code=404,
            detail="Assignment not found.",
        )

    # Do not delete assignments containing student submissions.
    submission_count = (
        db.query(AssignmentSubmission)
        .filter(
            AssignmentSubmission.assignment_id == assignment_id
        )
        .count()
    )

    if submission_count > 0:
        raise HTTPException(
            status_code=409,
            detail=(
                "This assignment has student submissions "
                "and cannot be deleted."
            ),
        )

    try:
        # Remove student assignment targets first.
        db.query(AssignmentTarget).filter(
            AssignmentTarget.assignment_id == assignment_id
        ).delete(synchronize_session=False)

        db.delete(assignment)
        db.commit()

        return {
            "message": "Assignment deleted successfully.",
            "assignment_id": assignment_id,
        }

    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail="Could not delete assignment.",
        )

# ---------------------------------------------------------
# ADMIN: VIEW ALL ASSIGNMENTS
# ---------------------------------------------------------

@router.get("/admin/all")
def admin_assignments(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_admin(current_user)

    assignments = (
        db.query(Assignment)
        .options(
            joinedload(Assignment.targets),
            joinedload(Assignment.submissions),
        )
        .order_by(Assignment.created_at.desc())
        .all()
    )

    return {
        "assignments": [
            assignment_data(assignment)
            for assignment in assignments
        ]
    }


# ---------------------------------------------------------
# STUDENT: VIEW ASSIGNED TASKS
# ---------------------------------------------------------

@router.get("/my")
def my_assignments(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_student(current_user)

    assignments = (
        db.query(Assignment)
        .join(
            AssignmentTarget,
            AssignmentTarget.assignment_id == Assignment.id,
        )
        .filter(
            AssignmentTarget.student_id == current_user.id,
            Assignment.status == "published",
        )
        .options(
            joinedload(Assignment.targets),
            joinedload(Assignment.submissions),
        )
        .order_by(Assignment.due_at.asc())
        .all()
    )

    now = datetime.utcnow()
    results = []

    for assignment in assignments:
        item = assignment_data(
            assignment,
            student_id=current_user.id,
        )

        start_at = _as_utc_naive(assignment.start_at)
        due_at = _as_utc_naive(assignment.due_at)

        item["available"] = (
            start_at is None or start_at <= now
        )

        item["deadline_passed"] = (
            due_at is not None and due_at < now
        )

        results.append(item)

    return {"assignments": results}


# ---------------------------------------------------------
# STUDENT: SUBMIT ASSIGNMENT
# ---------------------------------------------------------

@router.post("/{assignment_id}/submit", status_code=201)
async def submit_assignment(
    assignment_id: int,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_student(current_user)

    assignment = (
        db.query(Assignment)
        .filter(Assignment.id == assignment_id)
        .first()
    )

    if assignment is None:
        raise HTTPException(404, "Assignment not found.")

    target = (
        db.query(AssignmentTarget)
        .filter(
            AssignmentTarget.assignment_id == assignment_id,
            AssignmentTarget.student_id == current_user.id,
        )
        .first()
    )

    if target is None:
        raise HTTPException(
            403,
            "You are not assigned this task.",
        )

    if assignment.status != "published":
        raise HTTPException(
            400,
            "This assignment is not open for submissions.",
        )

    now = datetime.utcnow()
    start_at = _as_utc_naive(assignment.start_at)
    due_at = _as_utc_naive(assignment.due_at)

    if start_at and now < start_at:
        raise HTTPException(
            400,
            "This assignment is not open yet.",
        )

    if due_at and now > due_at:
        raise HTTPException(
            400,
            "The submission deadline has passed.",
        )

    filename = Path(file.filename or "").name

    if not filename or filename in {".", ".."}:
        raise HTTPException(400, "Invalid filename.")

    try:
        content = await file.read(MAX_FILE_SIZE + 1)
    finally:
        await file.close()

    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(
            413,
            "File size exceeds the 10 MB limit.",
        )

    validate_file_content(filename, content)

    duplicate = detect_duplicate(
        content=content,
        db=db,
        current_user_id=current_user.id,
    )
    
    # Record exact-file duplicate information without blocking submission.
    file_duplicate = duplicate.get("is_duplicate", False)
    duplicate_reference_id = duplicate.get("reference_id")

    extension = Path(filename).suffix.lower()
    stored_filename = f"{uuid4().hex}{extension}"

    user_directory = UPLOAD_DIR / str(current_user.id)
    user_directory.mkdir(parents=True, exist_ok=True)

    file_path = user_directory / stored_filename

    document = Document(
        user_id=current_user.id,
        original_filename=filename,
        stored_filename=stored_filename,
        document_type=assignment.document_type,
        document_category=assignment.category,
        file_path=str(file_path.resolve()),
        status="uploaded",
    )

    try:
        with file_path.open("xb") as output:
            output.write(content)

        db.add(document)
        db.flush()

        submission = AssignmentSubmission(
            assignment_id=assignment.id,
            student_id=current_user.id,
            document_id=document.id,
            verification_status="queued",
            review_status="pending",
        )

        db.add(submission)
        db.commit()
        db.refresh(submission)
        background_tasks.add_task(
            process_assignment_verification,
            document.id,
            current_user.id,
            file_duplicate,
            duplicate_reference_id,
        )
        

    except Exception:
        db.rollback()

        if file_path.exists():
            file_path.unlink()

        raise HTTPException(
            500,
            "Could not save the assignment submission.",
        )

    return {
        "message": "Assignment submitted successfully. Verification is processing in the background.",
        "submission": {
            "id": submission.id,
            "assignment_id": submission.assignment_id,
            "document_id": submission.document_id,
            "submitted_at": submission.submitted_at,
            "verification_status": 
              submission.verification_status,
              
            "review_status": submission.review_status,
            "review_notes": submission.review_notes,
            "reviewed_by": submission.reviewed_by,
            "reviewed_at": submission.reviewed_at,
            "verification":  None,
        },
    }


# ---------------------------------------------------------
# ADMIN: VIEW ONE ASSIGNMENT AND ITS SUBMISSIONS
# ---------------------------------------------------------

@router.get("/admin/{assignment_id}")
def get_assignment(
    assignment_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_admin(current_user)

    assignment = (
        db.query(Assignment)
        .options(
            joinedload(Assignment.targets).joinedload(
                AssignmentTarget.student
            ),
            joinedload(Assignment.submissions).joinedload(
                AssignmentSubmission.student
            ),
            joinedload(Assignment.submissions)
            .joinedload(AssignmentSubmission.document)
            .joinedload(Document.verification_result),
        )
        .filter(Assignment.id == assignment_id)
        .first()
    )

    if not assignment:
        raise HTTPException(404, "Assignment not found.")

    result = assignment_data(assignment)

    result["students"] = [
        {
            "student_id": target.student.id,
            "student_name": target.student.full_name,
            "email": target.student.email,
        }
        for target in assignment.targets
    ]

    detailed_submissions = []

    for submission in assignment.submissions:
        document = submission.document
        verification = (
            document.verification_result if document else None
        )
        verification_details = {}
        
        if verification and verification.details:
            try:
                verification_details = json.loads(
                    verification.details
                )
            except (TypeError, ValueError):
                verification_details = {}

        detailed_submissions.append(
            {
                "submission_id": submission.id,
                "student_id": submission.student_id,
                "student_name": (
                    submission.student.full_name
                    if submission.student else None
                ),
                "document_id": submission.document_id,
                "filename": (
                    document.original_filename if document else None
                ),
                "document_type": (
                    document.document_type if document else None
                ),
                "submitted_at": submission.submitted_at,
                "verification_status": submission.verification_status,
                "review_status": submission.review_status,
                
                "review_notes": submission.review_notes,
                "reviewed_by": submission.reviewed_by,
                "reviewed_at": submission.reviewed_at,
                "verification": (
                    {
                        "overall_score": verification.overall_score,
                        "verdict": verification.verdict,
                        "ocr_confidence": verification.ocr_confidence,
                        "authenticity_score": verification.authenticity_score,
                        "similarity_score": verification.similarity_score,
                        "details": verification_details,
                    }
                    if verification else None
                ),
            }
        )

    result["submissions"] = detailed_submissions

    return result

# ---------------------------------------------------------
# ADMIN: UPDATE SUBMISSION REVIEW DECISION
# ---------------------------------------------------------

@router.patch("/submissions/{submission_id}/review")
def update_submission_review(
    submission_id: int,
    data: AdminReviewUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_admin(current_user)

    allowed_decisions = {
        "verified",
        "suspicious",
        "needs_review",
    }

    decision = data.decision.strip().casefold()

    if decision not in allowed_decisions:
        raise HTTPException(
            status_code=400,
            detail="Invalid review decision.",
        )

    submission = (
        db.query(AssignmentSubmission)
        .filter(AssignmentSubmission.id == submission_id)
        .first()
    )

    if submission is None:
        raise HTTPException(
            status_code=404,
            detail="Submission not found.",
        )

    try:
        submission.review_status = decision
        submission.review_notes = (
            data.notes.strip() if data.notes else None
        )
        submission.reviewed_by = current_user.id
        submission.reviewed_at = datetime.utcnow()

        db.commit()
        db.refresh(submission)

        return {
            "message": "Submission review updated successfully.",
            "submission_id": submission.id,
            "review_status": submission.review_status,
            "verification_status": submission.verification_status,
            "review_notes": submission.review_notes,
            "reviewed_by": submission.reviewed_by,
            "reviewed_at": submission.reviewed_at,
            
        }

    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail="Could not update submission review.",
        )
