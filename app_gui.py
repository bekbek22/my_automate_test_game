
from __future__ import annotations

import json
import logging
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import ttk, scrolledtext

CONFIG_FILE = "gui_config.json"
MACRO_DIR = "macro"                 # recorded macros live here (one .json per macro)

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
        self.title("CookieRun Automation — Control Panel")
        # Tall enough to show the whole sidebar un-maximized (restore-down size),
        # and start MAXIMIZED on Windows so nothing clips out of the box.
        self.geometry("880x850")
        self.minsize(760, 600)
        try:
            self.state("zoomed")            # Windows/most X11 window managers
        except tk.TclError:
            try:
                self.attributes("-zoomed", True)   # some Linux WMs
            except tk.TclError:
                pass

        self.log_queue: "queue.Queue[str]" = queue.Queue()
        self._orig_stdout = sys.stdout

        # Thread-safe run counter: the orchestrator (background thread) only
        # increments the int under a lock; the main-thread poll loop is the ONLY
        # code that touches the Tk widget -> no cross-thread widget access.
        self._run_count = 0
        self._run_count_lock = threading.Lock()
        self._run_count_shown = -1

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

        self._setup_style()
        self._build_widgets()
        if self._saved:
            self.log_queue.put("[INIT] Previous configuration restored successfully.\n")
        self._poll_log()
        self._heartbeat()
        self.protocol("WM_DELETE_WINDOW", self._on_close)


    _BG = "#f4f6f8"
    _SIDEBAR_W = 224

    def _setup_style(self) -> None:
        """Compact, developer-dashboard ttk theme: 9pt UI font, tight padding,
        accent/danger action buttons."""
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        base = ("Segoe UI", 9)
        self.configure(bg=self._BG)
        style.configure(".", font=base, background=self._BG, foreground="#2c3e50")
        style.configure("TFrame", background=self._BG)
        style.configure("TLabel", background=self._BG, foreground="#2c3e50")
        style.configure("TCheckbutton", background=self._BG, font=base, padding=0)
        style.configure("TRadiobutton", background=self._BG, font=base, padding=0)
        style.configure("TLabelframe", background=self._BG, relief="solid",
                        borderwidth=1, padding=4)
        style.configure("TLabelframe.Label", background=self._BG,
                        font=("Segoe UI", 9, "bold"), foreground="#33475b")
        style.configure("TButton", font=base, padding=(4, 2))
        style.configure("TEntry", padding=1)
        style.configure("Header.TLabel", font=("Segoe UI", 11, "bold"),
                        foreground="#1b2a3a")
        style.configure("Sub.TLabel", font=("Segoe UI", 8), foreground="#7a8899")
        style.configure("Stat.TLabel", font=("Segoe UI", 13, "bold"),
                        foreground="#2e9e44")
        style.configure("Accent.TButton", font=("Segoe UI", 9, "bold"), padding=(4, 3))
        style.map("Accent.TButton",
                  background=[("disabled", "#b8c4cc"), ("!disabled", "#2e9e44")],
                  foreground=[("!disabled", "#ffffff")])
        style.configure("Danger.TButton", font=("Segoe UI", 9, "bold"), padding=(4, 3))
        style.map("Danger.TButton",
                  background=[("disabled", "#b8c4cc"), ("!disabled", "#d9333f")],
                  foreground=[("!disabled", "#ffffff")])

    def _build_widgets(self) -> None:
        s = self._saved
        root = ttk.Frame(self, padding=6)
        root.pack(fill="both", expand=True)

        # Slim control sidebar (fixed width) | dominant log stream (expands).
        sidebar = ttk.Frame(root, width=self._SIDEBAR_W)
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)
        logpane = ttk.Frame(root)
        logpane.pack(side="left", fill="both", expand=True, padx=(6, 0))

        gp = {"fill": "x", "pady": (0, 4)}          # compact group spacing

        ttk.Label(sidebar, text="CookieRun Automation",
                  style="Header.TLabel").pack(anchor="w", pady=(0, 4))

        # --- Connection ---
        conn = ttk.LabelFrame(sidebar, text="Connection")
        conn.pack(**gp)
        self.status_label = tk.Label(conn, text="🔴 Disconnected", fg="#d9333f",
                                     bg=self._BG, font=("Segoe UI", 9, "bold"))
        self.status_label.pack(anchor="w")
        ttk.Label(conn, text=self.adb_cfg.serial, style="Sub.TLabel").pack(anchor="w")
        self.reconnect_btn = ttk.Button(conn, text="🔌 Reconnect",
                                        command=self._on_reconnect)
        self.reconnect_btn.pack(fill="x", pady=(3, 0))

        # --- Session Statistics ---
        stats = ttk.LabelFrame(sidebar, text="Session Statistics")
        stats.pack(**gp)
        self.runs_var = tk.StringVar(value="Completed Runs: 0")
        ttk.Label(stats, textvariable=self.runs_var, style="Stat.TLabel").pack(anchor="w")
        self.reset_runs_btn = ttk.Button(stats, text="Reset Counter",
                                         command=self._reset_run_count)
        self.reset_runs_btn.pack(fill="x", pady=(3, 0))

        # --- Primary actions (pinned high so they never clip) ---
        self.start_btn = ttk.Button(sidebar, text="▶  Start Automation",
                                    style="Accent.TButton", command=self._on_start)
        self.start_btn.pack(fill="x", pady=(0, 2))
        self.stop_btn = ttk.Button(sidebar, text="■  Stop / Emergency Break",
                                   style="Danger.TButton", command=self._on_stop,
                                   state="disabled")
        self.stop_btn.pack(fill="x", pady=(0, 4))

        # --- Mode ---
        mode_box = ttk.LabelFrame(sidebar, text="Mode")
        mode_box.pack(**gp)
        self.mode_var = tk.StringVar(value=s.get("mode", M.MODE))
        for label in ("FULL_AUTO", "CAPTCHA_ONLY"):
            ttk.Radiobutton(mode_box, text=label, value=label,
                            variable=self.mode_var).pack(anchor="w")

        # --- Playing Mode ---
        play_box = ttk.LabelFrame(sidebar, text="Playing Mode")
        play_box.pack(**gp)
        self.play_mode_var = tk.StringVar(value=s.get("playing_mode", M.PLAYING_MODE))
        for text, val in (("Macro Play", "macro"), ("Long Run", "long_run")):
            ttk.Radiobutton(play_box, text=text, value=val, variable=self.play_mode_var,
                            command=self._on_play_mode_change).pack(anchor="w")

        # --- Long Run Options ---
        lr_box = ttk.LabelFrame(sidebar, text="Long Run Options")
        lr_box.pack(**gp)
        self.lr_boost_var = tk.BooleanVar(
            value=s.get("long_run_boost_enabled", M.long_run_boost_enabled))
        self.lr_relay_var = tk.BooleanVar(
            value=s.get("long_run_relay_enabled", M.long_run_relay_enabled))
        ttk.Checkbutton(lr_box, text="Enable Boost Start", variable=self.lr_boost_var,
                        command=self._on_long_run_toggle).pack(anchor="w")
        ttk.Checkbutton(lr_box, text="Enable Relay", variable=self.lr_relay_var,
                        command=self._on_long_run_toggle).pack(anchor="w")

        # --- Pre-Match Checklist ---
        chk_box = ttk.LabelFrame(sidebar, text="Pre-Match Checklist")
        chk_box.pack(**gp)
        self.boost_var = tk.BooleanVar(value=s.get("buy_boost_start", M.buy_boost_start))
        self.relay_var = tk.BooleanVar(value=s.get("buy_relay_character", M.buy_relay_character))
        self.roll_var = tk.BooleanVar(value=s.get("roll_random_buff", M.roll_random_buff))
        ttk.Checkbutton(chk_box, text="Buy Boost Start",
                        variable=self.boost_var).pack(anchor="w")
        ttk.Checkbutton(chk_box, text="Buy Relay Character",
                        variable=self.relay_var).pack(anchor="w")
        ttk.Checkbutton(chk_box, text="Roll Random Buff",
                        variable=self.roll_var).pack(anchor="w")
        self.reward_claim_var = tk.BooleanVar(
            value=s.get("reward_claim_enabled", M.reward_claim_enabled))
        ttk.Checkbutton(chk_box, text="Auto-Click 'Get!' Reward",
                        variable=self.reward_claim_var,
                        command=self._on_reward_claim_toggle).pack(anchor="w")

        # --- Macro Configuration ---
        macro_box = ttk.LabelFrame(sidebar, text="Macro Configuration")
        macro_box.pack(**gp)
        macro_box.columnconfigure(1, weight=1)
        ttk.Label(macro_box, text="Macro").grid(row=0, column=0, sticky="w")
        _macros = self._scan_macros()
        _default = s.get("macro_name", "")
        if _default not in _macros:
            _default = _macros[0] if _macros else "session"
        self.name_var = tk.StringVar(value=_default)
        # Editable dropdown: pick an existing macro from the macro/ folder, or type
        # a new name to record to. The list refreshes each time it's opened.
        self.macro_combo = ttk.Combobox(macro_box, textvariable=self.name_var,
                                        values=_macros)
        self.macro_combo.grid(row=0, column=1, sticky="ew", padx=(4, 0), pady=1)
        self.macro_combo.configure(postcommand=lambda: self.macro_combo.configure(
            values=self._scan_macros()))
        ttk.Label(macro_box, text="Cycles").grid(row=1, column=0, sticky="w")
        self.loops_var = tk.StringVar(value=str(s.get("cycles", -1)))
        ttk.Entry(macro_box, textvariable=self.loops_var).grid(
            row=1, column=1, sticky="ew", padx=(4, 0), pady=1)
        # Mirror of the Long Run "Enable Relay" toggle, bound to the SAME var so
        # both checkboxes stay in sync -- the macro-mode watchdog reads this flag
        # too (revive-on-death gating), so it's surfaced here for convenience.
        ttk.Checkbutton(macro_box, text="Enable Relay (revive on death)",
                        variable=self.lr_relay_var,
                        command=self._on_long_run_toggle).grid(
                            row=2, column=0, columnspan=2, sticky="w", pady=(3, 0))

        # --- Recorder & Tools ---
        tools_box = ttk.LabelFrame(sidebar, text="Recorder & Tools")
        tools_box.pack(**gp)
        self.record_btn = ttk.Button(tools_box, text="⏺ Record New Macro",
                                     command=self._on_record)
        self.record_btn.pack(fill="x", pady=1)
        self.stop_rec_btn = ttk.Button(tools_box, text="⏹ Stop Recording",
                                       command=self._on_stop_record, state="disabled")
        self.stop_rec_btn.pack(fill="x", pady=1)
        self.test_btn = ttk.Button(tools_box, text="▶ Test Play Macro",
                                   command=self._on_test)
        self.test_btn.pack(fill="x", pady=1)

        # --- Dominant log stream ---
        log_head = ttk.Frame(logpane)
        log_head.pack(fill="x", pady=(0, 3))
        ttk.Label(log_head, text="Automation Live Logs",
                  style="Header.TLabel").pack(side="left")
        ttk.Button(log_head, text="Clear", width=7,
                   command=self._on_clear_log).pack(side="right")
        ttk.Label(log_head, text="watchdog · captcha · macro · clicks",
                  style="Sub.TLabel").pack(side="right", padx=8)
        self.log = scrolledtext.ScrolledText(logpane, state="disabled",
                                             bg="#101418", fg="#d6deeb",
                                             insertbackground="#d6deeb",
                                             font=("Consolas", 9),
                                             relief="flat", borderwidth=0)
        self.log.pack(fill="both", expand=True)
        self._attach_log_copy_bindings(self.log)


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
            self.orch.long_run_boost_enabled = boost
            self.orch.long_run_relay_enabled = relay
        self._save_config()
        self._append(f"[LONG RUN] Boost Start={boost}  Relay={relay}\n")

    def _on_reward_claim_toggle(self) -> None:
        enabled = self.reward_claim_var.get()
        M.reward_claim_enabled = enabled
        if self.orch:                                # live-apply to a running loop
            self.orch.reward_claim_enabled = enabled
        self._save_config()
        self._append(f"[REWARD] Auto-Click 'Get!' = {enabled}\n")

    def _scan_macros(self) -> list:
        """Sorted list of macro base-names (no .json) in the macro/ folder."""
        try:
            return sorted(f[:-5] for f in os.listdir(MACRO_DIR)
                          if f.lower().endswith(".json"))
        except OSError:
            return []

    def _macro_path(self) -> str:
        name = self.name_var.get().strip() or "session"
        if name.lower().endswith(".json"):
            name = name[:-5]
        return os.path.join(MACRO_DIR, f"{name}.json")

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
            "reward_claim_enabled": self.reward_claim_var.get(),
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
        M.reward_claim_enabled = self.reward_claim_var.get()

        self._save_config()
        self.orch = Orchestrator(M.MODE)
        self.orch.on_run_complete = self._bump_run_count
        self._launch("orch", self.orch.run)


    def _on_record(self) -> None:
        self._save_config()
        os.makedirs(MACRO_DIR, exist_ok=True)      # ensure macro/ exists
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

        # Run counter: read the shared int (written by the orchestrator thread)
        # under the lock and refresh the label only when it changed. This is the
        # ONLY place the counter widget is touched -> stays on the main thread.
        with self._run_count_lock:
            count = self._run_count
        if count != self._run_count_shown:
            self._run_count_shown = count
            self.runs_var.set(f"Completed Runs: {count}")

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

    def _attach_log_copy_bindings(self, widget) -> None:
        """Make the read-only log drag-selectable AND copyable. A disabled Text is
        already selectable by mouse, but it never accepts keyboard focus, so the
        default Ctrl+C is swallowed. We grab focus on click and bind copy /
        select-all (Ctrl and Cmd) plus a right-click Copy menu explicitly, leaving
        the widget disabled so it stays read-only."""
        widget.configure(takefocus=True)
        widget.bind("<Button-1>", lambda e: widget.focus_set(), add="+")
        for seq in ("<Control-c>", "<Control-C>", "<Command-c>", "<Command-C>"):
            widget.bind(seq, self._copy_log_selection)
        for seq in ("<Control-a>", "<Control-A>", "<Command-a>", "<Command-A>"):
            widget.bind(seq, self._select_all_log)
        menu = tk.Menu(widget, tearoff=0)
        menu.add_command(label="Copy", command=self._copy_log_selection)
        menu.add_command(label="Select All", command=self._select_all_log)

        def _popup(event):
            widget.focus_set()
            menu.tk_popup(event.x_root, event.y_root)

        widget.bind("<Button-3>", _popup)          # right-click context menu

    def _copy_log_selection(self, event=None) -> str:
        try:
            text = self.log.get("sel.first", "sel.last")
        except tk.TclError:
            return "break"                          # nothing selected
        self.clipboard_clear()
        self.clipboard_append(text)
        return "break"

    def _select_all_log(self, event=None) -> str:
        self.log.tag_add("sel", "1.0", "end-1c")
        return "break"

    def _on_clear_log(self) -> None:
        self.log.config(state="normal")
        self.log.delete("1.0", "end")
        self.log.config(state="disabled")

    def _bump_run_count(self) -> None:
        """Called from the orchestrator's background thread on each completed run.
        Only mutates the guarded int -- the label is refreshed by _poll_log on the
        main thread, so no Tk widget is ever touched off-thread."""
        with self._run_count_lock:
            self._run_count += 1

    def _reset_run_count(self) -> None:
        """Zero the session run counter (the label updates on the next poll)."""
        with self._run_count_lock:
            self._run_count = 0
        self._append("[STATS] Run counter reset to 0.\n")

    def _on_close(self) -> None:
        self._save_config()
        self._abort.set()
        if self.orch:
            self.orch.running = False
        logging.getLogger().removeHandler(self._log_handler)
        self.destroy()


if __name__ == "__main__":
    AutomationGUI().mainloop()
