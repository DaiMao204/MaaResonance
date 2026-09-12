Travel pickup recognition templates use the standard 1280 x 720 game layout.

The active pickup action now taps one fixed right-side point, (783, 416).
`cruise_hud_text*.png` are used in its runtime guard; cube detection/templates remain
available for offline diagnostics and are not prerequisites for tapping.

- `cube_small_*`: resized inner cube from the first ground-cargo reference (16 x 16).
- `cube_large_*`: resized inner cube from the second, nearer ground-cargo reference (30 x 30).
- `cruise_hud.png`: the first reference's cruise indicator (162 x 33).
- `cruise_hud_text.png`: its stable white-text crop (81 x 20), used to locate
  the full indicator before checking the original white-pixel brightness guards.
- `cruise_hud_text_1080.png`: text crop (81 x 20) from the 2026-09-11 feedback
  capture, whose glyph raster differs after the controller's 1920 x 1080 to
  1280 x 720 resize. Extracted at `(618,114,81,20)` from the normalized
  `2026.09.11-23.56.42.380_ManualTwoCityBusinessTravelInProgress.png` error frame.
  Its 46 text pixels with minimum BGR channel >=235 form a separate brightness
  sample set; do not apply the old full-indicator samples to this text crop.
  Both variants require score >=0.88, >=85% samples at brightness >=210,
  and median brightness >=225. The old variant is tried first.

The two balloon screenshots were held out from template generation. Their
markers match the shared inner cube despite different light pillars. Sizes
10 to 38 in steps of 2 are stored to avoid runtime image libraries; the detector
only searches sizes appropriate to each blue candidate's small ROI.

`maa_resonance/logic/travel_pickup.py` also checks the absolute brightness of
white HUD pixels: normalized correlation alone still matches a dimmed popup
background. Color candidates alone are never accepted as pickup targets.

Replay original PNG screenshots without game input:

    python tools/replay_travel_pickup.py --image screenshot.png --negative-checks
