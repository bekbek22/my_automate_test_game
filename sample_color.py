
from __future__ import annotations

import argparse
import collections

from adb_macro_manager import Adb, Config
from main_automation import REGION_CONGRATS_TEXT

QUANT = 16
STEP = 2


def sample_region(x: int, y: int, w: int, h: int) -> None:
    adb = Adb(Config())
    adb.connect()
    shot = adb.screenshot()

    rs = gs = bs = n = 0
    hist: "collections.Counter" = collections.Counter()
    for yy in range(y, y + h, STEP):
        for xx in range(x, x + w, STEP):
            r, g, b = shot.pixel(xx, yy)
            rs += r; gs += g; bs += b; n += 1
            hist[(r // QUANT * QUANT, g // QUANT * QUANT, b // QUANT * QUANT)] += 1

    if n == 0:
        print("No pixels sampled (empty region?).")
        return

    mean = (rs // n, gs // n, bs // n)
    print(f"Region (x, y, w, h) = ({x}, {y}, {w}, {h}); sampled {n} px (step={STEP})")
    print(f"MEAN RGB        : {mean}")

    print(f"DOMINANT RGB    (quantized /{QUANT}, top 6 by frequency):")
    for color, count in hist.most_common(6):
        print(f"   {str(color):<18} {count / n * 100:5.1f}%")

    top_color, top_count = hist.most_common(1)[0]
    print(f"\nSUGGESTED CONGRATS_TARGET_RGB = {top_color}  "
          f"(covers {top_count / n * 100:.1f}% of the region)")
    print("   -> set the tolerance wide enough to span the top few buckets above.")

    print("\nRAW pixel grid (evenly spaced across the region):")
    rows, cols = 3, 6
    for ry in range(rows):
        yy = y + (h * ry) // rows + h // (2 * rows)
        cells = []
        for cx in range(cols):
            xx = x + (w * cx) // cols + w // (2 * cols)
            cells.append(f"{str(shot.pixel(xx, yy)):<15}")
        print("   " + " ".join(cells))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="One-shot region color sampler")
    parser.add_argument("coords", nargs="*", type=int,
                        help="optional x y w h (defaults to REGION_CONGRATS_TEXT)")
    args = parser.parse_args(argv)

    if len(args.coords) == 4:
        x, y, w, h = args.coords
    elif len(args.coords) == 0:
        x, y, w, h = REGION_CONGRATS_TEXT
    else:
        parser.error("provide exactly 4 ints (x y w h) or none")
    sample_region(x, y, w, h)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
