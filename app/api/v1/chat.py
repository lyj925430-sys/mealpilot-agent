from collections.abc import AsyncIterator

from fastapi import APIRouter, Header, Query
from fastapi.responses import StreamingResponse

from app.agents.personal_chief import clear_messages, get_messages, search_recipes
from app.models.schemas import ChatRequest, THREAD_ID_PATTERN
from app.services.auth_service import auth_store


router = APIRouter()


def _optional_user_id(authorization: str) -> str | None:
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None
    try:
        return auth_store.get_user_by_token(token.strip())["id"]
    except Exception:
        return None


async def _stream_chat(request: ChatRequest, user_id: str | None, meal_context: str) -> AsyncIterator[str]:
    async for chunk in search_recipes(request.message, request.image_url, request.thread_id, user_id, meal_context):
        yield chunk


@router.post("/chat/stream")
async def chat_endpoint(
    request: ChatRequest,
    authorization: str = Header(""),
):
    user_id = _optional_user_id(authorization)
    return StreamingResponse(
        _stream_chat(request, user_id, request.meal_context),
        media_type="text/plain; charset=utf-8",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/chat/messages")
async def get_chat_messages(
    thread_id: str = Query(..., min_length=1, max_length=80, pattern=THREAD_ID_PATTERN.pattern),
):
    return {"messages": get_messages(thread_id)}


@router.delete("/chat/messages")
async def clear_chat_messages(
    thread_id: str = Query(..., min_length=1, max_length=80, pattern=THREAD_ID_PATTERN.pattern),
):
    clear_messages(thread_id)
    return {"success": True}
