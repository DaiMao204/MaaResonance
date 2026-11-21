from __future__ import annotations

import ctypes
import json
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import agent.utils.input_guard as input_guard
from agent.guarded_click_action import GuardedClickAction
from agent.utils.input_guard import (
    WIN32_BG_CLICK_DURATION_MS,
    clear_recorded_controller_info,
    get_effective_controller_info,
    is_win32_bg_controller_info,
    logical_point_to_client_point,
    pin_cursor_for_win32_click,
    record_controller_info,
    resolve_click_target_point,
    run_controller_click_guarded,
    safe_screencap,
    sleep_with_stop,
    wait_mouse_button_released,
)
from agent import clarity_recovery_action as cr


def _make_reco_detail(entries: list[dict[str, object]]):
    results = [
        SimpleNamespace(
            text=e["text"],
            box=e["box"],
            score=e.get("score", 0.99),
        )
        for e in entries
    ]
    return SimpleNamespace(hit=bool(results), all_results=results, filtered_results=results)


class InputGuardAndClarityRetryTest(unittest.TestCase):
    def test_wait_mouse_button_released_zero_delay_wait_stop_and_timeout(self) -> None:
        ctx = SimpleNamespace(tasker=SimpleNamespace(stopping=False))
        sleeps: list[float] = []

        # 1. Button already released -> zero wait
        ok = wait_mouse_button_released(
            ctx,
            is_button_down=lambda: False,
            sleep=sleeps.append,
        )
        self.assertTrue(ok)
        self.assertEqual(sleeps, [])

        # 2. Held for 2 polls then released -> waits and returns True
        states = iter([True, True, True, False])
        now = [0.0]

        def fake_sleep(dt: float) -> None:
            sleeps.append(dt)
            now[0] += dt

        ok = wait_mouse_button_released(
            ctx,
            max_wait_sec=1.0,
            poll_sec=0.05,
            is_button_down=lambda: next(states, False),
            clock=lambda: now[0],
            sleep=fake_sleep,
        )
        self.assertTrue(ok)
        self.assertEqual(sleeps, [0.05, 0.05])

        # 3. Stopping during wait -> aborts immediately returning False
        stop_ctx = SimpleNamespace(tasker=SimpleNamespace(stopping=False))
        polls = [0]

        def stop_on_second_sleep(dt: float) -> None:
            polls[0] += 1
            if polls[0] >= 1:
                stop_ctx.tasker.stopping = True

        self.assertFalse(
            wait_mouse_button_released(
                stop_ctx,
                max_wait_sec=1.0,
                poll_sec=0.05,
                is_button_down=lambda: True,
                clock=lambda: 0.0,
                sleep=stop_on_second_sleep,
            )
        )

        # 4. Timeout reached while still held -> unblocks returning True
        t_now = [0.0]
        self.assertTrue(
            wait_mouse_button_released(
                ctx,
                max_wait_sec=0.12,
                poll_sec=0.05,
                is_button_down=lambda: True,
                clock=lambda: t_now[0],
                sleep=lambda dt: t_now.__setitem__(0, t_now[0] + dt),
            )
        )
        self.assertGreaterEqual(t_now[0], 0.12)

    def test_wait_mouse_button_released_ignores_unconfigured_mock_stopping(self) -> None:
        self.assertTrue(wait_mouse_button_released(Mock(), is_button_down=lambda: False))
        self.assertFalse(
            wait_mouse_button_released(
                SimpleNamespace(tasker=SimpleNamespace(stopping=True)),
                is_button_down=lambda: False,
            )
        )

    def test_safe_screencap_and_sleep_handle_stopping_and_access_violation(self) -> None:
        # Stopping task -> returns None immediately without calling controller
        ctrl_stop = SimpleNamespace(
            post_screencap=lambda: self.fail("should not call post_screencap when stopping"),
            cached_image="img",
        )
        self.assertIsNone(safe_screencap(SimpleNamespace(tasker=SimpleNamespace(stopping=True, controller=ctrl_stop))))

        # Access violation OSError during controller teardown -> caught and returns None
        def _boom():
            raise OSError("exception: access violation reading 0xFFFFFFFFFFFFFFFF")

        ctrl_boom = SimpleNamespace(post_screencap=_boom, cached_image=None)
        self.assertIsNone(safe_screencap(SimpleNamespace(tasker=SimpleNamespace(stopping=False, controller=ctrl_boom))))

        # Normal capture
        ctrl_ok = SimpleNamespace(
            post_screencap=lambda: SimpleNamespace(wait=lambda: SimpleNamespace(succeeded=True)),
            cached_image="frame_ok",
        )
        self.assertEqual(
            safe_screencap(SimpleNamespace(tasker=SimpleNamespace(stopping=False, controller=ctrl_ok))),
            "frame_ok",
        )

        # sleep_with_stop stops promptly
        ctx = SimpleNamespace(tasker=SimpleNamespace(stopping=False))
        ticks = [0]

        def _tick(_dt: float) -> None:
            ticks[0] += 1
            if ticks[0] == 2:
                ctx.tasker.stopping = True

        self.assertFalse(sleep_with_stop(ctx, 1.0, step=0.1, sleep=_tick))
        self.assertEqual(ticks[0], 2)

    def _clarity_select_screen(self) -> list[dict[str, object]]:
        return [
            {"text": "澄明度", "box": [169, 321, 173, 65]},
            {"text": "19/290", "box": [165, 398, 187, 71]},
            {"text": "请选择恢复方式", "box": [349, 349, 191, 36]},
            {"text": "10", "box": [664, 627, 28, 16]},
            {"text": "仙人掌能量跳糖", "box": [793, 551, 121, 23]},
        ]

    def _clarity_confirm_popup(self) -> list[dict[str, object]]:
        return [
            {"text": "取消", "box": [324, 567, 50, 31]},
            {"text": "最少", "box": [364, 461, 48, 31]},
            {"text": "当前澄明度", "box": [453, 406, 85, 22]},
            {"text": "确认", "box": [958, 566, 52, 32]},
        ]

    def test_clarity_recover_retries_missed_confirm_without_double_counting(self) -> None:
        cr._CLARITY_USED_BY_TASK.clear()
        taps: list[tuple[str, tuple[int, int]]] = []
        screens = iter(
            [
                self._clarity_select_screen(),  # initial scan
                self._clarity_confirm_popup(),  # popup after tapping card
                self._clarity_confirm_popup(),  # after 1st confirm missed!
                [{"text": "已恢复", "box": [540, 320, 120, 35]}],  # after 2nd confirm succeeded!
                [{"text": "前往作战", "box": [940, 520, 120, 40]}],  # after closing notice
            ]
        )

        def fake_run_reco(node_name, image, override):
            return _make_reco_detail(next(screens))

        def fake_run_action(node_name, box, detail, override):
            target = override[node_name]["target"]
            taps.append((node_name, (int(target[0]), int(target[1]))))
            return SimpleNamespace(succeeded=True)

        ctx = SimpleNamespace(
            tasker=SimpleNamespace(
                stopping=False,
                controller=SimpleNamespace(
                    post_screencap=lambda: SimpleNamespace(wait=lambda: SimpleNamespace(succeeded=True)),
                    cached_image="dummy",
                ),
            ),
            run_recognition=fake_run_reco,
            run_action=fake_run_action,
        )
        argv = SimpleNamespace(
            node_name="TestClarity",
            custom_action_param=json.dumps({"candy_use_limit": 2}),
            task_detail=SimpleNamespace(task_id=9901),
        )

        with patch("agent.utils.input_guard.wait_mouse_button_released", return_value=True), patch(
            "agent.clarity_recovery_action.sleep_with_stop", return_value=True
        ):
            ok = cr.ClarityRecoveryAction().run(ctx, argv)

        self.assertTrue(ok)
        self.assertEqual(cr._CLARITY_USED_BY_TASK[9901].get("candy"), 1)
        confirm_taps = [name for name, _pt in taps if "Confirm" in name]
        self.assertEqual(len(confirm_taps), 2)

    def test_clarity_recover_aborts_and_cancels_after_3_missed_confirms(self) -> None:
        cr._CLARITY_USED_BY_TASK.clear()
        taps: list[tuple[str, tuple[int, int]]] = []
        screens = iter(
            [
                self._clarity_select_screen(),
                self._clarity_confirm_popup(),
                self._clarity_confirm_popup(),
                self._clarity_confirm_popup(),
                self._clarity_confirm_popup(),
            ]
        )

        def fake_run_reco(node_name, image, override):
            return _make_reco_detail(next(screens))

        def fake_run_action(node_name, box, detail, override):
            target = override[node_name]["target"]
            taps.append((node_name, (int(target[0]), int(target[1]))))
            return SimpleNamespace(succeeded=True)

        ctx = SimpleNamespace(
            tasker=SimpleNamespace(
                stopping=False,
                controller=SimpleNamespace(
                    post_screencap=lambda: SimpleNamespace(wait=lambda: SimpleNamespace(succeeded=True)),
                    cached_image="dummy",
                ),
            ),
            run_recognition=fake_run_reco,
            run_action=fake_run_action,
        )
        argv = SimpleNamespace(
            node_name="TestClarityFail",
            custom_action_param=json.dumps({"candy_use_limit": 2}),
            task_detail=SimpleNamespace(task_id=9902),
        )

        with patch("agent.utils.input_guard.wait_mouse_button_released", return_value=True), patch(
            "agent.clarity_recovery_action.sleep_with_stop", return_value=True
        ):
            ok = cr.ClarityRecoveryAction().run(ctx, argv)

        self.assertFalse(ok)
        self.assertEqual(cr._CLARITY_USED_BY_TASK[9902].get("candy", 0), 0)
        confirm_taps = [name for name, _pt in taps if "Confirm" in name]
        cancel_taps = [name for name, _pt in taps if "AbortCancel" in name]
        self.assertEqual(len(confirm_taps), 3)
        self.assertEqual(len(cancel_taps), 1)

    def test_win32_bg_controller_detection_and_cache(self) -> None:
        clear_recorded_controller_info()
        try:
            self.assertTrue(is_win32_bg_controller_info({"type": "win32", "mouse_method": 64}))
            self.assertTrue(is_win32_bg_controller_info({"type": "win32", "mouse_method": 256}))
            self.assertTrue(is_win32_bg_controller_info({"type": "win32", "mouse_method": 32}))
            self.assertTrue(is_win32_bg_controller_info({"type": "win32", "mouse_method": 128}))
            self.assertFalse(is_win32_bg_controller_info({"type": "win32", "mouse_method": 1}))
            self.assertFalse(is_win32_bg_controller_info({"type": "adb", "mouse_method": 64}))
            self.assertFalse(is_win32_bg_controller_info(None))

            # Fallback to controller.info when cache is empty
            ctx_cursor = SimpleNamespace(
                tasker=SimpleNamespace(controller=SimpleNamespace(info={"type": "win32", "mouse_method": 64}))
            )
            ctx_adb = SimpleNamespace(
                tasker=SimpleNamespace(controller=SimpleNamespace(info={"type": "adb", "mouse_method": 0}))
            )
            self.assertTrue(is_win32_bg_controller_info(get_effective_controller_info(ctx_cursor)))
            self.assertFalse(is_win32_bg_controller_info(get_effective_controller_info(ctx_adb)))
            self.assertFalse(is_win32_bg_controller_info(get_effective_controller_info(Mock())))

            # Recorded sink info takes precedence without calling controller.info
            record_controller_info({"type": "win32", "mouse_method": 256})
            self.assertTrue(is_win32_bg_controller_info(get_effective_controller_info(ctx_adb)))
            record_controller_info({"type": "adb"})
            self.assertFalse(is_win32_bg_controller_info(get_effective_controller_info(ctx_cursor)))
        finally:
            clear_recorded_controller_info()

    def test_resolve_click_target_point_and_guarded_click_action(self) -> None:
        self.assertEqual(resolve_click_target_point((100, 200, 40, 20), {}), (120, 210))
        self.assertEqual(resolve_click_target_point((100, 200, 40, 20), {"target": [640, 660]}), (640, 660))
        self.assertEqual(
            resolve_click_target_point((100, 200, 40, 20), {"target": [10, 20, 10, 10], "target_offset": [5, -5]}),
            (20, 20),
        )
        self.assertIsNone(resolve_click_target_point((0, 0, 0, 0), {}))

        recorded_actions: list[tuple[str, dict[str, object]]] = []

        def fake_run_action(node_name, box, detail, override):
            recorded_actions.append((node_name, override[node_name]))
            return SimpleNamespace(succeeded=True)

        def _make_ctx(info: dict[str, object]):
            return SimpleNamespace(
                tasker=SimpleNamespace(stopping=False, controller=SimpleNamespace(info=info)),
                run_action=fake_run_action,
            )

        ctx_cursor = _make_ctx({"type": "win32", "mouse_method": 64})
        ctx_window = _make_ctx({"type": "win32", "mouse_method": 256})
        ctx_seize = _make_ctx({"type": "win32", "mouse_method": 1})
        ctx_adb = _make_ctx({"type": "adb", "mouse_method": 0})
        argv = SimpleNamespace(
            node_name="DailyPrepEnterCombat",
            box=(940, 520, 120, 40),
            custom_action_param="{}",
        )
        clear_recorded_controller_info()
        try:
            with patch("agent.guarded_click_action.wait_mouse_button_released", return_value=True):
                # 1. Win32 background WithCursorPos -> LongPress(160ms)
                self.assertTrue(GuardedClickAction().run(ctx_cursor, argv))
                # 2. Win32 background WithWindowPos -> LongPress(160ms)
                self.assertTrue(GuardedClickAction().run(ctx_window, argv))
                # 3. Explicit custom_action_param duration override -> LongPress(220ms)
                argv_custom_dur = SimpleNamespace(
                    node_name="DailyPrepEnterCombat",
                    box=(940, 520, 120, 40),
                    custom_action_param=json.dumps({"duration": 220}),
                )
                self.assertTrue(GuardedClickAction().run(ctx_cursor, argv_custom_dur))
                # 4. Win32 foreground Seize & ADB -> plain Click without duration
                self.assertTrue(GuardedClickAction().run(ctx_seize, argv))
                self.assertTrue(GuardedClickAction().run(ctx_adb, argv))
        finally:
            clear_recorded_controller_info()

        self.assertEqual(len(recorded_actions), 5)
        for idx in (0, 1):
            tap_name, tap_def = recorded_actions[idx]
            self.assertEqual(tap_name, "DailyPrepEnterCombatGuardedTap")
            self.assertEqual(tap_def["action"], "LongPress")
            self.assertEqual(tap_def["duration"], WIN32_BG_CLICK_DURATION_MS)
            self.assertEqual(tap_def["target"], [1000, 540, 1, 1])
            self.assertEqual(tap_def["pre_delay"], 0)
            self.assertEqual(tap_def["post_delay"], 0)

        self.assertEqual(recorded_actions[2][1]["action"], "LongPress")
        self.assertEqual(recorded_actions[2][1]["duration"], 220)

        for idx in (3, 4):
            tap_name, tap_def = recorded_actions[idx]
            self.assertEqual(tap_name, "DailyPrepEnterCombatGuardedTap")
            self.assertEqual(tap_def["action"], "Click")
            self.assertNotIn("duration", tap_def)
            self.assertEqual(tap_def["target"], [1000, 540, 1, 1])
            self.assertEqual(tap_def["pre_delay"], 0)
            self.assertEqual(tap_def["post_delay"], 0)

        # MaaFramework passes maa.define.Rect(x, y, w, h) objects at runtime (not list/tuple).
        rect_obj = SimpleNamespace(x=1149, y=394, w=86, h=27)
        self.assertEqual(resolve_click_target_point(rect_obj, {}), (1192, 408))
        self.assertEqual(resolve_click_target_point({"x": 1149, "y": 394, "w": 86, "h": 27}, {}), (1192, 408))
        self.assertIsNone(resolve_click_target_point(SimpleNamespace(x=0, y=0, w=0, h=0), {}))
        try:
            from maa.define import Rect
        except ImportError:
            Rect = None
        if Rect is not None:
            rect_arg = Rect(1149, 394, 86, 27)
            self.assertEqual(resolve_click_target_point(rect_arg, {}), (1192, 408))
        else:
            rect_arg = rect_obj

        recorded_actions.clear()
        argv_rect = SimpleNamespace(
            node_name="DailyPrepLobbyClickTerminal",
            box=rect_arg,
            custom_action_param="null",
        )
        clear_recorded_controller_info()
        try:
            with patch("agent.guarded_click_action.wait_mouse_button_released", return_value=True):
                ok_rect = GuardedClickAction().run(ctx_cursor, argv_rect)
        finally:
            clear_recorded_controller_info()

        self.assertTrue(ok_rect)
        self.assertEqual(len(recorded_actions), 1)
        self.assertEqual(recorded_actions[0][0], "DailyPrepLobbyClickTerminalGuardedTap")
        self.assertEqual(recorded_actions[0][1]["action"], "LongPress")
        self.assertEqual(recorded_actions[0][1]["duration"], WIN32_BG_CLICK_DURATION_MS)
        self.assertEqual(recorded_actions[0][1]["target"], [1192, 408, 1, 1])

    def test_logical_point_to_client_point_scaling(self) -> None:
        self.assertEqual(logical_point_to_client_point(155, 675, 1920, 1080), (233, 1013))
        self.assertEqual(logical_point_to_client_point(1000, 540, 1920, 1080), (1500, 810))
        self.assertEqual(logical_point_to_client_point(640, 360, 2560, 1440), (1280, 720))
        self.assertEqual(logical_point_to_client_point(1280, 720, 1280, 720), (1279, 719))
        self.assertEqual(logical_point_to_client_point(-5, -10, 1920, 1080), (0, 0))
        self.assertIsNone(logical_point_to_client_point(100, 100, 0, 1080))
        self.assertIsNone(logical_point_to_client_point(100, 100, 1920, 0))

    @unittest.skipUnless(sys.platform == "win32", "Win32 cursor pinning requires Windows")
    def test_pin_cursor_for_win32_click_pin_hover_settle_and_restore(self) -> None:
        def _deref(ptr_or_ref):
            return ptr_or_ref._obj if hasattr(ptr_or_ref, "_obj") else ptr_or_ref.contents

        def _make_fake_user32(*, is_window_ret: int = 1, get_cursor_ret: int = 1, set_cursor_ret: int = 1):
            events: list[tuple[object, ...]] = []

            def _is_window(hwnd):
                return is_window_ret

            def _get_client_rect(hwnd, rect_ref):
                rect = _deref(rect_ref)
                rect.left = 0
                rect.top = 0
                rect.right = 1920
                rect.bottom = 1080
                return 1

            def _client_to_screen(hwnd, pt_ref):
                pt = _deref(pt_ref)
                pt.x += 100
                pt.y += 50
                return 1

            def _get_cursor_pos(pt_ref):
                if not get_cursor_ret:
                    return 0
                pt = _deref(pt_ref)
                pt.x = 30
                pt.y = 40
                return 1

            def _set_cursor_pos(x, y):
                if not set_cursor_ret:
                    return 0
                events.append(("set", int(x), int(y)))
                return 1

            def _set_dpi(ctx_arg):
                val = ctx_arg.value if hasattr(ctx_arg, "value") else ctx_arg
                events.append(("dpi", val))
                return 0x22

            fake = SimpleNamespace(
                IsWindow=_is_window,
                GetClientRect=_get_client_rect,
                ClientToScreen=_client_to_screen,
                GetCursorPos=_get_cursor_pos,
                SetCursorPos=_set_cursor_pos,
                SetThreadDpiAwarenessContext=_set_dpi,
            )
            return fake, events

        ctx = SimpleNamespace(tasker=SimpleNamespace(stopping=False))

        # 1. WithCursorPos + valid hwnd -> pins to screen (1600, 860), hovers, runs, settles, restores (30, 40) & DPI
        fake_u32, events = _make_fake_user32()
        with patch.object(input_guard, "_USER32", fake_u32, create=True):
            with pin_cursor_for_win32_click(
                ctx,
                {"type": "win32", "mouse_method": 64, "hwnd": 12345},
                1000,
                540,
                pre_hover_sec=0.045,
                post_up_settle_sec=0.075,
                sleep=lambda dt: events.append(("sleep", round(dt, 6))),
            ) as pinned:
                events.append(("body", pinned))

        self.assertEqual(events[0], ("dpi", ctypes.c_void_p(-4).value))
        self.assertEqual(events[1], ("set", 1600, 860))
        body_idx = events.index(("body", True))
        pre_sleeps = sum(e[1] for e in events[2:body_idx] if e[0] == "sleep")
        post_sleeps = sum(e[1] for e in events[body_idx + 1:-2] if e[0] == "sleep")
        self.assertAlmostEqual(pre_sleeps, 0.045, places=6)
        self.assertAlmostEqual(post_sleeps, 0.075, places=6)
        self.assertEqual(events[-2], ("set", 30, 40))
        self.assertEqual(events[-1], ("dpi", 0x22))

        # 2. Exception inside body -> still restores cursor & DPI context
        fake_u32, events = _make_fake_user32()
        with patch.object(input_guard, "_USER32", fake_u32, create=True):
            with self.assertRaises(RuntimeError):
                with pin_cursor_for_win32_click(
                    ctx,
                    {"type": "win32", "mouse_method": 64, "hwnd": 12345},
                    1000,
                    540,
                    sleep=lambda dt: events.append(("sleep", dt)),
                ):
                    raise RuntimeError("boom")
        self.assertEqual(events[-2], ("set", 30, 40))
        self.assertEqual(events[-1], ("dpi", 0x22))

        # 3. WithWindowPos, Seize, and ADB -> does not touch cursor, sleep, or DPI context
        fake_u32, events = _make_fake_user32()
        with patch.object(input_guard, "_USER32", fake_u32, create=True):
            for info in (
                {"type": "win32", "mouse_method": 256, "hwnd": 12345},
                {"type": "win32", "mouse_method": 1, "hwnd": 12345},
                {"type": "adb", "mouse_method": 0},
            ):
                with pin_cursor_for_win32_click(
                    ctx,
                    info,
                    1000,
                    540,
                    sleep=lambda dt: events.append(("sleep", dt)),
                ) as pinned:
                    self.assertFalse(pinned)
        self.assertEqual(events, [])

        # 4. GetCursorPos=0 or IsWindow=0 -> graceful fallback without SetCursorPos or exception
        for bad_kwargs in ({"get_cursor_ret": 0}, {"is_window_ret": 0}):
            fake_u32, events = _make_fake_user32(**bad_kwargs)
            with patch.object(input_guard, "_USER32", fake_u32, create=True):
                with pin_cursor_for_win32_click(
                    ctx,
                    {"type": "win32", "mouse_method": 64, "hwnd": 12345},
                    1000,
                    540,
                    sleep=lambda dt: events.append(("sleep", dt)),
                ) as pinned:
                    self.assertFalse(pinned)
            set_calls = [e for e in events if e[0] == "set"]
            self.assertEqual(set_calls, [])
            self.assertEqual(events, [("dpi", ctypes.c_void_p(-4).value), ("dpi", 0x22)])

    def test_run_controller_click_guarded_routes_by_controller_type(self) -> None:
        clear_recorded_controller_info()
        try:
            # 1. Win32 background with run_action -> routes through run_guarded_click (LongPress + lock/pin)
            bg_actions: list[tuple[str, dict[str, object]]] = []
            ctx_bg = SimpleNamespace(
                tasker=SimpleNamespace(
                    stopping=False,
                    controller=SimpleNamespace(
                        info={"type": "win32", "mouse_method": 256},
                        post_click=lambda *_a: self.fail("should use run_guarded_click on win32 bg"),
                    ),
                ),
                run_action=lambda name, _b, _d, ov: bg_actions.append((name, ov[name])) or SimpleNamespace(succeeded=True),
            )
            with patch("agent.utils.input_guard.wait_mouse_button_released", return_value=True):
                self.assertTrue(run_controller_click_guarded(ctx_bg, 640, 360, tap_node="TradeTestTap"))
            self.assertEqual(len(bg_actions), 1)
            self.assertEqual(bg_actions[0][0], "TradeTestTap")
            self.assertEqual(bg_actions[0][1]["action"], "LongPress")

            # 2. Win32 background WITHOUT run_action (e.g. SimpleNamespace test ctx) -> falls back to post_click
            clicked: list[tuple[int, int]] = []
            ctx_bg_no_run = SimpleNamespace(
                tasker=SimpleNamespace(
                    stopping=False,
                    controller=SimpleNamespace(
                        info={"type": "win32", "mouse_method": 64},
                        post_click=lambda x, y: clicked.append((x, y)) or SimpleNamespace(
                            wait=lambda: SimpleNamespace(succeeded=True)
                        ),
                    ),
                ),
            )
            with patch("agent.utils.input_guard.wait_mouse_button_released", return_value=True):
                self.assertTrue(run_controller_click_guarded(ctx_bg_no_run, 100, 200))
            self.assertEqual(clicked, [(100, 200)])

            # 3. ADB / Win32 foreground Seize -> calls controller.post_click directly
            for info in ({"type": "adb", "mouse_method": 0}, {"type": "win32", "mouse_method": 1}):
                clicked.clear()
                ctx_direct = SimpleNamespace(
                    tasker=SimpleNamespace(
                        stopping=False,
                        controller=SimpleNamespace(
                            info=info,
                            post_click=lambda x, y: clicked.append((x, y)) or SimpleNamespace(
                                wait=lambda: SimpleNamespace(succeeded=True)
                            ),
                        ),
                    ),
                    run_action=lambda *_a, **_kw: self.fail("should not use run_guarded_click on ADB/Seize"),
                )
                with patch("agent.utils.input_guard.wait_mouse_button_released", return_value=True):
                    self.assertTrue(run_controller_click_guarded(ctx_direct, 320, 240))
                self.assertEqual(clicked, [(320, 240)])
        finally:
            clear_recorded_controller_info()


if __name__ == "__main__":
    unittest.main()
