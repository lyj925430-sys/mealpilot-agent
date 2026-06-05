from __future__ import annotations

import json
import re
import sqlite3
from threading import RLock
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from app.core.settings import settings
from app.models.schemas import (
    ConsumedIngredient,
    CookingSessionStartRequest,
    IngredientItem,
    IngredientSubstitutionRequest,
    MealPlanRequest,
    NutritionEstimateRequest,
    UserPreferences,
)


@dataclass(frozen=True)
class InventorySnapshot:
    items: list[dict[str, Any]]
    preferences: dict[str, Any]


REMAINING_PATTERN = re.compile(r"\[remaining_percent=(\d{1,3})\]")


def _remaining_percent_from_notes(notes: str) -> int:
    match = REMAINING_PATTERN.search(notes or "")
    if not match:
        return 100
    return max(0, min(100, int(match.group(1))))


def _with_remaining_percent(notes: str, percent: int) -> str:
    percent = max(0, min(100, percent))
    cleaned = REMAINING_PATTERN.sub("", notes or "").strip(" ;")
    marker = f"[remaining_percent={percent}]"
    return f"{cleaned}; {marker}" if cleaned else marker


def _fresh_days_for_item(name: str, category: str = "") -> int:
    text = f"{name} {category}"
    if any(word in text for word in ("鱼", "虾", "蟹", "海鲜", "肉", "鸡", "鸭", "牛", "猪", "羊")):
        return 2
    if any(word in text for word in ("生菜", "菠菜", "青菜", "蔬菜", "叶菜", "葱", "香菜")):
        return 3
    if any(word in text for word in ("番茄", "土豆", "胡萝卜", "洋葱", "菌菇", "蘑菇")):
        return 5
    if any(word in text for word in ("蛋", "鸡蛋", "鸭蛋")):
        return 21
    if any(word in text for word in ("油", "盐", "酱", "醋", "糖", "料酒", "调味")):
        return 180
    return 7


def _normalized_expires_on(item: IngredientItem, today: date) -> date:
    if item.expires_on and item.expires_on >= today:
        return item.expires_on
    return today + timedelta(days=_fresh_days_for_item(item.name, item.category))


