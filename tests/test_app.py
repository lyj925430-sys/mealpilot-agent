import unittest

from fastapi.testclient import TestClient

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
        self.assertEqual(len(inventory_response.json()["items"]), 2)

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


if __name__ == "__main__":
    unittest.main()
