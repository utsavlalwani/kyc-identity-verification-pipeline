# KYC Identity Verification Pipeline

A standalone async FastAPI microservice that handles KYC (Know Your Customer)
identity-document processing for a digital-lending platform ("LoanFlow", an NBFC).
It accepts identity documents, runs OCR, cross-validates the extracted fields against
the applicant's declared data, masks PII, and routes mismatches to a manual ops-review
queue.

It runs on port **8001** so it does not clash with the Loan Origination Service on 8000
(its Postgres is exposed on host port **5433** vs. LoanFlow's 5432).

## Standalone-microservice design

This is **one service in a multi-service system** and it does not share a database with
any other service. `KYCDocument.application_id` is stored as a **plain UUID — deliberately
NOT a foreign key** to another service's database. The application is verified out-of-band
via an HTTP call to the Loan Service (`LOAN_SERVICE_URL`). There are no cross-service FK
constraints.

## Feature flags: real vs. mock infrastructure

Two settings in `config.py` decide whether external infrastructure is touched. Both
**default to `False`**, so the service runs end-to-end locally with no AWS credentials:

- `USE_AWS_S3` — `False`: files are written to local disk under
  `local_uploads/{application_id}/{document_type}/`. `True`: upload to AWS S3 with
  server-side AES-256 encryption.
- `USE_REAL_OCR` — `False`: return **deterministic mock OCR data seeded from the
  filename**, so the same file always yields the same extracted values (the mock also
  simulates an occasional "unreadable" result). `True`: call AWS Textract.

## Document lifecycle

1. Client uploads a document via `POST /api/v1/applications/{application_id}/documents`.
2. The endpoint synchronously validates content-type, file extension, size, and checks
   for a duplicate active document of the same type, uploads the file, persists a row
   with status `processing`, and returns **202 Accepted** immediately.
3. A background task then runs **OCR → cross-validation against declared data →
   PII masking** before storing.
4. The document status moves to `verified`, `flagged`, or `unreadable`.
5. Flagged documents create a `DocumentReview` row and enter the manual ops-review queue.

### PII masking

Raw identifiers are never persisted. Before any write, Aadhaar is reduced to its last 4
digits, PAN to a masked display form, bank-account numbers to their last 4 digits, and
income to a range bucket (never the exact figure). Masking lives in
`services/masking.py`.

## Endpoints

All `/api/v1` endpoints require a Bearer JWT (obtain one from the login endpoint).
Ops-only endpoints additionally require the `admin` or `ops` role.

### Auth
- `POST /api/v1/auth/login` — exchange username/password for a JWT.

### KYC documents (prefix `/api/v1/applications`)
- `POST /{application_id}/documents` — upload a KYC document (returns 202).
- `GET /{application_id}/documents` — list all documents for an application.
- `GET /{application_id}/documents/{document_id}` — get full document details, including
  extracted fields.
- `GET /{application_id}/documents/{document_id}/download-url` — get a time-limited
  presigned download URL (ops/admin only).
- `GET /flagged` — list flagged documents awaiting review (ops/admin only).
- `PATCH /{application_id}/documents/{document_id}/review` — submit a manual review
  outcome for a flagged document (ops/admin only).

### Health
- `GET /health/` — liveness check.
- `GET /health/db` — database connectivity check.

Interactive API docs are served at `/docs` (Swagger) and `/redoc`.

## Running locally

The simplest path is Docker Compose, which starts Postgres (host port 5433) and the API
(port 8001):

```bash
docker-compose up
```

The API is then available at http://localhost:8001 (docs at http://localhost:8001/docs).

To run without Docker, copy `.env.example` to `.env`, install dependencies, and start the
dev server:

```bash
cp .env.example .env
pip install -r requirements.txt
python main.py   # uvicorn on port 8001 with reload
```

## Tests

```bash
pytest
```

Tests talk to a **real async Postgres** (not SQLite). `tests/conftest.py` uses
`postgresql+asyncpg://postgres:password@localhost:5432/kyc_pipeline_test`; that database
must exist and be reachable. Tables are created and dropped automatically per session.
