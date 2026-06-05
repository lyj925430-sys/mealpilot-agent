import sqlite3
from typing import Any

from langchain.agents import create_agent
from langchain.chat_models import init_chat_model
from langchain.tools import tool
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage
from langchain_tavily import TavilySearch
from langgraph.checkpoint.sqlite import SqliteSaver

from app.common.logger import logger
from app.core.settings import settings
from app.models.schemas import MealPlanRequest
from app.services.meal_planner import chef_memory_store, generate_meal_plan, inventory_context


SYSTEM_PROMPT = """
\u4f60\u662f\u4e00\u540d\u79c1\u4eba AI \u53a8\u5e08\u3002\u6536\u5230\u7528\u6237\u63d0\u4f9b\u7684\u98df\u6750\u7167\u7247\u6216\u98df\u6750\u6e05\u5355\u540e\uff0c\u8bf7\u6309\u4ee5\u4e0b\u6d41\u7a0b\u5de5\u4f5c\uff1a

1. \u8bc6\u522b\u548c\u8bc4\u4f30\u98df\u6750\uff1a\u5982\u679c\u7528\u6237\u63d0\u4f9b\u7167\u7247\uff0c\u5148\u8bc6\u522b\u6240\u6709\u53ef\u89c1\u98df\u6750\uff1b\u7ed3\u5408\u5916\u89c2\u72b6\u6001\uff0c\u8bc4\u4f30\u65b0\u9c9c\u5ea6\u548c\u53ef\u7528\u91cf\uff0c\u6574\u7406\u51fa\u201c\u5f53\u524d\u53ef\u7528\u98df\u6750\u6e05\u5355\u201d\u3002
2. \u667a\u80fd\u98df\u8c31\u68c0\u7d22\uff1a\u4f18\u5148\u8c03\u7528 web_search \u5de5\u5177\uff0c\u4ee5\u53ef\u7528\u98df\u6750\u6e05\u5355\u4e3a\u6838\u5fc3\u5173\u952e\u8bcd\uff0c\u67e5\u627e\u53ef\u884c\u83dc\u8c31\u3002
3. \u591a\u7ef4\u5ea6\u8bc4\u4f30\u4e0e\u6392\u5e8f\uff1a\u4ece\u8425\u517b\u4ef7\u503c\u3001\u5236\u4f5c\u96be\u5ea6\u3001\u8017\u65f6\u3001\u98df\u6750\u5339\u914d\u5ea6\u51e0\u4e2a\u7ef4\u5ea6\u7ed9\u5019\u9009\u83dc\u8c31\u6253\u5206\uff0c\u5e76\u628a\u7b80\u5355\u4e14\u8425\u517b\u5747\u8861\u7684\u65b9\u6848\u6392\u5728\u524d\u9762\u3002
4. \u7ed3\u6784\u5316\u8f93\u51fa\uff1a\u8f93\u51fa\u6e05\u6670\u7684\u5efa\u8bae\u62a5\u544a\uff0c\u5305\u542b\u83dc\u8c31\u540d\u79f0\u3001\u63a8\u8350\u5206\u3001\u63a8\u8350\u7406\u7531\u3001\u6240\u9700\u98df\u6750\u3001\u7b80\u8981\u6b65\u9aa4\u3001\u6ce8\u610f\u4e8b\u9879\u548c\u53c2\u8003\u6765\u6e90\u3002

\u8981\u6c42\uff1a
- \u4e25\u683c\u4f18\u5148\u4f7f\u7528 web_search \u68c0\u7d22\u83dc\u8c31\uff1b\u641c\u7d22\u4e0d\u5230\u65f6\u518d\u57fa\u4e8e\u5e38\u8bc6\u8865\u5145\u3002
- \u56de\u7b54\u8981\u5177\u4f53\u3001\u53ef\u6267\u884c\uff0c\u907f\u514d\u7a7a\u6cdb\u63cf\u8ff0\u3002
- \u5982\u679c\u56fe\u7247\u4fe1\u606f\u4e0d\u8db3\uff0c\u8bf7\u4e3b\u52a8\u8bf4\u660e\u4e0d\u786e\u5b9a\u9879\uff0c\u5e76\u5efa\u8bae\u7528\u6237\u8865\u5145\u98df\u6750\u6e05\u5355\u3002
- \u5982\u679c\u7528\u6237\u63d0\u5230\u51cf\u8102\u3001\u5fcc\u53e3\u3001\u8fc7\u654f\u3001\u63a7\u7cd6\u3001\u8001\u4eba\u3001\u513f\u7ae5\u3001\u5b55\u5987\u7b49\u5065\u5eb7\u7ea6\u675f\uff0c\u8bf7\u5728\u63a8\u8350\u91cc\u4e3b\u52a8\u7ed9\u51fa\u8425\u517b\u63d0\u9192\u3002
"""