class ChefMemoryStore:
    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(db_path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._lock = RLock()
        self._setup()

    def _setup(self) -> None:
        with self._lock:
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
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS cooking_sessions (
                    thread_id TEXT PRIMARY KEY,
                    recipe_name TEXT NOT NULL,
                    steps TEXT NOT NULL,
                    current_step INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'active',
                    updated_at TEXT NOT NULL
                )
                """
            )
            self._connection.commit()

    def upsert_inventory(self, thread_id: str, items: list[IngredientItem]) -> list[dict[str, Any]]:
        with self._lock:
            now = datetime.now(UTC).isoformat(timespec="seconds")
            today = datetime.now(UTC).date()
            for item in items:
                expires_on = _normalized_expires_on(item, today)
                remaining_percent = _remaining_percent_from_notes(item.notes)
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
                        expires_on.isoformat(),
                        _with_remaining_percent(item.notes or "", remaining_percent),
                        now,
                    ),
                )
            self._connection.commit()
            return self.list_inventory(thread_id)

    def list_inventory(self, thread_id: str) -> list[dict[str, Any]]:
        with self._lock:
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
            today = datetime.now(UTC).date()
            items = []
            for row in rows:
                item = dict(row)
                expires_on = item.get("expires_on")
                if expires_on:
                    try:
                        parsed = date.fromisoformat(expires_on)
                    except ValueError:
                        parsed = None
                    if parsed and parsed < today:
                        parsed = today + timedelta(days=_fresh_days_for_item(item["name"], item.get("category", "")))
                        item["expires_on"] = parsed.isoformat()
                        item["expires_estimated"] = True
                item["remaining_percent"] = _remaining_percent_from_notes(item.get("notes", ""))
                items.append(item)
            return items

    def clear_inventory(self, thread_id: str) -> None:
        with self._lock:
            self._connection.execute("DELETE FROM inventory_items WHERE thread_id = ?", (thread_id,))
            self._connection.commit()

    def consume_inventory(
        self,
        thread_id: str,
        items: list[ConsumedIngredient],
        recipe_name: str = "",
    ) -> dict[str, Any]:
        with self._lock:
            now = datetime.now(UTC).isoformat(timespec="seconds")
            consumed = []
            missing = []
            for item in items:
                row = self._connection.execute(
                    """
                    SELECT name, quantity, category, expires_on, notes
                    FROM inventory_items
                    WHERE thread_id = ? AND name = ?
                    """,
                    (thread_id, item.name),
                ).fetchone()
                if not row:
                    missing.append(item.name)
                    continue

                current_remaining = _remaining_percent_from_notes(row["notes"] or "")
                next_remaining = item.remaining_percent
                should_remove = item.remove_from_inventory or next_remaining == 0
                consumed.append({
                    "name": item.name,
                    "amount": item.amount,
                    "previous_remaining_percent": current_remaining,
                    "remaining_percent": next_remaining if next_remaining is not None else current_remaining,
                    "removed": should_remove,
                })
                if should_remove:
                    self._connection.execute(
                        "DELETE FROM inventory_items WHERE thread_id = ? AND name = ?",
                        (thread_id, item.name),
                    )
                    continue

                note_parts = [row["notes"]] if row["notes"] else []
                amount = item.amount or "some"
                source = f" for {recipe_name}" if recipe_name else ""
                note_parts.append(f"consumed {amount}{source} at {now}")
                next_notes = "; ".join(note_parts)
                if next_remaining is not None:
                    next_notes = _with_remaining_percent(next_notes, next_remaining)
                self._connection.execute(
                    """
                    UPDATE inventory_items
                    SET notes = ?, updated_at = ?
                    WHERE thread_id = ? AND name = ?
                    """,
                    (next_notes, now, thread_id, item.name),
                )

            self._connection.commit()
            return {
                "consumed": consumed,
                "missing": missing,
                "items": self.list_inventory(thread_id),
                "note": "Quantity strings are not parsed automatically; pass remove_from_inventory=true when an item is fully used.",
            }

    def save_preferences(self, thread_id: str, preferences: UserPreferences) -> dict[str, Any]:
        with self._lock:
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
        with self._lock:
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

    def start_cooking_session(self, request: CookingSessionStartRequest) -> dict[str, Any]:
        with self._lock:
            now = datetime.now(UTC).isoformat(timespec="seconds")
            self._connection.execute(
                """
                INSERT INTO cooking_sessions
                    (thread_id, recipe_name, steps, current_step, status, updated_at)
                VALUES (?, ?, ?, 0, 'active', ?)
                ON CONFLICT(thread_id) DO UPDATE SET
                    recipe_name=excluded.recipe_name,
                    steps=excluded.steps,
                    current_step=0,
                    status='active',
                    updated_at=excluded.updated_at
                """,
                (request.thread_id, request.recipe_name, json.dumps(request.steps, ensure_ascii=False), now),
            )
            self._connection.commit()
            return self.get_cooking_session(request.thread_id)

    def advance_cooking_session(self, thread_id: str, action: str) -> dict[str, Any]:
        with self._lock:
            session = self.get_cooking_session(thread_id)
            if not session["exists"]:
                return session

            steps = session["steps"]
            index = session["current_step"]
            status = session["status"]
            if action == "next":
                index = min(index + 1, len(steps) - 1)
            elif action == "previous":
                index = max(index - 1, 0)
            elif action == "finish":
                status = "finished"

            now = datetime.now(UTC).isoformat(timespec="seconds")
            self._connection.execute(
                """
                UPDATE cooking_sessions
                SET current_step = ?, status = ?, updated_at = ?
                WHERE thread_id = ?
                """,
                (index, status, now, thread_id),
            )
            self._connection.commit()
            return self.get_cooking_session(thread_id)

    def get_cooking_session(self, thread_id: str) -> dict[str, Any]:
        with self._lock:
            row = self._connection.execute(
                """
                SELECT recipe_name, steps, current_step, status, updated_at
                FROM cooking_sessions
                WHERE thread_id = ?
                """,
                (thread_id,),
            ).fetchone()
            if not row:
                return {"exists": False, "thread_id": thread_id}

            steps = json.loads(row["steps"])
            current_step = min(row["current_step"], max(len(steps) - 1, 0))
            return {
                "exists": True,
                "thread_id": thread_id,
                "recipe_name": row["recipe_name"],
                "steps": steps,
                "current_step": current_step,
                "current_instruction": steps[current_step] if steps else "",
                "status": row["status"],
                "updated_at": row["updated_at"],
            }


chef_memory_store = ChefMemoryStore(settings.chef_memory_db_path)


def inventory_context(thread_id: str) -> str:
    snapshot = chef_memory_store.snapshot(thread_id)
    item_lines = []
    for item in snapshot.items[:20]:
        expires = f", expires_on={item['expires_on']}" if item.get("expires_on") else ""
        quantity = f", quantity={item['quantity']}" if item.get("quantity") else ""
        remaining = f", remaining={item.get('remaining_percent', 100)}%"
        item_lines.append(f"- {item['name']}{quantity}{remaining}{expires}")

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
            optional_suggestions = _optional_purchase_suggestions(selected)
            day_meals.append(
                {
                    "meal": meal_name,
                    "dish": dish,
                    "use_inventory": selected,
                    "required_ingredients": selected,
                    "missing_ingredients": [],
                    "optional_purchase_suggestions": optional_suggestions,
                    "reason": _reason(selected, preferences),
                    "steps": _steps(dish),
                }
            )
        plan_days.append({"date": day.isoformat(), "meals": day_meals})

    shopping = _optional_shopping_list(plan_days)
    return {
        "thread_id": request.thread_id,
        "strategy": "优先使用现有库存和临期食材生成可直接制作的菜单；加购内容仅作为可选升级建议。",
        "inventory_summary": {
            "total_items": len(items),
            "priority_items": priority_items,
            "preferences": preferences,
        },
        "days": plan_days,
        "shopping_list": shopping,
        "optional_shopping_list": shopping,
        "agent_talking_points": [
            "库存状态独立持久化，聊天 Agent 可读取同一份厨房记忆。",
            "菜单规划会优先使用临期食材，减少浪费。",
            "推荐菜肴默认应使用现有食材即可制作，加购清单只作为可选升级。",
        ],
    }


def suggest_substitutions(request: IngredientSubstitutionRequest) -> dict[str, Any]:
    snapshot = chef_memory_store.snapshot(request.thread_id)
    inventory_names = {item["name"] for item in snapshot.items}
    preferences = snapshot.preferences
    disliked = set(preferences.get("disliked_ingredients") or [])
    allergies = set(preferences.get("allergies") or [])
    blocked = disliked | allergies

    candidates = SUBSTITUTION_RULES.get(request.ingredient, DEFAULT_SUBSTITUTIONS)
    suggestions = []
    for candidate in candidates:
        if candidate["name"] in blocked:
            continue
        suggestions.append(
            {
                **candidate,
                "available_in_inventory": candidate["name"] in inventory_names,
            }
        )

    suggestions.sort(key=lambda item: not item["available_in_inventory"])
    return {
        "ingredient": request.ingredient,
        "dish": request.dish,
        "suggestions": suggestions,
        "blocked_by_preferences": sorted(blocked),
        "strategy": "Prefer substitutes already in inventory, then filter allergies and disliked ingredients.",
    }


def estimate_nutrition(request: NutritionEstimateRequest) -> dict[str, Any]:
    totals = {"calories": 0.0, "protein_g": 0.0, "carbs_g": 0.0, "fat_g": 0.0}
    details = []
    for ingredient in request.ingredients:
        profile = NUTRITION_PROFILES.get(ingredient.name, DEFAULT_NUTRITION)
        grams = _amount_to_grams(ingredient.amount)
        multiplier = grams / 100
        item_total = {
            key: round(profile[key] * multiplier, 1)
            for key in totals
        }
        for key, value in item_total.items():
            totals[key] += value
        details.append(
            {
                "name": ingredient.name,
                "amount": ingredient.amount,
                "estimated_grams": grams,
                "nutrition": item_total,
                "confidence": "medium" if ingredient.name in NUTRITION_PROFILES else "low",
            }
        )

    per_serving = {
        key: round(value / request.servings, 1)
        for key, value in totals.items()
    }
    return {
        "servings": request.servings,
        "total": {key: round(value, 1) for key, value in totals.items()},
        "per_serving": per_serving,
        "details": details,
        "note": "This is a lightweight estimate for meal planning, not medical nutrition advice.",
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


def _optional_purchase_suggestions(ingredients: list[str]) -> list[str]:
    suggestions = ["葱姜蒜", "生抽", "盐"]
    if len(ingredients) < 2:
        suggestions.append("时令青菜")
    return suggestions


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


def _optional_shopping_list(plan_days: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for day in plan_days:
        for meal in day["meals"]:
            for ingredient in meal["optional_purchase_suggestions"]:
                counts[ingredient] = counts.get(ingredient, 0) + 1
    return [
        {"name": name, "priority": count, "optional": True}
        for name, count in sorted(counts.items())
    ]


SUBSTITUTION_RULES = {
    "黄油": [
        {"name": "橄榄油", "ratio": "用量约为黄油的 70%-80%", "impact": "更清爽，奶香减少"},
        {"name": "植物油", "ratio": "等量或略少", "impact": "适合中式炒菜，风味更轻"},
        {"name": "奶油奶酪", "ratio": "少量替代", "impact": "适合烘焙或浓汤，口感更厚"},
    ],
    "牛奶": [
        {"name": "豆浆", "ratio": "等量", "impact": "蛋白质较高，豆香明显"},
        {"name": "椰奶", "ratio": "等量", "impact": "更香甜，适合咖喱和甜品"},
        {"name": "清水", "ratio": "等量", "impact": "风味变淡，适合应急"},
    ],
    "鸡蛋": [
        {"name": "豆腐", "ratio": "半盒替代 1-2 个鸡蛋", "impact": "蛋白质保留，口感更软"},
        {"name": "鸡胸肉", "ratio": "100g 替代 1-2 个鸡蛋", "impact": "蛋白质更高，烹饪时间增加"},
        {"name": "虾仁", "ratio": "80g 替代 1-2 个鸡蛋", "impact": "更鲜，成本略高"},
    ],
    "米饭": [
        {"name": "面条", "ratio": "按食量等量替代", "impact": "更适合汤面或拌面"},
        {"name": "土豆", "ratio": "中等土豆 1-2 个", "impact": "饱腹感强，适合减脂餐"},
        {"name": "玉米", "ratio": "1 根替代一小碗米饭", "impact": "甜味更明显，纤维更高"},
    ],
}

DEFAULT_SUBSTITUTIONS = [
    {"name": "鸡蛋", "ratio": "按蛋白质需求替代", "impact": "快手、通用"},
    {"name": "豆腐", "ratio": "按体积等量替代", "impact": "清淡、低脂"},
    {"name": "时令青菜", "ratio": "按口味添加", "impact": "补充纤维和颜色"},
]

NUTRITION_PROFILES = {
    "鸡蛋": {"calories": 143, "protein_g": 12.6, "carbs_g": 0.7, "fat_g": 9.5},
    "番茄": {"calories": 18, "protein_g": 0.9, "carbs_g": 3.9, "fat_g": 0.2},
    "鸡胸肉": {"calories": 165, "protein_g": 31.0, "carbs_g": 0.0, "fat_g": 3.6},
    "米饭": {"calories": 116, "protein_g": 2.6, "carbs_g": 25.9, "fat_g": 0.3},
    "豆腐": {"calories": 76, "protein_g": 8.0, "carbs_g": 1.9, "fat_g": 4.8},
    "土豆": {"calories": 77, "protein_g": 2.0, "carbs_g": 17.0, "fat_g": 0.1},
    "牛奶": {"calories": 61, "protein_g": 3.2, "carbs_g": 4.8, "fat_g": 3.3},
    "虾仁": {"calories": 99, "protein_g": 24.0, "carbs_g": 0.2, "fat_g": 0.3},
}
DEFAULT_NUTRITION = {"calories": 80, "protein_g": 3.0, "carbs_g": 10.0, "fat_g": 2.0}


def _amount_to_grams(amount: str) -> float:
    if not amount:
        return 100.0

    digits = "".join(char for char in amount if char.isdigit() or char == ".")
    if not digits:
        return 100.0

    value = float(digits)
    lowered = amount.lower()
    if "kg" in lowered or "公斤" in amount or "千克" in amount:
        return value * 1000
    if "个" in amount:
        return value * 50
    if "ml" in lowered or "毫升" in amount:
        return value
    return value
