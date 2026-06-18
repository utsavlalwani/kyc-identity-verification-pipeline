import datetime
from typing import Optional, List
from uuid import UUID
from pydantic import BaseModel, Field
from models import DocumentType, DocumentStatus, ReviewOutcome


# --- Request Schemas --------------------------------------

class ApplicationContext(BaseModel):
    """
    The KYC service is standalone -- it doesn't have the applicant's declared data in its own DB. The caller passes this context so we can cross-validate OCR results against declared values.
    """
    applicant_name: str = Field(..., min_length=2, max_length=200)
    date_of_birth: str = Field(..., description="YYYY-MM-DD")
    declared_income: Optional[float] = Field(None, ge=0)
    pan_number: Optional[str] = Field(None, min_length=10, max_length=10)


class ReviewUpdate(BaseModel):
    outcome: ReviewOutcome
    reviewer_notes: Optional[str] = Field(None, max_length=1000)


# --- Response Schemas --------------------------------------------------

class ReviewResponse(BaseModel):
    id: UUID
    outcome: Optional[ReviewOutcome]
    reviewer_notes: Optional[str]
    assigned_to: Optional[str]
    created_at: datetime.datetime
    resolved_at: Optional[datetime.datetime]

    model_config = {"from_attributes": True}


class DocumentResponse(BaseModel):
    id: UUID
    application_id: UUID
    document_type: DocumentType
    file_name: str
    file_size_bytes: int
    status: DocumentStatus
    extracted_name: Optional[str]
    extracted_dob: Optional[str]
    extracted_id_number: Optional[str]  # already masked
    extracted_income: Optional[str]
    ocr_confidence: Optional[int]
    flag_reason: Optional[str]
    uploaded_by: str
    uploaded_at: datetime.datetime
    processed_at: Optional[datetime.datetime]
    reviews: List[ReviewResponse] = []

    model_config = {"from_attributes": True}


class DocumentSummary(BaseModel):
    id: UUID
    application_id: UUID
    document_type: DocumentType
    file_name: str
    status: DocumentStatus
    uploaded_at: datetime.datetime

    model_config = {"from_attributes": True}


class PresignedUrlResponse(BaseModel):
    document_id: UUID
    download_url: str
    expires_in_seconds: int


class DocumentUploadResponse(BaseModel):
    message: str
    document_id: UUID
    document_type: DocumentType
    file_name: str
    status: DocumentStatus
    storage: str  # "s3" or "local"

