import logging, datetime
from uuid import UUID
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, BackgroundTasks, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from database import AsyncSessionLocal
from dependencies import get_db, get_current_user, require_role
from models import KYCDocument, DocumentType, DocumentStatus, DocumentReview, ReviewOutcome
from schemas.document import DocumentResponse, DocumentType, DocumentStatus, PresignedUrlResponse,ReviewUpdate, DocumentUploadResponse, DocumentSummary
from services.storage import StorageService
from services.ocr import OCRService
from services.validator import CrossValidator
from services.masking import mask_aadhaar, mask_pan, mask_bank_account, income_to_bucket
from config import settings

logger = logging.getLogger(__name__)
router = APIRouter()

ALLOWED_CONTENT_TYPES = {
    "application/pdf",
    "image/jpeg",
    "image/jpg",
    "image/png",
}


# --- Uploading a KYC document -----------------------------------------

@router.post(
    "/{application_id}/documents",
    response_model=DocumentUploadResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Upload a KYC document",
    description=(
        "Accepts a document file, validates it, uploads to S3 (encrypted), "
        "and returns 202 immediately. OCR extraction and cross-validation "
        "run as background tasks."
    ),
)
async def upload_document(
    application_id: UUID,
    background_tasks: BackgroundTasks,
        document_type: DocumentType = Form(...),
        # Application context -- used for cross-validation
        applicant_name: str = Form(..., min_length=2, max_length=200),
        date_of_birth: str = Form(..., description="YYYY-MM-DD"),
        declared_income: Optional[float] = Form(None),
        file: UploadFile = File(...),
        db: AsyncSession = Depends(get_db),
        current_user: dict = Depends(get_current_user),
):
    # 1. File type validation
    if file.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=(
                f"File type '{file.content_type}' is not supported. "
                f"Allowed: PDF, JPEG, PNG."
            ),
        )

    # 1b. File extension validation
    filename = file.filename or ""
    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if extension not in settings.allowed_extensions_list:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=(
                f"File extension '{extension}' is not supported. "
                f"Allowed extensions: {', '.join(settings.allowed_extensions_list)}."
            ),
        )

    # 2. File size validation (read headers; actual content checked during upload)
    file_content = await file.read()
    if len(file_content) > settings.max_file_size_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File size exceeds the {settings.MAX_FILE_SIZE_MB}MB limit.",
        )
    # Seeking back -- file was fully read for size check
    await file.seek(0)

    # 3. Duplicate document type check
    existing = await db.execute(
        select(KYCDocument).where(
            KYCDocument.application_id == application_id,
            KYCDocument.document_type == document_type,
            KYCDocument.status.not_in([
                DocumentStatus.REJECTED,
                DocumentStatus.UNREADABLE,
            ]),
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"A '{document_type.value}' document is already submitted "
                f"for application {application_id} and is pending review."
            ),
        )

    # 4. Upload file to S3 / local
    storage = StorageService()
    storage_result = await storage.upload(
        file=file,
        application_id=str(application_id),
        document_type=document_type.value,
    )

    # 5. Persist document metadata -- status starts as PROCESSING
    doc = KYCDocument(
        application_id=application_id,
        document_type=document_type,
        s3_key=storage_result.get("s3_key"),
        local_path=storage_result.get("local_path"),
        file_name=file.filename,
        file_size_bytes=len(file_content),
        content_type=file.content_type,
        status=DocumentStatus.PROCESSING,
        uploaded_by=current_user["user_id"],
    )
    db.add(doc)
    await db.flush()
    await db.refresh(doc)

    # 6. Queue async OCR + validation -- rums after 202 is sent
    background_tasks.add_task(
        _process_document,
        document_id=doc.id,
        file_content=file_content,
        document_type=document_type.value,
        file_name=file.filename,
        applicant_name=applicant_name,
        date_of_birth=date_of_birth,
        declared_income=declared_income,
    )

    logger.info(
        f"Document {doc.id} uploaded for application {application_id}. "
        f"Type={document_type.value} Storage={storage_result['storage']}"
    )

    return DocumentUploadResponse(
        message="Document uploaded successfully. OCR processing started.",
        document_id=doc.id,
        document_type=document_type,
        file_name=file.filename,
        status=DocumentStatus.PROCESSING,
        storage=storage_result["storage"],
    )