CONFIG_ERROR_MESSAGE = "\u670d\u52a1\u914d\u7f6e\u4e0d\u5b8c\u6574\uff0c\u8bf7\u5148\u68c0\u67e5 DASHSCOPE_API_KEY \u548c BASE_URL\u3002"
AGENT_ERROR_MESSAGE = "\u4fe1\u606f\u68c0\u7d22\u5931\u8d25\uff0c\u8bf7\u7a0d\u540e\u91cd\u8bd5\uff0c\u6216\u8005\u5148\u624b\u52a8\u8f93\u5165\u98df\u6750\u6e05\u5355\u3002"

SYSTEM_PROMPT += """

Agent upgrade:
- If the user asks for multi-day menus, inventory consumption, shopping lists, or what to eat this week, use kitchen_memory and meal_plan first.
- Prefer ingredients that expire soon. Clearly separate ingredients already in the kitchen from ingredients that need to be bought.
- Treat saved inventory and preferences as long-term kitchen memory for the current thread_id.
"""


def _create_checkpointer() -> SqliteSaver:
    settings.database_dir.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(settings.memory_db_path, check_same_thread=False)
    checkpointer = SqliteSaver(connection)
    checkpointer.setup()
    return checkpointer


checkpointer = _create_checkpointer()


@tool
def web_search(query: str) -> Any:
    """Search recipes by ingredients or cooking requirements."""
    if not settings.search_ready:
        return "Search is unavailable because TAVILY_API_KEY is not configured."

    search = TavilySearch(max_results=5, topic="general")
    return search.invoke(query)


@tool
def kitchen_memory(thread_id: str) -> Any:
    """Get saved inventory and cooking preferences for a conversation thread."""
    snapshot = chef_memory_store.snapshot(thread_id)
    return {"items": snapshot.items, "preferences": snapshot.preferences}


@tool
def meal_plan(thread_id: str, days: int = 3) -> Any:
    """Create a multi-day meal plan from saved inventory and preferences."""
    return generate_meal_plan(MealPlanRequest(thread_id=thread_id, days=days))


def _create_agent():
    missing = []
    if not settings.llm_ready:
        missing.append("DASHSCOPE_API_KEY/BASE_URL")

    if missing:
        logger.warning("Agent is not ready, missing config: %s", ", ".join(missing))
        return None

    model = init_chat_model(
        model=settings.model_name,
        model_provider=settings.model_provider,
        api_key=settings.dashscope_api_key,
        base_url=settings.base_url,
    )

    return create_agent(
        model=model,
        tools=[web_search, kitchen_memory, meal_plan],
        checkpointer=checkpointer,
        system_prompt=SYSTEM_PROMPT,
    )


agent = _create_agent()


async def search_recipes(prompt: str, image: str | None, thread_id: str):
    logger.info("[user] thread_id=%s image=%s prompt=%s", thread_id, bool(image), prompt)

    if agent is None:
        yield CONFIG_ERROR_MESSAGE
        return

    try:
        context = inventory_context(thread_id)
        if context:
            prompt = f"当前 thread_id: {thread_id}\n{context}\n\n当前用户请求:\n{prompt}"

        if not image:
            message = HumanMessage(content=prompt)
        else:
            message = HumanMessage(
                content=[
                    {"type": "image_url", "image_url": {"url": image}},
                    {"type": "text", "text": prompt},
                ]
            )

        for chunk, _metadata in agent.stream(
            {"messages": [message]},
            {"configurable": {"thread_id": thread_id}},
            stream_mode="messages",
        ):
            if isinstance(chunk, AIMessageChunk) and chunk.content:
                yield chunk.content

    except Exception as exc:
        logger.exception("Agent stream failed: %s", exc)
        yield AGENT_ERROR_MESSAGE


def clear_messages(thread_id: str) -> None:
    logger.info("Clear conversation history: thread_id=%s", thread_id)
    checkpointer.delete_thread(thread_id)


def _message_content(content: Any) -> Any:
    if isinstance(content, str):
        return content
    return content


def get_messages(thread_id: str) -> list[dict[str, Any]]:
    logger.info("Get conversation history: thread_id=%s", thread_id)
    checkpoint = checkpointer.get({"configurable": {"thread_id": thread_id}})
    if not checkpoint:
        return []

    channel_values = checkpoint.get("channel_values") or {}
    messages = channel_values.get("messages") or []

    result: list[dict[str, Any]] = []
    for msg in messages:
        if not getattr(msg, "content", None):
            continue

        if isinstance(msg, HumanMessage):
            result.append({"role": "user", "content": _message_content(msg.content)})
        elif isinstance(msg, AIMessage):
            result.append({"role": "assistant", "content": _message_content(msg.content)})

    return result
