from fastapi import APIRouter, Query

from app.models.schemas import (
    CookingSessionAdvanceRequest,
    CookingSessionStartRequest,
    InventoryUpdateRequest,
    IngredientSubstitutionRequest,
    InventoryConsumeRequest,
    MealPlanRequest,
    NutritionEstimateRequest,
    PreferencesUpdateRequest,
    THREAD_ID_PATTERN,
)
from app.services.meal_planner import (
    chef_memory_store,
    estimate_nutrition,
    generate_meal_plan,
    suggest_substitutions,
)


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


@router.post("/chef/inventory/consume")
def consume_inventory(request: InventoryConsumeRequest):
    return chef_memory_store.consume_inventory(request.thread_id, request.items, request.recipe_name)


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


@router.post("/chef/substitutions")
def create_substitutions(request: IngredientSubstitutionRequest):
    return suggest_substitutions(request)


@router.post("/chef/nutrition")
def create_nutrition_estimate(request: NutritionEstimateRequest):
    return estimate_nutrition(request)


@router.post("/chef/cooking-session")
def start_cooking_session(request: CookingSessionStartRequest):
    return chef_memory_store.start_cooking_session(request)


@router.get("/chef/cooking-session")
def get_cooking_session(
    thread_id: str = Query(..., min_length=1, max_length=80, pattern=THREAD_ID_PATTERN.pattern),
):
    return chef_memory_store.get_cooking_session(thread_id)


@router.post("/chef/cooking-session/advance")
def advance_cooking_session(request: CookingSessionAdvanceRequest):
    return chef_memory_store.advance_cooking_session(request.thread_id, request.action)
