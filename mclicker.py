import sys
import os
import time
import json
import random
import threading
import math
import webbrowser
from pathlib import Path
import tkinter as tk
from tkinter import messagebox
import customtkinter as ctk
from pynput import keyboard, mouse
from PIL import Image
import pystray

def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return Path(base_path) / relative_path

def data_dir():
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
    else:
        base = os.path.expanduser("~")
    d = Path(base) / "MClicker"
    d.mkdir(parents=True, exist_ok=True)
    return d

if sys.platform == "win32":
    import ctypes
    import ctypes.wintypes as wintypes

ctk.set_appearance_mode("Dark")

CONFIG_FILE = data_dir() / "mclicker_config.json"
SETTINGS_FILE = data_dir() / "mclicker_settings.json"
ICON_ICO = resource_path("colorx_icon.ico")
ICON_PNG = resource_path("1.png")

FONT_FAMILY = "Segoe UI"
COLOR_BG = "#101010"
COLOR_CARD = "#1C1C1C"
COLOR_BORDER = "#333333"
COLOR_ACCENT = "#F5A623"
COLOR_ACCENT_HOVER = "#D48A14"
COLOR_TEXT_MAIN = "#FFFFFF"
COLOR_TEXT_SUB = "#999999"
COLOR_DANGER = "#E53935"

MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010

INJECTED_MARKER = 0xC1A55E17

if sys.platform == "win32":
    WH_MOUSE_LL = 14
    WM_LBUTTONDOWN = 0x0201
    WM_LBUTTONUP = 0x0202
    WM_RBUTTONDOWN = 0x0204
    WM_RBUTTONUP = 0x0205

    ULONG_PTR = ctypes.c_size_t

    class MSLLHOOKSTRUCT(ctypes.Structure):
        _fields_ = [
            ("pt", wintypes.POINT),
            ("mouseData", wintypes.DWORD),
            ("flags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", ULONG_PTR),
        ]

    LowLevelMouseProc = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)

    ctypes.windll.user32.SetWindowsHookExA.restype = wintypes.HANDLE
    ctypes.windll.user32.SetWindowsHookExA.argtypes = [ctypes.c_int, LowLevelMouseProc, wintypes.HINSTANCE, wintypes.DWORD]
    ctypes.windll.user32.CallNextHookEx.restype = wintypes.LPARAM
    ctypes.windll.user32.CallNextHookEx.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
    ctypes.windll.user32.mouse_event.restype = None
    ctypes.windll.user32.mouse_event.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ULONG_PTR]
    ctypes.windll.user32.GetMessageW.restype = ctypes.c_int
    ctypes.windll.user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, ctypes.c_uint, ctypes.c_uint]


class PhysicalMouseTracker:
    def __init__(self):
        self.left_down = False
        self.right_down = False
        self._proc = None

        if sys.platform == "win32":
            threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        def hook_callback(nCode, wParam, lParam):
            if nCode == 0:
                info = ctypes.cast(lParam, ctypes.POINTER(MSLLHOOKSTRUCT)).contents
                if info.dwExtraInfo != INJECTED_MARKER:
                    if wParam == WM_LBUTTONDOWN:
                        self.left_down = True
                    elif wParam == WM_LBUTTONUP:
                        self.left_down = False
                    elif wParam == WM_RBUTTONDOWN:
                        self.right_down = True
                    elif wParam == WM_RBUTTONUP:
                        self.right_down = False
            return ctypes.windll.user32.CallNextHookEx(None, nCode, wParam, lParam)

        self._proc = LowLevelMouseProc(hook_callback)
        ctypes.windll.user32.SetWindowsHookExA(WH_MOUSE_LL, self._proc, None, 0)

        msg = wintypes.MSG()
        while ctypes.windll.user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
            ctypes.windll.user32.TranslateMessage(ctypes.byref(msg))
            ctypes.windll.user32.DispatchMessageW(ctypes.byref(msg))

    def is_pressed(self, button):
        if sys.platform != "win32":
            return False
        return self.left_down if button == "Left" else self.right_down


