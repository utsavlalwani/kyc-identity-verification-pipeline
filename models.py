import uuid, enum, datetime
from typing import Optional

from sqlalchemy import String, Text, Integer, DateTime, ForeignKey, Enum as SAEnum, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


# --- Enums ----------------------------------------

class DocumentType(str, enum.Enum):
    AADHAAR = "aadhaar"
    PAN = "pan"
    SALARY_SLIP = "salary_slip"
    BANK_STATEMENT = "bank_statement"
    PASSPORT = "passport"
    VOTER_ID = "voter_id"


class DocumentStatus(str, enum.Enum):
    PROCESSING = "processing"  # Uploaded, OCR not yet run
    VERIFIED = "verified"  # OCR passed, fields match
    FLAGGED = "flagged"  # OCR ran but fields mismatch -- manual review
    UNREADABLE = "unreadable"  # OCR failed -- customer must re-upload
    REJECTED = "rejected"  # manually rejected by ops


class ReviewOutcome(str, enum.Enum):
    APPROVED = "approved"
    REJECTED = "rejected"


# --- KYC Document ----------------------------------------------

class KYCDocument(Base):
    """
    One row per uploaded document.

    NOTE: This service is a standalone microservice.
    application_id is stored as a plain UUID -- NOT a Foreign Key to another service's database. The application is verified via an HTTP call to the Loan Service.
    """
    __tablename__ = "kyc_documents"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    # Cross-service reference -- plain UUID, no Foreign Key
    application_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )

    document_type: Mapped[str] = mapped_column(
        SAEnum(DocumentType), nullable=False
    )

    # Storage
    s3_key: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    local_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    file_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=False)
    file_size_bytes: Mapped[Optional[str]] = mapped_column(Integer, nullable=False)
    content_type: Mapped[str] = mapped_column(String(100), nullable=False)

    # OCR extracted fields -- stored masked for compliance
    # PII is partially redacted before storage (Aadhaar last-4, PAN encrypted)
    extracted_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    extracted_dob: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    extracted_id_number: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)  # masked
    extracted_income: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)  # salary slip only
    ocr_confidence: Mapped[Optional[str]] = mapped_column(Integer, nullable=True)  # 0-100

    # Validation
    status: Mapped[str] = mapped_column(SAEnum(DocumentStatus), default=DocumentStatus.PROCESSING, nullable=False)
    flag_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Audit
    uploaded_by: Mapped[str] = mapped_column(String(200), nullable=False)
    uploaded_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.datetime.utcnow
    )
    processed_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    reviews: Mapped[list["DocumentReview"]] = relationship(
        "DocumentReview", back_populates="document", lazy="selectin"
    )

    __table_args__ = (
        # Non-unique lookup index on (application_id, document_type) to speed up
        # per-application duplicate checks and listings. Uniqueness (one active doc
        # per type per application) is NOT enforced here -- it is enforced at the
        # application layer by the upload endpoint's duplicate-check.
        Index("ix_kyc_app_doctype", "application_id", "document_type"),
    )


# --- Manual Review Queue ----------------------------------------------

class DocumentReview(Base):
    """
    Created when a document is flagged. Ops agents review flagged documents here.
    """
    __tablename__ = "document_reviews"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("kyc_documents.id"), nullable=False, index=True
    )
    assigned_to: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    outcome: Mapped[Optional[str]] = mapped_column(SAEnum(ReviewOutcome), nullable=True)
    reviewer_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.datetime.utcnow
    )
    resolved_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    document: Mapped["KYCDocument"] = relationship(
        "KYCDocument", back_populates="reviews"
    )

