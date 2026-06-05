from fastapi import APIRouter, Query

from app.models.schemas import (
    InventoryUpdateRequest,
    MealPlanRequest,
    PreferencesUpdateRequest,
    THREAD_ID_PATTERN,
)
from app.services.meal_planner import chef_memory_store, generate_meal_plan


router = APIRouter()


@router.get("/chef/inventory")
def get_inventory(
    thread_id: str = Query(..., min_length=1, max_length=80, pattern=THREAD_ID_PATTERN.pattern),
):
    return {"items": chef_memory_store.list_inventory(thread_id)}


@router.post("/chef/inventory")
def upsert_inventory(request: InventoryUpdateRequest):
    return {"items": chef_memory_store.upsert_inventory(request.thread_id, request.items)}


@router.delete("/chef/inventory")
def clear_inventory(
    thread_id: str = Query(..., min_length=1, max_length=80, pattern=THREAD_ID_PATTERN.pattern),
):
    chef_memory_store.clear_inventory(thread_id)
    return {"success": True}


@router.get("/chef/preferences")
def get_preferences(
    thread_id: str = Query(..., min_length=1, max_length=80, pattern=THREAD_ID_PATTERN.pattern),
):
    return {"preferences": chef_memory_store.get_preferences(thread_id)}


@router.post("/chef/preferences")
def save_preferences(request: PreferencesUpdateRequest):
    return {"preferences": chef_memory_store.save_preferences(request.thread_id, request.preferences)}


@router.post("/chef/meal-plan")
def create_meal_plan(request: MealPlanRequest):
    return generate_meal_plan(request)