class HardwareClicker:
    def __init__(self, ui_callback=None):
        self.mouse_controller = mouse.Controller()

        self.armed = False
        self.button = "Left"
        self.trigger_mode = "Toggle"

        self.min_cps = 10
        self.max_cps = 14

        self.use_fluctuate = True
        self.use_gaussian = True
        self.use_hold_time = True
        self.use_fatigue = True

        self.ui_callback = ui_callback
        self.click_count = 0
        self.last_cps_reset = time.time()

        self.physical_tracker = PhysicalMouseTracker()

        self.click_thread = threading.Thread(target=self._click_loop, daemon=True)
        self.click_thread.start()

    def _is_physically_pressed(self):
        return self.physical_tracker.is_pressed(self.button)

    def _click_loop(self):
        debounce_timeout = 0.05
        last_physical_down = 0

        while True:
            if not self.armed:
                time.sleep(0.02)
                continue

            should_click = False

            if self.trigger_mode == "Toggle":
                should_click = True
            elif self.trigger_mode == "Hold":
                if self._is_physically_pressed():
                    last_physical_down = time.time()
                    should_click = True
                else:
                    if time.time() - last_physical_down < debounce_timeout:
                        should_click = True
                    else:
                        should_click = False

            if should_click:
                actual_min = min(self.min_cps, self.max_cps)
                actual_max = max(self.min_cps, self.max_cps)

                if self.use_fluctuate:
                    time_sec = time.time()
                    mid_cps = (actual_min + actual_max) / 2.0
                    amplitude = (actual_max - actual_min) / 2.0
                    fluctuation = (math.sin(time_sec * 1.5) * amplitude) + random.uniform(-0.5, 0.5)
                    current_cps = mid_cps + fluctuation
                else:
                    current_cps = random.uniform(actual_min, actual_max)

                current_cps = max(1.0, current_cps)

                if self.use_fatigue and random.random() < 0.05:
                    current_cps = max(1.0, current_cps - random.uniform(2, 4))

                base_delay = 1.0 / current_cps

                if self.use_gaussian:
                    std_dev = base_delay * 0.15
                    delay = random.gauss(base_delay, std_dev)
                    delay = max(0.005, delay)
                else:
                    delay = base_delay

                hold_time = random.uniform(0.015, 0.035) if self.use_hold_time else 0.005

                active_button = self.button
                if active_button == "Left":
                    ctypes.windll.user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, INJECTED_MARKER)
                    time.sleep(hold_time)
                    ctypes.windll.user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, INJECTED_MARKER)
                else:
                    ctypes.windll.user32.mouse_event(MOUSEEVENTF_RIGHTDOWN, 0, 0, 0, INJECTED_MARKER)
                    time.sleep(hold_time)
                    ctypes.windll.user32.mouse_event(MOUSEEVENTF_RIGHTUP, 0, 0, 0, INJECTED_MARKER)

                remaining_delay = max(0.001, delay - hold_time)
                time.sleep(remaining_delay)

                self.click_count += 1
                self._update_cps_telemetry()
            else:
                time.sleep(0.01)

    def _update_cps_telemetry(self):
        now = time.time()
        elapsed = now - self.last_cps_reset
        if elapsed >= 0.5:
            actual_cps = self.click_count / elapsed
            if self.ui_callback:
                self.ui_callback(round(actual_cps, 1))
            self.click_count = 0
            self.last_cps_reset = now


