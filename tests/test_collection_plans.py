import os
import tempfile
import unittest
from pathlib import Path


if "backend.main" not in __import__("sys").modules:
    os.environ["SYNCMATE_DB_PATH"] = str(Path(tempfile.mkdtemp(prefix="syncmate-collections-")) / "collections.db")

from fastapi.testclient import TestClient

from backend import main


class CollectionPlanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        main.initialize_database()
        cls.client = TestClient(main.app)
        cls.owner_headers = cls.login("demo", "123456")
        with main.db() as connection:
            cls.owner_id = connection.execute("SELECT id FROM users WHERE username = 'demo'").fetchone()["id"]
            cls.member_a = connection.execute("SELECT id FROM users WHERE username = 'member_lin'").fetchone()["id"]
            cls.member_b = connection.execute("SELECT id FROM users WHERE username = 'member_zhou'").fetchone()["id"]
            cls.member_a_headers = {"Authorization": f"Bearer {main.create_session(connection, cls.member_a)}"}
            cls.member_b_headers = {"Authorization": f"Bearer {main.create_session(connection, cls.member_b)}"}

    @classmethod
    def login(cls, username, password):
        response = cls.client.post("/api/auth/login", json={"username": username, "password": password})
        assert response.status_code == 200, response.text
        return {"Authorization": f"Bearer {response.json()['token']}"}

    def make_group(self):
        suffix = abs(hash(self.id())) % 100000
        response = self.client.post(
            "/api/groups", headers=self.owner_headers,
            json={"name": f"收款测试群 {suffix}", "type": "好友"},
        )
        self.assertEqual(response.status_code, 201, response.text)
        group_id = response.json()["id"]
        with main.db() as connection:
            connection.execute(
                "INSERT INTO memberships(group_id, user_id, role) VALUES (?, ?, 'member')",
                (group_id, self.member_a),
            )
            connection.execute(
                "INSERT INTO memberships(group_id, user_id, role) VALUES (?, ?, 'member')",
                (group_id, self.member_b),
            )
            activity = connection.execute(
                """INSERT INTO activities(group_id, creator_id, title, mode, status, start_at, end_at)
                VALUES (?, ?, '测试活动', 'fixed', 'published', '2026-09-10T10:00', '2026-09-10T12:00')""",
                (group_id, self.owner_id),
            )
        return group_id, activity.lastrowid

    def create_plan(self, group_id, title="九月共同支出"):
        response = self.client.post(
            f"/api/groups/{group_id}/collection-plans", headers=self.owner_headers,
            json={"title": title, "description": "成员分别提交垫付款"},
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def submit(self, plan_id, headers, **overrides):
        payload = {
            "activity_name": "测试活动", "title": "共同消费", "paid_cents": 1000,
            "split_mode": "all", "participant_ids": [], "ratios": {},
        }
        payload.update(overrides)
        response = self.client.post(f"/api/collection-plans/{plan_id}/entries", headers=headers, json=payload)
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def review_all(self, plan, decision="approved"):
        result = plan
        for entry in list(plan["entries"]):
            response = self.client.post(
                f"/api/collection-entries/{entry['id']}/review", headers=self.owner_headers,
                json={"decision": decision, "note": "核对无误"},
            )
            self.assertEqual(response.status_code, 200, response.text)
            result = response.json()
        return result

    def test_four_split_modes_minimum_cash_flow_and_double_confirmation(self):
        group_id, activity_id = self.make_group()
        plan = self.create_plan(group_id)
        plan = self.submit(
            plan["id"], self.owner_headers, activity_id=activity_id, activity_name="",
            title="群主请客", paid_cents=1000, split_mode="host",
        )
        plan = self.submit(
            plan["id"], self.member_a_headers, title="全员饮料", paid_cents=1001, split_mode="all",
        )
        plan = self.submit(
            plan["id"], self.member_b_headers, title="两人门票", paid_cents=901,
            split_mode="subset", participant_ids=[self.owner_id, self.member_b],
        )
        plan = self.submit(
            plan["id"], self.member_a_headers, title="按比例租车", paid_cents=1000,
            split_mode="ratio", ratios={str(self.owner_id): 1, str(self.member_a): 2, str(self.member_b): 1},
        )
        self.assertEqual(sum(entry["paid_cents"] for entry in plan["entries"]), 3902)
        for entry in plan["entries"]:
            self.assertEqual(sum(item["amount_cents"] for item in entry["participants"]), entry["paid_cents"])
        plan = self.review_all(plan)
        settled = self.client.post(
            f"/api/collection-plans/{plan['id']}/settle", headers=self.owner_headers,
        )
        self.assertEqual(settled.status_code, 200, settled.text)
        result = settled.json()
        self.assertEqual(result["status"], "settled")
        balances = {item["user_id"]: item["balance_cents"] for item in result["member_summaries"]}
        self.assertEqual(balances, {self.owner_id: -1035, self.member_a: 1167, self.member_b: -132})
        self.assertEqual(len(result["transfers"]), 2)
        self.assertEqual(sum(item["amount_cents"] for item in result["transfers"]), 1167)

        wrong = self.client.post(
            f"/api/collection-transfers/{result['transfers'][0]['id']}/confirm-payment",
            headers=self.member_a_headers,
        )
        self.assertEqual(wrong.status_code, 403)
        for transfer in result["transfers"]:
            payer_headers = self.owner_headers if transfer["from_user_id"] == self.owner_id else self.member_b_headers
            paid = self.client.post(
                f"/api/collection-transfers/{transfer['id']}/confirm-payment", headers=payer_headers,
            )
            self.assertEqual(paid.status_code, 200, paid.text)
            received = self.client.post(
                f"/api/collection-transfers/{transfer['id']}/confirm-receipt", headers=self.member_a_headers,
            )
            self.assertEqual(received.status_code, 200, received.text)
            result = received.json()
        self.assertEqual(result["status"], "completed")
        archived = self.client.post(
            f"/api/collection-plans/{plan['id']}/archive", headers=self.owner_headers,
        )
        self.assertEqual(archived.status_code, 200, archived.text)
        self.assertEqual(archived.json()["status"], "archived")

    def test_minimum_cash_flow_avoids_greedy_extra_edge(self):
        transfers = main.minimum_collection_transfers({1: -800, 2: -800, 3: -700, 4: 800, 5: 1500})
        self.assertEqual(len(transfers), 3)
        self.assertEqual(sum(item["amount_cents"] for item in transfers), 2300)

    def test_permissions_validation_and_settle_excludes_pending_entries(self):
        group_id, _ = self.make_group()
        forbidden_plan = self.client.post(
            f"/api/groups/{group_id}/collection-plans", headers=self.member_a_headers,
            json={"title": "无权创建", "description": ""},
        )
        self.assertEqual(forbidden_plan.status_code, 403)
        plan = self.create_plan(group_id, "随时结算测试")
        invalid_subset = self.client.post(
            f"/api/collection-plans/{plan['id']}/entries", headers=self.member_a_headers,
            json={
                "activity_name": "测试活动", "title": "无参与人", "paid_cents": 100,
                "split_mode": "subset", "participant_ids": [], "ratios": {},
            },
        )
        self.assertEqual(invalid_subset.status_code, 400)
        blank_ratio = self.client.post(
            f"/api/collection-plans/{plan['id']}/entries", headers=self.member_a_headers,
            json={
                "activity_name": "测试活动", "title": "比例部分留空", "paid_cents": 101,
                "split_mode": "ratio", "participant_ids": [],
                "ratios": {str(self.owner_id): "1", str(self.member_a): "", str(self.member_b): "0"},
            },
        )
        self.assertEqual(blank_ratio.status_code, 201, blank_ratio.text)
        blank_entry = next(item for item in blank_ratio.json()["entries"] if item["title"] == "比例部分留空")
        self.assertEqual(sum(item["amount_cents"] for item in blank_entry["participants"]), 101)
        plan = self.submit(plan["id"], self.owner_headers, title="已审核款项", paid_cents=600, split_mode="all")
        approved_entry = plan["entries"][0]
        approved = self.client.post(
            f"/api/collection-entries/{approved_entry['id']}/review", headers=self.owner_headers,
            json={"decision": "approved", "note": ""},
        )
        self.assertEqual(approved.status_code, 200, approved.text)
        plan = self.submit(plan["id"], self.member_a_headers, title="来不及审核", paid_cents=300, split_mode="all")
        pending_entry = next(item for item in plan["entries"] if item["title"] == "来不及审核")
        forbidden_review = self.client.post(
            f"/api/collection-entries/{pending_entry['id']}/review", headers=self.member_a_headers,
            json={"decision": "approved", "note": ""},
        )
        self.assertEqual(forbidden_review.status_code, 403)
        settled = self.client.post(f"/api/collection-plans/{plan['id']}/settle", headers=self.owner_headers)
        self.assertEqual(settled.status_code, 200, settled.text)
        result = settled.json()
        excluded = next(item for item in result["entries"] if item["id"] == pending_entry["id"])
        self.assertEqual(excluded["status"], "rejected")
        self.assertIn("未计入", excluded["review_note"])
        self.assertEqual(result["totals"]["approved_cents"], 600)
        self.assertEqual(sum(abs(item["balance_cents"]) for item in result["member_summaries"]), 800)

        ai_records = self.client.get(f"/api/groups/{group_id}/ai-bills", headers=self.owner_headers)
        self.assertEqual(ai_records.status_code, 200, ai_records.text)
        self.assertEqual(ai_records.json(), [])


if __name__ == "__main__":
    unittest.main()
