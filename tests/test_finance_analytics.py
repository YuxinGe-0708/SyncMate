import json
import os
import tempfile
import unittest
from pathlib import Path


TEST_DIR = tempfile.TemporaryDirectory(prefix="syncmate-finance-")
os.environ["SYNCMATE_DB_PATH"] = str(Path(TEST_DIR.name) / "syncmate-test.db")

from fastapi.testclient import TestClient

from backend import main


class FinanceAnalyticsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        main.initialize_database()
        cls.client = TestClient(main.app)
        login = cls.client.post("/api/auth/login", json={"username": "demo", "password": "123456"})
        assert login.status_code == 200, login.text
        cls.headers = {"Authorization": f"Bearer {login.json()['token']}"}
        with main.db() as connection:
            cls.user_id = connection.execute("SELECT id FROM users WHERE username = 'demo'").fetchone()["id"]
            group_rows = connection.execute(
                "SELECT id FROM groups_table WHERE owner_id = ? ORDER BY id LIMIT 2", (cls.user_id,)
            ).fetchall()
            cls.group_a, cls.group_b = (row["id"] for row in group_rows)
            cls.current_located = cls._add_expense(
                connection, cls.group_a, "商户 A", 10_000, "2026-09-03",
                {"餐饮": 7_000, "交通": 3_000}, 31.2304, 121.4737,
            )
            cls.previous_located = cls._add_expense(
                connection, cls.group_a, "商户 A", 5_000, "2026-08-13",
                {"餐饮": 5_000}, 31.2305, 121.4738,
            )
            cls.current_unlocated = cls._add_expense(
                connection, cls.group_b, "商户 B", 20_000, "2026-09-18",
                {"交通": 20_000}, None, None,
            )

    @classmethod
    def _add_expense(cls, connection, group_id, merchant, amount, spent_at, breakdown, lat, lng):
        result = {
            "bill": {"title": merchant, "total_cents": amount, "category": max(breakdown, key=breakdown.get)},
            "transfers": [],
        }
        cursor = connection.execute(
            """INSERT INTO ai_bills(group_id, creator_id, title, instruction, result_json, status)
            VALUES (?, ?, ?, 'test', ?, 'active')""",
            (group_id, cls.user_id, merchant, json.dumps(result, ensure_ascii=False)),
        )
        bill_id = cursor.lastrowid
        expense = connection.execute(
            """INSERT INTO expense_records(
                bill_id, group_id, receipt_index, merchant_name, category, category_breakdown,
                amount_cents, spent_at, location_name, address, lat, lng
            ) VALUES (?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                bill_id, group_id, merchant, max(breakdown, key=breakdown.get),
                json.dumps(breakdown, ensure_ascii=False), amount, spent_at,
                merchant if lat is not None else None, "测试地址" if lat is not None else "", lat, lng,
            ),
        )
        return expense.lastrowid

    def setUp(self):
        with main.db() as connection:
            connection.execute(
                """UPDATE expense_records SET location_name = NULL, address = '', lat = NULL, lng = NULL
                WHERE id = ?""", (self.current_unlocated,),
            )

    def analytics(self, **params):
        response = self.client.get("/api/finance/analytics", params={"month": "2026-09", **params}, headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_totals_heatmaps_ranking_and_comparison_are_consistent(self):
        data = self.analytics()
        self.assertEqual(data["summary"]["current_total_cents"], 30_000)
        self.assertEqual(data["summary"]["previous_total_cents"], 5_000)
        self.assertEqual(data["summary"]["change_percent"], 500.0)
        self.assertEqual(data["summary"]["expense_count"], 2)
        self.assertEqual(data["summary"]["located_count"], 1)
        self.assertEqual(data["summary"]["coverage_percent"], 50.0)
        self.assertEqual(sum(row["current_cents"] for row in data["group_heatmap"]), 30_000)
        self.assertEqual(sum(row["total_cents"] for row in data["category_heatmap"]), 30_000)
        self.assertEqual(data["merchant_ranking"][0]["merchant"], "商户 B")
        self.assertEqual(len(data["points"]["current"]), 1)
        self.assertEqual(len(data["points"]["previous"]), 1)
        self.assertEqual(len(data["area_comparison"]), 1)
        self.assertEqual(data["unlocated"][0]["expense_id"], self.current_unlocated)

    def test_group_and_category_filters_use_the_same_amount_basis(self):
        group = self.analytics(group_id=self.group_a)
        self.assertEqual(group["summary"]["current_total_cents"], 10_000)
        self.assertEqual(group["summary"]["previous_total_cents"], 5_000)
        dining = self.analytics(category="餐饮")
        self.assertEqual(dining["summary"]["current_total_cents"], 7_000)
        self.assertEqual(dining["summary"]["previous_total_cents"], 5_000)
        self.assertEqual(dining["points"]["current"][0]["amount_cents"], 7_000)
        self.assertEqual(sum(row["total_cents"] for row in dining["category_heatmap"]), 7_000)

    def test_location_update_refreshes_map_coverage(self):
        response = self.client.patch(
            f"/api/finance/expenses/{self.current_unlocated}/location",
            headers=self.headers,
            json={"name": "人民广场", "address": "测试路 1 号", "lat": 31.232, "lng": 121.475},
        )
        self.assertEqual(response.status_code, 200, response.text)
        data = self.analytics()
        self.assertEqual(data["summary"]["located_count"], 2)
        self.assertEqual(data["summary"]["coverage_percent"], 100.0)
        self.assertFalse(data["unlocated"])

    def test_invalid_month_and_inaccessible_group_are_rejected(self):
        invalid = self.client.get("/api/finance/analytics", params={"month": "2026-13"}, headers=self.headers)
        self.assertEqual(invalid.status_code, 422)
        forbidden = self.client.get("/api/finance/analytics", params={"month": "2026-09", "group_id": 999999}, headers=self.headers)
        self.assertEqual(forbidden.status_code, 403)

    def test_receipt_normalization_preserves_bill_total(self):
        result = {
            "bill": {
                "title": "多小票", "total_cents": 10_001, "category": "餐饮", "bill_date": "2026-09-01",
                "receipts": [
                    {"receipt_index": 1, "merchant": "甲", "total_cents": 5_000},
                    {"receipt_index": 2, "merchant": "乙", "total_cents": 5_000},
                ],
            }
        }
        rows = main.expense_rows_from_result(result, "多小票", "2026-09-01")
        self.assertEqual(sum(row["amount_cents"] for row in rows), 10_001)


if __name__ == "__main__":
    unittest.main()
