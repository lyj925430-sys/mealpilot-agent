from collections.abc import AsyncIterator

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse

from app.agents.personal_chief import clear_messages, get_messages, search_recipes
from app.models.schemas import ChatRequest, THREAD_ID_PATTERN


router = APIRouter()


async def _stream_chat(request: ChatRequest) -> AsyncIterator[str]:
    async for chunk in search_recipes(request.message, request.image_url, request.thread_id):
        yield chunk


@router.post("/chat/stream")
async def chat_endpoint(request: ChatRequest):
    return StreamingResponse(
        _stream_chat(request),
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
