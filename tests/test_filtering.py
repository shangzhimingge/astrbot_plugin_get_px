import sys
import unittest
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from astrbot_plugin_get_px.pixiv.filters import FiltersMixin
from astrbot_plugin_get_px.pixiv.index import ImageIndexStore
from astrbot_plugin_get_px.pixiv.safety import ContentSafetyPolicy


class FilteringTest(unittest.TestCase):
    def test_filter_manga_removes_manga_from_mixed_results(self):
        illusts = [
            {"id": "1", "type": "manga"},
            {"id": "2", "type": "illust"},
            {"id": "3", "type": "ugoira"},
        ]

        filtered = FiltersMixin._filter_manga(illusts)

        self.assertEqual([illust["id"] for illust in filtered], ["2", "3"])

    def test_safe_rating_only_keeps_general_audience(self):
        filtered = FiltersMixin._filter_safe_rating(
            [
                {"id": "1", "x_restrict": 0},
                {"id": "2", "x_restrict": 1},
                {"id": "3", "x_restrict": 2},
            ]
        )
        self.assertEqual([item["id"] for item in filtered], ["1"])


class SafetyFilteringTest(unittest.IsolatedAsyncioTestCase):
    async def test_all_four_switch_combinations_apply_independently(self):
        with tempfile.TemporaryDirectory() as tmp:
            mixin = object.__new__(FiltersMixin)
            mixin.image_index = ImageIndexStore(tmp)
            try:
                candidates = [
                    {"id": "safe", "x_restrict": 0, "title": "safe", "tags": []},
                    {"id": "rated", "x_restrict": 1, "title": "safe", "tags": []},
                    {"id": "builtin", "x_restrict": 0, "title": "guro", "tags": []},
                ]
                expected = {
                    (True, True): ["safe"],
                    (True, False): ["safe", "builtin"],
                    (False, True): ["safe", "rated"],
                    (False, False): ["safe", "rated", "builtin"],
                }
                for switches, ids in expected.items():
                    with self.subTest(switches=switches):
                        result = await mixin._filter_blacklisted_illusts(
                            candidates, ContentSafetyPolicy(*switches)
                        )
                        self.assertEqual([item["id"] for item in result], ids)
            finally:
                mixin.image_index.close()

    async def test_group_switches_do_not_disable_custom_terms_or_id_blacklist(self):
        with tempfile.TemporaryDirectory() as tmp:
            mixin = object.__new__(FiltersMixin)
            mixin.image_index = ImageIndexStore(tmp)
            try:
                await mixin.image_index.add_safety_term("customblocked", added_by="test")
                await mixin.image_index.add_blacklist_illust(illust_id="99")
                policy = ContentSafetyPolicy(
                    general_only_enabled=False,
                    builtin_terms_enabled=False,
                )
                self.assertFalse(await mixin._blocked_query_term("guro", policy))
                self.assertTrue(
                    await mixin._blocked_query_term("customblocked", policy)
                )
                filtered = await mixin._filter_blacklisted_illusts(
                    [
                        {"id": "1", "x_restrict": 1, "title": "guro", "tags": []},
                        {"id": "2", "x_restrict": 1, "title": "customblocked", "tags": []},
                        {"id": "99", "x_restrict": 0, "title": "safe", "tags": []},
                    ],
                    policy,
                )
                self.assertEqual([item["id"] for item in filtered], ["1"])
            finally:
                mixin.image_index.close()

    async def test_private_and_policy_read_failures_use_strict_defaults(self):
        class Event:
            def __init__(self, group_id):
                self.group_id = group_id

            def get_group_id(self):
                return self.group_id

        class BrokenStore:
            async def get_group_content_safety(self, group_id):
                raise OSError(group_id)

        mixin = object.__new__(FiltersMixin)
        mixin.checkin_store = BrokenStore()
        self.assertEqual(
            await mixin._content_safety_policy(Event("")),
            ContentSafetyPolicy(),
        )
        self.assertEqual(
            await mixin._content_safety_policy(Event("group-a")),
            ContentSafetyPolicy(),
        )

    async def test_builtin_and_custom_terms_filter_queries_and_works(self):
        with tempfile.TemporaryDirectory() as tmp:
            mixin = object.__new__(FiltersMixin)
            mixin.image_index = ImageIndexStore(tmp)
            try:
                self.assertTrue(await mixin._blocked_query_term("g u r o illustration"))
                await mixin.image_index.add_safety_term("危险主题", added_by="test")
                self.assertTrue(await mixin._blocked_query_term("危险-主题 壁纸"))
                filtered = await mixin._filter_blacklisted_illusts(
                    [
                        {"id": "1", "x_restrict": 0, "title": "safe", "tags": []},
                        {"id": "2", "x_restrict": 0, "title": "危险主题", "tags": []},
                        {"id": "3", "x_restrict": 1, "title": "safe", "tags": []},
                    ]
                )
                self.assertEqual([item["id"] for item in filtered], ["1"])
            finally:
                mixin.image_index.close()

    async def test_blacklist_store_failure_is_fail_closed(self):
        class BrokenIndex:
            async def get_custom_safety_terms(self):
                return set()

            async def get_blacklisted_illust_ids(self):
                raise OSError("database unavailable")

        mixin = object.__new__(FiltersMixin)
        mixin.image_index = BrokenIndex()
        with self.assertRaisesRegex(RuntimeError, "内容安全服务暂不可用"):
            await mixin._filter_blacklisted_illusts(
                [{"id": "1", "x_restrict": 0, "title": "safe", "tags": []}]
            )

    async def test_lolicon_page_id_is_blocked_by_pixiv_pid(self):
        with tempfile.TemporaryDirectory() as tmp:
            mixin = object.__new__(FiltersMixin)
            mixin.image_index = ImageIndexStore(tmp)
            try:
                await mixin.image_index.add_blacklist_illust(illust_id="123")

                filtered = await mixin._filter_blacklisted_illusts(
                    [
                        {
                            "id": "123:1",
                            "pid": "123",
                            "x_restrict": 0,
                            "title": "safe",
                            "tags": [],
                        }
                    ]
                )

                self.assertEqual(filtered, [])
            finally:
                mixin.image_index.close()


if __name__ == "__main__":
    unittest.main()
