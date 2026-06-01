import re
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
