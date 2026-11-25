
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from ..auth import (
    create_access_token,
    hash_password,
    verify_password,
    get_current_user,
)
from ..database import get_db
from ..models import User


router = APIRouter(
    prefix="/auth",
    tags=["Authentication"],
)


# ---------------------------------------------------------
# Request Schemas
# ---------------------------------------------------------

class RegisterRequest(BaseModel):
    full_name: str
    email: EmailStr
    password: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: str
class StudentProfileUpdate(BaseModel):
    course: str | None = None
    department: str | None = None
    academic_year: str | None = None
    semester: str | None = None
    admission_batch: str | None = None

# ---------------------------------------------------------
# User Registration
# ---------------------------------------------------------

@router.post("/register", status_code=status.HTTP_201_CREATED)
def register_user(
    data: RegisterRequest,
    db: Session = Depends(get_db),
):
    full_name = data.full_name.strip()
    email = str(data.email).lower().strip()

    if not full_name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Full name is required.",
        )

    if len(data.password) < 6:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password must contain at least 6 characters.",
        )

    existing_user = (
        db.query(User)
        .filter(User.email == email)
        .first()
    )

    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists.",
        )

    new_user = User(
        full_name=full_name,
        email=email,
        password_hash=hash_password(data.password),
        role="user",
        is_active=True,
    )

    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    return {
        "message": "User registered successfully.",
        "user": {
            "id": new_user.id,
            "full_name": new_user.full_name,
            "email": new_user.email,
            "role": new_user.role,
        },
    }


# ---------------------------------------------------------
# Shared Login Logic
# ---------------------------------------------------------

def authenticate_user(
    email: str,
    password: str,
    db: Session,
) -> dict:
    """Authenticate a user and return a JWT response."""

    email = email.lower().strip()

    user = (
        db.query(User)
        .filter(User.email == email)
        .first()
    )

    if not user or not verify_password(
        password,
        user.password_hash,
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account has been disabled.",
        )

    access_token = create_access_token(
        user_id=user.id,
        role=user.role,
    )

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": {
            "id": user.id,
            "full_name": user.full_name,
            "email": user.email,
            "role": user.role,
        },
    }


# ---------------------------------------------------------
# JSON Login (Existing Endpoint)
# ---------------------------------------------------------

@router.post("/login")
def login_user(
    data: LoginRequest,
    db: Session = Depends(get_db),
):
    return authenticate_user(
        email=str(data.email),
        password=data.password,
        db=db,
    )


# ---------------------------------------------------------
# OAuth2 Login (Swagger Authorize)
# ---------------------------------------------------------

@router.post("/login/oauth2")
def login_user_oauth2(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    # OAuth2PasswordRequestForm calls the email field "username".
    # Accept the registered email in that field.
    return authenticate_user(
        email=form_data.username,
        password=form_data.password,
        db=db,
    )
# ---------------------------------------------------------
# STUDENT PROFILE
# ---------------------------------------------------------

@router.get("/me")
def get_my_profile(
    current_user: User = Depends(get_current_user),
):
    return {
        "id": current_user.id,
        "full_name": current_user.full_name,
        "email": current_user.email,
        "role": current_user.role,
        "course": current_user.course,
        "department": current_user.department,
        "academic_year": current_user.academic_year,
        "semester": current_user.semester,
        "admission_batch": current_user.admission_batch,
    }


@router.patch("/profile")
def update_student_profile(
    data: StudentProfileUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if (current_user.role or "").casefold() not in {
        "user", "student"
    }:
        raise HTTPException(
            status_code=403,
            detail="Only student accounts can update this profile.",
        )

    updates = data.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(
            status_code=400,
            detail="Provide at least one profile field to update.",
        )
    

    for field, value in updates.items():
        if value is not None and not value.strip():
            raise HTTPException(
                status_code=400,
                detail=f"{field} cannot be empty.",
            )

        if value is not None:
            setattr(current_user, field, value.strip())

    db.commit()
    db.refresh(current_user)

    return {
        "message": "Student profile updated successfully.",
        "profile": {
            "course": current_user.course,
            "department": current_user.department,
            "academic_year": current_user.academic_year,
            "semester": current_user.semester,
            "admission_batch": current_user.admission_batch,
        },
    }