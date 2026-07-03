
from __future__ import annotations

import json
import logging
import queue
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import ttk, scrolledtext

CONFIG_FILE = "gui_config.json"

import main_automation as M
from main_automation import Orchestrator
from adb_macro_manager import Config as AdbConfig, Adb
from test_macro_io import record_session, playback_session


class _StreamToQueue:

    def __init__(self, q: "queue.Queue[str]"):
        self.q = q

    def write(self, text: str) -> None:
        if text:
            self.q.put(text)

    def flush(self) -> None:
        pass


class GuiLogHandler(logging.Handler):

    def __init__(self, q: "queue.Queue[str]"):
        super().__init__()
        self.q = q

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.q.put(self.format(record) + "\n")
        except Exception:
            self.handleError(record)


class AutomationGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Automation Control Panel")
        self.geometry("660x720")
        self.minsize(580, 600)

        self.log_queue: "queue.Queue[str]" = queue.Queue()
        self._orig_stdout = sys.stdout

        self._log_handler = GuiLogHandler(self.log_queue)
        self._log_handler.setFormatter(
            logging.Formatter("[%(levelname)s] %(name)s: %(message)s"))
        _root_logger = logging.getLogger()
        _root_logger.addHandler(self._log_handler)
        if _root_logger.level > logging.INFO or _root_logger.level == logging.NOTSET:
            _root_logger.setLevel(logging.INFO)

        self.worker: threading.Thread | None = None
        self.work_tag: str | None = None
        self._abort = threading.Event()

        self.adb_cfg = AdbConfig()
        self.orch: Orchestrator | None = None

        self._connected = False
        self._device_id: str | None = None
        self._checking = False
        self._conn_prev: bool | None = None

        self._saved = self._load_config()

        self._build_widgets()
        if self._saved:
            self.log_queue.put("[INIT] Previous configuration restored successfully.\n")
        self._poll_log()
        self._heartbeat()
        self.protocol("WM_DELETE_WINDOW", self._on_close)


    def _build_widgets(self) -> None:
        pad = {"padx": 8, "pady": 4}

        status_bar = ttk.Frame(self)
        status_bar.pack(fill="x", **pad)
        self.status_label = tk.Label(status_bar, text="🔴 Device Disconnected",
                                     fg="#d9333f", font=("Segoe UI", 10, "bold"))
        self.status_label.pack(side="left", padx=4)
        self.reconnect_btn = ttk.Button(status_bar, text="🔌 Reconnect",
                                        command=self._on_reconnect, width=14)
        self.reconnect_btn.pack(side="right", padx=4)

        s = self._saved
        mode_box = ttk.LabelFrame(self, text="Mode")
        mode_box.pack(fill="x", **pad)
        self.mode_var = tk.StringVar(value=s.get("mode", M.MODE))
        for label in ("FULL_AUTO", "CAPTCHA_ONLY"):
            ttk.Radiobutton(mode_box, text=label, value=label,
                            variable=self.mode_var).pack(side="left", padx=8, pady=4)

        chk_box = ttk.LabelFrame(self, text="Pre-Match Checklist")
        chk_box.pack(fill="x", **pad)
        self.boost_var = tk.BooleanVar(value=s.get("buy_boost_start", M.buy_boost_start))
        self.relay_var = tk.BooleanVar(value=s.get("buy_relay_character", M.buy_relay_character))
        self.roll_var = tk.BooleanVar(value=s.get("roll_random_buff", M.roll_random_buff))
        ttk.Checkbutton(chk_box, text="buy_boost_start",
                        variable=self.boost_var).pack(anchor="w", padx=8)
        ttk.Checkbutton(chk_box, text="buy_relay_character",
                        variable=self.relay_var).pack(anchor="w", padx=8)
        ttk.Checkbutton(chk_box, text="roll_random_buff",
                        variable=self.roll_var).pack(anchor="w", padx=8)

        play_box = ttk.LabelFrame(self, text="Playing Mode")
        play_box.pack(fill="x", **pad)
        self.play_mode_var = tk.StringVar(value=s.get("playing_mode", M.PLAYING_MODE))
        for text, val in (("Macro Play", "macro"), ("Long Run", "long_run")):
            ttk.Radiobutton(play_box, text=text, value=val,
                            variable=self.play_mode_var,
                            command=self._on_play_mode_change).pack(
                                side="left", padx=8, pady=4)

        lr_box = ttk.LabelFrame(self, text="Long Run Options")
        lr_box.pack(fill="x", **pad)
        self.lr_boost_var = tk.BooleanVar(
            value=s.get("long_run_boost_enabled", M.long_run_boost_enabled))
        self.lr_relay_var = tk.BooleanVar(
            value=s.get("long_run_relay_enabled", M.long_run_relay_enabled))
        ttk.Checkbutton(lr_box, text="Enable Boost Start", variable=self.lr_boost_var,
                        command=self._on_long_run_toggle).pack(side="left", padx=8, pady=4)
        ttk.Checkbutton(lr_box, text="Enable Relay", variable=self.lr_relay_var,
                        command=self._on_long_run_toggle).pack(side="left", padx=8, pady=4)

        macro_box = ttk.LabelFrame(self, text="Macro Configuration")
        macro_box.pack(fill="x", **pad)
        ttk.Label(macro_box, text="Macro Name:").grid(row=0, column=0,
                                                      sticky="w", padx=8, pady=4)
        self.name_var = tk.StringVar(value=s.get("macro_name", "session"))
        ttk.Entry(macro_box, textvariable=self.name_var, width=24).grid(
            row=0, column=1, sticky="w", padx=4, pady=4)
        ttk.Label(macro_box, text="(.json added automatically)").grid(
            row=0, column=2, sticky="w", padx=4)
        ttk.Label(macro_box, text="Cycles (-1 = infinite):").grid(
            row=1, column=0, sticky="w", padx=8, pady=4)
        self.loops_var = tk.StringVar(value=str(s.get("cycles", -1)))
        ttk.Entry(macro_box, textvariable=self.loops_var, width=8).grid(
            row=1, column=1, sticky="w", padx=4, pady=4)

        tools_box = ttk.LabelFrame(self, text="Macro Recorder & Tools")
        tools_box.pack(fill="x", **pad)
        self.record_btn = ttk.Button(tools_box, text="⏺ Record New Macro",
                                     command=self._on_record)
        self.record_btn.pack(side="left", padx=6, pady=6, ipadx=4, ipady=2)
        self.stop_rec_btn = ttk.Button(tools_box, text="⏹ Stop Recording",
                                       command=self._on_stop_record,
                                       state="disabled")
        self.stop_rec_btn.pack(side="left", padx=6, pady=6, ipadx=4, ipady=2)
        self.test_btn = ttk.Button(tools_box, text="▶ Test Play Macro",
                                   command=self._on_test)
        self.test_btn.pack(side="left", padx=6, pady=6, ipadx=4, ipady=2)

        btn_box = ttk.Frame(self)
        btn_box.pack(fill="x", **pad)
        self.start_btn = ttk.Button(btn_box, text="▶ Start Automation",
                                    command=self._on_start)
        self.start_btn.pack(side="left", padx=8, ipadx=10, ipady=4)
        self.stop_btn = ttk.Button(btn_box, text="■ Stop / Emergency Break",
                                   command=self._on_stop, state="disabled")
        self.stop_btn.pack(side="left", padx=8, ipadx=10, ipady=4)

        log_box = ttk.LabelFrame(self, text="Automation Live Logs")
        log_box.pack(fill="both", expand=True, **pad)
        log_toolbar = ttk.Frame(log_box)
        log_toolbar.pack(fill="x", padx=4, pady=(4, 0))
        ttk.Label(log_toolbar,
                  text="watchdog · captcha · macro · clicks  (real-time)",
                  foreground="#7a8899").pack(side="left")
        ttk.Button(log_toolbar, text="Clear", width=8,
                   command=self._on_clear_log).pack(side="right")
        self.log = scrolledtext.ScrolledText(log_box, height=16, state="disabled",
                                             bg="#101418", fg="#d6deeb",
                                             font=("Consolas", 9))
        self.log.pack(fill="both", expand=True, padx=4, pady=4)


    def _on_play_mode_change(self) -> None:
        mode = self.play_mode_var.get()
        M.PLAYING_MODE = mode
        if self.orch:
            self.orch.playing_mode = mode
        self._append(f"[PLAY] playing mode -> {mode}\n")

    def _on_long_run_toggle(self) -> None:
        boost = self.lr_boost_var.get()
        relay = self.lr_relay_var.get()
        M.long_run_boost_enabled = boost
        M.long_run_relay_enabled = relay
        if self.orch:
            self.orch.long_run_boost = boost
            self.orch.long_run_relay = relay
        self._save_config()
        self._append(f"[LONG RUN] Boost Start={boost}  Relay={relay}\n")

    def _macro_path(self) -> str:
        name = self.name_var.get().strip() or "session"
        if name.lower().endswith(".json"):
            name = name[:-5]
        return f"{name}.json"

    def _load_config(self) -> dict:
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            return data if isinstance(data, dict) else {}
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return {}

    def _save_config(self) -> None:
        try:
            cycles = int(self.loops_var.get())
        except ValueError:
            cycles = -1
        data = {
            "mode": self.mode_var.get(),
            "buy_boost_start": self.boost_var.get(),
            "buy_relay_character": self.relay_var.get(),
            "roll_random_buff": self.roll_var.get(),
            "macro_name": self.name_var.get().strip() or "session",
            "cycles": cycles,
            "playing_mode": self.play_mode_var.get(),
            "long_run_boost_enabled": self.lr_boost_var.get(),
            "long_run_relay_enabled": self.lr_relay_var.get(),
        }
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2)
        except OSError as exc:
            self._append(f"[WARN] could not save config: {exc}\n")


    def _heartbeat(self) -> None:
        if not self._checking:
            threading.Thread(target=self._check_connection, daemon=True).start()
        self.after(3000, self._heartbeat)

    def _on_reconnect(self) -> None:
        self.log_queue.put(f"[CONN] reconnecting to {self.adb_cfg.serial}...\n")
        if not self._checking:
            threading.Thread(
                target=lambda: self._check_connection(do_connect=True),
                daemon=True,
            ).start()

    def _check_connection(self, do_connect: bool = False) -> None:
        if self._checking:
            return
        self._checking = True
        try:
            if do_connect:
                subprocess.run(["adb", "connect", self.adb_cfg.serial],
                               capture_output=True, text=True, check=False)
            out = subprocess.run(["adb", "devices"], capture_output=True,
                                 text=True, check=False).stdout
            connected, dev = self._parse_devices(out)
            self._connected, self._device_id = connected, dev
            if connected != self._conn_prev:
                self._conn_prev = connected
                self.log_queue.put(
                    f"[CONN] device online: {dev}\n" if connected
                    else "[CONN] no device detected.\n")
        except Exception as exc:
            self._connected, self._device_id = False, None
            if self._conn_prev is not False:
                self._conn_prev = False
                self.log_queue.put(f"[CONN] check error: {exc}\n")
        finally:
            self._checking = False

    def _parse_devices(self, out: str) -> tuple[bool, str | None]:
        target = self.adb_cfg.serial
        fallback: str | None = None
        for line in out.splitlines()[1:]:
            line = line.strip()
            if not line or "\t" not in line:
                continue
            serial, state = (p.strip() for p in line.split("\t", 1))
            if state == "device":
                if serial == target:
                    return True, serial
                fallback = fallback or serial
        return (True, fallback) if fallback else (False, None)

    def _launch(self, tag: str, target) -> None:
        if self.worker and self.worker.is_alive():
            self._append("[BUSY] another action is already running.\n")
            return
        self._abort.clear()
        self.work_tag = tag
        sys.stdout = _StreamToQueue(self.log_queue)

        def runner():
            try:
                target()
            except Exception as exc:
                print(f"[FATAL] {type(exc).__name__}: {exc}")
            finally:
                sys.stdout = self._orig_stdout
                self.log_queue.put("\n")

        self.worker = threading.Thread(target=runner, daemon=True)
        self.worker.start()


    def _on_start(self) -> None:
        try:
            cycles = int(self.loops_var.get())
        except ValueError:
            self._append("[ERROR] Cycles must be an integer (use -1 for infinite).\n")
            return

        M.MODE = self.mode_var.get()
        M.buy_boost_start = self.boost_var.get()
        M.buy_relay_character = self.relay_var.get()
        M.roll_random_buff = self.roll_var.get()
        M.MACRO_SESSION_FILE = self._macro_path()
        M.MAX_CYCLES = cycles
        M.PLAYING_MODE = self.play_mode_var.get()
        M.long_run_boost_enabled = self.lr_boost_var.get()
        M.long_run_relay_enabled = self.lr_relay_var.get()

        self._save_config()
        self.orch = Orchestrator(M.MODE)
        self._launch("orch", self.orch.run)


    def _on_record(self) -> None:
        self._save_config()
        path = self._macro_path()

        def target():
            print(f"Recording -> {path}  (play in MuMu; press Q/Esc anywhere, "
                  f"or Stop, to finish)")
            record_session(path, stop_check=lambda: self._abort.is_set())

        self._launch("record", target)

    def _on_stop_record(self) -> None:
        self._abort.set()
        self._append("[REC] stop requested (or press Q/Esc anywhere)...\n")


    def _on_test(self) -> None:
        self._save_config()
        path = self._macro_path()
        adb = Adb(self.adb_cfg)

        def target():
            print(f"Test playback -> {path} (1 pass)")
            adb.connect()
            playback_session(path, adb=adb,
                             stop_check=lambda: self._abort.is_set())
            print("Test playback finished.")

        self._launch("test", target)


    def _on_stop(self) -> None:
        self._abort.set()
        if self.orch:
            self.orch.running = False
        self._append("[STOP] interruption signal sent...\n")


    def _poll_log(self) -> None:
        drained = ""
        try:
            while True:
                drained += self.log_queue.get_nowait()
        except queue.Empty:
            pass
        if drained:
            self._append(drained)

        running = bool(self.worker and self.worker.is_alive())
        tag = self.work_tag if running else None
        ops_state = "normal" if (not running and self._connected) else "disabled"
        self.start_btn.config(state=ops_state)
        self.record_btn.config(state=ops_state)
        self.test_btn.config(state=ops_state)
        self.stop_rec_btn.config(state="normal" if tag == "record" else "disabled")
        self.stop_btn.config(state="normal" if running else "disabled")

        if self._connected:
            self.status_label.config(text=f"🟢 Connected: {self._device_id}",
                                     fg="#2e9e44")
        else:
            self.status_label.config(text="🔴 Device Disconnected", fg="#d9333f")

        self.after(100, self._poll_log)

    def _append(self, text: str) -> None:
        self.log.config(state="normal")
        self.log.insert("end", text)
        self.log.see("end")
        self.log.config(state="disabled")

    def _on_clear_log(self) -> None:
        self.log.config(state="normal")
        self.log.delete("1.0", "end")
        self.log.config(state="disabled")

    def _on_close(self) -> None:
        self._save_config()
        self._abort.set()
        if self.orch:
            self.orch.running = False
        logging.getLogger().removeHandler(self._log_handler)
        self.destroy()


if __name__ == "__main__":
    AutomationGUI().mainloop()
