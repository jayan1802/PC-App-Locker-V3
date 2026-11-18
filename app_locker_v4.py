"""
PC App Locker V4 — Windows 10/11
Modern per-Windows-user app locker and screen-time manager.

Important:
- Each Windows account has its own settings and usage database in LOCALAPPDATA.
- Run/configure the app separately while signed into each Windows account.
- This is a user-session monitor, not tamper-proof OS enforcement. An administrator
  can stop it. Use a standard child account and Windows policy controls for stronger
  enforcement.
"""
import os
import sys
import json
import time
import queue
import hashlib
import secrets
import threading
import subprocess
import shutil
from pathlib import Path
from datetime import datetime, date
import tkinter as tk
from tkinter import filedialog, messagebox

try:
    import psutil
    import customtkinter as ctk
except ImportError as exc:
    raise SystemExit(
        "Required packages are missing. Run: py -m pip install -r requirements.txt"
    ) from exc

try:
    import pystray
    from PIL import Image, ImageDraw
except Exception:
    pystray = None
    Image = ImageDraw = None

APP_NAME = "PC App Locker"
APP_VERSION = "4.1"
APP_DIR = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "PCAppLocker"
CONFIG_FILE = APP_DIR / "profile.json"
POLL_SECONDS = 1.0
SAVE_SECONDS = 8


def digest_secret(value, salt):
    return hashlib.pbkdf2_hmac(
        "sha256", value.encode("utf-8"), bytes.fromhex(salt), 310_000
    ).hex()


def make_secret(value):
    salt = secrets.token_hex(16)
    return {"salt": salt, "digest": digest_secret(value, salt)}


def check_secret(value, record):
    try:
        return secrets.compare_digest(digest_secret(value, record["salt"]), record["digest"])
    except Exception:
        return False


def load_profile():
    APP_DIR.mkdir(parents=True, exist_ok=True)
    if CONFIG_FILE.exists():
        try:
            cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            cfg.setdefault("apps", [])
            cfg.setdefault("usage_date", date.today().isoformat())
            cfg.setdefault("usage", {})
            cfg.setdefault("history", {})
            cfg.setdefault("breaks", {})
            cfg.setdefault("startup", False)
            cfg.setdefault("failed_attempts", 0)
            cfg.setdefault("lockout_until", 0)
            # V4 uses one admin password. Migrate V3 password hash; discard separate PIN.
            if not cfg.get("admin_password"):
                cfg["admin_password"] = cfg.get("password")
            cfg.pop("pin", None)
            cfg.pop("password", None)
            return cfg
        except Exception:
            pass
    return {
        "version": APP_VERSION,
        "admin_password": None,
        "recovery": None,
        "apps": [],
        "usage_date": date.today().isoformat(),
        "usage": {},
        "history": {},
        "breaks": {},
        "startup": False,
        "failed_attempts": 0,
        "lockout_until": 0,
    }


def save_profile(cfg):
    APP_DIR.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    tmp.replace(CONFIG_FILE)


def parse_time(value):
    try:
        h, m = [int(x) for x in value.strip().split(":")]
        if 0 <= h <= 23 and 0 <= m <= 59:
            return h * 60 + m
    except Exception:
        pass
    return None


def in_schedule(app, now):
    if not app.get("schedule_enabled", False):
        return True
    start = parse_time(app.get("schedule_start", "17:00"))
    end = parse_time(app.get("schedule_end", "21:00"))
    if start is None or end is None or start == end:
        return False
    current = now.hour * 60 + now.minute
    if start < end:
        return start <= current < end
    return current >= start or current < end


