from __future__ import annotations

import unittest

from maa_resonance.logic.travel_pickup_runtime import (
    MAX_BURST_CLICKS, MAX_PICKUP_CLICKS, MAX_PICKUP_FRAMES,
    PICKUP_TAP_POINTS, run_pickup_window,
)


class FakeClock:
    def __init__(self):
        self.now = 0.0
        self.sleeps = []

    def __call__(self):
        return self.now

    def sleep(self, delay):
        self.sleeps.append(delay)
        self.now += delay

    def advance(self, delay):
        self.now += delay


class FakeImage(list):
    shape = (720, 1280, 3)


class FakeJob:
    def __init__(self, image=None, *, succeeded=True, on_wait=None):
        self.image = FakeImage(image) if isinstance(image, list) else image
        self.succeeded = succeeded
        self.on_wait = on_wait

    def wait(self):
        if self.on_wait:
            self.on_wait()
        return self

    def get(self):
        return self.image


class FakeController:
    def __init__(self, captures, *, click_succeeded=True, on_click_wait=None, clock=None):
        self.captures = iter(captures)
        self.click_succeeded = click_succeeded
        self.on_click_wait = on_click_wait
        self.clock = clock
        self.capture_count = 0
        self.clicks = []
        self.click_frames = []
        self.click_started_at = []
        self.click_completed_at = []

    @property
    def cached_image(self):
        raise AssertionError("pickup must never read cached_image")

    def post_screencap(self):
        self.capture_count += 1
        return next(self.captures)

    def post_click(self, x, y):
        self.clicks.append((x, y))
        self.click_frames.append(self.capture_count)
        if self.clock is not None:
            self.click_started_at.append(self.clock())
        def wait_for_input():
            if self.on_click_wait:
                self.on_click_wait()
            if self.clock is not None:
                self.click_completed_at.append(self.clock())

        return FakeJob(succeeded=self.click_succeeded, on_wait=wait_for_input)


class ReleaseController(FakeController):
    def __init__(self, captures, *, release_job, **kwargs):
        super().__init__(captures, **kwargs)
        self.release_job = release_job
        self.released_contacts = []

    def post_touch_up(self, contact):
        self.released_contacts.append(contact)
        return self.release_job


