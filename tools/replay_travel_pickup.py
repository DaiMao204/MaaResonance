"""Offline pickup replay using MaaFramework's real recognition context.

Example (from the repository root):
    python tools/replay_travel_pickup.py --image screenshot.png --negative-checks

Only a synthetic controller is created. It cannot send keyboard/mouse/touch
input. PNG decoding uses the standard library; cv2/Pillow are not required.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import struct
import sys
import tempfile
import time
import zlib

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from maa.buffer import ImageBuffer
from maa.controller import CustomController
from maa.custom_action import CustomAction
from maa.resource import Resource
from maa.tasker import Tasker
from maa_resonance.logic.travel_pickup import find_pickup_targets, is_travel_hud


def read_png(path: Path) -> np.ndarray:
    """Read non-interlaced 8-bit RGB/RGBA PNG into a BGR ndarray."""
    data = path.read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"Expected a PNG screenshot: {path}")
    offset, compressed = 8, bytearray()
    width = height = channels = 0
    while offset < len(data):
        length = struct.unpack_from(">I", data, offset)[0]
        kind = data[offset + 4:offset + 8]
        payload = data[offset + 8:offset + 8 + length]
        if kind == b"IHDR":
            width, height, depth, color, _, _, interlace = struct.unpack(">IIBBBBB", payload)
            if depth != 8 or color not in (2, 6) or interlace:
                raise ValueError("Use a non-interlaced 8-bit RGB/RGBA PNG screenshot")
            channels = 3 if color == 2 else 4
        elif kind == b"IDAT":
            compressed.extend(payload)
        elif kind == b"IEND":
            break
        offset += length + 12
    raw = zlib.decompress(compressed)
    stride = width * channels
    if not width or not height or len(raw) != height * (stride + 1):
        raise ValueError("Invalid PNG image data size")
    rows = np.empty((height, stride), dtype=np.uint8)
    previous = np.zeros(stride, dtype=np.uint8)
    for y in range(height):
        start = y * (stride + 1)
        mode = raw[start]
        row = np.frombuffer(raw[start + 1:start + 1 + stride], dtype=np.uint8).copy()
        if mode == 1:
            for channel in range(channels):
                row[channel::channels] = np.cumsum(row[channel::channels], dtype=np.uint64) % 256
        elif mode == 2:
            row = (row.astype(np.uint16) + previous).astype(np.uint8)
        elif mode in (3, 4):
            for x in range(stride):
                left = int(row[x - channels]) if x >= channels else 0
                up = int(previous[x])
                upper_left = int(previous[x - channels]) if x >= channels else 0
                if mode == 3:
                    prediction = (left + up) // 2
                else:
                    p = left + up - upper_left
                    dl, du, dul = abs(p - left), abs(p - up), abs(p - upper_left)
                    prediction = left if dl <= du and dl <= dul else up if du <= dul else upper_left
                row[x] = (int(row[x]) + prediction) & 255
        elif mode != 0:
            raise ValueError(f"Unsupported PNG filter {mode}")
        rows[y] = previous = row
    return np.ascontiguousarray(rows.reshape(height, width, channels)[:, :, :3][:, :, ::-1])


class OfflineController(CustomController):
    """An in-memory controller with no connection to any app/device."""

    def __init__(self):
        super().__init__()
        self.frame = np.zeros((720, 1280, 3), dtype=np.uint8)

    def connect(self):
        return True

    def request_uuid(self):
        return "pickup-offline-no-input"

    def get_features(self):
        return 0

    def screencap(self):
        return self.frame

    def click(self, x, y):
        raise RuntimeError("Offline replay must never request input")

    def touch_down(self, contact, x, y, pressure):
        raise RuntimeError("Offline replay must never request input")


class Replay(CustomAction):
    def __init__(self, controller: OfflineController):
        super().__init__()
        self.controller = controller
        self.results = []

    def run(self, context, argv):
        started = time.perf_counter()
        hud = is_travel_hud(context, self.controller.frame)
        hud_end = time.perf_counter()
        targets = find_pickup_targets(context, self.controller.frame) if hud else []
        ended = time.perf_counter()
        self.results.append({"hud": hud, "targets": targets,
                             "hud_ms": round((hud_end - started) * 1000, 2),
                             "total_ms": round((ended - started) * 1000, 2)})
        return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", action="append", type=Path, required=True)
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--negative-checks", action="store_true",
                        help="Also reject dimmed/missing HUD and frames with detected icons erased")
    args = parser.parse_args()
    if args.repeat < 1:
        parser.error("--repeat must be at least 1")
    # The native logger can retain its log handle until process shutdown on
    # Windows; cleanup must not turn a successful replay into a false failure.
    with tempfile.TemporaryDirectory(prefix="maa-pickup-offline-", ignore_cleanup_errors=True) as directory:
        scratch = Path(directory)
        bundle = scratch / "bundle"
        (bundle / "pipeline").mkdir(parents=True)
        (bundle / "pipeline" / "replay.json").write_text(json.dumps({
            "OfflinePickupReplay": {"recognition": "DirectHit", "action": "Custom",
                                    "custom_action": "OfflinePickupReplay", "pre_delay": 0,
                                    "post_delay": 0}
        }), encoding="utf-8")
        Tasker.set_log_dir(scratch / "logs")
        Tasker.set_save_draw(False)
        controller = OfflineController()
        if not controller.post_connection().wait().succeeded:
            raise RuntimeError("Could not initialize synthetic controller")
        resource = Resource()
        if not resource.post_bundle(bundle).wait().succeeded:
            raise RuntimeError("Could not load offline bundle")
        image_root = ROOT / "assets/resource/base/image"
        for template in (image_root / "business/travel_pickup").glob("*.png"):
            if not resource.override_image(template.relative_to(image_root).as_posix(), read_png(template)):
                raise RuntimeError(f"Could not register template {template}")
        replay = Replay(controller)
        resource.register_custom_action("OfflinePickupReplay", replay)
        tasker = Tasker()
        if not tasker.bind(resource, controller) or not tasker.inited:
            raise RuntimeError("Could not initialize offline recognition")

        def recognize(frame: np.ndarray) -> dict:
            controller.frame = frame
            if not tasker.post_task("OfflinePickupReplay").wait().succeeded:
                raise RuntimeError("Offline recognition failed")
            return replay.results[-1]

        failed = False
        for path in args.image:
            image = read_png(path)
            original_shape = image.shape
            buffer = ImageBuffer()
            buffer.set(image)
            # Match the game's short-edge 720 convention; unknown aspect ratios
            # remain unknown and the detector rejects them instead of stretching.
            buffer.resize(0, 720)
            frame = buffer.get()
            runs = [recognize(frame) for _ in range(args.repeat)]
            report = {"image": str(path), "original_shape": original_shape,
                      "frame_shape": frame.shape, "runs": runs}
            if args.negative_checks:
                dimmed = recognize((frame.astype(np.float32) * 0.65).astype(np.uint8))
                missing_hud = frame.copy()
                missing_hud[100:148, 550:735] = 0
                no_hud = recognize(missing_hud)
                erased = frame.copy()
                for target in runs[-1]["targets"]:
                    x, y, width, height = target["box"]
                    padding = max(width, height)
                    x1, y1 = max(0, x - padding), max(0, y - padding)
                    x2, y2 = min(1280, x + width + padding), min(720, y + height + padding)
                    erased[y1:y2, x1:x2] = 0
                removed = recognize(erased)
                report["negative"] = {"dimmed": dimmed, "hud_erased": no_hud, "icons_erased": removed}
                failed |= dimmed["hud"] or no_hud["hud"] or bool(removed["targets"])
            failed |= not runs[-1]["hud"] or not runs[-1]["targets"]
            print(json.dumps(report, ensure_ascii=False), flush=True)
        return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
