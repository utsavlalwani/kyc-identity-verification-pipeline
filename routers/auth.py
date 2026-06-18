from fastapi import APIRouter, HTTPException, status
from schemas.auth import UserLogin, Token
from dependencies import create_access_token

router = APIRouter()

MOCK_USERS = {
    "admin": {"password": "admin123", "role": "admin"},
    "ops_user": {"password": "ops123", "role": "ops"},
    "applicant": {"password": "app123", "role": "applicant"},
}


@router.post("/login", response_model=Token)
async def login(credentials: UserLogin):
    user = MOCK_USERS.get(credentials.username)
    if not user or user["password"] != credentials.password:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )
    return Token(
        access_token=create_access_token(
            user_id=credentials.username, role=user["role"]
        )
    )

