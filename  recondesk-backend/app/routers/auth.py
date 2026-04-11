from fastapi import APIRouter, Depends, HTTPException, status
from supabase import Client

from app.auth import create_access_token, get_current_active_user
from app.database import supabase_client
from app.models.user import LoginRequest, TokenResponse, UserCreate, UserResponse
from app.services.email_service import send_welcome_email

router = APIRouter()


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(payload: UserCreate, db: Client = Depends(supabase_client)):
    # Create auth user in Supabase
    try:
        auth_response = db.auth.sign_up({"email": payload.email, "password": payload.password})
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    if not auth_response.user:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Registration failed")

    user_id = str(auth_response.user.id)

    # Insert profile row
    profile = {
        "id": user_id,
        "email": payload.email,
        "full_name": payload.full_name,
        "company_name": payload.company_name,
        "is_active": True,
        "plan": "free",
    }
    db.table("users").insert(profile).execute()

    send_welcome_email(payload.email, payload.full_name or payload.email)

    token = create_access_token(subject=user_id)
    return TokenResponse(access_token=token, user=UserResponse(**profile))


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest, db: Client = Depends(supabase_client)):
    try:
        auth_response = db.auth.sign_in_with_password(
            {"email": payload.email, "password": payload.password}
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials"
        ) from exc

    if not auth_response.user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    user_id = str(auth_response.user.id)
    result = db.table("users").select("*").eq("id", user_id).single().execute()

    token = create_access_token(subject=user_id)
    return TokenResponse(access_token=token, user=UserResponse(**result.data))


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: dict = Depends(get_current_active_user)):
    return UserResponse(**current_user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(db: Client = Depends(supabase_client)):
    db.auth.sign_out()