def allowed_today(app, now):
    days = app.get("days", ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"])
    return now.strftime("%a") in days


def fmt_time(seconds):
    seconds = max(0, int(seconds))
    hours, rem = divmod(seconds, 3600)
    mins = rem // 60
    return f"{hours}h {mins:02d}m" if hours else f"{mins}m"


def set_startup(enabled):
    """Register/unregister current-user startup using HKCU Run."""
    if os.name != "nt":
        return False
    import winreg
    key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
    value_name = "PCAppLocker"
    exe = sys.executable
    if getattr(sys, "frozen", False):
        command = f'"{exe}"'
    else:
        command = f'"{exe}" "{Path(__file__).resolve()}"'
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            winreg.SetValueEx(key, value_name, 0, winreg.REG_SZ, command)
        else:
            try:
                winreg.DeleteValue(key, value_name)
            except FileNotFoundError:
                pass
    return True


class Modal(ctk.CTkToplevel):
    def __init__(self, parent, title, geometry="420x260"):
        super().__init__(parent)
        self.title(title)
        self.geometry(geometry)
        self.resizable(False, False)
        self.transient(parent)
        self.result = None
        self.protocol("WM_DELETE_WINDOW", self.destroy)


class CredentialPrompt(Modal):
    def __init__(self, parent, title, prompt, pin=False, confirm=False):
        super().__init__(parent, title, "440x300" if confirm else "440x250")
        self.pin = pin
        self.confirm = confirm
        self.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(self, text=prompt, wraplength=380, justify="left").pack(
            padx=24, pady=(24, 12), anchor="w"
        )
        label = "PIN" if pin else "Password"
        self.first = ctk.CTkEntry(self, placeholder_text=label, show="●", width=350)
        self.first.pack(padx=24, pady=8)
        self.second = None
        if confirm:
            self.second = ctk.CTkEntry(self, placeholder_text="Confirm " + label, show="●", width=350)
            self.second.pack(padx=24, pady=8)
        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(pady=16)
        ctk.CTkButton(row, text="Continue", command=self.accept, width=130).pack(side="left", padx=6)
        ctk.CTkButton(row, text="Cancel", command=self.cancel, width=110, fg_color="gray").pack(side="left", padx=6)
        self.bind("<Return>", lambda _e: self.accept())
        self.transient(parent)
        self.update_idletasks()
        self.lift()
        self.focus_force()
        self.grab_set()
        self.first.focus_set()
        self.wait_window(self)

    def accept(self):
        value = self.first.get()
        if not value:
            messagebox.showwarning(APP_NAME, "Enter a value.", parent=self)
            return
        if self.second is not None and value != self.second.get():
            messagebox.showerror(APP_NAME, "The values do not match.", parent=self)
            return
        self.result = value
        self.destroy()

    def cancel(self):
        self.result = None
        self.destroy()


class AppEditor(Modal):
    def __init__(self, parent, app):
        super().__init__(parent, "Application rules", "600x680")
        self.resizable(True, True)
        self.minsize(520, 480)
        self.app = app
        self.result = None
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)
        body = ctk.CTkScrollableFrame(self)
        body.grid(row=0, column=0, sticky="nsew", padx=12, pady=(12, 4))
        ctk.CTkLabel(body, text=app.get("name", "Application"),
                     font=ctk.CTkFont(size=21, weight="bold")).pack(
            padx=16, pady=(12, 6), anchor="w")
        ctk.CTkLabel(body, text="Set the limits that apply to this Windows account.",
                     text_color="gray").pack(padx=16, pady=(0, 12), anchor="w")
        self.daily = self.field(body, "Daily allowance (minutes)", str(app.get("daily", 60)))
        self.session = self.field(body, "Per-session limit (minutes)", str(app.get("session", 30)))
        self.warn = self.field(body, "Warning before limit (minutes)", str(app.get("warning", 5)))
        self.schedule_var = tk.BooleanVar(value=bool(app.get("schedule_enabled", False)))
        ctk.CTkCheckBox(body, text="Restrict to allowed hours", variable=self.schedule_var).pack(
            padx=16, pady=(12, 6), anchor="w")
        self.start = self.field(body, "Allowed from (HH:MM)", app.get("schedule_start", "15:00"))
        self.end = self.field(body, "Allowed until (HH:MM)", app.get("schedule_end", "21:00"))
        self.weekend_var = tk.BooleanVar(value=bool(app.get("weekend_extra", False)))
        ctk.CTkCheckBox(body, text="Use a separate weekend allowance", variable=self.weekend_var).pack(
            padx=16, pady=(12, 6), anchor="w")
        self.weekday = self.field(body, "Weekday daily allowance (minutes)",
                                  str(app.get("weekday_daily", app.get("daily", 60))))
        self.weekend = self.field(body, "Weekend daily allowance (minutes)",
                                  str(app.get("weekend_daily", app.get("daily", 90))))
        self.break_var = tk.BooleanVar(value=bool(app.get("break_enabled", False)))
        ctk.CTkCheckBox(body, text="Require a break after continuous use", variable=self.break_var).pack(
            padx=16, pady=(12, 6), anchor="w")
        self.break_after = self.field(body, "Continuous use before break (minutes)", str(app.get("break_after", 45)))
        self.break_for = self.field(body, "Break duration (minutes)", str(app.get("break_for", 10)))
        ctk.CTkLabel(body, text="Weekend means Saturday and Sunday. Schedule window can cross midnight.",
                     text_color="gray", wraplength=480).pack(padx=16, pady=12, anchor="w")
        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.grid(row=1, column=0, sticky="ew", padx=12, pady=12)
        ctk.CTkButton(footer, text="Save rules", command=self.save, width=140).pack(side="right", padx=6)
        ctk.CTkButton(footer, text="Cancel", command=self.destroy, width=100,
                      fg_color="gray").pack(side="right", padx=6)
        self.transient(parent)
        self.update_idletasks()
        self.lift()
        self.focus_force()
        self.grab_set()
        self.wait_window(self)

    def field(self, parent, label, default):
        ctk.CTkLabel(parent, text=label).pack(padx=16, pady=(7, 2), anchor="w")
        entry = ctk.CTkEntry(parent, width=450)
        entry.insert(0, default)
        entry.pack(padx=16, pady=(0, 4), anchor="w")
        return entry

    def save(self):
        try:
            daily, session, warning = int(self.daily.get()), int(self.session.get()), int(self.warn.get())
            weekday, weekend = int(self.weekday.get()), int(self.weekend.get())
            break_after, break_for = int(self.break_after.get()), int(self.break_for.get())
            if not all(1 <= x <= 1440 for x in [daily, session, weekday, weekend]):
                raise ValueError("Daily and session limits must be between 1 and 1440 minutes.")
            if not 0 <= warning <= 60:
                raise ValueError("Warning must be between 0 and 60 minutes.")
            if not 1 <= break_after <= 1440 or not 1 <= break_for <= 240:
                raise ValueError("Break settings are outside the supported range.")
            if self.break_var.get() and break_after >= session:
                raise ValueError("Break must trigger before the session limit.")
            start, end = self.start.get().strip(), self.end.get().strip()
            if self.schedule_var.get() and (parse_time(start) is None or parse_time(end) is None or parse_time(start) == parse_time(end)):
                raise ValueError("Enter valid, different schedule times in HH:MM format.")
            self.result = {
                "daily": daily, "session": session, "warning": warning,
                "schedule_enabled": self.schedule_var.get(), "schedule_start": start, "schedule_end": end,
                "weekend_extra": self.weekend_var.get(), "weekday_daily": weekday, "weekend_daily": weekend,
                "break_enabled": self.break_var.get(), "break_after": break_after, "break_for": break_for,
            }
            self.destroy()
        except ValueError as exc:
            messagebox.showerror(APP_NAME, str(exc), parent=self)


class LockerApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        ctk.set_appearance_mode("System")
        ctk.set_default_color_theme("blue")
        self.title(f"{APP_NAME} V{APP_VERSION}")
        self.geometry("1120x740")
        self.minsize(980, 650)
        self.cfg = load_profile()
        self.events = queue.Queue()
        self.stop_event = threading.Event()
        self.monitor_thread = None
        self.state_lock = threading.RLock()
        self.auth = {}          # app key -> {override, created, seen}
        self.pending = set()
        self.break_notified = set()
        self.runtime = {}       # app key -> session seconds / break state
        self.last_save = time.monotonic()
        self.tray = None
        self.closing = False
        self.username = os.environ.get("USERNAME", "Windows user")
        self.reset_day()
        self.build_shell()
        self.refresh_dashboard()
        self.after(250, self.handle_events)
        self.after(1200, self.refresh_dashboard)
        self.protocol("WM_DELETE_WINDOW", self.minimize_to_tray)
        if not self.cfg.get("admin_password"):
            self.after(400, self.first_setup)
        else:
            self.start_monitor()

    def reset_day(self):
        today = date.today().isoformat()
        if self.cfg.get("usage_date") != today:
            self.cfg["usage_date"] = today
            self.cfg["usage"] = {}
            # Keep historical daily totals for the weekly report.
            self.cfg.setdefault("history", {})
            save_profile(self.cfg)

    def build_shell(self):
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        side = ctk.CTkFrame(self, width=220, corner_radius=0)
        side.grid(row=0, column=0, sticky="nsew")
        side.grid_propagate(False)
        ctk.CTkLabel(side, text="◈  PC APP LOCKER", font=ctk.CTkFont(size=19, weight="bold")).pack(
            padx=18, pady=(28, 4), anchor="w"
        )
        ctk.CTkLabel(side, text="PERSONAL SECURITY  •  FAMILY", font=ctk.CTkFont(size=9), text_color="gray").pack(
            padx=20, pady=(0, 28), anchor="w"
        )
        self.nav_buttons = {}
        for label, command in [
            ("Overview", self.show_overview),
            ("Protected apps", self.show_apps),
            ("Usage reports", self.show_reports),
            ("Settings", self.show_settings),
        ]:
            btn = ctk.CTkButton(side, text=label, anchor="w", height=42, fg_color="transparent",
                                text_color=("gray10", "gray90"), hover_color=("gray80", "gray25"),
                                command=command)
            btn.pack(fill="x", padx=12, pady=4)
            self.nav_buttons[label] = btn
        ctk.CTkFrame(side, height=2, fg_color=("gray80", "gray25")).pack(fill="x", padx=16, pady=20)
        ctk.CTkLabel(side, text="WINDOWS PROFILE", text_color="gray", font=ctk.CTkFont(size=10, weight="bold")).pack(
            padx=18, anchor="w"
        )
        ctk.CTkLabel(side, text=self.username, font=ctk.CTkFont(size=14, weight="bold")).pack(
            padx=18, pady=(4, 2), anchor="w"
        )
        ctk.CTkLabel(side, text="Separate settings for this account", text_color="gray",
                     wraplength=180, justify="left").pack(padx=18, anchor="w")
        ctk.CTkButton(side, text="Minimize to tray", command=self.hide_window,
                      fg_color=("gray75", "gray25"), text_color=("gray10", "gray95")).pack(
            side="bottom", fill="x", padx=14, pady=18
        )

        self.main = ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")
        self.main.grid(row=0, column=1, sticky="nsew", padx=26, pady=24)
        self.main.grid_columnconfigure(0, weight=1)
        self.page = "Overview"

    def clear_main(self):
        for child in self.main.winfo_children():
            child.destroy()

    def heading(self, title, subtitle):
        ctk.CTkLabel(self.main, text=title, font=ctk.CTkFont(size=29, weight="bold")).pack(anchor="w")
        ctk.CTkLabel(self.main, text=subtitle, text_color="gray", font=ctk.CTkFont(size=13)).pack(
            anchor="w", pady=(3, 18)
        )

    def stat_card(self, parent, title, value, note):
        card = ctk.CTkFrame(parent, corner_radius=14)
        card.pack(side="left", fill="both", expand=True, padx=6)
        ctk.CTkLabel(card, text=title.upper(), text_color="gray", font=ctk.CTkFont(size=10, weight="bold")).pack(
            padx=16, pady=(15, 4), anchor="w"
        )
        ctk.CTkLabel(card, text=value, font=ctk.CTkFont(size=27, weight="bold")).pack(
            padx=16, anchor="w"
        )
        ctk.CTkLabel(card, text=note, text_color="gray", font=ctk.CTkFont(size=11)).pack(
            padx=16, pady=(2, 14), anchor="w"
        )

    def show_overview(self):
        self.page = "Overview"
        self.clear_main()
        self.heading("Good day, " + self.username, "Here's the screen-time and protection summary for this Windows account.")
        total = sum(self.cfg.get("usage", {}).values())
        app_count = len(self.cfg.get("apps", []))
        active = "Running" if self.monitor_thread and self.monitor_thread.is_alive() else "Stopped"
        cards = ctk.CTkFrame(self.main, fg_color="transparent")
        cards.pack(fill="x", pady=(0, 18))
        self.stat_card(cards, "Today's usage", fmt_time(total), "Tracked app runtime")
        self.stat_card(cards, "Protected apps", str(app_count), "Configured for this account")
        self.stat_card(cards, "Protection", active, "Background monitor status")

        ctk.CTkLabel(self.main, text="Application usage today", font=ctk.CTkFont(size=18, weight="bold")).pack(
            anchor="w", pady=(8, 10)
        )
        for app in self.cfg.get("apps", []):
            key = app.get("key")
            used = int(self.cfg.get("usage", {}).get(key, 0))
            limit = self.daily_limit_for(app, datetime.now()) * 60
            ratio = min(1.0, used / limit) if limit else 0
            row = ctk.CTkFrame(self.main, corner_radius=12)
            row.pack(fill="x", pady=5)
            top = ctk.CTkFrame(row, fg_color="transparent")
            top.pack(fill="x", padx=14, pady=(10, 3))
            ctk.CTkLabel(top, text=app.get("name", "App"), font=ctk.CTkFont(size=14, weight="bold")).pack(side="left")
            ctk.CTkLabel(top, text=f"{fmt_time(used)} / {limit // 60} min", text_color="gray").pack(side="right")
            bar = ctk.CTkProgressBar(row, height=9)
            bar.pack(fill="x", padx=14, pady=(3, 12))
            bar.set(ratio)
        if not self.cfg.get("apps"):
            ctk.CTkLabel(self.main, text="No protected apps yet. Add an application to get started.",
                         text_color="gray").pack(anchor="w", pady=20)
        ctk.CTkButton(self.main, text="Manage protected apps", command=self.show_apps, width=200).pack(
            anchor="w", pady=14
        )

    def show_apps(self):
        self.page = "Protected apps"
        self.clear_main()
        self.heading("Protected applications", "Choose protected apps and configure their time rules. Launches are automatic while time remains.")
        bar = ctk.CTkFrame(self.main, fg_color="transparent")
        bar.pack(fill="x", pady=(0, 12))
        ctk.CTkButton(bar, text="+ Add application", command=self.add_app).pack(side="left")
        ctk.CTkButton(bar, text="Refresh", command=self.show_apps, fg_color=("gray75", "gray25"),
                      text_color=("gray10", "gray95")).pack(side="left", padx=8)

        for app in self.cfg.get("apps", []):
            key = app.get("key")
            used = int(self.cfg.get("usage", {}).get(key, 0))
            limit = self.daily_limit_for(app, datetime.now())
            sched = f"{app.get('schedule_start')}–{app.get('schedule_end')}" if app.get("schedule_enabled") else "Any time"
            card = ctk.CTkFrame(self.main, corner_radius=13)
            card.pack(fill="x", pady=6)
            top = ctk.CTkFrame(card, fg_color="transparent")
            top.pack(fill="x", padx=14, pady=(12, 4))
            ctk.CTkLabel(top, text=app.get("name", "App"), font=ctk.CTkFont(size=16, weight="bold")).pack(side="left")
            ctk.CTkButton(top, text="Time rules", width=105, height=30,
                          command=lambda a=app: self.edit_app(a)).pack(side="right")
            ctk.CTkButton(top, text="Remove", width=80, height=30, fg_color="#9b3434",
                          hover_color="#762727", command=lambda a=app: self.remove_app(a)).pack(side="right", padx=6)
            ctk.CTkLabel(card, text=f"Daily: {limit} min   •   Session: {app.get('session', 30)} min   •   Schedule: {sched}",
                         text_color="gray").pack(anchor="w", padx=14, pady=(0, 3))
            ctk.CTkLabel(card, text=f"Used today: {fmt_time(used)}   •   Executable: {app.get('path', '')}",
                         text_color="gray", wraplength=800, justify="left").pack(anchor="w", padx=14, pady=(0, 12))
        if not self.cfg.get("apps"):
            ctk.CTkLabel(self.main, text="Your app list is empty.", text_color="gray").pack(anchor="w", pady=20)

    def show_reports(self):
        self.page = "Usage reports"
        self.clear_main()
        self.heading("Usage reports", "Usage totals are stored separately for the signed-in Windows account.")
        today_total = sum(self.cfg.get("usage", {}).values())
        history = self.cfg.get("history", {})
        week_dates = [(date.today() - __import__("datetime").timedelta(days=i)).isoformat() for i in range(7)]
        week_total = sum(sum(history.get(day, {}).values()) for day in week_dates)
        week_total += today_total
        cards = ctk.CTkFrame(self.main, fg_color="transparent")
        cards.pack(fill="x")
        self.stat_card(cards, "Today's total", fmt_time(today_total), date.today().strftime("%A, %d %B %Y"))
        self.stat_card(cards, "Last 7 days", fmt_time(week_total), "Includes today")
        ctk.CTkLabel(self.main, text="Daily usage — last 7 days", font=ctk.CTkFont(size=18, weight="bold")).pack(
            anchor="w", pady=(24, 10)
        )
        for day in reversed(week_dates):
            per_app = history.get(day, {})
            if day == date.today().isoformat():
                per_app = self.cfg.get("usage", {})
            total_day = sum(per_app.values())
            line = ctk.CTkFrame(self.main, corner_radius=10)
            line.pack(fill="x", pady=3)
            ctk.CTkLabel(line, text=day, width=130, anchor="w").pack(side="left", padx=12, pady=9)
            ctk.CTkLabel(line, text=fmt_time(total_day), text_color="gray").pack(side="right", padx=12)
        ctk.CTkButton(self.main, text="Export last 7 days to CSV", command=self.export_csv).pack(
            anchor="w", pady=20
        )

    def show_settings(self):
        self.page = "Settings"
        self.clear_main()
        self.heading("Settings & security", "Manage the protection profile for this Windows account.")
        ctk.CTkButton(self.main, text="Change admin password", command=self.change_credentials, width=240).pack(
            anchor="w", pady=8
        )
        ctk.CTkButton(self.main, text="Generate / replace recovery key", command=self.generate_recovery_key,
                      width=240, fg_color=("gray70", "gray30")).pack(anchor="w", pady=8)
        ctk.CTkButton(self.main, text="Recover forgotten password", command=self.recover_password,
                      width=240, fg_color=("gray70", "gray30")).pack(anchor="w", pady=8)
        self.startup_var = tk.BooleanVar(value=bool(self.cfg.get("startup", False)))
        ctk.CTkCheckBox(self.main, text="Start PC App Locker when this Windows account signs in",
                        variable=self.startup_var, command=self.toggle_startup).pack(anchor="w", pady=12)
        ctk.CTkLabel(self.main, text=f"Profile storage: {CONFIG_FILE}", text_color="gray",
                     wraplength=800, justify="left").pack(anchor="w", pady=10)
        ctk.CTkLabel(self.main,
                     text="Each Windows account has a separate profile. Sign into each account and configure its rules. "
                          "This release does not yet provide a central parent console to administer other accounts.",
                     text_color="gray", wraplength=850, justify="left").pack(anchor="w", pady=10)
        ctk.CTkLabel(self.main,
                     text="Security note: a local administrator can stop this user-session monitor. "
                          "Use a standard account for children and OS-level policy enforcement for stronger controls.",
                     text_color="#D39A35", wraplength=850, justify="left").pack(anchor="w", pady=10)

    def recover_password(self):
        if not self.cfg.get("recovery"):
            messagebox.showwarning(APP_NAME, "No recovery key is configured. Generate one while you still know the admin password.")
            return
        key = CredentialPrompt(self, "Password recovery", "Enter your saved recovery key.").result
        if key is None:
            return
        if not check_secret(key.strip().upper(), self.cfg.get("recovery", {})):
            self.record_failed_attempt()
            messagebox.showerror(APP_NAME, "Recovery key not recognised.")
            return
        self.change_credentials(first=False)

    def generate_recovery_key(self):
        if not messagebox.askyesno(APP_NAME, "Generate a new recovery key? Any previous key will stop working."):
            return
        recovery_key = secrets.token_hex(4).upper() + "-" + secrets.token_hex(4).upper()
        self.cfg["recovery"] = make_secret(recovery_key)
        save_profile(self.cfg)
        messagebox.showinfo(APP_NAME, "Write this recovery key down and keep it somewhere safe. It is shown only once:\\n\\n" + recovery_key)

    def daily_limit_for(self, app, now):
        if app.get("weekend_extra") and now.weekday() >= 5:
            return int(app.get("weekend_daily", app.get("daily", 60)))
        if app.get("weekend_extra"):
            return int(app.get("weekday_daily", app.get("daily", 60)))
        return int(app.get("daily", 60))

    def first_setup(self):
        messagebox.showinfo(APP_NAME, "Create one parent/admin password. Roblox and other protected apps will open without authentication while time remains.")
        self.change_credentials(first=True)

    def change_credentials(self, first=False):
        password = CredentialPrompt(self, "Set admin password", "Create one alphanumeric admin password (minimum 6 characters).", confirm=True).result
        if password is None:
            return
        if len(password) < 6 or not any(c.isalpha() for c in password) or not any(c.isdigit() for c in password):
            messagebox.showerror(APP_NAME, "Password must be at least 6 characters and contain both letters and numbers.")
            return
        self.cfg["admin_password"] = make_secret(password)
        # Generate a one-time recovery key on first setup; only its hash is stored.
        if not self.cfg.get("recovery"):
            recovery_key = secrets.token_hex(4).upper() + "-" + secrets.token_hex(4).upper()
            self.cfg["recovery"] = make_secret(recovery_key)
            save_profile(self.cfg)
            messagebox.showinfo(APP_NAME, "Save this recovery key somewhere safe. It is shown only once:\n\n" + recovery_key)
        else:
            save_profile(self.cfg)
            messagebox.showinfo(APP_NAME, "Admin password saved.")
        self.start_monitor()
        if self.page == "Overview":
            self.show_overview()

    def add_app(self):
        path = filedialog.askopenfilename(title="Select application executable",
                                          filetypes=[("Windows applications", "*.exe")])
        if not path:
            return
        path = os.path.abspath(path)
        key = hashlib.sha256(os.path.normcase(path).encode("utf-8")).hexdigest()[:16]
        if any(a.get("key") == key for a in self.cfg.get("apps", [])):
            messagebox.showinfo(APP_NAME, "This application is already protected.")
            return
        self.cfg["apps"].append({
            "key": key, "name": Path(path).stem, "path": path,
            "process": Path(path).name.lower(),
            "daily": 60, "session": 30, "warning": 5,
            "schedule_enabled": False, "schedule_start": "15:00", "schedule_end": "21:00",
            "weekend_extra": False, "weekday_daily": 60, "weekend_daily": 90,
            "break_enabled": False, "break_after": 45, "break_for": 10,
            "days": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
        })
        save_profile(self.cfg)
        self.show_apps()

    def edit_app(self, app):
        try:
            dialog = AppEditor(self, app)
            result = dialog.result
            if result:
                app.update(result)
                save_profile(self.cfg)
                self.show_apps()
        except Exception as exc:
            try:
                self.grab_release()
            except Exception:
                pass
            self.lift()
            messagebox.showerror(APP_NAME, f"Could not open application rules.\n\n{exc}", parent=self)

    def remove_app(self, app):
        if messagebox.askyesno(APP_NAME, f"Remove {app.get('name')} from protection?"):
            self.cfg["apps"] = [a for a in self.cfg["apps"] if a.get("key") != app.get("key")]
            save_profile(self.cfg)
            self.show_apps()

    def toggle_startup(self):
        try:
            enabled = bool(self.startup_var.get())
            set_startup(enabled)
            self.cfg["startup"] = enabled
            save_profile(self.cfg)
            messagebox.showinfo(APP_NAME, "Startup setting updated for this Windows account.")
        except Exception as exc:
            self.startup_var.set(False)
            messagebox.showerror(APP_NAME, f"Could not update startup setting:\n{exc}")

    def export_csv(self):
        target = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV files", "*.csv")],
                                              initialfile=f"AppUsage-{date.today().isoformat()}.csv")
        if not target:
            return
        import csv
        with open(target, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(["Windows user", "Date", "Application", "Executable", "Usage seconds", "Usage"])
            for app in self.cfg.get("apps", []):
                seconds = int(self.cfg.get("usage", {}).get(app.get("key"), 0))
                writer.writerow([self.username, date.today().isoformat(), app.get("name"),
                                 app.get("path"), seconds, fmt_time(seconds)])
        messagebox.showinfo(APP_NAME, f"Report exported:\n{target}")

    def start_monitor(self):
        if self.monitor_thread and self.monitor_thread.is_alive():
            return
        self.stop_event.clear()
        self.monitor_thread = threading.Thread(target=self.monitor_loop, daemon=True)
        self.monitor_thread.start()

    def process_for_app(self, proc, app):
        try:
            exe = proc.info.get("exe") or ""
            if exe:
                return os.path.normcase(os.path.abspath(exe)) == os.path.normcase(os.path.abspath(app["path"]))
            return (proc.info.get("name") or "").lower() == app.get("process", "")
        except Exception:
            return False

    def kill_app(self, app):
        target = os.path.normcase(os.path.abspath(app["path"]))
        for proc in psutil.process_iter(["pid", "name", "exe"]):
            try:
                if self.process_for_app(proc, app):
                    proc.terminate()
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                pass
        time.sleep(0.12)
        for proc in psutil.process_iter(["pid", "name", "exe"]):
            try:
                if self.process_for_app(proc, app):
                    proc.kill()
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                pass

    def restriction_reason(self, app, now, daily_used, session_used):
        if not allowed_today(app, now):
            return "schedule"
        if not in_schedule(app, now):
            return "schedule"
        if daily_used >= self.daily_limit_for(app, now) * 60:
            return "daily"
        if session_used >= int(app.get("session", 30)) * 60:
            return "session"
        return None

    def monitor_loop(self):
        last_tick = time.monotonic()
        while not self.stop_event.is_set():
            now_mono = time.monotonic()
            now_dt = datetime.now()
            self.reset_day()
            dt = max(0.0, now_mono - last_tick)
            last_tick = now_mono

            for app in list(self.cfg.get("apps", [])):
                key = app.get("key")
                break_until = float(self.cfg.get("breaks", {}).get(key, 0))
                if break_until and time.time() >= break_until:
                    self.cfg.get("breaks", {}).pop(key, None)
                    self.break_notified.discard(key)
                matches = []
                for proc in psutil.process_iter(["pid", "name", "exe"]):
                    try:
                        if self.process_for_app(proc, app):
                            matches.append(proc)
                    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                        continue

                if matches and break_until and time.time() < break_until:
                    self.kill_app(app)
                    if key not in self.break_notified:
                        self.break_notified.add(key)
                        self.events.put(("break", app, break_until - time.time()))
                    continue

                auth = self.auth.get(key)
                if not matches:
                    self.runtime.pop(key, None)
                    if auth and (auth.get("seen") or now_mono - auth.get("created", now_mono) > 20):
                        self.auth.pop(key, None)
                    continue

                if auth:
                    auth["seen"] = True
                if not auth:
                    reason = self.restriction_reason(
                        app, now_dt, float(self.cfg.get("usage", {}).get(key, 0)), 0
                    )
                    if reason:
                        self.kill_app(app)
                        if key not in self.pending:
                            self.pending.add(key)
                            self.events.put(("unlock", app, reason))
                        continue
                    # Normal launch/relaunch: no credentials while limits remain.
                    self.auth[key] = {"override": False, "created": now_mono, "seen": True}
                    auth = self.auth[key]

                if auth.get("override"):
                    # Overrides bypass restrictions for this run, but remain included in usage reports.
                    self.cfg["usage"][key] = float(self.cfg.get("usage", {}).get(key, 0)) + dt
                    day_key = now_dt.date().isoformat()
                    self.cfg.setdefault("history", {}).setdefault(day_key, {})
                    self.cfg["history"][day_key][key] = float(
                        self.cfg["history"][day_key].get(key, 0)
                    ) + dt
                    continue

                state = self.runtime.setdefault(key, {"session": 0.0, "warning_sent": set(), "break_until": 0.0})
                if state.get("break_until", 0) > now_mono:
                    self.kill_app(app)
                    self.auth.pop(key, None)
                    self.pending.add(key)
                    self.events.put(("break", app, state["break_until"] - now_mono))
                    continue
                state["session"] += dt
                self.cfg.setdefault("usage", {})[key] = float(self.cfg.get("usage", {}).get(key, 0)) + dt
                daily_used = self.cfg["usage"][key]
                session_used = state["session"]

                # Break requirement based on continuous app runtime.
                if app.get("break_enabled") and session_used >= int(app.get("break_after", 45)) * 60:
                    break_seconds = int(app.get("break_for", 10)) * 60
                    self.kill_app(app)
                    self.auth.pop(key, None)
                    self.runtime.pop(key, None)
                    self.cfg.setdefault("breaks", {})[key] = time.time() + break_seconds
                    self.break_notified.add(key)
                    self.pending.add(key)
                    self.events.put(("break", app, break_seconds))
                    continue

                # Warning once per threshold per session.
                remaining_session = int(app.get("session", 30)) * 60 - session_used
                remaining_daily = self.daily_limit_for(app, now_dt) * 60 - daily_used
                warn = int(app.get("warning", 5)) * 60
                for kind, remaining in [("session", remaining_session), ("daily", remaining_daily)]:
                    day_marker = int(now_dt.timestamp()) // 86400
                    thresholds = sorted(set([warn, 60]), reverse=True)
                    for threshold in thresholds:
                        marker = f"{kind}_{threshold}_{day_marker}"
                        if threshold > 0 and 0 < remaining <= threshold and marker not in state["warning_sent"]:
                            state["warning_sent"].add(marker)
                            self.events.put(("warning", app, kind, max(1, int(remaining))))
                reason = self.restriction_reason(app, now_dt, daily_used, session_used)
                if reason:
                    self.kill_app(app)
                    self.auth.pop(key, None)
                    self.runtime.pop(key, None)
                    self.pending.add(key)
                    self.events.put(("unlock", app, reason))

            if now_mono - self.last_save >= SAVE_SECONDS:
                save_profile(self.cfg)
                self.last_save = now_mono
                self.events.put(("refresh",))
            time.sleep(POLL_SECONDS)
        save_profile(self.cfg)

    def handle_events(self):
        try:
            while True:
                event = self.events.get_nowait()
                if event[0] == "unlock":
                    _, app, reason = event
                    self.prompt_unlock(app, reason)
                elif event[0] == "warning":
                    _, app, kind, seconds = event
                    self.show_warning(app, kind, seconds)
                elif event[0] == "break":
                    _, app, seconds = event
                    self.pending.discard(app.get("key"))
                    self.show_break(app, seconds)
                elif event[0] == "refresh":
                    if self.page == "Overview":
                        self.show_overview()
        except queue.Empty:
            pass
        if not self.closing:
            self.after(250, self.handle_events)

    def prompt_unlock(self, app, reason):
        now_epoch = time.time()
        locked_until = float(self.cfg.get("lockout_until", 0))
        if now_epoch < locked_until:
            remaining = max(1, int((locked_until - now_epoch + 59) // 60))
            messagebox.showerror(APP_NAME, f"Authentication is temporarily locked. Try again in about {remaining} minute(s).", parent=self)
            self.pending.discard(app["key"])
            return
        self.deiconify()
        self.lift()
        self.attributes("-topmost", True)
        self.after(800, lambda: self.attributes("-topmost", False))
        text = {
            "daily": "The daily allowance has expired.",
            "session": "The per-session time limit has expired.",
            "schedule": "This app is outside its allowed schedule.",
        }.get(reason, "The app is currently restricted.")
        if not messagebox.askyesno(APP_NAME, f"{app.get('name')}\\n\\n{text}\\n\\nEnter the admin password to grant a one-run override?"):
            self.pending.discard(app["key"])
            return
        password = CredentialPrompt(self, "Admin password", "Enter the parent/admin password.").result
        if password is None or not check_secret(password, self.cfg.get("admin_password", {})):
            self.record_failed_attempt()
            messagebox.showerror(APP_NAME, "Incorrect password. Access denied.", parent=self)
            self.pending.discard(app["key"])
            return
        self.cfg["failed_attempts"] = 0
        self.cfg["lockout_until"] = 0
        save_profile(self.cfg)
        if not Path(app["path"]).is_file():
            messagebox.showerror(APP_NAME, "The executable path no longer exists. Remove and add the app again.")
            self.pending.discard(app["key"])
            return
        self.auth[app["key"]] = {"override": True, "created": time.monotonic(), "seen": False}
        self.pending.discard(app["key"])
        try:
            subprocess.Popen([app["path"]], cwd=str(Path(app["path"]).parent))
        except Exception as exc:
            self.auth.pop(app["key"], None)
            messagebox.showerror(APP_NAME, f"Could not start application:\\n{exc}")

    def record_failed_attempt(self):
        self.cfg["failed_attempts"] = int(self.cfg.get("failed_attempts", 0)) + 1
        if self.cfg["failed_attempts"] >= 5:
            self.cfg["failed_attempts"] = 0
            self.cfg["lockout_until"] = time.time() + 300
        save_profile(self.cfg)

    def show_warning(self, app, kind, seconds):
        mins = max(1, (seconds + 59) // 60)
        self.bell()
        messagebox.showwarning(APP_NAME, f"{app.get('name')} has about {mins} minute(s) of {kind} time remaining.", parent=self)

    def show_break(self, app, seconds):
        mins = max(1, int((seconds + 59) // 60))
        messagebox.showinfo(APP_NAME, f"{app.get('name')} has been paused for a required break. Try again in about {mins} minute(s).", parent=self)

    def refresh_dashboard(self):
        self.show_overview()

    def hide_window(self):
        self.withdraw()
        self.ensure_tray()

    def minimize_to_tray(self):
        self.hide_window()

    def ensure_tray(self):
        if pystray is None or self.tray is not None:
            return
        try:
            img = Image.new("RGB", (64, 64), "#1f6aa5")
            draw = ImageDraw.Draw(img)
            draw.rounded_rectangle((10, 10, 54, 54), radius=10, outline="white", width=4)
            draw.text((22, 18), "L", fill="white")
            menu = pystray.Menu(
                pystray.MenuItem("Open PC App Locker", lambda: self.after(0, self.deiconify)),
                pystray.MenuItem("Exit (stop protection)", lambda: self.after(0, self.exit_app)),
            )
            self.tray = pystray.Icon("PCAppLocker", img, APP_NAME, menu)
            threading.Thread(target=self.tray.run, daemon=True).start()
        except Exception:
            self.tray = None
            self.deiconify()

    def exit_app(self):
        if messagebox.askyesno(APP_NAME, "Exit and stop app monitoring?"):
            self.closing = True
            self.stop_event.set()
            try:
                if self.tray:
                    self.tray.stop()
            except Exception:
                pass
            self.destroy()

    def export_csv(self):
        from tkinter import filedialog
        import csv
        target = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv")],
            initialfile=f"AppUsage-Last7Days-{date.today().isoformat()}.csv"
        )
        if not target:
            return
        days = [(date.today() - __import__("datetime").timedelta(days=i)).isoformat() for i in range(7)]
        with open(target, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(["Windows user", "Date", "Application", "Executable", "Usage seconds", "Usage"])
            for day in reversed(days):
                day_data = self.cfg.get("history", {}).get(day, {})
                if day == date.today().isoformat():
                    day_data = self.cfg.get("usage", {})
                for app in self.cfg.get("apps", []):
                    seconds = int(day_data.get(app.get("key"), 0))
                    writer.writerow([self.username, day, app.get("name"), app.get("path"), seconds, fmt_time(seconds)])
        messagebox.showinfo(APP_NAME, f"Last 7 days exported:\n{target}")

    def on_closing(self):
        self.minimize_to_tray()


def main():
    app = LockerApp()
    app.mainloop()


if __name__ == "__main__":
    main()
