from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from app.core.settings import settings
from app.models.schemas import IngredientItem, MealPlanRequest, UserPreferences


@dataclass(frozen=True)
class InventorySnapshot:
    items: list[dict[str, Any]]
    preferences: dict[str, Any]


class ChefMemoryStore:
    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(db_path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._setup()

    def _setup(self) -> None:
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS inventory_items (
                thread_id TEXT NOT NULL,
                name TEXT NOT NULL,
                quantity TEXT NOT NULL DEFAULT '',
                category TEXT NOT NULL DEFAULT '',
                expires_on TEXT,
                notes TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL,
                PRIMARY KEY (thread_id, name)
            )
            """
        )
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS user_preferences (
                thread_id TEXT PRIMARY KEY,
                dietary_goals TEXT NOT NULL DEFAULT '[]',
                allergies TEXT NOT NULL DEFAULT '[]',
                disliked_ingredients TEXT NOT NULL DEFAULT '[]',
                liked_flavors TEXT NOT NULL DEFAULT '[]',
                budget_level TEXT NOT NULL DEFAULT 'normal',
                cooking_time_minutes INTEGER,
                updated_at TEXT NOT NULL
            )
            """
        )
        self._connection.commit()

    def upsert_inventory(self, thread_id: str, items: list[IngredientItem]) -> list[dict[str, Any]]:
        now = datetime.now(UTC).isoformat(timespec="seconds")
        for item in items:
            self._connection.execute(
                """
                INSERT INTO inventory_items
                    (thread_id, name, quantity, category, expires_on, notes, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(thread_id, name) DO UPDATE SET
                    quantity=excluded.quantity,
                    category=excluded.category,
                    expires_on=excluded.expires_on,
                    notes=excluded.notes,
                    updated_at=excluded.updated_at
                """,
                (
                    thread_id,
                    item.name,
                    item.quantity or "",
                    item.category or "",
                    item.expires_on.isoformat() if item.expires_on else None,
                    item.notes or "",
                    now,
                ),
            )
        self._connection.commit()
        return self.list_inventory(thread_id)

    def list_inventory(self, thread_id: str) -> list[dict[str, Any]]:
        rows = self._connection.execute(
            """
            SELECT name, quantity, category, expires_on, notes, updated_at
            FROM inventory_items
            WHERE thread_id = ?
            ORDER BY
                CASE WHEN expires_on IS NULL THEN 1 ELSE 0 END,
                expires_on ASC,
                updated_at DESC,
                name ASC
            """,
            (thread_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def clear_inventory(self, thread_id: str) -> None:
        self._connection.execute("DELETE FROM inventory_items WHERE thread_id = ?", (thread_id,))
        self._connection.commit()

    def save_preferences(self, thread_id: str, preferences: UserPreferences) -> dict[str, Any]:
        now = datetime.now(UTC).isoformat(timespec="seconds")
        self._connection.execute(
            """
            INSERT INTO user_preferences
                (thread_id, dietary_goals, allergies, disliked_ingredients, liked_flavors,
                 budget_level, cooking_time_minutes, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(thread_id) DO UPDATE SET
                dietary_goals=excluded.dietary_goals,
                allergies=excluded.allergies,
                disliked_ingredients=excluded.disliked_ingredients,
                liked_flavors=excluded.liked_flavors,
                budget_level=excluded.budget_level,
                cooking_time_minutes=excluded.cooking_time_minutes,
                updated_at=excluded.updated_at
            """,
            (
                thread_id,
                json.dumps(preferences.dietary_goals, ensure_ascii=False),
                json.dumps(preferences.allergies, ensure_ascii=False),
                json.dumps(preferences.disliked_ingredients, ensure_ascii=False),
                json.dumps(preferences.liked_flavors, ensure_ascii=False),
                preferences.budget_level,
                preferences.cooking_time_minutes,
                now,
            ),
        )
        self._connection.commit()
        return self.get_preferences(thread_id)

    def get_preferences(self, thread_id: str) -> dict[str, Any]:
        row = self._connection.execute(
            """
            SELECT dietary_goals, allergies, disliked_ingredients, liked_flavors,
                   budget_level, cooking_time_minutes, updated_at
            FROM user_preferences
            WHERE thread_id = ?
            """,
            (thread_id,),
        ).fetchone()
        if not row:
            return {
                "dietary_goals": [],
                "allergies": [],
                "disliked_ingredients": [],
                "liked_flavors": [],
                "budget_level": "normal",
                "cooking_time_minutes": None,
                "updated_at": None,
            }

        return {
            "dietary_goals": json.loads(row["dietary_goals"]),
            "allergies": json.loads(row["allergies"]),
            "disliked_ingredients": json.loads(row["disliked_ingredients"]),
            "liked_flavors": json.loads(row["liked_flavors"]),
            "budget_level": row["budget_level"],
            "cooking_time_minutes": row["cooking_time_minutes"],
            "updated_at": row["updated_at"],
        }

    def snapshot(self, thread_id: str) -> InventorySnapshot:
        return InventorySnapshot(
            items=self.list_inventory(thread_id),
            preferences=self.get_preferences(thread_id),
        )


chef_memory_store = ChefMemoryStore(settings.chef_memory_db_path)


def inventory_context(thread_id: str) -> str:
    snapshot = chef_memory_store.snapshot(thread_id)
    item_lines = []
    for item in snapshot.items[:20]:
        expires = f", expires_on={item['expires_on']}" if item.get("expires_on") else ""
        quantity = f", quantity={item['quantity']}" if item.get("quantity") else ""
        item_lines.append(f"- {item['name']}{quantity}{expires}")

    preferences = snapshot.preferences
    preference_lines = [
        f"dietary_goals={preferences.get('dietary_goals', [])}",
        f"allergies={preferences.get('allergies', [])}",
        f"disliked_ingredients={preferences.get('disliked_ingredients', [])}",
        f"liked_flavors={preferences.get('liked_flavors', [])}",
        f"budget_level={preferences.get('budget_level', 'normal')}",
        f"cooking_time_minutes={preferences.get('cooking_time_minutes')}",
    ]

    if not item_lines and not any(preferences.get(key) for key in ("dietary_goals", "allergies", "disliked_ingredients", "liked_flavors")):
        return ""

    return "\n".join(
        [
            "用户长期厨房记忆:",
            "当前库存:",
            *(item_lines or ["- 暂无库存记录"]),
            "用户偏好:",
            *preference_lines,
        ]
    )


def generate_meal_plan(request: MealPlanRequest) -> dict[str, Any]:
    snapshot = chef_memory_store.snapshot(request.thread_id)
    items = snapshot.items
    preferences = snapshot.preferences

    available_names = [item["name"] for item in items]
    priority_items = _priority_items(items)
    usable = priority_items or available_names
    meals = request.meals or ["dinner"]
    plan_days = []
    used: set[str] = set()

    for offset in range(request.days):
        day = date.today() + timedelta(days=offset)
        day_meals = []
        for meal_name in meals:
            selected = _select_ingredients(usable, used, limit=3)
            used.update(selected)
            dish = _dish_name(selected, meal_name, offset)
            missing = _missing_for(selected)
            day_meals.append(
                {
                    "meal": meal_name,
                    "dish": dish,
                    "use_inventory": selected,
                    "missing_ingredients": missing,
                    "reason": _reason(selected, preferences),
                    "steps": _steps(dish),
                }
            )
        plan_days.append({"date": day.isoformat(), "meals": day_meals})

    shopping = _shopping_list(plan_days)
    return {
        "thread_id": request.thread_id,
        "strategy": "优先消耗临期食材，并结合用户忌口、预算和做饭时间生成可执行菜单。",
        "inventory_summary": {
            "total_items": len(items),
            "priority_items": priority_items,
            "preferences": preferences,
        },
        "days": plan_days,
        "shopping_list": shopping,
        "agent_talking_points": [
            "库存状态独立持久化，聊天 Agent 可读取同一份厨房记忆。",
            "菜单规划会优先使用临期食材，减少浪费。",
            "购物清单只列出库存外缺口，方便形成闭环。",
        ],
    }


def _priority_items(items: list[dict[str, Any]]) -> list[str]:
    today = date.today()
    scored = []
    for item in items:
        expires_on = item.get("expires_on")
        if not expires_on:
            continue
        try:
            days_left = (date.fromisoformat(expires_on) - today).days
        except ValueError:
            continue
        scored.append((days_left, item["name"]))
    return [name for days_left, name in sorted(scored) if days_left <= 5]


def _select_ingredients(names: list[str], used: set[str], limit: int) -> list[str]:
    fresh = [name for name in names if name not in used]
    selected = (fresh or names)[:limit]
    return selected or ["鸡蛋", "番茄"]


def _dish_name(ingredients: list[str], meal: str, offset: int) -> str:
    joined = "、".join(ingredients[:2])
    if "早餐" in meal or meal == "breakfast":
        return f"{joined}快手早餐碗"
    if offset % 3 == 1:
        return f"{joined}家常焖饭"
    if offset % 3 == 2:
        return f"{joined}清爽汤面"
    return f"{joined}营养小炒"


def _missing_for(ingredients: list[str]) -> list[str]:
    base = ["葱姜蒜", "生抽", "盐"]
    if len(ingredients) < 2:
        base.append("时令青菜")
    return base


def _reason(ingredients: list[str], preferences: dict[str, Any]) -> str:
    goal = "、".join(preferences.get("dietary_goals") or [])
    prefix = f"符合{goal}目标，" if goal else ""
    return f"{prefix}优先使用{ '、'.join(ingredients) }，减少库存浪费，步骤简单适合日常执行。"


def _steps(dish: str) -> list[str]:
    return [
        f"处理并切配{dish.replace('营养小炒', '').replace('家常焖饭', '').replace('清爽汤面', '').replace('快手早餐碗', '')}。",
        "热锅少油，先处理需要更久成熟的食材。",
        "加入调味料，控制盐和油的用量。",
        "出锅前试味，根据口味微调。",
    ]


def _shopping_list(plan_days: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for day in plan_days:
        for meal in day["meals"]:
            for ingredient in meal["missing_ingredients"]:
                counts[ingredient] = counts.get(ingredient, 0) + 1
    return [{"name": name, "priority": count} for name, count in sorted(counts.items())]