# --- Listing documents for an application -----------------------------------------

@router.get(
    "/{application_id}/documents",
    response_model=List[DocumentSummary],
    summary="List all documents for an application",
)
async def list_documents(
    application_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    result = await db.execute(
        select(KYCDocument)
        .where(KYCDocument.application_id == application_id)
        .order_by(KYCDocument.uploaded_at.desc())
    )
    return [DocumentSummary.model_validate(d) for d in result.scalars().all()]


# --- Geting a single document with full details -----------------------------------

@router.get(
    "/{application_id}/documents/{document_id}",
    response_model=DocumentResponse,
    summary="Get full documents details including extracted fields",
)
async def get_document(
    application_id: UUID,
    document_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    result = await db.execute(
        select(KYCDocument).where(
            KYCDocument.id == document_id,
            KYCDocument.application_id == application_id,
        )
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")
    return doc


# --- Getting the Presigned Download URL ------------------------------

@router.get(
    "/{application_id}/documents/{document_id}/download-url",
    response_model=PresignedUrlResponse,
    summary="Get a secure time-limited download URL - ops/admin only",
)
async def get_download_url(
    application_id: UUID,
    document_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role("admin", "ops")),
):
    result = await db.execute(
        select(KYCDocument).where(
            KYCDocument.id == document_id,
            KYCDocument.application_id == application_id,
        )
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")

    expiry = 3600  # 1 hour
    if doc.s3_key:
        storage = StorageService()
        url = storage.generate_presigned_url(doc.s3_key, expiry_seconds=expiry)
    else:
        url = f"http://localhost:8001/local-file/{doc.local_path}"

    return PresignedUrlResponse(
        document_id=doc.id,
        download_url=url,
        expires_in_seconds=expiry,
    )


# --- Flagged Documents Queue --------------------------------------------------

@router.get(
    "/flagged",
    response_model=List[DocumentSummary],
    summary="List all the flagged documents awaiting review -- ops/admin only",
)
async def list_flagged(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role("admin", "ops")),
):
    result = await db.execute(
        select(KYCDocument)
        .where(KYCDocument.status == DocumentStatus.FLAGGED)
        .order_by(KYCDocument.uploaded_at.asc())  # oldest first
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return [DocumentSummary.model_validate(d) for d in result.scalars().all()]


# --- Manual review -- ops resolves a flagged document ------------------------------------

@router.patch(
    "/{application_id}/documents/{document_id}/review",
    response_model=DocumentResponse,
    summary="Submit manual review outcome for a flagged document -- ops/admin only",
)
async def submit_review(
    application_id: UUID,
    document_id: UUID,
    payload: ReviewUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role("admin", "ops")),
):
    result = await db.execute(
        select(KYCDocument).where(
            KYCDocument.id == document_id,
            KYCDocument.application_id == application_id,
        )
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")
    if doc.status != DocumentStatus.FLAGGED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Document is '{doc.status.value}', not 'flagged'. Only flagged docs can be reviewed.",
        )

    # Updating the document status based on review outcome
    doc.status = DocumentStatus.VERIFIED if payload.outcome == ReviewOutcome.APPROVED else DocumentStatus.REJECTED
    doc.processed_at = datetime.datetime.utcnow()

    # Create review record
    review = DocumentReview(
        document_id=doc.id,
        assigned_to=current_user["user_id"],
        outcome=payload.outcome,
        reviewer_notes=payload.reviewer_notes,
        resolved_at=datetime.datetime.utcnow(),
    )
    db.add(review)

    logger.info(
        f"Document {document_id} reviewed by {current_user['user_id']}: "
        f"{payload.outcome.value}"
    )
    await db.flush()
    await db.refresh(doc)
    return doc


# --- Background task: OCR + validation ----------------------------------

async def _process_document(
    document_id: UUID,
    file_content: bytes,
    document_type: str,
    file_name: str,
    applicant_name: str,
    date_of_birth: str,
    declared_income: Optional[float],
):
    """
    Runs after 202 is sent to the client.
    Uses its own DB session -- the request session is already closed.

    Steps:
        1. Run OCR extraction
        2. Cross-validate extracted fields vs declared data
        3. Masked PII fields before storing
        4. Update document status
    """
    logger.info(f"OCR processing started for document {document_id}")

    async with AsyncSessionLocal() as db:
        try:
            # Fetching the document
            result = await db.execute(
                select(KYCDocument).where(KYCDocument.id == document_id)
            )
            doc = result.scalar_one_or_none()
            if not doc:
                logger.error(f"Document {document_id} not found in background task")
                return

            # Step 1: OCR extraction
            ocr = OCRService()
            ocr_result = await ocr.extract(file_content, document_type, file_name)

            logger.info(
                f"OCR complete for {document_id}: "
                f"confidence={ocr_result.get('confidence')} "
                f"error={ocr_result.get('error')}"
            )

            # Handling the complete OCR failure
            if ocr_result.get("error") and not ocr_result.get("name"):
                doc.status = DocumentStatus.UNREADABLE
                doc.flag_reason = ocr_result["error"]
                doc.ocr_confidence = ocr_result.get("confidence", 0)
                doc.processed_at = datetime.datetime.utcnow()
                await db.commit()
                logger.warning(f"Document {document_id} marked UNREADABLE")
                return

            # Step 2: Cross-validation
            validator = CrossValidator()
            is_valid, flag_reason = validator.validate(
                document_type=document_type,
                ocr_result=ocr_result,
                declared_name=applicant_name,
                declared_dob=date_of_birth,
                declared_income=declared_income,
            )

            # Step 3: Masking PII before storing
            raw_id = ocr_result.get("id_number", "")
            if document_type == "aadhaar" and raw_id:
                masked_id = mask_aadhaar(raw_id)
            elif document_type == "pan" and raw_id:
                masked_id = mask_pan(raw_id)
            elif document_type == "bank_statement" and raw_id:
                masked_id = mask_bank_account(raw_id)
            else:
                masked_id = raw_id

            income_val = ocr_result.get("income")
            masked_income = income_to_bucket(income_val) if income_val else None

            # Step 4: Persisting the Results
            doc.extracted_name = ocr_result.get("name")
            doc.extracted_dob = ocr_result.get("dob")
            doc.extracted_id_number = masked_id
            doc.extracted_income = masked_income
            doc.ocr_confidence = ocr_result.get("confidence")
            doc.processed_at = datetime.datetime.utcnow()

            if is_valid:
                doc.status = DocumentStatus.VERIFIED
                logger.info(f"Document {document_id} VERIFIED")
            else:
                doc.status = DocumentStatus.FLAGGED
                doc.flag_reason = flag_reason
                # Creating a review task for the ops team
                review = DocumentReview(document_id=doc.id)
                db.add(review)
                logger.warning(f"Document {document_id} FLAGGED: {flag_reason}")

            await db.commit()

        except Exception as exc:
            await db.rollback()
            logger.error(
                f"Background OCT task failed for {document_id}: {exc}",
                exc_info=True,
            )
            # Marking the document as requiring manual review
            try:
                async with AsyncSessionLocal() as fallback_db:
                    res = await fallback_db.execute(
                        select(KYCDocument).where(KYCDocument.id == document_id)
                    )
                    doc = res.scalar_one_or_none()
                    if doc:
                        doc.status = DocumentStatus.FLAGGED
                        doc.flag_reason = f"Processing error: {str(exc)}"
                        await fallback_db.commit()

            except Exception:
                pass