class TravelPickupRuntimeTest(unittest.TestCase):
    def run_window(self, controller, **kwargs):
        self.clock = kwargs.pop("clock", FakeClock())
        self.records = []
        options = {
            "is_travel_hud": lambda image: True,
            "should_stop": lambda: False,
            "on_click": self.records.append,
            "clock": self.clock,
            "sleep": self.clock.sleep,
        }
        options.update(kwargs)
        return run_pickup_window(controller, **options)

    def test_one_fresh_hud_allows_repeated_clicks_at_one_point_without_target_detection(self):
        seen = []
        controller = FakeController([FakeJob(["frame one"])])
        result = self.run_window(
            controller, is_travel_hud=lambda image: seen.append(image[0]) or True,
            should_stop=lambda: len(controller.clicks) == 3,
        )
        self.assertEqual(seen, ["frame one"])
        self.assertEqual(controller.clicks, [PICKUP_TAP_POINTS[0]] * 3)
        self.assertEqual(controller.capture_count, 1)
        self.assertEqual(result["tap_count"], 3)
        self.assertEqual(result["reason"], "stopped")
        self.assertEqual(result["next_point_index"], 0)
        self.assertEqual([r["point_index"] for r in self.records], [0, 0, 0])
        self.assertEqual([r["next_point_index"] for r in self.records], [0, 0, 0])
        self.assertEqual([r["target"] for r in self.records], [list(PICKUP_TAP_POINTS[0])] * 3)

    def test_burst_limit_requires_new_capture_and_hud_before_more_clicks(self):
        seen = []
        controller = FakeController([FakeJob([1]), FakeJob([2])])
        result = self.run_window(
            controller, tap_interval=0,
            is_travel_hud=lambda image: seen.append(image[0]) or True,
            should_stop=lambda: len(controller.clicks) == MAX_BURST_CLICKS + 1,
        )
        self.assertEqual(seen, [1, 2])
        self.assertEqual(controller.click_frames, [1] * MAX_BURST_CLICKS + [2])
        self.assertEqual(result["frames"], 2)

    def test_hud_disappearing_between_bursts_stops_all_further_clicks(self):
        controller = FakeController([FakeJob([True]), FakeJob([False]), FakeJob([False])])
        result = self.run_window(controller, tap_interval=0, is_travel_hud=lambda image: image[0])
        self.assertEqual(result["reason"], "travel_hud_lost")
        self.assertEqual(len(controller.clicks), MAX_BURST_CLICKS)
        self.assertEqual(result["tap_count"], MAX_BURST_CLICKS)
        self.assertEqual(controller.capture_count, 3)
        self.assertEqual(result["hud_misses"], 2)

    def test_transient_hud_miss_rechecks_a_fresh_frame_without_tapping_the_missed_frame(self):
        clock = FakeClock()
        controller = FakeController([
            FakeJob([True]), FakeJob([False]), FakeJob([True]),
        ], clock=clock)
        result = self.run_window(
            controller, clock=clock, is_travel_hud=lambda image: image[0],
            should_stop=lambda: len(controller.clicks) == 5,
        )
        self.assertEqual(result["reason"], "stopped")
        self.assertEqual(result["hud_misses"], 1)
        self.assertEqual(controller.click_frames, [1, 1, 1, 3, 3])
        self.assertEqual(controller.clicks, [(783, 416)] * 5)
        for previous_up, next_down in zip(controller.click_completed_at, controller.click_started_at[1:]):
            self.assertGreaterEqual(next_down - previous_up, 0.08 - 1e-9)

    def test_failed_hud_recheck_capture_never_reuses_the_previous_valid_hud(self):
        controller = FakeController([FakeJob([False]), FakeJob([True], succeeded=False)])
        result = self.run_window(controller, is_travel_hud=lambda image: image[0])
        self.assertEqual(result["reason"], "screencap_failed")
        self.assertEqual(controller.clicks, [])

    def test_successful_recheck_resets_the_consecutive_miss_count(self):
        controller = FakeController([FakeJob([visible]) for visible in (False, True, False, True)])
        result = self.run_window(
            controller, hud_interval=0, is_travel_hud=lambda image: image[0],
            should_stop=lambda: len(controller.clicks) == 2,
        )
        self.assertEqual(result["reason"], "stopped")
        self.assertEqual(result["hud_misses"], 2)
        self.assertEqual(controller.click_frames, [2, 4])

    def test_stop_after_hud_miss_prevents_even_the_confirmation_capture(self):
        stop = {"value": False}
        def recognize(_image):
            stop["value"] = True
            return False
        controller = FakeController([FakeJob([])])
        result = self.run_window(controller, is_travel_hud=recognize, should_stop=lambda: stop["value"])
        self.assertEqual(result["reason"], "stopped")
        self.assertEqual(controller.capture_count, 1)
        self.assertEqual(controller.clicks, [])

    def test_hud_interval_forces_refresh_before_next_tap(self):
        controller = FakeController([FakeJob([]), FakeJob([])])
        result = self.run_window(
            controller, tap_interval=0.05, hud_interval=0.12,
            should_stop=lambda: len(controller.clicks) == 4,
        )
        self.assertEqual(result["reason"], "stopped")
        self.assertEqual(controller.click_frames, [1, 1, 2, 2])
        self.assertTrue(all(record["frame_age_ms"] < 120 for record in self.records))

    def test_maximum_hud_age_forces_refresh_even_with_long_hud_interval(self):
        controller = FakeController([FakeJob([]) for _ in range(4)])
        result = self.run_window(
            controller, tap_interval=0.05, hud_interval=0.3, max_hud_age=0.06,
            should_stop=lambda: len(controller.clicks) == 3,
        )
        self.assertEqual(result["reason"], "stopped")
        self.assertEqual(result["tap_count"], 3)
        self.assertGreaterEqual(controller.capture_count, 2)
        self.assertTrue(all(record["frame_age_ms"] <= 60 for record in self.records))

    def test_capture_failure_never_reads_cache_or_clicks(self):
        controller = FakeController([FakeJob([], succeeded=False)])
        result = self.run_window(controller)
        self.assertEqual(result["reason"], "screencap_failed")
        self.assertEqual(controller.clicks, [])
        self.assertEqual(self.records, [])

    def test_capture_failure_after_burst_does_not_reuse_previous_hud(self):
        controller = FakeController([FakeJob([]), FakeJob([], succeeded=False)])
        result = self.run_window(controller, tap_interval=0)
        self.assertEqual(result["reason"], "screencap_failed")
        self.assertEqual(len(controller.clicks), MAX_BURST_CLICKS)
        self.assertEqual(result["tap_count"], MAX_BURST_CLICKS)

    def test_capture_without_image_stops_without_click(self):
        result = self.run_window(FakeController([FakeJob(None)]))
        self.assertEqual(result["reason"], "no_image")
        self.assertEqual(result["tap_count"], 0)

    def test_stop_before_capture_and_after_hud_prevents_click(self):
        controller = FakeController([])
        result = self.run_window(controller, should_stop=lambda: True)
        self.assertEqual(result["reason"], "stopped")
        self.assertEqual(controller.capture_count, 0)
        stop = {"value": False}

        def recognize(_image):
            stop["value"] = True
            return True

        controller = FakeController([FakeJob([])])
        result = self.run_window(controller, is_travel_hud=recognize, should_stop=lambda: stop["value"])
        self.assertEqual(result["reason"], "stopped")
        self.assertEqual(controller.clicks, [])

    def test_stop_after_one_click_interrupts_burst_without_extra_tap_or_delay(self):
        controller = FakeController([FakeJob([])])
        result = self.run_window(controller, should_stop=lambda: bool(controller.clicks))
        self.assertEqual(result["reason"], "stopped")
        self.assertEqual(len(controller.clicks), 1)
        self.assertEqual(controller.capture_count, 1)
        self.assertEqual(len(self.clock.sleeps), 1)
        self.assertAlmostEqual(self.clock.sleeps[0], 0.08)

    def test_stop_during_tap_wait_prevents_the_next_click(self):
        for allowed_clicks in (0, 1):
            with self.subTest(allowed_clicks=allowed_clicks):
                clock = FakeClock()
                stop = {"value": False}
                controller = FakeController([FakeJob([])])

                def pause(delay):
                    clock.sleep(delay)
                    if len(controller.clicks) >= allowed_clicks:
                        stop["value"] = True

                result = self.run_window(controller, clock=clock, sleep=pause,
                                         should_stop=lambda: stop["value"])
                self.assertEqual(result["reason"], "stopped")
                self.assertEqual(result["tap_count"], allowed_clicks)
                self.assertEqual(len(controller.clicks), allowed_clicks)

    def test_delayed_capture_below_max_age_allows_one_tap_then_refreshes(self):
        clock = FakeClock()
        controller = FakeController([
            FakeJob([], on_wait=lambda: clock.advance(0.3)),
            FakeJob([], on_wait=lambda: clock.advance(0.3)),
        ])
        result = self.run_window(
            controller, clock=clock, hud_interval=0.25, max_hud_age=0.6,
            should_stop=lambda: len(controller.clicks) == 2,
        )
        self.assertEqual(result["reason"], "stopped")
        self.assertEqual(controller.click_frames, [1, 2])
        self.assertEqual(result["tap_count"], 2)
        self.assertTrue(all(abs(r["frame_age_ms"] - 300) < 0.01 for r in self.records))

    def test_delayed_hud_check_below_max_age_also_allows_one_tap(self):
        clock = FakeClock()

        def recognize(_image):
            clock.advance(0.3)
            return True

        controller = FakeController([FakeJob([]), FakeJob([])])
        result = self.run_window(
            controller, clock=clock, is_travel_hud=recognize,
            should_stop=lambda: len(controller.clicks) == 2,
        )
        self.assertEqual(result["tap_count"], 2)
        self.assertEqual(controller.click_frames, [1, 2])

    def test_new_capture_older_than_max_age_stops_without_cached_fallback(self):
        clock = FakeClock()
        controller = FakeController([FakeJob([], on_wait=lambda: clock.advance(0.7)), FakeJob([])])
        result = self.run_window(controller, clock=clock)
        self.assertEqual(result["reason"], "stale_hud")
        self.assertEqual(controller.clicks, [])
        self.assertEqual(result["stale_frames"], 1)
        self.assertEqual(controller.capture_count, 1)

    def test_failed_click_does_not_record_success_or_advance_phase(self):
        controller = FakeController([FakeJob([])], click_succeeded=False)
        result = self.run_window(controller, start_index=3)
        self.assertEqual(result["reason"], "click_failed")
        self.assertEqual(result["tap_count"], 0)
        self.assertEqual(result["click_attempts"], 1)
        self.assertEqual(result["next_point_index"], 0)
        self.assertEqual(self.records, [])

    def test_failure_after_success_keeps_only_acknowledged_count_and_phase(self):
        controller = FakeController([FakeJob([])])
        controller.on_click_wait = lambda: setattr(controller, "click_succeeded", False)
        result = self.run_window(controller)
        self.assertEqual(result["reason"], "click_failed")
        self.assertEqual(result["tap_count"], 1)
        self.assertEqual(result["click_attempts"], 2)
        self.assertEqual(result["next_point_index"], 0)
        self.assertEqual(len(self.records), 1)

    def test_failed_click_waits_for_cleanup_release_and_never_retries_down(self):
        released = {"complete": False}
        controller = ReleaseController(
            [FakeJob([])], click_succeeded=False,
            release_job=FakeJob(on_wait=lambda: released.update(complete=True)),
        )
        result = self.run_window(controller)
        self.assertEqual(result["reason"], "click_failed")
        self.assertTrue(result["cleanup_release_attempted"])
        self.assertTrue(result["cleanup_release_succeeded"])
        self.assertTrue(released["complete"])
        self.assertEqual(controller.released_contacts, [0])
        self.assertEqual(len(controller.clicks), 1)
        self.assertEqual(result["tap_count"], 0)
        self.assertEqual(self.records, [])

    def test_click_exception_preserves_failure_when_cleanup_is_rejected_or_raises(self):
        def interrupted_press():
            raise RuntimeError("press interrupted")

        def interrupted_release():
            raise RuntimeError("release interrupted")

        for release_job in (FakeJob(succeeded=False), FakeJob(on_wait=interrupted_release)):
            with self.subTest(release_raises=release_job.on_wait is not None):
                controller = ReleaseController(
                    [FakeJob([])], on_click_wait=interrupted_press, release_job=release_job,
                )
                result = self.run_window(controller)
                self.assertEqual(result["reason"], "click_error")
                self.assertIn("press interrupted", result["error"])
                self.assertFalse(result["cleanup_release_succeeded"])
                self.assertEqual(controller.released_contacts, [0])
                self.assertEqual(len(controller.clicks), 1)
                self.assertEqual(result["tap_count"], 0)
                self.assertEqual(self.records, [])

    def test_successful_native_click_does_not_send_a_redundant_cleanup_release(self):
        controller = ReleaseController([FakeJob([])], release_job=FakeJob())
        result = self.run_window(controller, should_stop=lambda: bool(controller.clicks))
        self.assertEqual(result["tap_count"], 1)
        self.assertEqual(controller.released_contacts, [])
        self.assertFalse(result.get("cleanup_release_attempted", False))

    def test_click_record_has_capture_age_and_actual_input_duration(self):
        clock = FakeClock()
        controller = FakeController(
            [FakeJob([], on_wait=lambda: clock.advance(0.02))],
            on_click_wait=lambda: clock.advance(0.03),
        )
        result = self.run_window(controller, clock=clock, should_stop=lambda: bool(controller.clicks))
        self.assertAlmostEqual(self.records[0]["frame_age_ms"], 80)
        self.assertAlmostEqual(self.records[0]["click_duration_ms"], 30)
        self.assertAlmostEqual(result["click_ms"], 30)

    def test_native_click_completion_is_followed_by_full_release_gap_at_same_point(self):
        for input_duration in (0.051, 0.2):
            with self.subTest(input_duration=input_duration):
                clock = FakeClock()
                controller = FakeController(
                    [FakeJob([]) for _ in range(4)], clock=clock,
                    on_click_wait=lambda: clock.advance(input_duration),
                )
                result = self.run_window(
                    controller, clock=clock, should_stop=lambda: len(controller.clicks) == 3,
                )
                self.assertEqual(result["tap_count"], 3)
                self.assertEqual(controller.clicks, [PICKUP_TAP_POINTS[0]] * 3)
                self.assertAlmostEqual(controller.click_started_at[0], 0.08)
                for previous_up, next_down in zip(controller.click_completed_at, controller.click_started_at[1:]):
                    self.assertGreaterEqual(next_down - previous_up, 0.08 - 1e-9)
                self.assertGreaterEqual(sum(clock.sleeps), 0.24 - 1e-9)

    def test_capture_and_hud_time_can_satisfy_initial_release_gap(self):
        for capture_duration in (0, 0.03, 0.12):
            with self.subTest(capture_duration=capture_duration):
                clock = FakeClock()
                controller = FakeController(
                    [FakeJob([], on_wait=lambda: clock.advance(capture_duration))], clock=clock,
                )

                def recognize(_image):
                    clock.advance(0.02)
                    return True

                self.run_window(controller, clock=clock, is_travel_hud=recognize,
                                should_stop=lambda: bool(controller.clicks))
                self.assertEqual(len(controller.click_started_at), 1)
                self.assertAlmostEqual(controller.click_started_at[0], max(0.08, capture_duration + 0.02))

    def test_adjacent_windows_on_same_controller_preserve_release_gap(self):
        clock = FakeClock()
        controller = FakeController(
            [FakeJob([]), FakeJob([])], clock=clock, on_click_wait=lambda: clock.advance(0.051),
        )
        first = self.run_window(controller, clock=clock, should_stop=lambda: len(controller.clicks) == 1)
        second = self.run_window(
            controller, clock=clock, start_index=first["next_point_index"],
            should_stop=lambda: len(controller.clicks) == 2,
        )
        self.assertEqual(first["tap_count"], 1)
        self.assertEqual(second["tap_count"], 1)
        self.assertEqual(controller.clicks, [PICKUP_TAP_POINTS[0]] * 2)
        self.assertGreaterEqual(controller.click_started_at[1] - controller.click_completed_at[0], 0.08 - 1e-9)

    def test_click_overrunning_deadline_does_not_compress_next_window_release_gap(self):
        clock = FakeClock()
        controller = FakeController(
            [FakeJob([]), FakeJob([])], clock=clock, on_click_wait=lambda: clock.advance(0.2),
        )
        first = self.run_window(controller, clock=clock, duration=0.1)
        self.assertEqual(first["reason"], "duration_elapsed")
        self.assertEqual(first["tap_count"], 1)
        self.assertGreater(controller.click_completed_at[0], 0.1)
        second = self.run_window(
            controller, clock=clock, start_index=first["next_point_index"],
            should_stop=lambda: len(controller.clicks) == 2,
        )
        self.assertEqual(second["tap_count"], 1)
        self.assertGreaterEqual(controller.click_started_at[1] - controller.click_completed_at[0], 0.08 - 1e-9)

    def test_window_deadline_prevents_click_after_slow_hud_check(self):
        clock = FakeClock()

        def recognize(_image):
            clock.advance(0.3)
            return True

        controller = FakeController([FakeJob([])])
        result = self.run_window(controller, clock=clock, duration=0.2, is_travel_hud=recognize)
        self.assertEqual(result["reason"], "duration_elapsed")
        self.assertEqual(controller.clicks, [])

    def test_tap_wait_is_clipped_to_window_deadline(self):
        controller = FakeController([FakeJob([])])
        result = self.run_window(controller, duration=0.12, tap_interval=0.05)
        self.assertEqual(result["reason"], "duration_elapsed")
        self.assertEqual(result["tap_count"], 2)
        self.assertAlmostEqual(self.clock.now, 0.12)
        self.assertAlmostEqual(self.clock.sleeps[-1], 0.02)

    def test_click_limit_bounds_instantaneous_inputs_when_clock_does_not_advance(self):
        controller = FakeController([FakeJob([]) for _ in range(MAX_PICKUP_FRAMES)])
        result = self.run_window(controller, tap_interval=0)
        self.assertEqual(result["reason"], "click_limit")
        self.assertEqual(result["tap_count"], MAX_PICKUP_CLICKS)
        self.assertEqual(result["click_attempts"], MAX_PICKUP_CLICKS)
        self.assertEqual(len(controller.clicks), MAX_PICKUP_CLICKS)
        self.assertEqual(controller.capture_count, MAX_PICKUP_CLICKS // MAX_BURST_CLICKS)

    def test_frame_limit_independently_bounds_zero_interval_hud_refreshes(self):
        controller = FakeController([FakeJob([]) for _ in range(MAX_PICKUP_FRAMES)])
        result = self.run_window(controller, tap_interval=0, hud_interval=0)
        self.assertEqual(result["reason"], "frame_limit")
        self.assertEqual(result["frames"], MAX_PICKUP_FRAMES)
        self.assertEqual(len(controller.clicks), MAX_PICKUP_FRAMES)
        self.assertEqual(controller.click_frames, list(range(1, MAX_PICKUP_FRAMES + 1)))

    def test_legacy_cursor_and_window_boundaries_never_change_pickup_coordinate(self):
        for legacy_index in (*range(8), -1, 1_000_000):
            with self.subTest(legacy_index=legacy_index):
                clock = FakeClock()
                controller = FakeController(
                    [FakeJob([]) for _ in range(8)], clock=clock,
                    on_click_wait=lambda: clock.advance(0.051),
                )
                first = self.run_window(
                    controller, clock=clock, start_index=legacy_index,
                    should_stop=lambda: len(controller.clicks) == 5,
                )
                second = self.run_window(
                    controller, clock=clock, start_index=first["next_point_index"],
                    should_stop=lambda: len(controller.clicks) == 10,
                )
                self.assertEqual(first["tap_count"], 5)
                self.assertEqual(second["tap_count"], 5)
                self.assertEqual(first["next_point_index"], 0)
                self.assertEqual(second["next_point_index"], 0)
                # Pin the actual input contract, not a copy of the point table:
                # no jitter, sweep or switch after refreshing the HUD/window.
                self.assertEqual(controller.clicks, [(783, 416)] * 10)
                self.assertGreater(controller.capture_count, 2)
                for previous_up, next_down in zip(controller.click_completed_at, controller.click_started_at[1:]):
                    self.assertGreaterEqual(next_down - previous_up, 0.08 - 1e-9)

    def test_nonstandard_or_unknown_image_bounds_prevent_hud_check_and_click(self):
        def recognize(_image):
            raise AssertionError("fixed coordinates must not be used on another layout")

        for shape in ((720, 1279, 3), (720, 1281, 3), (1080, 1920, 3), None):
            with self.subTest(shape=shape):
                image = type("Image", (), {"shape": shape})()
                controller = FakeController([FakeJob(image)])
                result = self.run_window(controller, is_travel_hud=recognize)
                self.assertEqual(result["reason"], "invalid_image")
                self.assertEqual(controller.clicks, [])
                self.assertEqual(result["tap_count"], 0)


if __name__ == "__main__":
    unittest.main()
