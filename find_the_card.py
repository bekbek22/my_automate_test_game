from __future__ import annotations

import time
from dataclasses import dataclass, field

import cv2
import numpy as np

try:
    import pytesseract
    import os
    _TESS = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    if os.path.exists(_TESS):
        pytesseract.pytesseract.tesseract_cmd = _TESS
except ImportError:
    pytesseract = None


@dataclass
class Config:
    adb_host: str = "127.0.0.1"
    adb_port: int = 16384

    trigger_region: tuple[int, int, int, int] = (492, 43, 722, 71)
    trigger_text: str = "find the"

    tries_left_region: tuple[int, int, int, int] = (500, 150, 336, 54)
    tries_mae_thresh: float = 5.0

    card_regions: list[tuple[int, int, int, int]] = field(default_factory=lambda: [
        (437, 228, 216, 291),
        (683, 229, 216, 289),
        (928, 231, 214, 289),
        (439, 549, 213, 288),
        (682, 551, 218, 286),
        (927, 552, 218, 285),
    ])
    cols: int = 3
    cell_pad_frac: float = 0.08
    empty_std_thresh: float = 5.0
    respawn_std_thresh: float = 32.0
    respawn_margin: float = 2.0
    bg_ema_alpha: float = 0.3
    vanish_mae_thresh: float = 8.0
    low_conf_dev: float = 1000.0
    high_conf_top_frac: float = 0.10

    poll_interval_s: float = 0.5
    tap_delay_s: float = 1.5
    debug: bool = True
    debug_dir: str = "debug"


