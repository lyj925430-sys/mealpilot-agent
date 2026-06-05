from fastapi import APIRouter, Depends

from app.models.schemas import AuthRequest, AuthResponse, HouseholdProfileRequest
from app.services.auth_service import auth_store, get_current_token, get_current_user


router = APIRouter()


@router.post("/auth/register", response_model=AuthResponse)
def register(request: AuthRequest):
    return auth_store.register(request.username, request.password)


@router.post("/auth/login", response_model=AuthResponse)
def login(request: AuthRequest):
    return auth_store.login(request.username, request.password)


@router.get("/auth/me")
def me(user: dict[str, str] = Depends(get_current_user)):
    return {"user": user}


@router.post("/auth/logout")
def logout(token: str = Depends(get_current_token)):
    auth_store.logout(token)
    return {"success": True}


@router.get("/auth/household")
def get_household(user: dict[str, str] = Depends(get_current_user)):
    return auth_store.get_household_profile(user["id"])


@router.put("/auth/household")
def save_household(
    request: HouseholdProfileRequest,
    user: dict[str, str] = Depends(get_current_user),
):
    return auth_store.save_household_profile(user["id"], request)
