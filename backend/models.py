
from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from .database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    full_name = Column(String(150), nullable=False)
    email = Column(String(255), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)

    role = Column(String(20), nullable=False, default="user")
    is_active = Column(Boolean, nullable=False, default=True)

    # Student eligibility information
    course = Column(String(150), nullable=True)
    department = Column(String(150), nullable=True)
    academic_year = Column(String(50), nullable=True)
    semester = Column(String(50), nullable=True)
    admission_batch = Column(String(100), nullable=True)

    created_at = Column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
    )

    documents = relationship(
        "Document",
        back_populates="owner",
        cascade="all, delete-orphan",
    )

    created_assignments = relationship(
        "Assignment",
        back_populates="creator",
        foreign_keys="Assignment.created_by",
    )

    assignment_targets = relationship(
        "AssignmentTarget",
        back_populates="student",
        foreign_keys="AssignmentTarget.student_id",
    )

    assignment_submissions = relationship(
        "AssignmentSubmission",
        back_populates="student",
        foreign_keys="AssignmentSubmission.student_id",
    )

    reviewed_submissions = relationship(
        "AssignmentSubmission",
        back_populates="reviewer",
        foreign_keys="AssignmentSubmission.reviewed_by",
    )


class Document(Base):
    __tablename__ = "documents"

    id = Column(Integer, primary_key=True, index=True)

    user_id = Column(
        Integer,
        ForeignKey("users.id"),
        nullable=False,
        index=True,
    )

    original_filename = Column(String(255), nullable=False)
    stored_filename = Column(String(255), nullable=False)
    document_type = Column(String(100), nullable=True)
    file_path = Column(String(500), nullable=False)

    document_category = Column(
        String(50),
        nullable=False,
        default="academic",
    )

    uploaded_at = Column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
    )

    status = Column(
        String(30),
        nullable=False,
        default="uploaded",
    )

    owner = relationship(
        "User",
        back_populates="documents",
    )

    verification_result = relationship(
        "VerificationResult",
        back_populates="document",
        uselist=False,
        cascade="all, delete-orphan",
    )

    assignment_submission = relationship(
        "AssignmentSubmission",
        back_populates="document",
        uselist=False,
    )


class VerificationResult(Base):
    __tablename__ = "verification_results"

    id = Column(Integer, primary_key=True, index=True)

    document_id = Column(
        Integer,
        ForeignKey("documents.id"),
        unique=True,
        nullable=False,
    )

    overall_score = Column(Float, nullable=True)
    verdict = Column(String(50), nullable=True)
    authenticity_score = Column(Float, nullable=True)
    similarity_score = Column(Float, nullable=True)
    ocr_confidence = Column(Float, nullable=True)
    details = Column(Text, nullable=True)

    created_at = Column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
    )

    document = relationship(
        "Document",
        back_populates="verification_result",
    )


# ---------------------------------------------------------
# ASSIGNMENTS CREATED BY ADMIN
# ---------------------------------------------------------

class Assignment(Base):
    __tablename__ = "assignments"

    id = Column(Integer, primary_key=True, index=True)

    title = Column(String(255), nullable=False)
    instructions = Column(Text, nullable=True)

    category = Column(
        String(50),
        nullable=False,
    )  # academic / admission

    document_type = Column(
        String(100),
        nullable=False,
    )

    created_by = Column(
        Integer,
        ForeignKey("users.id"),
        nullable=False,
        index=True,
    )

    # all / individual / selected / course / department /
    # semester / academic_year / admission_batch
    eligibility_type = Column(
        String(50),
        nullable=False,
        default="all",
    )

    # Optional group eligibility criteria
    course = Column(String(150), nullable=True)
    department = Column(String(150), nullable=True)
    academic_year = Column(String(50), nullable=True)
    semester = Column(String(50), nullable=True)
    admission_batch = Column(String(100), nullable=True)

    start_at = Column(DateTime, nullable=True)
    due_at = Column(DateTime, nullable=True)

    # draft / published / closed
    status = Column(
        String(30),
        nullable=False,
        default="draft",
    )

    created_at = Column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
    )

    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    creator = relationship(
        "User",
        back_populates="created_assignments",
        foreign_keys=[created_by],
    )

    targets = relationship(
        "AssignmentTarget",
        back_populates="assignment",
        cascade="all, delete-orphan",
    )

    submissions = relationship(
        "AssignmentSubmission",
        back_populates="assignment",
        cascade="all, delete-orphan",
    )


# ---------------------------------------------------------
# STUDENTS SELECTED FOR ASSIGNMENTS
# ---------------------------------------------------------

class AssignmentTarget(Base):
    __tablename__ = "assignment_targets"

    id = Column(Integer, primary_key=True, index=True)

    assignment_id = Column(
        Integer,
        ForeignKey("assignments.id"),
        nullable=False,
        index=True,
    )

    student_id = Column(
        Integer,
        ForeignKey("users.id"),
        nullable=False,
        index=True,
    )

    assigned_at = Column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint(
            "assignment_id",
            "student_id",
            name="uq_assignment_student",
        ),
    )

    assignment = relationship(
        "Assignment",
        back_populates="targets",
    )

    student = relationship(
        "User",
        back_populates="assignment_targets",
        foreign_keys=[student_id],
    )


# ---------------------------------------------------------
# STUDENT SUBMISSIONS AGAINST ASSIGNMENTS
# ---------------------------------------------------------

class AssignmentSubmission(Base):
    __tablename__ = "assignment_submissions"

    id = Column(Integer, primary_key=True, index=True)

    assignment_id = Column(
        Integer,
        ForeignKey("assignments.id"),
        nullable=False,
        index=True,
    )

    student_id = Column(
        Integer,
        ForeignKey("users.id"),
        nullable=False,
        index=True,
    )

    document_id = Column(
        Integer,
        ForeignKey("documents.id"),
        unique=True,
        nullable=False,
    )

    submitted_at = Column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
    )
    # queued / processing / completed / failed
    verification_status = Column(
        String(30),
        nullable=False,
        default="queued",
    )

    # pending / verified / suspicious / needs_review
    review_status = Column(
        String(30),
        nullable=False,
        default="pending",
    )

    review_notes = Column(Text, nullable=True)

    reviewed_by = Column(
        Integer,
        ForeignKey("users.id"),
        nullable=True,
    )

    reviewed_at = Column(DateTime, nullable=True)

    assignment = relationship(
        "Assignment",
        back_populates="submissions",
    )

    student = relationship(
        "User",
        back_populates="assignment_submissions",
        foreign_keys=[student_id],
    )

    document = relationship(
        "Document",
        back_populates="assignment_submission",
    )

    reviewer = relationship(
        "User",
        back_populates="reviewed_submissions",
        foreign_keys=[reviewed_by],
    )


# ---------------------------------------------------------
# INSTITUTIONS
# ---------------------------------------------------------

class Institution(Base):
    __tablename__ = "institutions"

    id = Column(Integer, primary_key=True, index=True)

    name = Column(
        String(255),
        unique=True,
        nullable=False,
    )

    code = Column(
        String(100),
        unique=True,
        nullable=True,
    )

    email = Column(String(255), nullable=True)

    is_active = Column(
        Boolean,
        nullable=False,
        default=True,
    )

    created_at = Column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
    )