class Emulator:
    def __init__(self, cfg: Config):
        from ppadb.client import Client as AdbClient

        client = AdbClient(host="127.0.0.1", port=5037)
        client.remote_connect(cfg.adb_host, cfg.adb_port)
        serial = f"{cfg.adb_host}:{cfg.adb_port}"
        self.device = client.device(serial)
        if self.device is None:
            raise RuntimeError(
                f"ADB device {serial} not found. Start MuMu, then run "
                f"`adb connect {serial}` and `adb devices` to verify."
            )

    def screenshot(self) -> np.ndarray:
        png_bytes = self.device.screencap()
        arr = np.frombuffer(png_bytes, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img is None:
            raise RuntimeError("screencap returned no decodable image")
        return img

    def tap(self, x: int, y: int) -> None:
        self.device.shell(f"input tap {int(x)} {int(y)}")


def crop(img: np.ndarray, region: tuple[int, int, int, int]) -> np.ndarray:
    x, y, w, h = region
    return img[y:y + h, x:x + w]


def detect_trigger(img: np.ndarray, cfg: Config) -> bool:
    if pytesseract is None:
        raise RuntimeError(
            "pytesseract not installed. Install it + the Tesseract engine, or "
            "switch detect_trigger() to template matching."
        )
    banner = crop(img, cfg.trigger_region)
    gray = cv2.cvtColor(banner, cv2.COLOR_BGR2GRAY)
    gray = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
    text = pytesseract.image_to_string(gray, config="--psm 7").lower()
    return cfg.trigger_text in text


def tries_signature(img: np.ndarray, cfg: Config) -> np.ndarray:
    return cv2.cvtColor(crop(img, cfg.tries_left_region),
                        cv2.COLOR_BGR2GRAY).astype(np.float32)


def split_grid(img: np.ndarray, cfg: Config):
    cells = []
    for idx, (x, y, w, h) in enumerate(cfg.card_regions):
        r, c = divmod(idx, cfg.cols)
        pad_x = int(w * cfg.cell_pad_frac)
        pad_y = int(h * cfg.cell_pad_frac)
        cell = img[y + pad_y:y + h - pad_y, x + pad_x:x + w - pad_x]
        center = (x + w // 2, y + h // 2)
        cells.append((r, c, cell, center))
    return cells


def _get_fingerprint(cell: np.ndarray, size: int = 64) -> np.ndarray:
    small = cv2.resize(cell, (size, size), interpolation=cv2.INTER_AREA)
    hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
    return hsv[:, :, :2].astype(np.float32).flatten()


def _is_empty(cell: np.ndarray, cfg: Config) -> bool:
    gray = cv2.cvtColor(cell, cv2.COLOR_BGR2GRAY)
    return float(gray.std()) < cfg.empty_std_thresh


def capture_session_template(cells, cfg: Config):
    present = [t for t in cells if not _is_empty(t[2], cfg)]
    if len(present) != len(cfg.card_regions):
        return None

    feats = np.stack([_get_fingerprint(cell) for _, _, cell, _ in present])
    median = np.median(feats, axis=0)
    deviation = np.linalg.norm(feats - median, axis=1)
    return feats[int(np.argmin(deviation))]


def _cell_mae(pre: np.ndarray, post: np.ndarray) -> float:
    a = cv2.cvtColor(pre, cv2.COLOR_BGR2GRAY).astype(np.float32)
    b = cv2.cvtColor(post, cv2.COLOR_BGR2GRAY).astype(np.float32)
    return float(np.abs(a - b).mean())


def find_target_cells(cells, cfg: Config, excluded=frozenset(),
                      session_template=None, high_confidence=False):
    present = [t for t in cells if (t[0], t[1]) not in excluded]

    if cfg.debug:
        print("  [debug] cell std-dev (std, excluded?, row, col):")
        for r, c, cell, _ in cells:
            std = float(cv2.cvtColor(cell, cv2.COLOR_BGR2GRAY).std())
            flag = "EXCL" if (r, c) in excluded else "    "
            print(f"          {std:7.1f}  {flag}  ({r},{c})")

    if not present:
        return [], None

    feats = np.stack([_get_fingerprint(cell) for _, _, cell, _ in present])
    if session_template is not None:
        baseline = session_template
        source = "locked template"
    else:
        baseline = np.median(feats, axis=0)
        source = "frame median (fallback)"

    if high_confidence:
        absdiff = np.abs(feats - baseline)
        k = max(1, int(cfg.high_conf_top_frac * absdiff.shape[1]))
        deviation = np.sort(absdiff, axis=1)[:, -k:].mean(axis=1)
        source += " [high-confidence]"
    else:
        deviation = np.linalg.norm(feats - baseline, axis=1)
    best = int(np.argmax(deviation))

    if cfg.debug:
        print(f"  [debug] deviation from {source} (dev, row, col):")
        for i in np.argsort(deviation)[::-1]:
            r, c = present[i][0], present[i][1]
            mark = " <- TAP" if i == best else ""
            print(f"          {deviation[i]:10.1f}  ({r},{c}){mark}")

    return [present[best]], float(deviation[best])


def save_debug(img: np.ndarray, cells, targets, cfg: Config) -> None:
    if not cfg.debug:
        return
    import os
    os.makedirs(cfg.debug_dir, exist_ok=True)
    vis = img.copy()
    target_centers = {t[3] for t in targets}
    for r, c, _, center in cells:
        colour = (0, 0, 255) if center in target_centers else (0, 255, 0)
        cv2.circle(vis, center, 18, colour, 3)
        cv2.putText(vis, f"{r},{c}", (center[0] - 20, center[1] - 25),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, colour, 2)
    path = os.path.join(cfg.debug_dir, f"decision_{int(time.time())}.png")
    cv2.imwrite(path, vis)
    print(f"  [debug] wrote {path}")


def _respawn_thresh(rc, bg_ema, cfg: Config) -> float:
    if rc in bg_ema:
        return max(cfg.respawn_std_thresh, bg_ema[rc] + cfg.respawn_margin)
    return cfg.respawn_std_thresh


def run(cfg: Config) -> None:
    emu = Emulator(cfg)
    print("Connected. Waiting for the trigger banner...")

    bg_ema = {}
    stats = {"success": 0, "miss": 0, "low_conf": 0}

    while True:
        img = emu.screenshot()

        if not detect_trigger(img, cfg):
            time.sleep(cfg.poll_interval_s)
            continue

        print("Trigger detected -> clearing cards one by one...")
        tap_no = 0
        cleared = set()
        dead = set()
        session_template = None
        high_conf_next = False
        prev_tries = tries_signature(img, cfg)
        while detect_trigger(img, cfg):
            cells = split_grid(img, cfg)
            excluded = cleared | dead

            cur_tries = tries_signature(img, cfg)
            tries_mae = float(np.abs(cur_tries - prev_tries).mean())
            if cfg.debug:
                print(f"  [debug] tries MAE = {tries_mae:.2f} "
                      f"(thresh {cfg.tries_mae_thresh})")
            tries_changed = tries_mae > cfg.tries_mae_thresh
            std_by_cell = {(r, c): float(cv2.cvtColor(cell, cv2.COLOR_BGR2GRAY).std())
                           for r, c, cell, _ in cells}
            respawned = any(std_by_cell.get(rc, 0.0) > _respawn_thresh(rc, bg_ema, cfg)
                            for rc in cleared)
            if excluded and (tries_changed or respawned):
                print("  [debug] Sub-round shift or reset detected via "
                      "Tries-Left/Re-spawn! Re-wiping state.")
                cleared.clear()
                dead.clear()
                session_template = None
                high_conf_next = False
                excluded = set()
            prev_tries = cur_tries

            if session_template is None and not excluded:
                session_template = capture_session_template(cells, cfg)
                if session_template is not None:
                    print("  locked session template from full 6-card grid")

            targets, score = find_target_cells(cells, cfg, excluded,
                                               session_template, high_conf_next)
            save_debug(img, cells, targets, cfg)
            high_conf_next = False

            if not targets:
                time.sleep(cfg.tap_delay_s)
                img = emu.screenshot()
                continue

            tap_no += 1
            r, c, pre_cell, (x, y) = targets[0]
            low = (score is not None and session_template is not None
                   and score < cfg.low_conf_dev)
            if low:
                stats["low_conf"] += 1
            print(f"  tap {tap_no}: ({r},{c}) dev={score:.1f}"
                  + (" [LOW CONFIDENCE]" if low else ""))
            emu.tap(x, y)

            time.sleep(cfg.tap_delay_s)
            img = emu.screenshot()

            post_cell = split_grid(img, cfg)[r * cfg.cols + c][2]
            vanish_mae = _cell_mae(pre_cell, post_cell)
            if cfg.debug:
                print(f"  [debug] vanish MAE = {vanish_mae:.2f} "
                      f"(thresh {cfg.vanish_mae_thresh})")
            if vanish_mae > cfg.vanish_mae_thresh:
                cleared.add((r, c))
                stats["success"] += 1
                bg = float(cv2.cvtColor(post_cell, cv2.COLOR_BGR2GRAY).std())
                a = cfg.bg_ema_alpha
                bg_ema[(r, c)] = bg if (r, c) not in bg_ema else (1 - a) * bg_ema[(r, c)] + a * bg
                print(f"    -> vanished (success). bg[{(r, c)}]={bg_ema[(r, c)]:.1f}")
            else:
                dead.add((r, c))
                stats["miss"] += 1
                high_conf_next = True
                print(f"    -> still present (miss). high-confidence re-scan next.")
        print(f"Banner gone -> puzzle solved. stats success={stats['success']} "
              f"miss={stats['miss']} low_conf={stats['low_conf']}\n")


if __name__ == "__main__":
    run(Config())
