
from fastapi import FastAPI

from .database import Base, engine
from . import models

from .routes.auth_routes import router as auth_router
from .routes.document_routes import router as document_router
from .routes.assignment_routes import router as assignment_router


# Create database tables
Base.metadata.create_all(bind=engine)


app = FastAPI(
    title="Authenticity Validator for Academia API",
    description="Backend API for academic document authenticity verification",
    version="1.0.0",
)


# Register API routes
app.include_router(auth_router)
app.include_router(document_router)
app.include_router(assignment_router)


@app.get("/")
def root():
    return {
        "message": "Authenticity Validator Backend is running"
    }


@app.get("/health")
def health_check():
    return {
        "status": "healthy"
    }
