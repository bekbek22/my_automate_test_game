"""get_probe.py -- diagnose the MAIN_MENU "Get!" reward-claim detection.

Run this on the MAIN MENU (ideally with the relics FULL so the red "Get!" balloon
is showing). It reuses the EXACT same code handle_main_menu uses and prints:
  * screenshot resolution (catch a coordinate/scale mismatch),
  * the MAIN_MENU anchor match confidence -- if this is 0..0.75 the real code
    SKIPS the Get! OCR, so a bad anchor silently blocks the whole claim,
  * the TICKET_GET_REGION OCR read (normal + inverted) -- does it read "Get!"?,
and saves crops to debug/get/ so you can SEE whether each region lands right.

Usage:
    python get_probe.py            # runs ~2 minutes, Ctrl+C to stop early

Then send me:
  1) the "screenshot resolution" line,
  2) a few "anchor=... get_normal=... get_invert=..." lines (from when Get! shows),
  3) the images debug/get/_ticket_get_region.png and _anchor_region.png.
"""
import os
import time

import cv2

import main_automation as M
from main_automation import (Orchestrator, TICKET_GET_REGION,
                             MAIN_MENU_TICKET_REGION, TICKET_MATCH_THRESHOLD)

OUT_DIR = os.path.join("debug", "get")
DURATION_S = 120.0
POLL_S = 0.5


def main() -> None:
    os.makedirs(OUT_DIR, exist_ok=True)
    o = Orchestrator(M.MODE)
    o.adb.connect()

    shot = o._grab_watchdog_frame()
    gx, gy, gw, gh = TICKET_GET_REGION
    ax, ay, aw, ah = MAIN_MENU_TICKET_REGION
    print("=" * 60)
    print(f"screenshot resolution: {shot.width} x {shot.height}")
    print(f"TICKET_GET_REGION    = {TICKET_GET_REGION}  -> x:{gx}..{gx+gw} y:{gy}..{gy+gh}")
    print(f"MAIN_MENU_TICKET_REGION (anchor) = {MAIN_MENU_TICKET_REGION}")
    print(f"anchor match threshold = {TICKET_MATCH_THRESHOLD} "
          f"(real code skips Get! OCR when 0 <= conf < {TICKET_MATCH_THRESHOLD})")
    if gx + gw > shot.width or gy + gh > shot.height:
        print("  [!!] TICKET_GET_REGION OUT OF BOUNDS for this resolution.")
    print(f"crops saved under: {OUT_DIR}/")
    print("=" * 60)

    full = o._shot_to_bgr(shot)
    cv2.imwrite(os.path.join(OUT_DIR, "_full_frame.png"), full)
    cv2.imwrite(os.path.join(OUT_DIR, "_ticket_get_region.png"),
                full[gy:gy + gh, gx:gx + gw])
    cv2.imwrite(os.path.join(OUT_DIR, "_anchor_region.png"),
                full[ay:ay + ah, ax:ax + aw])

    print("\nWatching the main menu... (Ctrl+C to stop)\n")
    i = 0
    t0 = time.time()
    try:
        while time.time() - t0 < DURATION_S:
            shot = o._grab_watchdog_frame()
            conf = o._match_main_menu_anchor(shot)
            get_n = o._ocr_region_text(shot, TICKET_GET_REGION, upscale=3, psm=6)
            get_i = o._ocr_region_text(shot, TICKET_GET_REGION, upscale=3, psm=6,
                                       invert=True)
            hit = any("get" in (t or "").lower() for t in (get_n, get_i))
            gated = 0.0 <= conf < TICKET_MATCH_THRESHOLD
            stamp = time.strftime("%H:%M:%S")
            print(f"[{stamp}] anchor={conf:.3f}{' (GATES OUT)' if gated else ''}  "
                  f"get_normal={get_n!r}  get_invert={get_i!r}  -> would_claim="
                  f"{hit and not gated}", flush=True)

            if (get_n and get_n.strip()) or (get_i and get_i.strip()):
                cv2.imwrite(os.path.join(OUT_DIR, f"get_{i:03d}.png"),
                            o._shot_to_bgr(shot)[gy:gy + gh, gx:gx + gw])
                i += 1
            time.sleep(POLL_S)
    except KeyboardInterrupt:
        print("\nstopped.")

    print(f"\nDone. Saved {i} text-bearing crop(s) to {OUT_DIR}/")
    print("Open _ticket_get_region.png + _anchor_region.png to confirm the regions.")


if __name__ == "__main__":
    main()
