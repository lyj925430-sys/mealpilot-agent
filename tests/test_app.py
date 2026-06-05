import unittest
from datetime import date
from uuid import uuid4

from fastapi.testclient import TestClient

from app.agents.personal_chief import _inventory_guard_context, _inventory_guard_reply
from app.models.schemas import ConsumedIngredient, IngredientItem
from app.services.meal_planner import chef_memory_store
from app.main import app


client = TestClient(app)


class AppSmokeTests(unittest.TestCase):
    def test_health_check(self):
        response = client.get("/health")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "ok")
        self.assertIn("features", payload)

    def test_frontend_loads(self):
        response = client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Personal Chief", response.text)
        self.assertIn("thread-list", response.text)

    def test_chat_request_validation(self):
        response = client.post(
            "/api/v1/chat/stream",
            json={"message": "", "thread_id": "bad id with spaces"},
        )

        self.assertEqual(response.status_code, 422)

    def test_oss_rejects_nested_filename(self):
        response = client.get("/api/v1/oss/presign", params={"filename": "../food.png"})

        self.assertEqual(response.status_code, 400)

    def test_oss_rejects_unsupported_file_type(self):
        response = client.get("/api/v1/oss/presign", params={"filename": "food.txt"})

        self.assertEqual(response.status_code, 400)

    def test_auth_register_login_me_logout(self):
        username = f"user-{uuid4().hex[:8]}"
        password = "secret123"

        register_response = client.post(
            "/api/v1/auth/register",
            json={"username": username, "password": password},
        )
        self.assertEqual(register_response.status_code, 200)
        register_payload = register_response.json()
        self.assertIn("access_token", register_payload)
        self.assertEqual(register_payload["user"]["username"], username)

        duplicate_response = client.post(
            "/api/v1/auth/register",
            json={"username": username, "password": password},
        )
        self.assertEqual(duplicate_response.status_code, 409)

        login_response = client.post(
            "/api/v1/auth/login",
            json={"username": username, "password": password},
        )
        self.assertEqual(login_response.status_code, 200)
        token = login_response.json()["access_token"]

        me_response = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(me_response.status_code, 200)
        self.assertEqual(me_response.json()["user"]["username"], username)

        logout_response = client.post("/api/v1/auth/logout", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(logout_response.status_code, 200)

        expired_me_response = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(expired_me_response.status_code, 401)

    def test_auth_household_profile(self):
        username = f"profile-{uuid4().hex[:8]}"
        password = "secret123"
        register_response = client.post(
            "/api/v1/auth/register",
            json={"username": username, "password": password},
        )
        token = register_response.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        payload = {
            "profile": {
                "age": 28,
                "gender": "male",
                "height_cm": 175,
                "weight_kg": 70,
                "activity_level": "light",
                "health_goals": ["减脂"],
                "conditions": ["控糖"],
                "allergies": ["花生"],
                "dietary_preferences": ["清淡"],
                "notes": "晚餐少油",
            },
            "relatives": [
                {
                    "name": "妈妈",
                    "relation": "mother",
                    "age": 58,
                    "conditions": ["高血压"],
                    "allergies": [],
                    "dietary_preferences": ["软烂"],
                    "notes": "少盐",
                }
            ],
        }
        save_response = client.put("/api/v1/auth/household", json=payload, headers=headers)
        self.assertEqual(save_response.status_code, 200)
        self.assertEqual(save_response.json()["profile"]["age"], 28)
        self.assertEqual(save_response.json()["relatives"][0]["name"], "妈妈")

        get_response = client.get("/api/v1/auth/household", headers=headers)
        self.assertEqual(get_response.status_code, 200)
        self.assertEqual(get_response.json()["profile"]["conditions"], ["控糖"])

    def test_chef_inventory_and_meal_plan(self):
        thread_id = "test-chef-agent"
        client.delete("/api/v1/chef/inventory", params={"thread_id": thread_id})

        inventory_response = client.post(
            "/api/v1/chef/inventory",
            json={
                "thread_id": thread_id,
                "items": [
                    {
                        "name": "鸡蛋",
                        "quantity": "6个",
                        "category": "protein",
                        "expires_on": "2026-06-04",
                    },
                    {
                        "name": "番茄",
                        "quantity": "3个",
                        "category": "vegetable",
                    },
                ],
            },
        )

        self.assertEqual(inventory_response.status_code, 200)
        inventory_items = inventory_response.json()["items"]
        self.assertEqual(len(inventory_items), 2)
        self.assertTrue(all(date.fromisoformat(item["expires_on"]) >= date.today() for item in inventory_items))
        self.assertTrue(all(item["remaining_percent"] == 100 for item in inventory_items))

        preferences_response = client.post(
            "/api/v1/chef/preferences",
            json={
                "thread_id": thread_id,
                "preferences": {
                    "dietary_goals": ["减脂"],
                    "allergies": [],
                    "disliked_ingredients": ["香菜"],
                    "liked_flavors": ["清淡"],
                    "budget_level": "normal",
                    "cooking_time_minutes": 30,
                },
            },
        )

        self.assertEqual(preferences_response.status_code, 200)

        plan_response = client.post(
            "/api/v1/chef/meal-plan",
            json={"thread_id": thread_id, "days": 2, "meals": ["dinner"], "people": 1},
        )

        self.assertEqual(plan_response.status_code, 200)
        payload = plan_response.json()
        self.assertEqual(payload["inventory_summary"]["total_items"], 2)
        self.assertEqual(len(payload["days"]), 2)
        self.assertIn("shopping_list", payload)
        first_meal = payload["days"][0]["meals"][0]
        self.assertEqual(first_meal["missing_ingredients"], [])
        self.assertIn("optional_purchase_suggestions", first_meal)
        self.assertTrue(all(item["optional"] for item in payload["shopping_list"]))

    def test_chef_execution_tools(self):
        thread_id = "test-chef-tools"
        client.delete("/api/v1/chef/inventory", params={"thread_id": thread_id})

        client.post(
            "/api/v1/chef/inventory",
            json={
                "thread_id": thread_id,
                "items": [
                    {"name": "鸡蛋", "quantity": "6个", "category": "protein"},
                    {"name": "豆腐", "quantity": "1盒", "category": "protein"},
                    {"name": "橄榄油", "quantity": "半瓶", "category": "seasoning"},
                ],
            },
        )

        consume_response = client.post(
            "/api/v1/chef/inventory/consume",
            json={
                "thread_id": thread_id,
                "recipe_name": "番茄炒蛋",
                "items": [{"name": "鸡蛋", "amount": "剩余 60%", "remaining_percent": 60}],
            },
        )
        self.assertEqual(consume_response.status_code, 200)
        self.assertEqual(consume_response.json()["consumed"][0]["name"], "鸡蛋")
        self.assertEqual(consume_response.json()["consumed"][0]["remaining_percent"], 60)
        egg_items = [item for item in consume_response.json()["items"] if item["name"] == "鸡蛋"]
        self.assertEqual(egg_items[0]["remaining_percent"], 60)

        used_up_response = client.post(
            "/api/v1/chef/inventory/consume",
            json={
                "thread_id": thread_id,
                "items": [{"name": "豆腐", "amount": "剩余 0%", "remaining_percent": 0}],
            },
        )
        self.assertEqual(used_up_response.status_code, 200)
        self.assertNotIn("豆腐", [item["name"] for item in used_up_response.json()["items"]])

        substitution_response = client.post(
            "/api/v1/chef/substitutions",
            json={"thread_id": thread_id, "ingredient": "黄油", "dish": "煎蛋"},
        )
        self.assertEqual(substitution_response.status_code, 200)
        suggestions = substitution_response.json()["suggestions"]
        self.assertTrue(suggestions[0]["available_in_inventory"])

        nutrition_response = client.post(
            "/api/v1/chef/nutrition",
            json={
                "thread_id": thread_id,
                "servings": 1,
                "ingredients": [
                    {"name": "鸡蛋", "amount": "2个"},
                    {"name": "番茄", "amount": "200g"},
                ],
            },
        )
        self.assertEqual(nutrition_response.status_code, 200)
        self.assertGreater(nutrition_response.json()["total"]["protein_g"], 0)

        session_response = client.post(
            "/api/v1/chef/cooking-session",
            json={
                "thread_id": thread_id,
                "recipe_name": "番茄炒蛋",
                "steps": ["切番茄", "炒鸡蛋", "合炒调味"],
            },
        )
        self.assertEqual(session_response.status_code, 200)
        self.assertEqual(session_response.json()["current_step"], 0)

        next_response = client.post(
            "/api/v1/chef/cooking-session/advance",
            json={"thread_id": thread_id, "action": "next"},
        )
        self.assertEqual(next_response.status_code, 200)
        self.assertEqual(next_response.json()["current_instruction"], "炒鸡蛋")

    def test_inventory_guard_detects_used_up_requested_food(self):
        thread_id = "test-inventory-guard"
        chef_memory_store.clear_inventory(thread_id)
        chef_memory_store.upsert_inventory(
            thread_id,
            [
                IngredientItem(name="三文鱼", quantity="1块", category="protein")
            ],
        )
        chef_memory_store.consume_inventory(
            thread_id,
            [
                ConsumedIngredient(name="三文鱼", amount="剩余 0%", remaining_percent=0)
            ],
        )

        guard = _inventory_guard_context("我想吃三文鱼", thread_id)
        self.assertIn("三文鱼", guard)
        self.assertIn("当前食材余量中没有", guard)

        reply = _inventory_guard_reply("我想吃三文鱼", thread_id)
        self.assertIn("当前食材余量里没有 三文鱼", reply)
        self.assertIn("不能直接", reply)


if __name__ == "__main__":
    unittest.main()
