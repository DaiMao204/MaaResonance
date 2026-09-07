from __future__ import annotations

import unittest

from maa_resonance.logic.navigation_runtime import run_navigation_transition


class FakeClock:
    def __init__(self):
        self.now = 0.0
        self.sleeps = []

    def __call__(self):
        return self.now

    def sleep(self, duration):
        self.sleeps.append(duration)
        self.now += duration

    def advance(self, duration):
        self.now += duration


class NavigationRuntimeTest(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.clicked = []

    def run_transition(self, observe, **kwargs):
        def click(point):
            self.clicked.append((self.clock(), point))
            return True

        options = {
            "observe": observe, "click": click, "should_stop": lambda: False,
            "clock": self.clock, "sleep": self.clock.sleep,
        }
        options.update(kwargs)
        return run_navigation_transition(**options)

    def test_nine_second_loading_does_not_spend_click_budget(self):
        def observe():
            if self.clock() < 9:
                return {"state": "loading", "point": (960, 323)}
            return {"state": "ready"} if self.clicked else {"state": "source", "point": (960, 323)}

        result = self.run_transition(observe, max_clicks=1)
        self.assertTrue(result["ok"])
        self.assertEqual(result["reason"], "ready")
        self.assertEqual(result["clicks"], 1)
        self.assertGreaterEqual(self.clicked[0][0], 9)
        self.assertGreaterEqual(result["loading_observations"], 20)

    def test_ineffective_first_click_retries_only_after_completed_input_interval(self):
        starts, completed = [], []

        def click(point):
            starts.append(self.clock())
            self.clock.advance(0.7)
            completed.append(self.clock())
            return True

        def observe():
            return {"state": "ready"} if len(starts) == 2 else {"state": "source", "point": (960, 323)}

        result = self.run_transition(observe, click=click)
        self.assertTrue(result["ok"])
        self.assertEqual(result["clicks"], 2)
        self.assertGreaterEqual(starts[1] - completed[0], 2.0)

    def test_persistent_source_has_bounded_clicks_and_last_attempt_grace(self):
        result = self.run_transition(lambda: {"state": "source", "point": (960, 323)})
        self.assertEqual(result["reason"], "click_limit")
        self.assertEqual(len(self.clicked), 3)
        self.assertEqual(result["clicks"], 3)
        self.assertGreaterEqual(self.clock() - self.clicked[-1][0], 2.0)

    def test_source_disappearing_after_click_never_reuses_the_old_point(self):
        result = self.run_transition(
            lambda: {"state": "unknown", "point": (960, 323)} if self.clicked
            else {"state": "source", "point": (960, 323)}, timeout=4,
        )
        self.assertEqual(result["reason"], "timeout")
        self.assertEqual(len(self.clicked), 1)

    def test_retry_uses_latest_source_point(self):
        def observe():
            if len(self.clicked) == 2:
                return {"state": "ready"}
            return {"state": "source", "point": (100, 200) if not self.clicked else (300, 400)}

        result = self.run_transition(observe)
        self.assertTrue(result["ok"])
        self.assertEqual([p for _, p in self.clicked], [(100, 200), (300, 400)])

    def test_loading_with_target_point_never_clicks(self):
        result = self.run_transition(lambda: {"state": "loading", "point": (960, 323)}, timeout=1)
        self.assertEqual(result["reason"], "timeout")
        self.assertEqual(self.clicked, [])
        self.assertEqual(result["click_attempts"], 0)

    def test_loading_after_final_click_can_complete_after_retry_interval(self):
        def observe():
            if not self.clicked:
                return {"state": "source", "point": (960, 323)}
            return {"state": "loading"} if self.clock() < 5 else {"state": "ready"}

        result = self.run_transition(observe, max_clicks=1)
        self.assertTrue(result["ok"])
        self.assertEqual(result["clicks"], 1)
        self.assertGreaterEqual(self.clock(), 5)

    def test_unknown_after_final_click_waits_for_ready_instead_of_click_limit(self):
        def observe():
            if not self.clicked:
                return {"state": "source", "point": (960, 323)}
            return {"state": "unknown"} if self.clock() < 3 else {"state": "ready"}

        result = self.run_transition(observe, max_clicks=1)
        self.assertTrue(result["ok"])
        self.assertEqual(result["clicks"], 1)

    def test_observe_consuming_deadline_prevents_click_or_late_success(self):
        for state in ("source", "ready"):
            with self.subTest(state=state):
                self.setUp()
                def observe():
                    self.clock.advance(2)
                    return {"state": state, "point": (960, 323)}
                result = self.run_transition(observe, timeout=1)
                self.assertEqual(result["reason"], "timeout")
                self.assertEqual(result["observations"], 1)
                self.assertEqual(self.clicked, [])

    def test_click_crossing_deadline_is_counted_but_never_retried(self):
        def click(point):
            self.clicked.append((self.clock(), point))
            self.clock.advance(2)
            return True

        result = self.run_transition(lambda: {"state": "source", "point": (960, 323)}, click=click, timeout=1)
        self.assertEqual(result["reason"], "timeout")
        self.assertEqual(result["clicks"], 1)
        self.assertEqual(result["observations"], 1)

    def test_stop_before_observation_sends_no_input(self):
        result = self.run_transition(lambda: self.fail("must not observe"), should_stop=lambda: True)
        self.assertEqual(result["reason"], "stopped")
        self.assertEqual(result["observations"], 0)
        self.assertEqual(self.clicked, [])

    def test_stop_during_observation_sends_no_input(self):
        stop = False
        def observe():
            nonlocal stop
            stop = True
            return {"state": "source", "point": (960, 323)}
        result = self.run_transition(observe, should_stop=lambda: stop)
        self.assertEqual(result["reason"], "stopped")
        self.assertEqual(self.clicked, [])

    def test_stop_during_wait_does_not_observe_or_click_again(self):
        result = self.run_transition(
            lambda: {"state": "source", "point": (960, 323)},
            should_stop=lambda: self.clock() >= 0.2, poll_interval=3,
        )
        self.assertEqual(result["reason"], "stopped")
        self.assertEqual(result["observations"], 1)
        self.assertEqual(len(self.clicked), 1)
        self.assertLessEqual(self.clock(), 0.3)

    def test_observation_error_is_explicit_and_has_no_input(self):
        def observe():
            raise RuntimeError("capture failed")
        result = self.run_transition(observe)
        self.assertEqual(result["reason"], "observe_error")
        self.assertIn("capture failed", result["error"])
        self.assertEqual(self.clicked, [])

    def test_click_exception_is_explicit_and_never_retried(self):
        def click(point):
            raise RuntimeError("input failed")
        result = self.run_transition(lambda: {"state": "source", "point": (960, 323)}, click=click)
        self.assertEqual(result["reason"], "click_error")
        self.assertEqual(result["click_attempts"], 1)
        self.assertEqual(result["clicks"], 0)
        self.assertEqual(result["observations"], 1)

    def test_failed_click_is_explicit_and_never_retried(self):
        result = self.run_transition(lambda: {"state": "source", "point": (960, 323)}, click=lambda p: False)
        self.assertEqual(result["reason"], "click_failed")
        self.assertFalse(result["ok"])
        self.assertEqual(result["click_attempts"], 1)
        self.assertEqual(result["clicks"], 0)

    def test_stop_check_error_fails_closed(self):
        def should_stop():
            raise RuntimeError("stop state unavailable")
        result = self.run_transition(lambda: self.fail("must not observe"), should_stop=should_stop)
        self.assertEqual(result["reason"], "stop_check_error")
        self.assertEqual(self.clicked, [])

    def test_ready_does_not_require_or_spend_click_budget(self):
        result = self.run_transition(lambda: {"state": "ready"}, max_clicks=0)
        self.assertTrue(result["ok"])
        self.assertEqual(result["observations"], 1)
        self.assertEqual(self.clicked, [])

    def test_invalid_observation_or_source_point_never_clicks(self):
        for observation, reason in [
            (None, "invalid_observation"), ({"state": "typo"}, "invalid_observation"),
            ({"state": "source"}, "invalid_source_point"),
            ({"state": "source", "point": (float("nan"), 3)}, "invalid_source_point"),
            ({"state": "source", "point": (-1, 3)}, "invalid_source_point"),
        ]:
            with self.subTest(observation=observation):
                result = self.run_transition(lambda: observation)
                self.assertEqual(result["reason"], reason)
                self.assertEqual(self.clicked, [])


if __name__ == "__main__":
    unittest.main()
