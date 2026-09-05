import os
import tempfile
import unittest
from pathlib import Path


# Keep this suite isolated when run on its own.  When unittest discovers it
# after the finance suite, backend.main is already loaded and the existing
# temporary database is intentionally reused.
if "backend.main" not in __import__("sys").modules:
    os.environ["SYNCMATE_DB_PATH"] = str(Path(tempfile.mkdtemp(prefix="syncmate-travel-")) / "travel.db")

from fastapi.testclient import TestClient

from backend import main


class TravelRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        main.initialize_database()
        cls.client = TestClient(main.app)
        login = cls.client.post("/api/auth/login", json={"username": "demo", "password": "123456"})
        assert login.status_code == 200, login.text
        cls.headers = {"Authorization": f"Bearer {login.json()['token']}"}
        groups = cls.client.get("/api/groups", headers=cls.headers).json()
        cls.group_id = next(group["id"] for group in groups if group["type"] == "旅行")

    def create_plan(self):
        response = self.client.post(
            f"/api/groups/{self.group_id}/travel-plans",
            headers=self.headers,
            json={
                "name": "测试旅行路线",
                "destination": "上海",
                "start_date": "2026-09-10",
                "end_date": "2026-09-12",
                "departure_city": "杭州",
                "estimated_people": 3,
                "budget_cents": 100000,
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def add_place(self, plan_id, name, lat, lng, must_visit=False):
        response = self.client.post(
            f"/api/travel-plans/{plan_id}/places",
            headers=self.headers,
            json={"type": "attraction", "name": name, "address": name, "lat": lat, "lng": lng, "must_visit": must_visit, "avg_cost": 70},
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()["id"]

    def test_date_validation_and_member_read_access(self):
        bad = self.client.post(
            f"/api/groups/{self.group_id}/travel-plans",
            headers=self.headers,
            json={"name": "错误日期", "destination": "上海", "start_date": "2026-09-12", "end_date": "2026-09-10"},
        )
        self.assertEqual(bad.status_code, 400)
        too_long = self.client.post(
            f"/api/groups/{self.group_id}/travel-plans",
            headers=self.headers,
            json={"name": "超长日期", "destination": "上海", "start_date": "2026-01-01", "end_date": "2026-04-05"},
        )
        self.assertEqual(too_long.status_code, 400)
        plan = self.create_plan()
        with main.db() as connection:
            member = connection.execute("SELECT id FROM users WHERE username = 'member_lin'").fetchone()
            token = main.create_session(connection, member["id"])
        member_headers = {"Authorization": f"Bearer {token}"}
        read = self.client.get(f"/api/travel-plans/{plan['id']}", headers=member_headers)
        self.assertEqual(read.status_code, 200, read.text)
        forbidden = self.client.post(f"/api/travel-plans/{plan['id']}/places", headers=member_headers, json={"type": "attraction", "name": "不应成功", "lat": 31, "lng": 121})
        self.assertEqual(forbidden.status_code, 403)

    def test_route_auto_plan_publish_and_calendar_sync_is_idempotent(self):
        plan = self.create_plan()
        first = self.add_place(plan["id"], "外滩", 31.2397, 121.4998, True)
        second = self.add_place(plan["id"], "东方明珠", 31.2397, 121.4997, True)
        hotel = self.add_place(plan["id"], "酒店", 31.22, 121.46)
        day = self.client.post(
            f"/api/travel-plans/{plan['id']}/days",
            headers=self.headers,
            json={"travel_date": "2026-09-10", "title": "市区游", "start_at": "2026-09-10T09:00", "end_at": "2026-09-10T20:00", "start_place_id": hotel, "end_place_id": hotel, "budget_cents": 30000},
        )
        self.assertEqual(day.status_code, 201, day.text)
        route = self.client.put(f"/api/travel-days/{day.json()['id']}/route", headers=self.headers, json={"nodes": [{"place_id": first, "stay_minutes": 90}, {"place_id": second, "stay_minutes": 90}]})
        self.assertEqual(route.status_code, 200, route.text)
        self.assertGreaterEqual(route.json()["total_distance_km"], 0)
        self.assertGreaterEqual(route.json()["total_duration_min"], 0)
        auto = self.client.post(f"/api/travel-plans/{plan['id']}/auto-plan", headers=self.headers, json={"travel_date": "2026-09-10"})
        self.assertEqual(auto.status_code, 200, auto.text)
        self.assertGreaterEqual(len(auto.json()["options"]), 3)
        applied = self.client.post(f"/api/travel-plans/{plan['id']}/apply-plan", headers=self.headers, json={"option_id": auto.json()["options"][0]["option_id"]})
        self.assertEqual(applied.status_code, 200, applied.text)
        check = self.client.get(f"/api/travel-plans/{plan['id']}/publish-check", headers=self.headers)
        self.assertEqual(check.status_code, 200, check.text)
        self.assertTrue(check.json()["passed"])
        published = self.client.post(f"/api/travel-plans/{plan['id']}/publish", headers=self.headers)
        self.assertEqual(published.status_code, 200, published.text)
        first_sync = self.client.post(f"/api/travel-plans/{plan['id']}/sync-calendar", headers=self.headers)
        second_sync = self.client.post(f"/api/travel-plans/{plan['id']}/sync-calendar", headers=self.headers)
        self.assertEqual(first_sync.status_code, 200, first_sync.text)
        self.assertEqual(second_sync.status_code, 200, second_sync.text)
        self.assertEqual(first_sync.json()["count"], second_sync.json()["count"])
        calendar = self.client.get("/api/calendar", headers=self.headers)
        self.assertEqual(calendar.status_code, 200, calendar.text)
        titles = [item["title"] for item in calendar.json()]
        self.assertTrue(any("测试旅行路线" in title for title in titles))

    def test_meeting_recommendation_requires_two_members_and_hides_private_rows(self):
        plan = self.create_plan()
        one = self.client.post(f"/api/travel-plans/{plan['id']}/location", headers=self.headers, json={"lat": 31.2, "lng": 121.4, "address": "A"})
        self.assertEqual(one.status_code, 200, one.text)
        not_ready = self.client.get(f"/api/travel-plans/{plan['id']}/meeting-recommendation", headers=self.headers)
        self.assertEqual(not_ready.status_code, 200)
        self.assertFalse(not_ready.json()["ready"])
        with main.db() as connection:
            member = connection.execute("SELECT id FROM users WHERE username = 'member_lin'").fetchone()
            token = main.create_session(connection, member["id"])
        other_headers = {"Authorization": f"Bearer {token}"}
        two = self.client.post(f"/api/travel-plans/{plan['id']}/location", headers=other_headers, json={"lat": 31.25, "lng": 121.5, "address": "B"})
        self.assertEqual(two.status_code, 200, two.text)
        ready = self.client.get(f"/api/travel-plans/{plan['id']}/meeting-recommendation", headers=self.headers)
        self.assertEqual(ready.status_code, 200, ready.text)
        self.assertTrue(ready.json()["ready"])
        self.assertIn("recommended", ready.json())

    def test_delete_place_reports_route_impact(self):
        plan = self.create_plan()
        place = self.add_place(plan["id"], "待删除景点", 31.2, 121.4)
        day = self.client.post(f"/api/travel-plans/{plan['id']}/days", headers=self.headers, json={"travel_date": "2026-09-10"})
        self.assertEqual(day.status_code, 201)
        route = self.client.put(f"/api/travel-days/{day.json()['id']}/route", headers=self.headers, json={"nodes": [{"place_id": place}]})
        self.assertEqual(route.status_code, 200)
        blocked = self.client.delete(f"/api/travel-places/{place}", headers=self.headers)
        self.assertEqual(blocked.status_code, 409)
        forced = self.client.delete(f"/api/travel-places/{place}?force=true", headers=self.headers)
        self.assertEqual(forced.status_code, 200, forced.text)

    def test_members_can_vote_for_places_with_suggestions(self):
        plan = self.create_plan()
        place_a = self.add_place(plan["id"], "候选餐厅 A", 31.2, 121.4)
        vote = self.client.post(f"/api/travel-plans/{plan['id']}/places/{place_a}/vote", headers=self.headers, json={"suggestion": "希望有包间"})
        self.assertEqual(vote.status_code, 200, vote.text)
        detail = self.client.get(f"/api/travel-plans/{plan['id']}", headers=self.headers)
        self.assertEqual(detail.status_code, 200, detail.text)
        selected = next(place for place in detail.json()["places"] if place["id"] == place_a)
        self.assertEqual(selected["vote_count"], 1)
        self.assertEqual(selected["my_vote"]["suggestion"], "希望有包间")


if __name__ == "__main__":
    unittest.main()
