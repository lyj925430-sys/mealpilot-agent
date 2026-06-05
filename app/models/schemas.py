import re
from datetime import date
from typing import Optional

from pydantic import BaseModel, Field, field_validator


THREAD_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]{1,80}$")
USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{3,32}$")


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)
    image_url: Optional[str] = None
    thread_id: str = Field(..., min_length=1, max_length=80)
    meal_context: str = Field("", max_length=2000)

    @field_validator("thread_id")
    @classmethod
    def validate_thread_id(cls, value: str) -> str:
        if not THREAD_ID_PATTERN.fullmatch(value):
            raise ValueError("thread_id only supports letters, numbers, underscores, dots, colons, and hyphens")
        return value

    @field_validator("image_url")
    @classmethod
    def normalize_image_url(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        value = value.strip()
        return value or None

    @field_validator("meal_context")
    @classmethod
    def normalize_meal_context(cls, value: str) -> str:
        return value.strip()


class AuthRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=32)
    password: str = Field(..., min_length=6, max_length=128)

    @field_validator("username")
    @classmethod
    def validate_username(cls, value: str) -> str:
        value = value.strip()
        if not USERNAME_PATTERN.fullmatch(value):
            raise ValueError("username only supports letters, numbers, underscores, dots, and hyphens")
        return value


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: dict[str, str]


class UserHealthProfile(BaseModel):
    age: Optional[int] = Field(default=None, ge=1, le=120)
    gender: str = Field("", max_length=20)
    height_cm: Optional[float] = Field(default=None, ge=40, le=260)
    weight_kg: Optional[float] = Field(default=None, ge=2, le=400)
    activity_level: str = Field("", max_length=40)
    health_goals: list[str] = Field(default_factory=list, max_length=20)
    conditions: list[str] = Field(default_factory=list, max_length=30)
    allergies: list[str] = Field(default_factory=list, max_length=30)
    dietary_preferences: list[str] = Field(default_factory=list, max_length=30)
    notes: str = Field("", max_length=500)

    @field_validator("gender", "activity_level", "notes")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return value.strip()

    @field_validator("health_goals", "conditions", "allergies", "dietary_preferences")
    @classmethod
    def normalize_list(cls, value: list[str]) -> list[str]:
        return [item.strip() for item in value if item.strip()]


class RelativeProfile(BaseModel):
    id: str = Field("", max_length=40)
    name: str = Field(..., min_length=1, max_length=40)
    relation: str = Field("", max_length=40)
    age: Optional[int] = Field(default=None, ge=1, le=120)
    conditions: list[str] = Field(default_factory=list, max_length=30)
    allergies: list[str] = Field(default_factory=list, max_length=30)
    dietary_preferences: list[str] = Field(default_factory=list, max_length=30)
    notes: str = Field("", max_length=500)

    @field_validator("id", "name", "relation", "notes")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return value.strip()

    @field_validator("conditions", "allergies", "dietary_preferences")
    @classmethod
    def normalize_list(cls, value: list[str]) -> list[str]:
        return [item.strip() for item in value if item.strip()]


class HouseholdProfileRequest(BaseModel):
    profile: UserHealthProfile = Field(default_factory=UserHealthProfile)
    relatives: list[RelativeProfile] = Field(default_factory=list, max_length=20)


class ThreadRequest(BaseModel):
    thread_id: str = Field(..., min_length=1, max_length=80)

    @field_validator("thread_id")
    @classmethod
    def validate_thread_id(cls, value: str) -> str:
        if not THREAD_ID_PATTERN.fullmatch(value):
            raise ValueError("thread_id only supports letters, numbers, underscores, dots, colons, and hyphens")
        return value


class IngredientItem(BaseModel):
    name: str = Field(..., min_length=1, max_length=40)
    quantity: str = Field("", max_length=40)
    category: str = Field("", max_length=40)
    expires_on: Optional[date] = None
    notes: str = Field("", max_length=200)

    @field_validator("name", "quantity", "category", "notes")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return value.strip()


class InventoryUpdateRequest(ThreadRequest):
    items: list[IngredientItem] = Field(..., min_length=1, max_length=100)


class ConsumedIngredient(BaseModel):
    name: str = Field(..., min_length=1, max_length=40)
    amount: str = Field("", max_length=40)
    remove_from_inventory: bool = False
    remaining_percent: Optional[int] = Field(default=None, ge=0, le=100)

    @field_validator("name", "amount")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return value.strip()


class InventoryConsumeRequest(ThreadRequest):
    items: list[ConsumedIngredient] = Field(..., min_length=1, max_length=50)
    recipe_name: str = Field("", max_length=80)


class UserPreferences(BaseModel):
    dietary_goals: list[str] = Field(default_factory=list, max_length=10)
    allergies: list[str] = Field(default_factory=list, max_length=20)
    disliked_ingredients: list[str] = Field(default_factory=list, max_length=30)
    liked_flavors: list[str] = Field(default_factory=list, max_length=20)
    budget_level: str = Field("normal", pattern="^(low|normal|high)$")
    cooking_time_minutes: Optional[int] = Field(default=None, ge=5, le=240)

    @field_validator("dietary_goals", "allergies", "disliked_ingredients", "liked_flavors")
    @classmethod
    def normalize_list(cls, value: list[str]) -> list[str]:
        return [item.strip() for item in value if item.strip()]


class PreferencesUpdateRequest(ThreadRequest):
    preferences: UserPreferences = Field(default_factory=UserPreferences)


class MealPlanRequest(ThreadRequest):
    days: int = Field(3, ge=1, le=7)
    meals: list[str] = Field(default_factory=lambda: ["dinner"], min_length=1, max_length=3)
    people: int = Field(1, ge=1, le=12)
    notes: str = Field("", max_length=500)

    @field_validator("meals")
    @classmethod
    def normalize_meals(cls, value: list[str]) -> list[str]:
        return [item.strip() for item in value if item.strip()]


class IngredientSubstitutionRequest(ThreadRequest):
    ingredient: str = Field(..., min_length=1, max_length=40)
    dish: str = Field("", max_length=80)

    @field_validator("ingredient", "dish")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return value.strip()


class NutritionEstimateRequest(ThreadRequest):
    ingredients: list[ConsumedIngredient] = Field(..., min_length=1, max_length=30)
    servings: int = Field(1, ge=1, le=12)


class CookingSessionStartRequest(ThreadRequest):
    recipe_name: str = Field(..., min_length=1, max_length=80)
    steps: list[str] = Field(..., min_length=1, max_length=30)

    @field_validator("recipe_name")
    @classmethod
    def strip_recipe_name(cls, value: str) -> str:
        return value.strip()

    @field_validator("steps")
    @classmethod
    def normalize_steps(cls, value: list[str]) -> list[str]:
        return [item.strip() for item in value if item.strip()]


class CookingSessionAdvanceRequest(ThreadRequest):
    action: str = Field("next", pattern="^(next|previous|current|finish)$")
