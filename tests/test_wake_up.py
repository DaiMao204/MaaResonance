from __future__ import annotations

from contextlib import contextmanager
import importlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np

from maa_resonance.logic.wake_up import (
    WAKEUP_NEWS_DISMISS_POINT,
    WAKEUP_POPUP_DISMISS_POINTS,
    WAKEUP_POPUP_SAFE_POINT,
    WAKEUP_TITLE_TAP_POINT,
    choose_wake_up_action,
    is_game_screen_entries,
    is_loading_screen,
    is_login_auth_blocker,
    is_news_announcement_popup,
    is_title_start_screen,
    parse_resource_download_mb,
)

ROOT = Path(__file__).resolve().parents[1]


@contextmanager
def _real_maa_resource():
    saved = {}
    maa_mod = sys.modules.get("maa")
    stashed = maa_mod is not None and not hasattr(maa_mod, "__path__")
    if stashed:
        for name in list(sys.modules):
            if name == "maa" or name.startswith("maa."):
                saved[name] = sys.modules.pop(name)
    try:
        try:
            resource_mod = importlib.import_module("maa.resource")
            yield resource_mod.Resource
        except ImportError:
            yield None
    finally:
        if stashed:
            for name in list(sys.modules):
                if name == "maa" or name.startswith("maa."):
                    sys.modules.pop(name, None)
            sys.modules.update(saved)


class WakeUpLogicTest(unittest.TestCase):
    def test_download_news_title_loading_and_auth_blockers(self) -> None:
        self.assertAlmostEqual(
            parse_resource_download_mb([{"text": "需要下载资源包（共26.44MB）"}]),
            26.44,
        )
        self.assertAlmostEqual(
            parse_resource_download_mb([{"text": "需要下载资源包（共1.5GB）"}]),
            1536.0,
        )
        self.assertEqual(
            choose_wake_up_action(
                [
                    {"text": "需要下载资源包（共26.44MB）"},
                    {"text": "确认", "box": [600, 490, 80, 30]},
                ]
            ),
            {"action": "confirm_download", "point": (640, 505), "size_mb": 26.44},
        )
        large = choose_wake_up_action([{"text": "需要下载资源包（共1.5GB）"}])
        self.assertEqual(large["action"], "stop_large_download")

        self.assertTrue(is_login_auth_blocker([{"text": "请输入验证码"}]))
        self.assertEqual(choose_wake_up_action([{"text": "手机号登录"}])["action"], "stop_auth")

        news = [{"text": "资讯"}, {"text": "公告"}, {"text": "触碰空白区域退出"}]
        self.assertTrue(is_news_announcement_popup(news))
        self.assertEqual(choose_wake_up_action(news)["point"], WAKEUP_NEWS_DISMISS_POINT)

        title = [{"text": "点击屏幕进入游戏", "box": [558, 547, 163, 23]}]
        self.assertTrue(is_title_start_screen(title))
        self.assertEqual(choose_wake_up_action(title)["point"], WAKEUP_TITLE_TAP_POINT)

        loading = [{"text": "89%"}]
        self.assertTrue(is_loading_screen(loading))
        self.assertTrue(is_game_screen_entries(loading))
        self.assertEqual(choose_wake_up_action(loading)["action"], "wait")

        self.assertEqual(WAKEUP_POPUP_SAFE_POINT, (640, 680))

        monthly_popup = [{"text": "月卡每日领取"}, {"text": "触碰空白区域退出"}]
        self.assertEqual(
            choose_wake_up_action(monthly_popup),
            {"action": "dismiss_popup", "point": WAKEUP_POPUP_SAFE_POINT},
        )

        checkin_popup = [{"text": "每日签到奖励"}, {"text": "触碰空白区域退出"}]
        self.assertEqual(
            [choose_wake_up_action(checkin_popup, dismiss_attempt=idx)["point"] for idx in range(4)],
            list(WAKEUP_POPUP_DISMISS_POINTS),
        )

        self.assertEqual(
            choose_wake_up_action([{"text": "未知活动大图"}], allow_blind_dismiss=True, unknown_streak=2)["action"],
            "blind_dismiss",
        )

    def test_wake_up_action_rotates_dismiss_points_on_consecutive_popups(self) -> None:
        with _real_maa_resource() as Resource:
            if Resource is None:
                self.skipTest("maafw is not installed")
            import agent.wake_up_action as wua

            img = np.zeros((720, 1280, 3), dtype=np.uint8)
            tapped: list[tuple[str, tuple[int, int]]] = []
            lobby_calls = {"count": 0}

            def fake_is_lobby(_ctx, name: str, _img) -> bool:
                if name.endswith("InitLobby"):
                    return False
                lobby_calls["count"] += 1
                # First two loop checks (L0, L1) see check-in popup; L2 + LVerify2 see lobby.
                return lobby_calls["count"] >= 3

            def fake_ocr(_ctx, _img, name: str, _roi):
                return [{"text": "每日签到奖励"}, {"text": "触碰空白区域退出"}]

            def fake_tap(_ctx, name: str, pt: tuple[int, int]) -> bool:
                tapped.append((name, pt))
                return True

            ctx = SimpleNamespace(tasker=SimpleNamespace(stopping=False), get_node_data=lambda _n: None)
            argv = SimpleNamespace(node_name="WakeUpStart", custom_action_param={})
            action = wua.WakeUpToLobbyAction()
            with (
                patch.object(wua, "safe_screencap", return_value=img),
                patch.object(wua, "is_drawer", return_value=(False, [])),
                patch.object(wua, "is_lobby", side_effect=fake_is_lobby),
                patch.object(wua, "ocr_roi", side_effect=fake_ocr),
                patch.object(wua, "tap_point", side_effect=fake_tap),
                patch.object(wua, "_is_adb_controller", return_value=False),
                patch.object(wua, "sleep_with_stop", return_value=True),
            ):
                res = action.run(ctx, argv)

            self.assertTrue(getattr(res, "success", True))
            self.assertEqual(
                tapped,
                [
                    ("WakeUpStartAct0_dismiss_popup", (640, 680)),
                    ("WakeUpStartAct1_dismiss_popup", (200, 660)),
                ],
            )

    def test_pipeline_loads_and_no_native_click_swipe(self) -> None:
        pipeline = json.loads((ROOT / "assets/resource/base/pipeline/daily/wake_up.json").read_text(encoding="utf-8"))
        for node_name, node in pipeline.items():
            act = node.get("action")
            act_type = act.get("type") if isinstance(act, dict) else act
            self.assertNotIn(act_type, ("Click", "Swipe"), msg=node_name)

        with _real_maa_resource() as Resource:
            if Resource is None:
                self.skipTest("maafw is not installed")
            res = Resource()
            self.assertTrue(res.post_bundle(ROOT / "assets" / "resource" / "base").wait().succeeded)
            for node_name in pipeline:
                self.assertIsNotNone(res.get_node_data(node_name), msg=f"Missing node: {node_name}")


if __name__ == "__main__":
    unittest.main()
