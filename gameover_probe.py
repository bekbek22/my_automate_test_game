"""gameover_probe.py -- capture the text on the GAME-OVER / RESULT screen so we
can switch game-over detection from fragile yellow-color to reliable OCR.

Game-over happens every run, so this is easy: just run it and die once.

It OCRs the EXISTING result regions (both polarities) and saves crops, so we can
pick the most stable word to match.

Usage:
    python gameover_probe.py            # runs ~2 minutes, Ctrl+C to stop early

Then send me:
  1) a few "RESULT_REGION=... RESULT_COLOR_REGION=..." lines from the moment the
     game-over/result screen is up,
  2) the images debug/gameover/_result_region.png and _result_color_region.png.
"""
import os
import time

import cv2

import main_automation as M
from main_automation import Orchestrator, RESULT_REGION, RESULT_COLOR_REGION

OUT_DIR = os.path.join("debug", "gameover")
DURATION_S = 120.0
POLL_S = 0.5


def _crop(o, shot, region):
    x, y, w, h = region
    return o._shot_to_bgr(shot)[y:y + h, x:x + w]


def main() -> None:
    os.makedirs(OUT_DIR, exist_ok=True)
    o = Orchestrator(M.MODE)
    o.adb.connect()

    shot = o._grab_watchdog_frame()
    print("=" * 60)
    print(f"screenshot resolution: {shot.width} x {shot.height}")
    print(f"RESULT_REGION       = {RESULT_REGION}")
    print(f"RESULT_COLOR_REGION = {RESULT_COLOR_REGION}")
    print(f"crops saved under: {OUT_DIR}/")
    print("=" * 60)

    cv2.imwrite(os.path.join(OUT_DIR, "_full_frame.png"), o._shot_to_bgr(shot))
    cv2.imwrite(os.path.join(OUT_DIR, "_result_region.png"), _crop(o, shot, RESULT_REGION))
    cv2.imwrite(os.path.join(OUT_DIR, "_result_color_region.png"),
                _crop(o, shot, RESULT_COLOR_REGION))

    print("\nPlay a run and DIE so the game-over screen shows... (Ctrl+C to stop)\n")
    i = 0
    t0 = time.time()
    try:
        while time.time() - t0 < DURATION_S:
            shot = o._grab_watchdog_frame()
            r_n = o._ocr_region_text(shot, RESULT_REGION, upscale=3, psm=7)
            r_i = o._ocr_region_text(shot, RESULT_REGION, upscale=3, psm=7, invert=True)
            c_n = o._ocr_region_text(shot, RESULT_COLOR_REGION, upscale=3, psm=7)
            c_i = o._ocr_region_text(shot, RESULT_COLOR_REGION, upscale=3, psm=7, invert=True)
            stamp = time.strftime("%H:%M:%S")
            print(f"[{stamp}] RESULT_REGION n={r_n!r} i={r_i!r} | "
                  f"COLOR_REGION n={c_n!r} i={c_i!r}", flush=True)

            if any(t and t.strip() for t in (r_n, r_i, c_n, c_i)):
                cv2.imwrite(os.path.join(OUT_DIR, f"result_{i:03d}.png"),
                            _crop(o, shot, RESULT_REGION))
                i += 1
            time.sleep(POLL_S)
    except KeyboardInterrupt:
        print("\nstopped.")

    print(f"\nDone. Saved {i} text-bearing crop(s) to {OUT_DIR}/")
    print("Open _result_region.png + _result_color_region.png to see the regions.")


if __name__ == "__main__":
    main()
