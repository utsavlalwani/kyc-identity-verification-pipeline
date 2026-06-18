import io, pytest

APP_ID = "550e8400-e29b-41d4-a716-446655440000"

FORM_CONTEXT = {
    "document_type": "aadhaar",
    "applicant_name": "Rahul Sharma",
    "date_of_birth": "1990-06-15",
    "declared_income": "75000",
}


def _make_file(content=b"fake pdf content", filename="aadhaar.pdf"):
    return ("file", (filename, io.BytesIO(content), "application/pdf"))


@pytest.mark.asyncio
async def test_upload_document_success(client, auth_token):
    r = await client.post(
        f"/api/v1/applications/{APP_ID}/documents",
        data=FORM_CONTEXT,
        files=[_make_file()],
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    assert r.status_code == 202
    data = r.json()
    assert data["status"] == "processing"
    assert "document_id" in data


@pytest.mark.asyncio
async def test_upload_required_auth(client):
    r = await client.post(
        f"/api/v1/applications/{APP_ID}/documents",
        data=FORM_CONTEXT,
        files=[_make_file()],
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_unsupported_file_type_rejected(client, auth_token):
    r = await client.post(
        f"/api/v1/applications/{APP_ID}/documents",
        data=FORM_CONTEXT,
        files=[("file", ("doc.exe", io.BytesIO(b"bad"), "application/octet-stream"))],
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    assert r.status_code == 415


@pytest.mark.asyncio
async def test_file_too_large_rejected(client, auth_token):
    big = b"0" * (6 * 1024 * 1024)  # 6 MB, limit is 5 MB
    r = await client.post(
        f"/api/v1/applications/{APP_ID}/documents",
        data=FORM_CONTEXT,
        files=[_make_file(content=big)],
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    assert r.status_code == 413


@pytest.mark.asyncio
async def test_duplicate_doc_type_rejected(client, auth_token):
    headers = {"Authorization": f"Bearer {auth_token}"}
    app_id = "660e8400-e29b-41d4-a716-446655440001"
    # First upload
    r1 = await client.post(
        f"/api/v1/applications/{app_id}/documents",
        data={**FORM_CONTEXT},
        files=[_make_file()],
        headers=headers,
    )
    assert r1.status_code == 202
    # Second upload same type
    r2 = await client.post(
        f"/api/v1/applications/{app_id}/documents",
        data={**FORM_CONTEXT},
        files=[_make_file()],
        headers=headers,
    )
    assert r2.status_code == 409


@pytest.mark.asyncio
async def test_list_documents(client, auth_token):
    r = await client.get(
        f"/api/v1/applications/{APP_ID}/documents",
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    assert r.status_code == 200
    assert isinstance(r.json(), list)


@pytest.mark.asyncio
async def test_flagged_list_requires_ops(client, auth_token, ops_token):
    r1 = await client.get(
        "/api/v1/applications/flagged",
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    assert r1.status_code == 403

    r2 = await client.get(
        "/api/v1/applications/flagged",
        headers={"Authorization": f"Bearer {ops_token}"},
    )
    assert r2.status_code == 200


@pytest.mark.asyncio
async def test_health(client):
    r = await client.get("/health/")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"

    