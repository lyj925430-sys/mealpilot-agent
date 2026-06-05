import re
from datetime import date
from typing import Optional

from pydantic import BaseModel, Field, field_validator


THREAD_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]{1,80}$")


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)
    image_url: Optional[str] = None
    thread_id: str = Field(..., min_length=1, max_length=80)

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
