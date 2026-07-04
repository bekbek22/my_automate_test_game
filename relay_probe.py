"""relay_probe.py -- diagnose why the relay banner isn't detected.

Run this WHILE a match is on screen (play a run; when the
"Tap to activate Cookie Relay Boost!" banner appears it will be captured).

It reuses the EXACT same capture + OCR code the bot uses, and additionally:
  * prints the real screenshot resolution (to catch a coordinate/scale mismatch),
  * saves crops of RELAY_PROMPT_REGION to debug/relay/ so you can SEE whether the
    region actually lands on the banner text,
  * prints what Tesseract reads in BOTH polarities each frame.

Usage:
    python relay_probe.py            # runs ~2 minutes, Ctrl+C to stop early

Then send me:
  1) the "screenshot resolution" line,
  2) a few of the printed "normal=... invert=..." lines from when the banner was up,
  3) one saved image from debug/relay/ (especially one taken while the banner showed).
"""
import os
import time

import cv2

import main_automation as M
from main_automation import Orchestrator, RELAY_PROMPT_REGION

OUT_DIR = os.path.join("debug", "relay")
DURATION_S = 120.0
POLL_S = 0.4


def main() -> None:
    os.makedirs(OUT_DIR, exist_ok=True)
    o = Orchestrator(M.MODE)
    o.adb.connect()

    # --- resolution / region sanity ------------------------------------------
    shot = o._grab_watchdog_frame()
    x, y, w, h = RELAY_PROMPT_REGION
    print("=" * 60)
    print(f"screenshot resolution: {shot.width} x {shot.height}")
    print(f"relay region RELAY_PROMPT_REGION = {RELAY_PROMPT_REGION}")
    print(f"  -> x:{x}..{x + w}   y:{y}..{y + h}")
    if x + w > shot.width or y + h > shot.height:
        print("  [!!] REGION IS OUT OF BOUNDS for this resolution -- "
              "coordinates were measured at a different scale.")
    print(f"crops + full frame saved under: {OUT_DIR}/")
    print("=" * 60)

    # Save a full frame + the initial crop so the region can be eyeballed even
    # before the banner appears.
    full = o._shot_to_bgr(shot)
    cv2.imwrite(os.path.join(OUT_DIR, "_full_frame.png"), full)
    cv2.imwrite(os.path.join(OUT_DIR, "_region_sanity.png"), full[y:y + h, x:x + w])

    print("\nWatching for the relay banner... (Ctrl+C to stop)\n")
    i = 0
    t0 = time.time()
    try:
        while time.time() - t0 < DURATION_S:
            shot = o._grab_watchdog_frame()
            crop = o._shot_to_bgr(shot)[y:y + h, x:x + w]
            txt_n = o._ocr_region_text(shot, RELAY_PROMPT_REGION, upscale=3)
            txt_i = o._ocr_region_text(shot, RELAY_PROMPT_REGION,
                                       upscale=3, invert=True)
            stamp = time.strftime("%H:%M:%S")
            print(f"[{stamp}] normal={txt_n!r}  invert={txt_i!r}", flush=True)

            # Save any frame where OCR saw letters (likely the banner).
            if (txt_n and txt_n.strip()) or (txt_i and txt_i.strip()):
                path = os.path.join(OUT_DIR, f"relay_{i:03d}.png")
                cv2.imwrite(path, crop)
                i += 1
            time.sleep(POLL_S)
    except KeyboardInterrupt:
        print("\nstopped.")

    print(f"\nDone. Saved {i} text-bearing crop(s) to {OUT_DIR}/")
    print("Open _region_sanity.png first to confirm the region lands on the banner.")


if __name__ == "__main__":
    main()
