import pytest, pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from main import app
from database import Base
from dependencies import get_db

TEST_DB_URL = "postgresql+asyncpg://postgres:password@localhost:5432/kyc_pipeline_test"
test_engine = create_async_engine(TEST_DB_URL, echo=False)
TestSession = async_sessionmaker(bind=test_engine, class_=AsyncSession, expire_on_commit=False)


@pytest_asyncio.fixture(scope="session", autouse=True)
async def setup_db():
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def db_session():
    async with TestSession() as s:
        yield s
        await s.rollback()


@pytest_asyncio.fixture
async def client(db_session):
    async def override():
        yield db_session
    app.dependency_overrides[get_db] = override
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def auth_token(client):
    r = await client.post(
        "/api/v1/auth/login",
        json={"username": "applicant", "password": "app123"},
    )
    return r.json()["access_token"]


@pytest_asyncio.fixture
async def ops_token(client):
    r = await client.post(
        "/api/v1/auth/login",
        json={"username": "ops_user", "password": "ops123"},
    )
    return r.json()["access_token"]