class MClickerUI(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("MClicker")
        self.geometry("740x520")
        self.resizable(False, False)
        self.configure(fg_color=COLOR_BG)
        self._apply_window_icon()

        self.clicker = HardwareClicker(ui_callback=self.update_cps_display)

        self.clicker_hotkey_str = "f8"
        self.swap_hotkey_str = "f7"
        self._load_settings()

        self.shortcut_listener = keyboard.Listener(on_press=self._handle_global_shortcuts)
        self.shortcut_listener.start()

        self.tray_icon = None

        self.build_ui()

        self.protocol("WM_DELETE_WINDOW", self.hide_to_tray)

    def _apply_window_icon(self):
        if ICON_ICO.exists():
            try:
                self.iconbitmap(str(ICON_ICO))
            except Exception:
                pass
        if ICON_PNG.exists():
            try:
                self._icon_photo = tk.PhotoImage(file=str(ICON_PNG))
                self.iconphoto(True, self._icon_photo)
            except Exception:
                pass

    def _load_settings(self):
        if not SETTINGS_FILE.exists():
            return
        try:
            data = json.loads(SETTINGS_FILE.read_text())
            self.clicker_hotkey_str = data.get("hotkey_clicker", self.clicker_hotkey_str)
            self.swap_hotkey_str = data.get("hotkey_swap", self.swap_hotkey_str)
        except Exception:
            pass

    def _save_settings(self):
        try:
            SETTINGS_FILE.write_text(json.dumps({
                "hotkey_clicker": self.clicker_hotkey_str,
                "hotkey_swap": self.swap_hotkey_str,
            }, indent=4))
        except Exception:
            pass

    def _init_tray(self):
        if self.tray_icon is not None:
            return
        tray_image = Image.open(ICON_PNG) if ICON_PNG.exists() else Image.new("RGB", (64, 64), COLOR_ACCENT)
        menu = pystray.Menu(
            pystray.MenuItem("Show MClicker", self._tray_show, default=True),
            pystray.MenuItem("Quit", self._tray_quit),
        )
        self.tray_icon = pystray.Icon("MClicker", tray_image, "MClicker", menu)
        threading.Thread(target=self.tray_icon.run, daemon=True).start()

    def hide_to_tray(self):
        self._init_tray()
        self.withdraw()

    def _tray_show(self, icon=None, item=None):
        self.after(0, self.deiconify)

    def _tray_quit(self, icon=None, item=None):
        if self.tray_icon:
            self.tray_icon.stop()
        self.after(0, self._shutdown)

    def _shutdown(self):
        self._save_settings()
        self.destroy()
        os._exit(0)

    def build_ui(self):
        self.nav_frame = ctk.CTkFrame(self, height=50, corner_radius=0, fg_color=COLOR_BG)
        self.nav_frame.pack(fill="x", padx=15, pady=10)
        self.nav_frame.pack_propagate(False)

        if ICON_PNG.exists():
            self.logo_image = ctk.CTkImage(light_image=Image.open(ICON_PNG), dark_image=Image.open(ICON_PNG), size=(28, 28))
            ctk.CTkLabel(self.nav_frame, image=self.logo_image, text="").pack(side="left", padx=(10, 6))
        ctk.CTkLabel(self.nav_frame, text="MClicker", font=ctk.CTkFont(family=FONT_FAMILY, size=20, weight="bold"), text_color=COLOR_TEXT_MAIN).pack(side="left", padx=(0, 10))

        ctk.CTkLabel(self.nav_frame, text="DASHBOARD", font=ctk.CTkFont(family=FONT_FAMILY, size=13, weight="bold"), text_color=COLOR_ACCENT).pack(side="left", padx=20)

        self.btn_settings = ctk.CTkButton(self.nav_frame, text="SETTINGS", width=80, height=35, corner_radius=0, font=ctk.CTkFont(size=12, weight="bold"), fg_color=COLOR_CARD, hover_color=COLOR_BORDER, text_color=COLOR_TEXT_MAIN, command=lambda: self.select_view("settings"))
        self.btn_settings.pack(side="right")

        # Footer credit link, bottom right of the window.
        # Packed with side="bottom" BEFORE main_container so it reserves its
        # strip at the bottom; main_container then fills the remaining space.
        self.footer_frame = ctk.CTkFrame(self, height=24, corner_radius=0, fg_color=COLOR_BG)
        self.footer_frame.pack(side="bottom", fill="x", padx=15, pady=(0, 8))
        self.footer_frame.pack_propagate(False)

        self.lbl_credit = ctk.CTkLabel(
            self.footer_frame,
            text="made by GoldenRee",
            font=ctk.CTkFont(family=FONT_FAMILY, size=11, weight="bold", underline=False),
            text_color=COLOR_TEXT_SUB,
            cursor="hand2",
        )
        self.lbl_credit.pack(side="right")
        self.lbl_credit.bind("<Button-1>", self._open_credit_link)
        self.lbl_credit.bind("<Enter>", lambda e: self.lbl_credit.configure(text_color=COLOR_ACCENT))
        self.lbl_credit.bind("<Leave>", lambda e: self.lbl_credit.configure(text_color=COLOR_TEXT_SUB))

        self.main_container = ctk.CTkFrame(self, fg_color="transparent", corner_radius=0)
        self.main_container.pack(fill="both", expand=True, padx=15, pady=(0, 15))

        self.views = {}
        self.create_dashboard_view()
        self.create_settings_view()

        self.select_view("Dashboard")

    def _open_credit_link(self, event=None):
        webbrowser.open("https://github.com/GoldenRee")

    def _create_card(self, parent):
        return ctk.CTkFrame(parent, corner_radius=0, fg_color=COLOR_CARD, border_width=1, border_color=COLOR_BORDER)

    def create_dashboard_view(self):
        cv = ctk.CTkFrame(self.main_container, fg_color="transparent", corner_radius=0)
        self.views["Dashboard"] = cv

        left_col = ctk.CTkFrame(cv, fg_color="transparent", corner_radius=0)
        left_col.pack(side="left", fill="both", expand=True, padx=(0, 8))

        right_col = ctk.CTkFrame(cv, fg_color="transparent", corner_radius=0)
        right_col.pack(side="right", fill="both", expand=True, padx=(8, 0))

        config_card = self._create_card(left_col)
        config_card.pack(fill="x", pady=(0, 10))

        def _add_slider_row(parent, label_text, default_val, cmd):
            row = ctk.CTkFrame(parent, fg_color="transparent")
            row.pack(fill="x", padx=15, pady=12)
            lbl = ctk.CTkLabel(row, text=f"{label_text} [{default_val}]", font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"), text_color=COLOR_TEXT_MAIN)
            lbl.pack(side="left")
            slider = ctk.CTkSlider(row, from_=1, to=30, number_of_steps=29, width=130, button_color=COLOR_ACCENT, progress_color=COLOR_ACCENT, button_corner_radius=0, corner_radius=0, command=lambda v: self._update_slider_lbl(lbl, label_text, v, cmd))
            slider.set(default_val)
            slider.pack(side="right")
            return slider

        self.slider_min = _add_slider_row(config_card, "Min CPS", 10, lambda v: setattr(self.clicker, 'min_cps', v))
        self.slider_max = _add_slider_row(config_card, "Max CPS", 14, lambda v: setattr(self.clicker, 'max_cps', v))

        hk_row = ctk.CTkFrame(config_card, fg_color="transparent")
        hk_row.pack(fill="x", padx=15, pady=12)
        ctk.CTkLabel(hk_row, text="Activation Mode", font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold")).pack(side="left")

        self.seg_mode = ctk.CTkSegmentedButton(hk_row, values=["Toggle", "Hold"], corner_radius=0, command=lambda v: setattr(self.clicker, 'trigger_mode', v), selected_color=COLOR_BORDER, unselected_color=COLOR_BG)
        self.seg_mode.set("Toggle")
        self.seg_mode.pack(side="right")

        mb_row = ctk.CTkFrame(config_card, fg_color="transparent")
        mb_row.pack(fill="x", padx=15, pady=12)
        self.lbl_target_button = ctk.CTkLabel(mb_row, text=f"Target Button ({self.swap_hotkey_str.upper()} to swap)", font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"))
        self.lbl_target_button.pack(side="left")
        self.seg_btn = ctk.CTkSegmentedButton(mb_row, values=["Left", "Right"], corner_radius=0, command=lambda v: setattr(self.clicker, 'button', v), selected_color=COLOR_BORDER, unselected_color=COLOR_BG)
        self.seg_btn.set("Left")
        self.seg_btn.pack(side="right")

        tele_card = self._create_card(left_col)
        tele_card.pack(fill="x", pady=10)
        ctk.CTkLabel(tele_card, text="CPS OUTPUT", font=ctk.CTkFont(family=FONT_FAMILY, size=11, weight="bold"), text_color=COLOR_TEXT_SUB).pack(pady=(10, 0))
        self.lbl_realtime_cps = ctk.CTkLabel(tele_card, text="0.0", font=ctk.CTkFont(family=FONT_FAMILY, size=42, weight="bold"), text_color=COLOR_ACCENT)
        self.lbl_realtime_cps.pack(pady=(0, 10))

        self.btn_toggle = ctk.CTkButton(left_col, text=f"ARM MCLICKER ({self.clicker_hotkey_str.upper()})", corner_radius=0, font=ctk.CTkFont(family=FONT_FAMILY, size=14, weight="bold"), height=45, fg_color=COLOR_BORDER, hover_color=COLOR_CARD, command=self.toggle_clicker)
        self.btn_toggle.pack(fill="x", pady=10)

        def _build_feature_card(title, desc, attr_name):
            card = self._create_card(right_col)
            card.pack(fill="x", pady=(0, 12))

            top_row = ctk.CTkFrame(card, fg_color="transparent")
            top_row.pack(fill="x", padx=15, pady=(12, 5))
            ctk.CTkLabel(top_row, text=title, font=ctk.CTkFont(family=FONT_FAMILY, size=13, weight="bold")).pack(side="left")

            seg = ctk.CTkSegmentedButton(top_row, values=["OFF", "ON"], corner_radius=0, selected_color=COLOR_ACCENT, unselected_color=COLOR_BG, command=lambda v: setattr(self.clicker, attr_name, v == "ON"))
            seg.set("ON")
            seg.pack(side="right")

            ctk.CTkLabel(card, text=desc, font=ctk.CTkFont(family=FONT_FAMILY, size=10), text_color=COLOR_TEXT_SUB, justify="left", wraplength=310).pack(fill="x", padx=15, pady=(0, 12), anchor="w")
            return seg

        self.seg_fluctuate = _build_feature_card("Dynamic Fluctuation", "Smoothly curves the CPS up and down using a sine wave.", "use_fluctuate")
        self.seg_gaussian = _build_feature_card("Speed Variation", "Randomizes exact click timing intervals.", "use_gaussian")
        self.seg_hold = _build_feature_card("Variable Hold Time", "Randomizes duration mouse switch stays held down (15ms-35ms).", "use_hold_time")
        self.seg_fatigue = _build_feature_card("Muscle Fatigue", "Simulates human stamina by occasionally dropping CPS briefly.", "use_fatigue")

    def _update_slider_lbl(self, label_obj, base_text, val, cmd):
        val = int(val)
        label_obj.configure(text=f"{base_text} [{val}]")
        cmd(val)

    def create_settings_view(self):
        cv = ctk.CTkFrame(self.main_container, fg_color="transparent", corner_radius=0)
        self.views["settings"] = cv

        left_col = ctk.CTkFrame(cv, fg_color="transparent", corner_radius=0)
        left_col.pack(side="left", fill="both", expand=True, padx=(0, 8))

        right_col = ctk.CTkFrame(cv, fg_color="transparent", corner_radius=0)
        right_col.pack(side="right", fill="both", expand=True, padx=(8, 0))

        p_card = self._create_card(left_col)
        p_card.pack(fill="x", pady=10)

        ctk.CTkLabel(p_card, text="Profiles", font=ctk.CTkFont(family=FONT_FAMILY, size=16, weight="bold")).pack(pady=(15, 5), padx=15, anchor="w")
        self.entry_profile_name = ctk.CTkEntry(p_card, height=35, corner_radius=0, font=ctk.CTkFont(family=FONT_FAMILY, size=12), placeholder_text="Profile Name", fg_color=COLOR_BG, border_color=COLOR_BORDER)
        self.entry_profile_name.pack(padx=15, pady=10, fill="x")

        btn_box = ctk.CTkFrame(p_card, fg_color="transparent")
        btn_box.pack(padx=15, pady=10, fill="x")
        ctk.CTkButton(btn_box, text="Load", height=35, corner_radius=0, fg_color=COLOR_BORDER, hover_color=COLOR_BG, command=self.load_profile).pack(side="left", fill="x", expand=True, padx=(0, 5))
        ctk.CTkButton(btn_box, text="Save", height=35, corner_radius=0, fg_color=COLOR_ACCENT, hover_color=COLOR_ACCENT_HOVER, text_color="black", command=self.save_profile).pack(side="right", fill="x", expand=True, padx=(5, 0))

        k_card = self._create_card(right_col)
        k_card.pack(fill="x", pady=10)

        ctk.CTkLabel(k_card, text="Global Keybinds", font=ctk.CTkFont(family=FONT_FAMILY, size=16, weight="bold")).pack(pady=(15, 5), padx=15, anchor="w")

        def _add_hotkey_row(parent, label_text, default_val):
            row = ctk.CTkFrame(parent, fg_color="transparent")
            row.pack(fill="x", padx=15, pady=8)
            ctk.CTkLabel(row, text=label_text, font=ctk.CTkFont(family=FONT_FAMILY, size=12)).pack(side="left")
            entry = ctk.CTkEntry(row, width=80, height=30, corner_radius=0, justify="center", fg_color=COLOR_BG, border_color=COLOR_BORDER)
            entry.insert(0, default_val)
            entry.pack(side="right")
            return entry

        self.entry_clicker_hk = _add_hotkey_row(k_card, "Arm Clicker", self.clicker_hotkey_str)
        self.entry_swap_hk = _add_hotkey_row(k_card, "Swap L/R Button", self.swap_hotkey_str)

        ctk.CTkButton(k_card, text="Apply Keybinds", corner_radius=0, height=35, fg_color=COLOR_BORDER, hover_color=COLOR_BG, command=self.update_hotkey_bindings).pack(padx=15, pady=15, fill="x")

    def select_view(self, view_name):
        if view_name == "settings":
            self.btn_settings.configure(fg_color=COLOR_BORDER)
        else:
            self.btn_settings.configure(fg_color=COLOR_CARD)

        for name, frame in self.views.items():
            if name == view_name:
                frame.pack(fill="both", expand=True)
            else:
                frame.pack_forget()

    def update_cps_display(self, current_cps):
        self.after(0, lambda: self.lbl_realtime_cps.configure(text=f"{current_cps:.1f}"))

    def toggle_clicker(self):
        self.clicker.armed = not self.clicker.armed
        if self.clicker.armed:
            mode_str = "HOLD ACTIVE" if self.clicker.trigger_mode == "Hold" else "SYSTEM ARMED"
            self.btn_toggle.configure(text=f"DISARM SYSTEM ({mode_str})", fg_color=COLOR_DANGER, hover_color="#b91c1c")
        else:
            self.btn_toggle.configure(text=f"ARM MCLICKER ({self.clicker_hotkey_str.upper()})", fg_color=COLOR_BORDER, hover_color=COLOR_CARD)
            self.lbl_realtime_cps.configure(text="0.0")

    def toggle_target_button(self):
        new_button = "Right" if self.clicker.button == "Left" else "Left"
        self.clicker.button = new_button
        self.seg_btn.set(new_button)

    def _parse_key(self, raw_key):
        raw_key = raw_key.strip().lower()
        if hasattr(keyboard.Key, raw_key):
            return getattr(keyboard.Key, raw_key)
        elif len(raw_key) == 1:
            return keyboard.KeyCode.from_char(raw_key)
        else:
            try:
                return keyboard.Key[raw_key]
            except KeyError:
                return None

    def update_hotkey_bindings(self):
        c_key = self._parse_key(self.entry_clicker_hk.get())
        s_key = self._parse_key(self.entry_swap_hk.get())

        if not c_key or not s_key:
            messagebox.showerror("Keybind Error", "Invalid Key String provided.")
            return

        self.clicker_hotkey_str = self.entry_clicker_hk.get().strip().lower()
        self.swap_hotkey_str = self.entry_swap_hk.get().strip().lower()

        self.btn_toggle.configure(text=f"ARM MCLICKER ({self.clicker_hotkey_str.upper()})")
        self.lbl_target_button.configure(text=f"Target Button ({self.swap_hotkey_str.upper()} to swap)")

        self._save_settings()
        self.select_view("Dashboard")

    def _handle_global_shortcuts(self, key):
        try:
            key_str = key.char.lower() if hasattr(key, 'char') and key.char else key.name.lower()
            if key_str == self.clicker_hotkey_str:
                self.after(0, self.toggle_clicker)
            elif key_str == self.swap_hotkey_str:
                self.after(0, self.toggle_target_button)
        except Exception:
            pass

    def save_profile(self):
        p_name = self.entry_profile_name.get().strip()
        if not p_name:
            return
        config_payload = {
            "min_cps": self.clicker.min_cps,
            "max_cps": self.clicker.max_cps,
            "mouse_button": self.clicker.button,
            "trigger_mode": self.clicker.trigger_mode,
            "hotkey_clicker": self.clicker_hotkey_str,
            "hotkey_swap": self.swap_hotkey_str,
            "anti_detect": {
                "fluctuate": self.clicker.use_fluctuate,
                "gaussian": self.clicker.use_gaussian,
                "hold_time": self.clicker.use_hold_time,
                "fatigue": self.clicker.use_fatigue
            }
        }
        profiles = {}
        if CONFIG_FILE.exists():
            try:
                profiles = json.loads(CONFIG_FILE.read_text())
            except Exception:
                pass
        profiles[p_name] = config_payload
        CONFIG_FILE.write_text(json.dumps(profiles, indent=4))
        self.entry_profile_name.delete(0, tk.END)
        self.select_view("Dashboard")

    def load_profile(self):
        p_name = self.entry_profile_name.get().strip()
        if not CONFIG_FILE.exists() or not p_name:
            return
        try:
            profiles = json.loads(CONFIG_FILE.read_text())
            if p_name in profiles:
                data = profiles[p_name]

                self.slider_min.set(data.get("min_cps", 10))
                self.slider_max.set(data.get("max_cps", 14))
                self.clicker.min_cps = data.get("min_cps", 10)
                self.clicker.max_cps = data.get("max_cps", 14)

                self.seg_btn.set(data.get("mouse_button", "Left"))
                self.clicker.button = data.get("mouse_button", "Left")

                self.seg_mode.set(data.get("trigger_mode", "Toggle"))
                self.clicker.trigger_mode = data.get("trigger_mode", "Toggle")

                self.entry_clicker_hk.delete(0, tk.END)
                self.entry_clicker_hk.insert(0, data.get("hotkey_clicker", "f8"))
                self.entry_swap_hk.delete(0, tk.END)
                self.entry_swap_hk.insert(0, data.get("hotkey_swap", "f7"))
                self.update_hotkey_bindings()

                ad = data.get("anti_detect", {})
                self.seg_fluctuate.set("ON" if ad.get("fluctuate", True) else "OFF")
                self.clicker.use_fluctuate = ad.get("fluctuate", True)

                self.seg_gaussian.set("ON" if ad.get("gaussian", True) else "OFF")
                self.clicker.use_gaussian = ad.get("gaussian", True)

                self.seg_hold.set("ON" if ad.get("hold_time", True) else "OFF")
                self.clicker.use_hold_time = ad.get("hold_time", True)

                self.seg_fatigue.set("ON" if ad.get("fatigue", True) else "OFF")
                self.clicker.use_fatigue = ad.get("fatigue", True)

                self.select_view("Dashboard")
        except Exception:
            pass


if __name__ == "__main__":
    if sys.platform == "win32":
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("MClicker.AutoClicker")
        except Exception:
            pass
    app = MClickerUI()
    app.mainloop()
