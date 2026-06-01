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


if __name__ == "__main__":
    unittest.main()
