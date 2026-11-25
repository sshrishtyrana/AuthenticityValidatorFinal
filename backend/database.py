from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker


# Project root = Authenticity-Validator-for-Academia/
BASE_DIR = Path(__file__).resolve().parent.parent

# Database file will be created in the project root
DATABASE_PATH = BASE_DIR / "authenticity_validator.db"

DATABASE_URL = f"sqlite:///{DATABASE_PATH}"


# Database engine
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
)


# Database session factory
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)


# Base class for all database models
Base = declarative_base()


# Used by API routes when they need a database connection
def get_db():
    db = SessionLocal()

    try:
        yield db
    finally:
        db.close()