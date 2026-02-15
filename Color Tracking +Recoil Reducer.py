"""
color_trigger_gui.py  ·  v4.0  — Recoil Reducer Edition
────────────────────────────────────────────────────────────────────────────
INSTALL:
  pip install pywin32 pynput pillow pystray

RUN:
  python color_trigger_gui.py

FEATURES:
  • Live capture preview with zoom & match highlight
  • In-GUI color editor  (add / remove / edit target colors + eyedropper)
  • Capture zone positioner  (drag overlay to pick position)
  • Profiles  (save / load / delete named configs as JSON)
  • Global hotkey  (F8 toggles active state from anywhere)
  • Auto-stop  (stop after N triggers or after a time limit)
  • Key sequences  (press multiple keys / combos per trigger)
  • Statistics dashboard  (trigger rate chart, session summary)
  • Log export  (save event log to .txt)
  • System-tray icon  (minimize to tray, right-click menu)
  • Sound alert  (Windows Beep on trigger, toggleable)
  • Capture position modes  (centered, custom XY, follow-mouse)
  ── NEW IN v4 ──
  • Recoil Reducer — mouse moves down (and optionally sideways) to
    counteract weapon recoil while left mouse button is held.
    Supports linear, smooth (sine-eased), and stepped patterns.
    Per-weapon presets, adjustable strength/speed/humanization jitter,
    separate hotkey, independent enable/disable toggle.
────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import ctypes, ctypes.wintypes
import json, os, random, threading, time
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, colorchooser
from typing import Optional, List, Tuple

# ── optional tray ──────────────────────────────────────────────────────────
try:
    import pystray
    from PIL import Image as PILImage, ImageDraw as ImageDrawModule
    HAS_TRAY = True
except ImportError:
    HAS_TRAY = False

# ── optional PIL for preview ───────────────────────────────────────────────
try:
    from PIL import Image as PILImage, ImageTk, ImageDraw as ImageDrawModule
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

# ═══════════════════════════════════════════════════════════════════════════
#  DEFAULTS
# ═══════════════════════════════════════════════════════════════════════════

DEFAULT = {
    "capture_width":      40,
    "capture_height":     40,
    "tolerance":          10,
    "target_colors":      [(222,132,255),(238,143,211),(253,118,255),(255,150,235)],
    "key_sequence":       ["space"],
    "sequence_gap_ms":    50,
    "pre_min":  10,   "pre_max":  50,
    "hold_min": 20,   "hold_max": 80,
    "cool_min": 500,  "cool_max": 1500,
    "capture_sleep_ms":   2,
    "position_mode":      "center",
    "capture_x":          0,
    "capture_y":          0,
    "auto_stop_triggers": 0,
    "auto_stop_seconds":  0,
    "sound_alert":        False,
    "hotkey":             "f8",
    # ── Recoil Reducer ─────────────────────────────────────────────────
    "rr_enabled":         False,
    "rr_hotkey":          "f7",
    "rr_pattern":         "smooth",  # "linear" | "smooth" | "stepped"
    "rr_y_step":          4,         # pixels down per interval
    "rr_x_step":          0,         # pixels sideways per interval (0=none)
    "rr_interval_ms":     10,        # ms between each nudge
    "rr_jitter":          1,         # ±pixel random noise per step
    "rr_start_delay_ms":  50,        # ms after LMB before compensation starts
    "rr_max_duration_ms": 3000,      # safety cutoff in ms
    "rr_presets": {
        "Default":  {"rr_y_step":4,  "rr_x_step":0, "rr_interval_ms":10, "rr_pattern":"smooth"},
        "AK-47":    {"rr_y_step":6,  "rr_x_step":1, "rr_interval_ms":8,  "rr_pattern":"smooth"},
        "M4/AR":    {"rr_y_step":4,  "rr_x_step":0, "rr_interval_ms":10, "rr_pattern":"smooth"},
        "Sniper":   {"rr_y_step":2,  "rr_x_step":0, "rr_interval_ms":20, "rr_pattern":"linear"},
        "SMG":      {"rr_y_step":3,  "rr_x_step":0, "rr_interval_ms":8,  "rr_pattern":"stepped"},
    },
}

PROFILES_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "ct_profiles.json")

# ═══════════════════════════════════════════════════════════════════════════
#  DESIGN TOKENS
# ═══════════════════════════════════════════════════════════════════════════

BG_BASE      = "#0d1117"
BG_PANEL     = "#161b22"
BG_RAISED    = "#1c2333"
BG_INPUT     = "#1f2937"
BORDER_DARK  = "#21262d"
BORDER_MID   = "#30363d"
ACCENT       = "#f0a500"
ACCENT_DARK  = "#c4821a"
ACCENT_DIM   = "#2d1f08"
ACCENT2      = "#58a6ff"
GREEN_ACTIVE = "#3fb950"
RED_OFF      = "#f85149"
ORANGE       = "#e3b341"
TEXT_PRIMARY = "#e6edf3"
TEXT_MUTED   = "#6e7681"
TEXT_LABEL   = "#8b949e"
TEXT_CODE    = "#79c0ff"
CHART_LINE   = "#f0a500"
CHART_GRID   = "#21262d"
CHART_BG     = "#0d1117"

FONT_MONO    = ("Consolas", 9)
FONT_MONO_SM = ("Consolas", 8)
FONT_LABEL   = ("Segoe UI", 9)
FONT_BODY    = ("Segoe UI", 9)
FONT_HEADING = ("Segoe UI Semibold", 9)
FONT_TITLE   = ("Segoe UI Light", 16)
FONT_STATUS  = ("Consolas", 11, "bold")
FONT_STAT_N  = ("Consolas", 20, "bold")

# ═══════════════════════════════════════════════════════════════════════════
#  WIN32 SCREEN CAPTURE
# ═══════════════════════════════════════════════════════════════════════════

_gdi32    = ctypes.windll.gdi32
_user32   = ctypes.windll.user32
_kernel32 = ctypes.windll.kernel32

SRCCOPY       = 0x00CC0020
CAPTUREBLT    = 0x40000000
BI_RGB        = 0
DIB_RGB_COLORS = 0

class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize",ctypes.c_uint32),("biWidth",ctypes.c_int32),
        ("biHeight",ctypes.c_int32),("biPlanes",ctypes.c_uint16),
        ("biBitCount",ctypes.c_uint16),("biCompression",ctypes.c_uint32),
        ("biSizeImage",ctypes.c_uint32),("biXPelsPerMeter",ctypes.c_int32),
        ("biYPelsPerMeter",ctypes.c_int32),("biClrUsed",ctypes.c_uint32),
        ("biClrImportant",ctypes.c_uint32),
    ]

class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader",BITMAPINFOHEADER),("bmiColors",ctypes.c_uint32*3)]


class ScreenCapture:
    """Low-latency DIBSection-backed BitBlt screen capture."""

    def __init__(self, x:int, y:int, w:int, h:int):
        self.x, self.y, self.width, self.height = x, y, w, h
        self._sdc = _user32.GetDC(None)
        self._mdc = _gdi32.CreateCompatibleDC(self._sdc)
        bmi = BITMAPINFO()
        bmi.bmiHeader.biSize        = ctypes.sizeof(BITMAPINFOHEADER)
        bmi.bmiHeader.biWidth       =  w
        bmi.bmiHeader.biHeight      = -h
        bmi.bmiHeader.biPlanes      = 1
        bmi.bmiHeader.biBitCount    = 32
        bmi.bmiHeader.biCompression = BI_RGB
        self._ptr = ctypes.c_void_p()
        self._hbmp = _gdi32.CreateDIBSection(
            self._mdc, ctypes.byref(bmi), DIB_RGB_COLORS,
            ctypes.byref(self._ptr), None, 0)
        self._old = _gdi32.SelectObject(self._mdc, self._hbmp)
        self._pix = (ctypes.c_uint32*(w*h)).from_address(self._ptr.value)

    def capture(self):
        _gdi32.BitBlt(self._mdc,0,0,self.width,self.height,
                      self._sdc,self.x,self.y,SRCCOPY|CAPTUREBLT)
        return self._pix

    def close(self):
        try:
            if self._old:  _gdi32.SelectObject(self._mdc, self._old)
            if self._hbmp: _gdi32.DeleteObject(self._hbmp)
            if self._mdc:  _gdi32.DeleteDC(self._mdc)
            if self._sdc:  _user32.ReleaseDC(None, self._sdc)
        except Exception: pass


def screen_size() -> Tuple[int,int]:
    return _user32.GetSystemMetrics(0), _user32.GetSystemMetrics(1)

def read_pixel(x:int, y:int) -> Tuple[int,int,int]:
    dc  = _user32.GetDC(None)
    rgb = _gdi32.GetPixel(dc, x, y)
    _user32.ReleaseDC(None, dc)
    return (rgb&0xFF, (rgb>>8)&0xFF, (rgb>>16)&0xFF)

# ═══════════════════════════════════════════════════════════════════════════
#  COLOR MATCHING
# ═══════════════════════════════════════════════════════════════════════════

def matches_any(pixel:int, targets:list, tol:int) -> bool:
    pb =  pixel        & 0xFF
    pg = (pixel >>  8) & 0xFF
    pr = (pixel >> 16) & 0xFF
    for (tr,tg,tb) in targets:
        if abs(pr-tr)<=tol and abs(pg-tg)<=tol and abs(pb-tb)<=tol:
            return True
    return False

# ═══════════════════════════════════════════════════════════════════════════
#  PROFILE MANAGER
# ═══════════════════════════════════════════════════════════════════════════

class ProfileManager:
    def __init__(self, path:str):
        self.path = path
        self._d: dict = {}
        self._load()

    def _load(self):
        try:
            with open(self.path) as f: self._d = json.load(f)
        except: self._d = {}

    def _save(self):
        with open(self.path,"w") as f: json.dump(self._d,f,indent=2)

    def names(self) -> List[str]: return sorted(self._d.keys())

    def save(self, name:str, cfg:dict):
        safe = dict(cfg)
        safe["target_colors"] = [list(c) for c in cfg.get("target_colors",[])]
        self._d[name] = safe; self._save()

    def load(self, name:str) -> Optional[dict]:
        d = self._d.get(name)
        if d is None: return None
        d = dict(d)
        d["target_colors"] = [tuple(c) for c in d.get("target_colors",[])]
        return d

    def delete(self, name:str):
        self._d.pop(name,None); self._save()

# ═══════════════════════════════════════════════════════════════════════════
#  DETECTION ENGINE
# ═══════════════════════════════════════════════════════════════════════════

class DetectionEngine:
    def __init__(self, config:dict, log_fn, stats_fn, preview_fn):
        self._cfg     = config
        self._log     = log_fn
        self._stats   = stats_fn
        self._preview = preview_fn
        self._stop    = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.triggers = 0
        self.scans    = 0
        self._t0      = 0.0
        self._rate_hist: List[Tuple[float,int]] = []

    def start(self):
        self._stop.clear()
        self.triggers = 0; self.scans = 0
        self._t0 = time.monotonic()
        self._rate_hist = [(self._t0, 0)]
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self): self._stop.set()

    def elapsed(self) -> float:
        return time.monotonic() - self._t0 if self._t0 else 0.0

    def _resolve_key(self, name:str):
        from pynput.keyboard import Key, KeyCode
        name = name.strip().lower()
        try:    return Key[name]
        except: pass
        if len(name)==1: return KeyCode.from_char(name)
        try:    return KeyCode.from_vk(int(name))
        except: return Key.space

    def _run(self):
        from pynput.keyboard import Controller
        kb = Controller()
        cfg = self._cfg
        sw, sh = screen_size()
        cooldown_end  = time.monotonic()
        session_start = time.monotonic()
        prev_counter  = 0

        def make_cap():
            mode = cfg.get("position_mode","center")
            w,h  = cfg["capture_width"], cfg["capture_height"]
            if mode == "center":
                x,y = (sw-w)//2, (sh-h)//2
            elif mode == "custom":
                x,y = cfg.get("capture_x",0), cfg.get("capture_y",0)
            else:  # mouse
                pt = ctypes.wintypes.POINT()
                _user32.GetCursorPos(ctypes.byref(pt))
                x,y = max(0,pt.x-w//2), max(0,pt.y-h//2)
            return ScreenCapture(x,y,w,h)

        cap = make_cap()
        self._log(f"Engine started — {cfg.get('position_mode')} "
                  f"{cap.width}×{cap.height}", "info")

        try:
            while not self._stop.is_set():
                # Remake cap if size or mouse-follow changed
                nw,nh = cfg["capture_width"], cfg["capture_height"]
                if nw!=cap.width or nh!=cap.height or cfg.get("position_mode")=="mouse":
                    cap.close(); cap = make_cap()

                pixels  = cap.capture()
                targets = cfg["target_colors"]
                tol     = cfg["tolerance"]
                total   = cap.width * cap.height
                self.scans += 1

                found,midx = False,-1
                for i in range(total):
                    if matches_any(pixels[i],targets,tol):
                        found=True; midx=i; break

                # Preview every ~100 ms
                prev_counter += 1
                if prev_counter >= max(1, int(100/max(1,cfg["capture_sleep_ms"]))):
                    prev_counter = 0
                    self._preview(list(pixels), cap.width, cap.height, midx)

                now = time.monotonic()

                # Auto-stop
                at  = cfg.get("auto_stop_triggers",0)
                asc = cfg.get("auto_stop_seconds",0)
                if at>0  and self.triggers>=at:
                    self._log(f"Auto-stop: {at} triggers reached.","info")
                    self._stop.set(); break
                if asc>0 and (now-session_start)>=asc:
                    self._log(f"Auto-stop: {asc}s limit reached.","info")
                    self._stop.set(); break

                if found and now>=cooldown_end:
                    keys   = [self._resolve_key(k) for k in cfg.get("key_sequence",["space"])]
                    gap_ms = cfg.get("sequence_gap_ms",50)
                    pre    = random.randint(cfg["pre_min"],  cfg["pre_max"])
                    hold   = random.randint(cfg["hold_min"], cfg["hold_max"])
                    cool   = random.randint(cfg["cool_min"], cfg["cool_max"])

                    self._stop.wait(pre/1000.0)
                    if self._stop.is_set(): break

                    for ki,key in enumerate(keys):
                        kb.press(key)
                        self._stop.wait(hold/1000.0)
                        kb.release(key)
                        if ki<len(keys)-1:
                            self._stop.wait(gap_ms/1000.0)

                    cooldown_end = time.monotonic() + cool/1000.0
                    self.triggers += 1
                    self._rate_hist.append((time.monotonic(),self.triggers))
                    cutoff = time.monotonic()-60
                    self._rate_hist = [(t,v) for t,v in self._rate_hist if t>=cutoff]

                    if cfg.get("sound_alert"):
                        try: _kernel32.Beep(880,80)
                        except: pass

                    seq = "+".join(cfg.get("key_sequence",["space"]))
                    self._log(f"▶ [{seq}]  pre={pre}ms  hold={hold}ms  "
                              f"cool={cool}ms  px=({midx%cap.width},{midx//cap.width})",
                              "trigger")

                self._stats(self.triggers, self.scans, self.elapsed(), self._rate_hist)
                self._stop.wait(cfg["capture_sleep_ms"]/1000.0)
        finally:
            cap.close()
            self._log("Engine stopped.","info")


# ═══════════════════════════════════════════════════════════════════════════
#  RECOIL REDUCER ENGINE
# ═══════════════════════════════════════════════════════════════════════════
#
#  HOW IT WORKS:
#  A background thread polls the Win32 left-mouse-button state every
#  `rr_interval_ms` milliseconds. While LMB is held AND rr_enabled is True,
#  the thread moves the mouse cursor downward (and optionally sideways) by a
#  configurable step using mouse_event() — a raw relative movement that
#  bypasses Windows pointer acceleration.
#
#  THREE PATTERNS:
#    linear  — constant step every interval (simple, predictable)
#    smooth  — sine-eased step that ramps up then tapers out
#              (mimics how real recoil peaks then recovers)
#    stepped — step applied every Nth interval, mimicking burst recoil
#
#  HUMANIZATION:
#    Each step gets ±rr_jitter pixels of random noise on both axes so the
#    movement pattern is never perfectly regular (same MT19937 approach used
#    elsewhere in the codebase).
#
#  SAFETY:
#    rr_max_duration_ms caps how long a single burst can run, preventing
#    runaway movement if LMB gets stuck in a held state.
# ═══════════════════════════════════════════════════════════════════════════

# Win32 mouse_event constants for raw relative movement
MOUSEEVENTF_MOVE = 0x0001

class RecoilReducer:
    """
    Independent recoil-compensation engine.
    Runs its own daemon thread, completely separate from DetectionEngine.
    """

    def __init__(self, config: dict, log_fn):
        self._cfg   = config
        self._log   = log_fn
        self._stop  = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._active = False

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._active = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        self._log("Recoil reducer armed.", "info")

    def stop(self):
        self._active = False
        self._stop.set()

    def toggle(self):
        if self._active: self.stop()
        else:            self.start()

    @property
    def is_active(self): return self._active

    # ── internal helpers ──────────────────────────────────────────────────

    @staticmethod
    def _lmb_down() -> bool:
        """True while the left mouse button is physically held."""
        # GetAsyncKeyState bit 15 = currently pressed
        return bool(_user32.GetAsyncKeyState(0x01) & 0x8000)

    @staticmethod
    def _move_mouse(dx: int, dy: int):
        """Inject raw relative mouse movement — bypasses acceleration."""
        _user32.mouse_event(MOUSEEVENTF_MOVE, ctypes.c_ulong(dx),
                            ctypes.c_ulong(dy), 0, 0)

    def _run(self):
        import math
        cfg = self._cfg

        while not self._stop.is_set():
            # Wait until LMB goes down
            if not self._lmb_down():
                self._stop.wait(0.005)
                continue

            # Check master enable flag (can be toggled from GUI while running)
            if not cfg.get("rr_enabled", False):
                self._stop.wait(0.005)
                continue

            # ── LMB just went down — start compensation ──────────────────
            start_delay = cfg.get("rr_start_delay_ms", 50) / 1000.0
            self._stop.wait(start_delay)
            if not self._lmb_down(): continue   # released during start delay

            pattern     = cfg.get("rr_pattern",      "smooth")
            y_step      = cfg.get("rr_y_step",        4)
            x_step      = cfg.get("rr_x_step",        0)
            interval    = cfg.get("rr_interval_ms",   10) / 1000.0
            jitter      = cfg.get("rr_jitter",        1)
            max_dur     = cfg.get("rr_max_duration_ms", 3000) / 1000.0

            burst_start = time.monotonic()
            step_idx    = 0

            while (self._lmb_down() and
                   not self._stop.is_set() and
                   cfg.get("rr_enabled", False)):

                elapsed = time.monotonic() - burst_start
                if elapsed >= max_dur:
                    break

                progress = min(elapsed / max_dur, 1.0)  # 0.0 → 1.0

                # ── Pattern multiplier ────────────────────────────────────
                if pattern == "linear":
                    mult = 1.0

                elif pattern == "smooth":
                    # Sine curve: peaks at 50% of burst, eases in and out.
                    # sin(π·t) gives 0 at t=0, 1 at t=0.5, 0 at t=1
                    mult = math.sin(math.pi * progress)
                    mult = max(0.2, mult)  # floor so it never fully stops

                elif pattern == "stepped":
                    # Move every 3rd step only — mimics burst-fire rhythm
                    mult = 1.0 if (step_idx % 3 == 0) else 0.0

                else:
                    mult = 1.0

                # ── Compute this step's delta ────────────────────────────
                dy = int(round(y_step * mult))
                dx = int(round(x_step * mult))

                # Humanization jitter
                if jitter > 0:
                    dy += random.randint(-jitter, jitter)
                    dx += random.randint(-jitter, jitter)

                if dy != 0 or dx != 0:
                    self._move_mouse(dx, dy)

                step_idx += 1
                self._stop.wait(interval)

        self._log("Recoil reducer stopped.", "info")


# ═══════════════════════════════════════════════════════════════════════════
#  POSITION OVERLAY
# ═══════════════════════════════════════════════════════════════════════════

class PositionOverlay(tk.Toplevel):
    def __init__(self, master, w:int, h:int, callback):
        super().__init__(master)
        self._cb = callback
        sw,sh = screen_size()
        self.geometry(f"{sw}x{sh}+0+0")
        self.overrideredirect(True)
        self.attributes("-topmost",True)
        self.attributes("-alpha",0.22)
        self.configure(bg="black")

        self._w, self._h = w, h
        self._cv = tk.Canvas(self, bg="black", highlightthickness=0,
                              width=sw, height=sh, cursor="crosshair")
        self._cv.pack()

        lbl = tk.Label(self, text="Click to place capture zone  ·  Esc to cancel",
                       font=("Segoe UI",11), bg="black", fg="#f0a500")
        lbl.place(x=20,y=16)

        self._sx, self._sy = (sw-w)//2, (sh-h)//2
        self._draw(self._sx, self._sy)

        self._cv.bind("<Motion>",          self._move)
        self._cv.bind("<ButtonRelease-1>", self._click)
        self.bind("<Escape>", lambda _: self.destroy())
        self._cv.focus_set()

    def _draw(self, x,y):
        c=self._cv; c.delete("all")
        w,h=self._w,self._h
        c.create_rectangle(x,y,x+w,y+h,outline="#f0a500",width=2,dash=(6,3))
        sw,sh=screen_size()
        cx,cy=x+w//2,y+h//2
        c.create_line(0,cy,sw,cy,fill="#f0a500",width=1,dash=(4,6))
        c.create_line(cx,0,cx,sh,fill="#f0a500",width=1,dash=(4,6))
        c.create_text(x+w+8,y,text=f"({x},{y})",fill="#f0a500",anchor="nw",font=("Consolas",9))

    def _move(self,e):
        self._sx=max(0,e.x-self._w//2)
        self._sy=max(0,e.y-self._h//2)
        self._draw(self._sx,self._sy)

    def _click(self,e):
        self._cb(self._sx,self._sy)
        self.destroy()


# ═══════════════════════════════════════════════════════════════════════════
#  MAIN APP
# ═══════════════════════════════════════════════════════════════════════════

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("ColorTrigger  v3")
        self.geometry("700x680")
        self.minsize(660,600)
        self.configure(bg=BG_BASE)
        try: ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except: pass

        self._cfg = dict(DEFAULT)
        self._cfg["target_colors"] = list(DEFAULT["target_colors"])
        self._cfg["key_sequence"]  = list(DEFAULT["key_sequence"])
        self._engine: Optional[DetectionEngine] = None
        self._is_active = False
        self._profiles  = ProfileManager(PROFILES_FILE)
        self._tray_icon = None
        self._chart_pts: List[Tuple[float,float]] = []
        self._peak_rate = 0.0
        self._rr_engine: Optional[RecoilReducer] = None

        self._build_ui()
        self._start_hotkey_listener()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        if HAS_TRAY: self._build_tray()

    # ══════════════════════════════════════════════════════════════════════
    #  BUILD UI
    # ══════════════════════════════════════════════════════════════════════

    def _build_ui(self):
        self._style_ttk()

        # Title bar
        tb = tk.Frame(self,bg=BG_BASE,height=50); tb.pack(fill="x"); tb.pack_propagate(False)
        tk.Label(tb,text="◈  ColorTrigger",font=FONT_TITLE,bg=BG_BASE,
                 fg=TEXT_PRIMARY).pack(side="left",padx=18,pady=8)
        self._hk_badge = tk.Label(tb,text=f"  {self._cfg['hotkey'].upper()} = toggle  ",
                                   font=FONT_MONO_SM,bg=ACCENT_DIM,fg=ACCENT,pady=2)
        self._hk_badge.pack(side="right",padx=16,pady=12)
        tk.Label(tb,text="v3",font=FONT_MONO_SM,bg=BG_PANEL,fg=TEXT_MUTED,
                 padx=6,pady=2).pack(side="right",padx=4,pady=12)
        tk.Frame(self,bg=BORDER_DARK,height=1).pack(fill="x")

        # Notebook
        self._nb = ttk.Notebook(self,style="D.TNotebook")
        self._nb.pack(fill="both",expand=True)
        self._tabs = {}
        for name in ["Control","Colors","Config","Recoil","Profiles","Stats","How It Works"]:
            f = tk.Frame(self._nb,bg=BG_BASE)
            self._nb.add(f,text=f"  {name}  ")
            self._tabs[name] = f

        self._build_control(self._tabs["Control"])
        self._build_colors(self._tabs["Colors"])
        self._build_config(self._tabs["Config"])
        self._build_recoil(self._tabs["Recoil"])
        self._build_profiles(self._tabs["Profiles"])
        self._build_stats(self._tabs["Stats"])
        self._build_explain(self._tabs["How It Works"])

    def _style_ttk(self):
        s = ttk.Style(self); s.theme_use("clam")
        s.configure("D.TNotebook",background=BG_BASE,borderwidth=0,tabmargins=[0,0,0,0])
        s.configure("D.TNotebook.Tab",background=BG_PANEL,foreground=TEXT_MUTED,
                    padding=[12,7],font=FONT_HEADING,borderwidth=0,focuscolor=BG_PANEL)
        s.map("D.TNotebook.Tab",
              background=[("selected",BG_BASE),("active",BG_RAISED)],
              foreground=[("selected",ACCENT),("active",TEXT_PRIMARY)])
        s.configure("D.Vertical.TScrollbar",gripcount=0,background=BG_RAISED,
                    troughcolor=BG_PANEL,bordercolor=BG_PANEL,arrowcolor=TEXT_MUTED,borderwidth=0)

    # ─────────────────────────────────────────────────────────────────────
    #  CONTROL TAB
    # ─────────────────────────────────────────────────────────────────────

    def _build_control(self, p):
        # Status card
        sc = self._card(p); sc.pack(fill="x",padx=16,pady=(14,6))
        tr = tk.Frame(sc,bg=BG_PANEL); tr.pack(fill="x",padx=14,pady=(12,4))
        self._dot = tk.Canvas(tr,width=14,height=14,bg=BG_PANEL,highlightthickness=0)
        self._dot.pack(side="left",padx=(0,8))
        self._dot_oval = self._dot.create_oval(2,2,12,12,fill=RED_OFF,outline="")
        self._status_lbl = tk.Label(tr,text="INACTIVE",font=FONT_STATUS,bg=BG_PANEL,fg=RED_OFF)
        self._status_lbl.pack(side="left")
        self._timer_lbl = tk.Label(tr,text="00:00",font=FONT_MONO,bg=BG_PANEL,fg=TEXT_MUTED)
        self._timer_lbl.pack(side="right",padx=4)
        tk.Label(tr,text="session",font=FONT_MONO_SM,bg=BG_PANEL,fg=TEXT_MUTED).pack(side="right")

        sr = tk.Frame(sc,bg=BG_PANEL); sr.pack(fill="x",padx=14,pady=(0,12))
        self._sv_trg  = self._stat_w(sr,"Triggers","0")
        self._sv_scn  = self._stat_w(sr,"Scans","0")
        self._sv_rate = self._stat_w(sr,"Rate /min","0.0")
        self._sv_upt  = self._stat_w(sr,"Session","—")

        # Buttons
        br = tk.Frame(p,bg=BG_BASE); br.pack(fill="x",padx=16,pady=(4,4))
        self._btn_act = self._btn(br,"▶  ACTIVATE",ACCENT,"#0d1117",self._activate)
        self._btn_act.pack(side="left",fill="x",expand=True,padx=(0,5))
        self._btn_dea = self._btn(br,"■  DEACTIVATE",BG_RAISED,TEXT_MUTED,
                                   self._deactivate,state="disabled")
        self._btn_dea.pack(side="left",fill="x",expand=True,padx=(5,0))

        # Preview
        prev_hdr = tk.Frame(p,bg=BG_BASE); prev_hdr.pack(fill="x",padx=16,pady=(8,2))
        tk.Label(prev_hdr,text="LIVE PREVIEW",font=("Segoe UI Semibold",8),
                 bg=BG_BASE,fg=TEXT_MUTED,anchor="w").pack(side="left")
        self._zoom_var = tk.IntVar(value=4)
        tk.Label(prev_hdr,text="zoom:",font=FONT_MONO_SM,bg=BG_BASE,fg=TEXT_MUTED
                 ).pack(side="right",padx=(0,2))
        for z in (2,4,6,8):
            tk.Radiobutton(prev_hdr,text=f"{z}×",value=z,variable=self._zoom_var,
                           font=FONT_MONO_SM,bg=BG_BASE,fg=TEXT_MUTED,
                           selectcolor=BG_BASE,activebackground=BG_BASE,
                           activeforeground=ACCENT,indicatoron=False,
                           relief="flat",padx=4,pady=1).pack(side="right")

        pf = self._card(p); pf.pack(fill="x",padx=16,pady=(0,4))
        self._prev_cv = tk.Canvas(pf,bg=CHART_BG,highlightthickness=0,width=200,height=200)
        self._prev_cv.pack(padx=10,pady=10)
        self._prev_lbl = tk.Label(pf,text="Start engine to see preview",
                                   font=FONT_MONO_SM,bg=BG_PANEL,fg=TEXT_MUTED)
        self._prev_lbl.pack(pady=(0,8))

        # Log
        lhdr = tk.Frame(p,bg=BG_BASE); lhdr.pack(fill="x",padx=16,pady=(6,2))
        tk.Label(lhdr,text="EVENT LOG",font=("Segoe UI Semibold",8),
                 bg=BG_BASE,fg=TEXT_MUTED,anchor="w").pack(side="left")
        self._lbtn_small("Export",lhdr,self._export_log).pack(side="right")
        self._lbtn_small("Clear",lhdr,lambda:self._log_txt.delete("1.0","end")
                         ).pack(side="right",padx=6)

        lf = self._card(p); lf.pack(fill="both",expand=True,padx=16,pady=(0,14))
        self._log_txt = tk.Text(lf,bg=BG_PANEL,fg=TEXT_PRIMARY,font=FONT_MONO,
                                relief="flat",bd=0,state="disabled",wrap="word",
                                insertbackground=ACCENT,selectbackground=BORDER_MID,
                                padx=10,pady=8)
        vsb = ttk.Scrollbar(lf,orient="vertical",command=self._log_txt.yview,
                            style="D.Vertical.TScrollbar")
        self._log_txt.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right",fill="y"); self._log_txt.pack(fill="both",expand=True)
        self._log_txt.tag_config("trigger",foreground=ACCENT)
        self._log_txt.tag_config("info",   foreground=TEXT_MUTED)
        self._log_txt.tag_config("err",    foreground=RED_OFF)

        self._tick_timer()

    def _stat_w(self, parent, label, init):
        f = tk.Frame(parent,bg=BG_PANEL); f.pack(side="left",padx=(0,18))
        v = tk.Label(f,text=init,font=FONT_STAT_N,bg=BG_PANEL,fg=TEXT_PRIMARY)
        v.pack(anchor="w")
        tk.Label(f,text=label,font=("Segoe UI",8),bg=BG_PANEL,fg=TEXT_MUTED).pack(anchor="w")
        return v

    # ─────────────────────────────────────────────────────────────────────
    #  COLORS TAB
    # ─────────────────────────────────────────────────────────────────────

    def _build_colors(self, p):
        tk.Label(p,text="Target Colors",font=FONT_HEADING,bg=BG_BASE,
                 fg=TEXT_LABEL,anchor="w",padx=16,pady=8).pack(fill="x")
        tk.Label(p,text="The engine fires when ANY pixel matches ANY color below.",
                 font=FONT_LABEL,bg=BG_BASE,fg=TEXT_MUTED,anchor="w",padx=16).pack(fill="x")

        cf = self._card(p); cf.pack(fill="x",padx=16,pady=8)
        self._clr_frame = tk.Frame(cf,bg=BG_PANEL)
        self._clr_frame.pack(fill="x",padx=6,pady=6)
        self._refresh_colors()

        ar = tk.Frame(p,bg=BG_BASE); ar.pack(fill="x",padx=16,pady=4)
        self._btn(ar,"＋  Manual",BG_RAISED,TEXT_PRIMARY,self._add_color_manual
                  ).pack(side="left",padx=(0,6))
        self._btn(ar,"🖉  Eyedropper",BG_RAISED,TEXT_PRIMARY,self._eyedropper
                  ).pack(side="left",padx=(0,6))
        self._btn(ar,"🗑  Clear All",BG_RAISED,RED_OFF,self._clear_colors
                  ).pack(side="right")

        tk.Frame(p,bg=BORDER_DARK,height=1).pack(fill="x",padx=16,pady=(10,0))
        slr = tk.Frame(p,bg=BG_BASE); slr.pack(fill="x",padx=16,pady=8)
        tk.Label(slr,text="Tolerance per channel:",font=FONT_LABEL,
                 bg=BG_BASE,fg=TEXT_LABEL).pack(side="left")
        self._tol_var = tk.IntVar(value=self._cfg["tolerance"])
        self._tol_lbl = tk.Label(slr,text=str(self._cfg["tolerance"]),
                                  font=FONT_MONO,bg=BG_BASE,fg=ACCENT,width=3)
        self._tol_lbl.pack(side="right")
        tk.Scale(slr,variable=self._tol_var,from_=0,to=60,orient="horizontal",
                 bg=BG_BASE,fg=TEXT_PRIMARY,troughcolor=BG_RAISED,
                 highlightthickness=0,activebackground=ACCENT,sliderrelief="flat",
                 bd=0,showvalue=False,
                 command=lambda v:(self._tol_lbl.configure(text=str(int(float(v)))),
                                   self._cfg.update({"tolerance":int(float(v))}))
                 ).pack(side="right",fill="x",expand=True,padx=8)

    def _refresh_colors(self):
        for w in self._clr_frame.winfo_children(): w.destroy()
        colors = self._cfg["target_colors"]
        if not colors:
            tk.Label(self._clr_frame,text="No colors — add one below.",
                     font=FONT_LABEL,bg=BG_PANEL,fg=TEXT_MUTED,pady=12).pack()
            return
        for i,(r,g,b) in enumerate(colors):
            self._make_color_row(i,r,g,b)

    def _make_color_row(self, idx, r, g, b):
        row = tk.Frame(self._clr_frame,bg=BG_PANEL); row.pack(fill="x",pady=2,padx=4)
        hex_c = f"#{r:02x}{g:02x}{b:02x}"
        sw = tk.Frame(row,bg=hex_c,width=28,height=28,
                      highlightbackground=BORDER_MID,highlightthickness=1)
        sw.pack(side="left",padx=(0,8)); sw.pack_propagate(False)
        sw.bind("<Button-1>",lambda e,i=idx:self._edit_color(i))

        rv,gv,bv = tk.StringVar(value=str(r)),tk.StringVar(value=str(g)),tk.StringVar(value=str(b))
        for lbl,var in [("R",rv),("G",gv),("B",bv)]:
            tk.Label(row,text=lbl,font=FONT_MONO_SM,bg=BG_PANEL,fg=TEXT_MUTED,width=1).pack(side="left")
            e = tk.Entry(row,textvariable=var,width=4,font=FONT_MONO,bg=BG_INPUT,
                         fg=TEXT_PRIMARY,relief="flat",insertbackground=ACCENT,bd=0)
            e.pack(side="left",padx=(0,5),ipady=3,ipadx=2)
            var.trace_add("write",lambda *a,i=idx,rv=rv,gv=gv,bv=bv,sw=sw:
                self._update_color_entry(i,rv,gv,bv,sw))

        tk.Label(row,text=hex_c,font=FONT_MONO_SM,bg=BG_PANEL,fg=TEXT_CODE,width=8
                 ).pack(side="left",padx=8)
        self._lbtn_small("✕",row,lambda i=idx:self._remove_color(i)).pack(side="right",padx=4)

    def _update_color_entry(self,idx,rv,gv,bv,sw):
        try:
            r,g,b=int(rv.get())%256,int(gv.get())%256,int(bv.get())%256
            self._cfg["target_colors"][idx]=(r,g,b)
            sw.configure(bg=f"#{r:02x}{g:02x}{b:02x}")
        except: pass

    def _add_color_manual(self):
        self._cfg["target_colors"].append((128,128,128))
        self._refresh_colors()

    def _remove_color(self,idx):
        if 0<=idx<len(self._cfg["target_colors"]):
            self._cfg["target_colors"].pop(idx); self._refresh_colors()

    def _clear_colors(self):
        if messagebox.askyesno("Clear All","Remove all target colors?"):
            self._cfg["target_colors"].clear(); self._refresh_colors()

    def _edit_color(self,idx):
        r,g,b=self._cfg["target_colors"][idx]
        res=colorchooser.askcolor(color=f"#{r:02x}{g:02x}{b:02x}",title="Pick Color")
        if res and res[0]:
            nr,ng,nb=[int(x) for x in res[0]]
            self._cfg["target_colors"][idx]=(nr,ng,nb); self._refresh_colors()

    def _eyedropper(self):
        self.withdraw()
        self.after(250,self._do_eyedrop)

    def _do_eyedrop(self):
        ov = tk.Toplevel(self)
        sw,sh=screen_size()
        ov.geometry(f"{sw}x{sh}+0+0")
        ov.overrideredirect(True)
        ov.attributes("-topmost",True)
        ov.attributes("-alpha",0.01)
        ov.configure(bg="black",cursor="crosshair")
        self.deiconify()
        info = tk.Label(self,text="🖉  Click anywhere to sample color  ·  Esc to cancel",
                        font=("Segoe UI",10),bg=ACCENT_DIM,fg=ACCENT,padx=10,pady=6)
        info.place(x=18,y=18)
        def click(e):
            x,y=ov.winfo_pointerx(),ov.winfo_pointery()
            r,g,b=read_pixel(x,y)
            self._cfg["target_colors"].append((r,g,b))
            self._refresh_colors(); info.destroy(); ov.destroy()
        def esc(e):
            info.destroy(); ov.destroy()
        ov.bind("<Button-1>",click); ov.bind("<Escape>",esc); ov.focus_set()

    # ─────────────────────────────────────────────────────────────────────
    #  CONFIG TAB
    # ─────────────────────────────────────────────────────────────────────

    def _build_config(self, p):
        c,_ = self._scrollable(p)
        inner = tk.Frame(c,bg=BG_BASE)
        wid = c.create_window((0,0),window=inner,anchor="nw")
        inner.bind("<Configure>",lambda e:c.configure(scrollregion=c.bbox("all")))
        c.bind("<Configure>",   lambda e:c.itemconfig(wid,width=e.width))
        c.bind_all("<MouseWheel>",lambda e:c.yview_scroll(-1*(e.delta//120),"units"))

        self._sec(inner,"Capture Zone")
        r1=self._row(inner)
        self._cv_w = self._field(r1,"Width (px)",  DEFAULT["capture_width"])
        self._cv_h = self._field(r1,"Height (px)", DEFAULT["capture_height"])

        self._sec(inner,"Capture Position")
        pm=self._row(inner)
        self._pos_mode = tk.StringVar(value=self._cfg["position_mode"])
        for val,lbl in [("center","Center of screen"),("custom","Custom XY"),("mouse","Follow mouse")]:
            tk.Radiobutton(pm,text=lbl,value=val,variable=self._pos_mode,
                           font=FONT_LABEL,bg=BG_BASE,fg=TEXT_PRIMARY,
                           selectcolor=BG_BASE,activebackground=BG_BASE,
                           activeforeground=ACCENT).pack(side="left",padx=(0,14))
        r_pos=self._row(inner)
        self._cv_px = self._field(r_pos,"Custom X",DEFAULT["capture_x"])
        self._cv_py = self._field(r_pos,"Custom Y",DEFAULT["capture_y"])
        self._btn(r_pos,"🞋  Pick on screen",BG_RAISED,ACCENT,
                  self._open_picker).pack(side="left",padx=8,pady=4)

        self._sec(inner,"Key Sequence")
        tk.Label(inner,text="Space-separated key names per trigger:  space  f1  ctrl+s  a b c",
                 font=FONT_LABEL,bg=BG_BASE,fg=TEXT_MUTED,padx=20,pady=2).pack(fill="x",anchor="w")
        rk=self._row(inner)
        self._cv_keys = self._field(rk,"Keys"," ".join(DEFAULT["key_sequence"]),width=26)
        self._cv_gap  = self._field(rk,"Gap between keys (ms)",DEFAULT["sequence_gap_ms"])

        self._sec(inner,"Global Hotkey")
        rh=self._row(inner)
        self._cv_hotkey = self._field(rh,"Key name",DEFAULT["hotkey"],width=10)
        tk.Label(rh,text="Toggles active/inactive from anywhere",
                 font=FONT_LABEL,bg=BG_BASE,fg=TEXT_MUTED).pack(side="left",padx=8)

        self._sec(inner,"Auto-Stop  (0 = disabled)")
        ra=self._row(inner)
        self._cv_ast = self._field(ra,"Stop after N triggers",DEFAULT["auto_stop_triggers"])
        self._cv_ass = self._field(ra,"Stop after N seconds",DEFAULT["auto_stop_seconds"])

        self._sec(inner,"Humanization Timing  (ms)")
        r2=self._row(inner)
        self._cv_pre_mn=self._field(r2,"Pre-press min",DEFAULT["pre_min"])
        self._cv_pre_mx=self._field(r2,"Pre-press max",DEFAULT["pre_max"])
        r3=self._row(inner)
        self._cv_hld_mn=self._field(r3,"Hold min",DEFAULT["hold_min"])
        self._cv_hld_mx=self._field(r3,"Hold max",DEFAULT["hold_max"])
        r4=self._row(inner)
        self._cv_cld_mn=self._field(r4,"Cooldown min",DEFAULT["cool_min"])
        self._cv_cld_mx=self._field(r4,"Cooldown max",DEFAULT["cool_max"])
        r5=self._row(inner)
        self._cv_slp=self._field(r5,"Capture sleep",DEFAULT["capture_sleep_ms"])

        self._sec(inner,"Misc")
        mr=self._row(inner)
        self._sound_var = tk.BooleanVar(value=DEFAULT["sound_alert"])
        tk.Checkbutton(mr,text="Sound alert on trigger (Windows Beep)",
                       variable=self._sound_var,font=FONT_LABEL,bg=BG_BASE,
                       fg=TEXT_PRIMARY,selectcolor=BG_RAISED,
                       activebackground=BG_BASE,activeforeground=ACCENT).pack(side="left")

        tk.Frame(inner,bg=BORDER_DARK,height=1).pack(fill="x",padx=16,pady=(14,0))
        fr=tk.Frame(inner,bg=BG_BASE); fr.pack(fill="x",padx=16,pady=10)
        self._btn(fr,"Apply Configuration",ACCENT,"#0d1117",self._apply_config).pack(side="right")
        self._cfg_msg=tk.Label(fr,text="",font=FONT_MONO,bg=BG_BASE,fg=GREEN_ACTIVE)
        self._cfg_msg.pack(side="right",padx=10)
        tk.Frame(inner,bg=BG_BASE,height=16).pack()

    def _open_picker(self):
        w = self._int(self._cv_w, DEFAULT["capture_width"])
        h = self._int(self._cv_h, DEFAULT["capture_height"])
        def cb(x,y):
            self._cv_px.set(str(x)); self._cv_py.set(str(y))
            self._pos_mode.set("custom")
        PositionOverlay(self,w,h,cb)

    # ─────────────────────────────────────────────────────────────────────
    #  RECOIL REDUCER TAB
    # ─────────────────────────────────────────────────────────────────────

    def _build_recoil(self, p):
        # ── Master toggle card ────────────────────────────────────────────
        hdr = self._card(p); hdr.pack(fill="x",padx=16,pady=(14,6))
        hr  = tk.Frame(hdr,bg=BG_PANEL); hr.pack(fill="x",padx=14,pady=10)

        self._rr_dot = tk.Canvas(hr,width=14,height=14,bg=BG_PANEL,highlightthickness=0)
        self._rr_dot.pack(side="left",padx=(0,8))
        self._rr_dot_oval = self._rr_dot.create_oval(2,2,12,12,fill=RED_OFF,outline="")
        self._rr_status = tk.Label(hr,text="RECOIL REDUCER  OFF",font=FONT_STATUS,
                                    bg=BG_PANEL,fg=RED_OFF)
        self._rr_status.pack(side="left")

        # Enable checkbox
        self._rr_enabled_var = tk.BooleanVar(value=self._cfg.get("rr_enabled",False))
        tk.Checkbutton(hr,text="Enable",variable=self._rr_enabled_var,
                       font=FONT_HEADING,bg=BG_PANEL,fg=TEXT_PRIMARY,
                       selectcolor=BG_RAISED,activebackground=BG_PANEL,
                       activeforeground=ACCENT,
                       command=self._rr_toggle_enable
                       ).pack(side="right",padx=8)

        # Arm/Disarm buttons
        br = tk.Frame(p,bg=BG_BASE); br.pack(fill="x",padx=16,pady=(2,6))
        self._rr_btn_arm = self._btn(br,"⊕  ARM RECOIL REDUCER",ACCENT,"#0d1117",
                                      self._rr_arm)
        self._rr_btn_arm.pack(side="left",fill="x",expand=True,padx=(0,5))
        self._rr_btn_dis = self._btn(br,"⊗  DISARM",BG_RAISED,TEXT_MUTED,
                                      self._rr_disarm,state="disabled")
        self._rr_btn_dis.pack(side="left",fill="x",expand=True,padx=(5,0))

        # Info label
        self._rr_info = tk.Label(p,
            text="Hold LMB → mouse moves down automatically to counter recoil.",
            font=FONT_LABEL,bg=BG_BASE,fg=TEXT_MUTED,anchor="w",padx=16)
        self._rr_info.pack(fill="x",pady=(0,4))

        # ── Settings ──────────────────────────────────────────────────────
        c,_ = self._scrollable(p)
        inner = tk.Frame(c,bg=BG_BASE)
        wid = c.create_window((0,0),window=inner,anchor="nw")
        inner.bind("<Configure>",lambda e:c.configure(scrollregion=c.bbox("all")))
        c.bind("<Configure>",   lambda e:c.itemconfig(wid,width=e.width))

        # Pattern
        self._sec(inner,"Compensation Pattern")
        pr = self._row(inner)
        self._rr_pattern = tk.StringVar(value=self._cfg.get("rr_pattern","smooth"))
        pattern_desc = {
            "linear":  "Constant step every interval — simple & predictable",
            "smooth":  "Sine-eased — ramps up, peaks at 50%, tapers out  (recommended)",
            "stepped": "Every 3rd interval only — mimics burst-fire recoil",
        }
        for val in ("linear","smooth","stepped"):
            rf = tk.Frame(inner,bg=BG_BASE); rf.pack(fill="x",padx=20,pady=2)
            tk.Radiobutton(rf,text=val.capitalize(),value=val,
                           variable=self._rr_pattern,
                           font=FONT_HEADING,bg=BG_BASE,fg=TEXT_PRIMARY,
                           selectcolor=BG_BASE,activebackground=BG_BASE,
                           activeforeground=ACCENT,width=9,anchor="w"
                           ).pack(side="left")
            tk.Label(rf,text=pattern_desc[val],font=FONT_LABEL,
                     bg=BG_BASE,fg=TEXT_MUTED,anchor="w").pack(side="left")

        # Movement
        self._sec(inner,"Movement  (pixels)")
        r1 = self._row(inner)
        self._rr_y = self._field(r1,"Downward step (Y)",   self._cfg.get("rr_y_step",4))
        self._rr_x = self._field(r1,"Sideways step (X)",   self._cfg.get("rr_x_step",0))
        tk.Label(inner,text="Y moves the mouse down to fight vertical recoil. "
                             "X corrects horizontal drift (positive=right, negative=left).",
                 font=FONT_LABEL,bg=BG_BASE,fg=TEXT_MUTED,wraplength=520,
                 justify="left",padx=20,pady=2).pack(fill="x",anchor="w")

        # Timing
        self._sec(inner,"Timing  (ms)")
        r2 = self._row(inner)
        self._rr_interval   = self._field(r2,"Interval between steps", self._cfg.get("rr_interval_ms",10))
        self._rr_startdelay = self._field(r2,"Start delay after LMB",  self._cfg.get("rr_start_delay_ms",50))
        r3 = self._row(inner)
        self._rr_maxdur = self._field(r3,"Max burst duration",          self._cfg.get("rr_max_duration_ms",3000))
        tk.Label(inner,
                 text="Shorter interval = smoother but more CPU. "
                      "Max duration is a safety cutoff.",
                 font=FONT_LABEL,bg=BG_BASE,fg=TEXT_MUTED,
                 padx=20,pady=2).pack(fill="x",anchor="w")

        # Humanization
        self._sec(inner,"Humanization")
        r4 = self._row(inner)
        self._rr_jitter = self._field(r4,"Jitter (±px per step)", self._cfg.get("rr_jitter",1))
        tk.Label(inner,
                 text="Random ±pixel noise added to each step so the pattern is "
                      "never perfectly uniform. 0=off, 1–3=recommended.",
                 font=FONT_LABEL,bg=BG_BASE,fg=TEXT_MUTED,
                 wraplength=520,justify="left",padx=20,pady=2).pack(fill="x",anchor="w")

        # Hotkey
        self._sec(inner,"Hotkey")
        r5 = self._row(inner)
        self._rr_hotkey_field = self._field(r5,"Toggle hotkey (arm/disarm)",
                                             self._cfg.get("rr_hotkey","f7"),width=10)
        tk.Label(inner,
                 text="Independent of the main F8 hotkey. Arms / disarms the recoil "
                      "reducer from anywhere without opening the GUI.",
                 font=FONT_LABEL,bg=BG_BASE,fg=TEXT_MUTED,
                 wraplength=520,justify="left",padx=20,pady=2).pack(fill="x",anchor="w")

        # ── Weapon presets ────────────────────────────────────────────────
        self._sec(inner,"Weapon Presets")
        tk.Label(inner,
                 text="Click a preset to load its values. Save Current writes "
                      "a new preset with the name you enter.",
                 font=FONT_LABEL,bg=BG_BASE,fg=TEXT_MUTED,
                 padx=20,pady=2).pack(fill="x",anchor="w")

        preset_card = self._card(inner); preset_card.pack(fill="x",padx=16,pady=6)
        self._rr_preset_list = tk.Listbox(preset_card,bg=BG_PANEL,fg=TEXT_PRIMARY,
                                           font=FONT_MONO,relief="flat",bd=0,
                                           selectbackground=ACCENT_DIM,
                                           selectforeground=ACCENT,
                                           activestyle="none",height=6)
        vsb = ttk.Scrollbar(preset_card,orient="vertical",
                            command=self._rr_preset_list.yview,
                            style="D.Vertical.TScrollbar")
        self._rr_preset_list.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right",fill="y")
        self._rr_preset_list.pack(fill="both",expand=True,padx=4,pady=4)
        self._rr_refresh_presets()

        pbr = tk.Frame(inner,bg=BG_BASE); pbr.pack(fill="x",padx=16,pady=(2,4))
        self._btn(pbr,"Load Preset",BG_RAISED,TEXT_PRIMARY,
                  self._rr_load_preset).pack(side="left",padx=(0,6))
        self._rr_pname = tk.Entry(pbr,width=14,font=FONT_MONO,bg=BG_INPUT,
                                   fg=TEXT_PRIMARY,relief="flat",
                                   insertbackground=ACCENT,bd=0)
        self._rr_pname.insert(0,"MyWeapon")
        self._rr_pname.pack(side="left",padx=(0,6),ipady=4,ipadx=4)
        self._btn(pbr,"Save Current",ACCENT,"#0d1117",
                  self._rr_save_preset).pack(side="left",padx=(0,6))
        self._btn(pbr,"Delete",BG_RAISED,RED_OFF,
                  self._rr_delete_preset).pack(side="left")

        # Apply button
        tk.Frame(inner,bg=BORDER_DARK,height=1).pack(fill="x",padx=16,pady=(14,0))
        af = tk.Frame(inner,bg=BG_BASE); af.pack(fill="x",padx=16,pady=10)
        self._btn(af,"Apply Recoil Settings",ACCENT,"#0d1117",
                  self._rr_apply).pack(side="right")
        self._rr_msg = tk.Label(af,text="",font=FONT_MONO,bg=BG_BASE,fg=GREEN_ACTIVE)
        self._rr_msg.pack(side="right",padx=10)
        tk.Frame(inner,bg=BG_BASE,height=16).pack()

    # ── Recoil reducer helpers ─────────────────────────────────────────────

    def _rr_toggle_enable(self):
        enabled = self._rr_enabled_var.get()
        self._cfg["rr_enabled"] = enabled
        if self._rr_engine:
            self._rr_engine._cfg["rr_enabled"] = enabled

    def _rr_arm(self):
        self._rr_apply(silent=True)
        if not self._rr_engine:
            self._rr_engine = RecoilReducer(config=self._cfg,log_fn=self._post_log)
        self._rr_engine.start()
        self._rr_update_status(True)
        self._rr_btn_arm.configure(state="disabled",bg=BG_RAISED,fg=TEXT_MUTED)
        self._rr_btn_dis.configure(state="normal",bg="#7c3aed",fg="#ffffff",
                                    activebackground="#5b21b6")

    def _rr_disarm(self):
        if self._rr_engine:
            self._rr_engine.stop()
        self._rr_update_status(False)
        self._rr_btn_arm.configure(state="normal",bg=ACCENT,fg="#0d1117",
                                    activebackground=ACCENT_DARK)
        self._rr_btn_dis.configure(state="disabled",bg=BG_RAISED,fg=TEXT_MUTED)

    def _rr_update_status(self, armed:bool):
        PURPLE = "#a78bfa"
        if armed:
            self._rr_dot.itemconfig(self._rr_dot_oval, fill=PURPLE)
            self._rr_status.configure(text="RECOIL REDUCER  ARMED", fg=PURPLE)
        else:
            self._rr_dot.itemconfig(self._rr_dot_oval, fill=RED_OFF)
            self._rr_status.configure(text="RECOIL REDUCER  OFF", fg=RED_OFF)

    def _rr_apply(self, silent=False):
        self._cfg.update({
            "rr_enabled":         self._rr_enabled_var.get(),
            "rr_hotkey":          self._rr_hotkey_field.get().strip() or "f7",
            "rr_pattern":         self._rr_pattern.get(),
            "rr_y_step":          self._int(self._rr_y,            4),
            "rr_x_step":          self._int(self._rr_x,            0),
            "rr_interval_ms":     self._int(self._rr_interval,     10),
            "rr_start_delay_ms":  self._int(self._rr_startdelay,   50),
            "rr_max_duration_ms": self._int(self._rr_maxdur,       3000),
            "rr_jitter":          self._int(self._rr_jitter,       1),
        })
        if self._rr_engine:
            self._rr_engine._cfg.update(self._cfg)
        if not silent:
            self._rr_msg.configure(text="✓ Applied",fg=GREEN_ACTIVE)
            self.after(2000,lambda:self._rr_msg.configure(text=""))

    def _rr_refresh_presets(self):
        self._rr_preset_list.delete(0,"end")
        presets = self._cfg.get("rr_presets",{})
        for name in sorted(presets.keys()):
            p = presets[name]
            self._rr_preset_list.insert("end",
                f"  {name:<14}  Y={p.get('rr_y_step',4)}  "
                f"X={p.get('rr_x_step',0)}  "
                f"{p.get('rr_pattern','smooth')}")

    def _rr_load_preset(self):
        sel = self._rr_preset_list.curselection()
        if not sel: return
        raw  = self._rr_preset_list.get(sel[0]).strip()
        name = raw.split()[0]
        p    = self._cfg.get("rr_presets",{}).get(name)
        if not p: return
        self._rr_y.set(str(p.get("rr_y_step",4)))
        self._rr_x.set(str(p.get("rr_x_step",0)))
        self._rr_interval.set(str(p.get("rr_interval_ms",10)))
        self._rr_pattern.set(p.get("rr_pattern","smooth"))
        self._rr_pname.delete(0,"end"); self._rr_pname.insert(0,name)
        self._rr_msg.configure(text=f"✓ Loaded '{name}'",fg=GREEN_ACTIVE)
        self.after(2000,lambda:self._rr_msg.configure(text=""))

    def _rr_save_preset(self):
        self._rr_apply(silent=True)
        name = self._rr_pname.get().strip() or "Custom"
        presets = self._cfg.setdefault("rr_presets",{})
        presets[name] = {
            "rr_y_step":     self._cfg["rr_y_step"],
            "rr_x_step":     self._cfg["rr_x_step"],
            "rr_interval_ms":self._cfg["rr_interval_ms"],
            "rr_pattern":    self._cfg["rr_pattern"],
        }
        self._rr_refresh_presets()
        self._rr_msg.configure(text=f"✓ Saved '{name}'",fg=GREEN_ACTIVE)
        self.after(2000,lambda:self._rr_msg.configure(text=""))

    def _rr_delete_preset(self):
        sel = self._rr_preset_list.curselection()
        if not sel: return
        name = self._rr_preset_list.get(sel[0]).strip().split()[0]
        if messagebox.askyesno("Delete",f"Delete preset '{name}'?"):
            self._cfg.get("rr_presets",{}).pop(name,None)
            self._rr_refresh_presets()

    # ─────────────────────────────────────────────────────────────────────
    #  PROFILES TAB
    # ─────────────────────────────────────────────────────────────────────

    def _build_profiles(self, p):
        tk.Label(p,text="Profiles",font=FONT_HEADING,bg=BG_BASE,
                 fg=TEXT_LABEL,anchor="w",padx=16,pady=8).pack(fill="x")
        tk.Label(p,text="Save and restore complete configurations. Stored in ct_profiles.json.",
                 font=FONT_LABEL,bg=BG_BASE,fg=TEXT_MUTED,anchor="w",padx=16).pack(fill="x")

        nr=tk.Frame(p,bg=BG_BASE); nr.pack(fill="x",padx=16,pady=10)
        tk.Label(nr,text="Name:",font=FONT_LABEL,bg=BG_BASE,fg=TEXT_LABEL).pack(side="left")
        self._prof_name=tk.Entry(nr,width=22,font=FONT_MONO,bg=BG_INPUT,
                                  fg=TEXT_PRIMARY,relief="flat",insertbackground=ACCENT,bd=0)
        self._prof_name.pack(side="left",padx=8,ipady=4,ipadx=6)
        self._btn(nr,"Save",ACCENT,"#0d1117",self._prof_save).pack(side="left",padx=4)

        lf=self._card(p); lf.pack(fill="both",expand=True,padx=16,pady=4)
        self._prof_lb=tk.Listbox(lf,bg=BG_PANEL,fg=TEXT_PRIMARY,font=FONT_MONO,
                                  relief="flat",bd=0,selectbackground=ACCENT_DIM,
                                  selectforeground=ACCENT,activestyle="none",height=10)
        vsb=ttk.Scrollbar(lf,orient="vertical",command=self._prof_lb.yview,style="D.Vertical.TScrollbar")
        self._prof_lb.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right",fill="y"); self._prof_lb.pack(fill="both",expand=True,padx=4,pady=4)

        br=tk.Frame(p,bg=BG_BASE); br.pack(fill="x",padx=16,pady=6)
        self._btn(br,"Load",BG_RAISED,TEXT_PRIMARY,self._prof_load).pack(side="left",padx=(0,6))
        self._btn(br,"Delete",BG_RAISED,RED_OFF,self._prof_delete).pack(side="left")
        self._prof_msg=tk.Label(br,text="",font=FONT_MONO_SM,bg=BG_BASE,fg=GREEN_ACTIVE)
        self._prof_msg.pack(side="right",padx=8)
        self._refresh_prof_list()

    def _refresh_prof_list(self):
        self._prof_lb.delete(0,"end")
        for n in self._profiles.names(): self._prof_lb.insert("end",f"  {n}")

    def _prof_save(self):
        name=self._prof_name.get().strip()
        if not name: messagebox.showwarning("Name required","Enter a profile name."); return
        self._apply_config(silent=True)
        self._profiles.save(name,self._cfg)
        self._refresh_prof_list()
        self._prof_msg.configure(text=f"✓ Saved '{name}'")
        self.after(2500,lambda:self._prof_msg.configure(text=""))

    def _prof_load(self):
        sel=self._prof_lb.curselection()
        if not sel: return
        name=self._prof_lb.get(sel[0]).strip()
        d=self._profiles.load(name)
        if not d: return
        self._cfg.update(d); self._load_cfg_to_ui()
        self._prof_msg.configure(text=f"✓ Loaded '{name}'")
        self.after(2500,lambda:self._prof_msg.configure(text=""))

    def _prof_delete(self):
        sel=self._prof_lb.curselection()
        if not sel: return
        name=self._prof_lb.get(sel[0]).strip()
        if messagebox.askyesno("Delete",f"Delete '{name}'?"):
            self._profiles.delete(name); self._refresh_prof_list()

    # ─────────────────────────────────────────────────────────────────────
    #  STATS TAB
    # ─────────────────────────────────────────────────────────────────────

    def _build_stats(self, p):
        tk.Label(p,text="Statistics",font=FONT_HEADING,bg=BG_BASE,
                 fg=TEXT_LABEL,anchor="w",padx=16,pady=8).pack(fill="x")

        sf=self._card(p); sf.pack(fill="x",padx=16,pady=6)
        sr=tk.Frame(sf,bg=BG_PANEL); sr.pack(fill="x",padx=12,pady=10)
        self._st_total  =self._stat_w(sr,"Total Triggers","0")
        self._st_sess   =self._stat_w(sr,"Session Time","—")
        self._st_avg    =self._stat_w(sr,"Avg /min","0.0")
        self._st_peak   =self._stat_w(sr,"Peak /min","0.0")

        tk.Label(p,text="TRIGGER RATE  (per minute, rolling 60s)",
                 font=("Segoe UI Semibold",8),bg=BG_BASE,fg=TEXT_MUTED,
                 anchor="w",padx=16).pack(fill="x",pady=(8,2))
        cf=self._card(p); cf.pack(fill="x",padx=16,pady=(0,8))
        self._chart=tk.Canvas(cf,bg=CHART_BG,height=130,highlightthickness=0)
        self._chart.pack(fill="x",padx=4,pady=4)

        self._btn(p,"Reset Statistics",BG_RAISED,TEXT_MUTED,self._reset_stats
                  ).pack(anchor="e",padx=16,pady=4)

    def _reset_stats(self):
        self._chart_pts=[]; self._peak_rate=0.0
        for w in [self._st_total,self._st_sess,self._st_avg,self._st_peak,
                  self._sv_trg,self._sv_scn,self._sv_rate,self._sv_upt]:
            w.configure(text="0")
        self._chart.delete("all")

    # ─────────────────────────────────────────────────────────────────────
    #  HOW IT WORKS TAB
    # ─────────────────────────────────────────────────────────────────────

    def _build_explain(self, p):
        c,_ = self._scrollable(p)
        inner = tk.Frame(c,bg=BG_BASE)
        wid=c.create_window((0,0),window=inner,anchor="nw")
        inner.bind("<Configure>",lambda e:c.configure(scrollregion=c.bbox("all")))
        c.bind("<Configure>",   lambda e:c.itemconfig(wid,width=e.width))
        c.bind_all("<MouseWheel>",lambda e:c.yview_scroll(-1*(e.delta//120),"units"))

        sections = [
          ("◈  Overview",
           "ColorTrigger monitors a configurable screen region, detects pixels matching "
           "target colors, and fires simulated keystrokes with human-like random timing "
           "so the pattern cannot be fingerprinted as automated."),
          ("◈  Screen Capture",
           "Uses Win32 BitBlt into a DIBSection — a raw 32-bit BGRA pixel buffer "
           "allocated once and reused every frame with zero heap allocation in the hot loop. "
           "For 40×40 px this takes under 1 ms. 'Follow Mouse' mode re-creates the capture "
           "region each frame centered on the cursor position."),
          ("◈  Color Matching",
           "Each pixel is compared to every target color via per-channel absolute difference:\n\n"
           "    match = |R_px − R_target| ≤ tolerance\n"
           "         AND |G_px − G_target| ≤ tolerance\n"
           "         AND |B_px − B_target| ≤ tolerance\n\n"
           "Scanning exits on the first match. tolerance=0 is exact; tolerance=60 is loose."),
          ("◈  Key Sequences",
           "Each trigger fires a sequence of keys in order with a configurable gap "
           "between them. Enter space-separated pynput key names in Config:\n\n"
           "  space          →  press Space\n"
           "  f1             →  press F1\n"
           "  ctrl shift s   →  press Ctrl, then Shift, then S (each held + released)"),
          ("◈  Humanization",
           "Three independent uniform random distributions are sampled each trigger:\n\n"
           "  • Pre-press delay  — jitter before key goes down (reaction time variance)\n"
           "  • Hold duration    — how long the key stays pressed\n"
           "  • Cooldown window  — lockout period between trigger events\n\n"
           "Wider min/max ranges produce more variation and are harder to fingerprint."),
          ("◈  Global Hotkey",
           "A pynput keyboard listener watches for the configured hotkey (default F8) "
           "regardless of which window has focus. It toggles the engine on/off instantly "
           "without touching the GUI. Change the hotkey in Config → Global Hotkey."),
          ("◈  Live Preview",
           "The Control tab shows a zoomed live view of the capture zone, refreshed ~10 "
           "times per second. When a matching pixel is found, its cell is highlighted in "
           "amber. Zoom levels 2×–8× let you see the region clearly regardless of its size."),
          ("◈  Eyedropper",
           "In the Colors tab, click 'Eyedropper'. The cursor becomes a crosshair. "
           "Click anywhere on the screen to read that pixel's exact RGB values and add "
           "them as a new target color automatically — no need to guess hex codes."),
          ("◈  Position Picker",
           "In Config → Capture Position, click 'Pick on screen'. A dark transparent "
           "overlay covers the screen with a crosshair. Move the mouse to position the "
           "capture rectangle and click to confirm. Coordinates are written back to Config."),
          ("◈  Profiles",
           "The Profiles tab saves the complete configuration (colors, timing, position, "
           "keys, auto-stop settings) to ct_profiles.json as named JSON presets. "
           "Switch between setups instantly without restarting."),
          ("◈  Auto-Stop",
           "Set 'Stop after N triggers' or 'Stop after N seconds' in Config (0 = disabled). "
           "When either limit is reached the engine deactivates and logs the reason. "
           "Useful for burst-mode operation or timed sessions."),
          ("◈  Statistics",
           "The Stats tab shows total triggers, session duration, average and peak trigger "
           "rates (per minute), and a rolling 60-second rate chart drawn live as the engine "
           "runs. Use 'Reset Statistics' to clear between sessions."),
          ("◈  System Tray",
           "With pystray + Pillow installed, closing the window offers to minimize to the "
           "system tray rather than quitting. Right-click the amber tray icon to Activate, "
           "Deactivate, or Quit from outside the GUI."),
          ("◈  Tips",
           "• Run as Administrator if the target window captures elevated input.\n"
           "• Keep capture zone 40–80 px for lowest latency and CPU use.\n"
           "• Use Eyedropper to sample exact on-screen colors — don't guess.\n"
           "• Wider randomization ranges make the timing pattern harder to detect.\n"
           "• Set COOLDOWN_MIN high enough to match your intended action rhythm.\n"
           "• Use Profiles to save per-game or per-app configurations.\n"
           "• For recoil: start with Y=4, interval=10ms, smooth pattern, then tune up/down.\n"
           "• The recoil reducer and color trigger run as fully independent threads."),
          ("◈  Recoil Reducer",
           "The Recoil Reducer compensates for weapon recoil by nudging the mouse "
           "downward (and optionally sideways) while the left mouse button is held.\n\n"
           "HOW IT WORKS:\n"
           "A daemon thread polls GetAsyncKeyState every rr_interval_ms milliseconds. "
           "While LMB is physically held AND the reducer is armed AND enabled, it calls "
           "mouse_event(MOUSEEVENTF_MOVE, dx, dy) — a raw relative move that bypasses "
           "Windows pointer acceleration entirely.\n\n"
           "THREE PATTERNS:\n"
           "  • Linear  — constant Y pixels every interval. Simple, predictable.\n"
           "  • Smooth  — sine-eased: ramps up at shot start, peaks at 50% of burst "
           "duration, then tapers. Closely mimics real automatic weapon recoil curves.\n"
           "  • Stepped — moves every 3rd interval only, mimicking burst-fire guns.\n\n"
           "TUNING:\n"
           "  Y step controls vertical pull strength. Start at 3–5 and increase if "
           "crosshair still climbs. X step corrects horizontal drift (positive = right, "
           "negative = left). Interval sets update frequency — 8–12 ms is smooth. "
           "Jitter adds ±pixel noise per step so the pattern is never mechanically "
           "uniform. Start delay lets the first bullet fire normally before "
           "compensation kicks in.\n\n"
           "HOTKEY:\n"
           "Default F7 arms/disarms the reducer from anywhere. It is independent of "
           "the main F8 color trigger toggle so you can enable/disable each separately.\n\n"
           "PRESETS:\n"
           "Each weapon/loadout can be saved as a named preset. Load it in one click "
           "before switching weapons. Presets are stored inside ct_profiles.json."),
        ]

        for heading,body in sections:
            hf=tk.Frame(inner,bg=ACCENT_DIM,highlightbackground=ACCENT,highlightthickness=1)
            hf.pack(fill="x",padx=16,pady=(12,0))
            tk.Label(hf,text=heading,font=FONT_HEADING,bg=ACCENT_DIM,
                     fg=ACCENT,anchor="w",padx=12,pady=6).pack(fill="x")
            bf=tk.Frame(inner,bg=BG_PANEL,highlightbackground=BORDER_DARK,highlightthickness=1)
            bf.pack(fill="x",padx=16,pady=(0,2))
            tk.Label(bf,text=body,font=FONT_BODY,bg=BG_PANEL,fg=TEXT_PRIMARY,
                     anchor="nw",justify="left",wraplength=590,padx=14,pady=10
                     ).pack(fill="x",anchor="w")
        tk.Frame(inner,bg=BG_BASE,height=20).pack()

    # ══════════════════════════════════════════════════════════════════════
    #  ENGINE CONTROL
    # ══════════════════════════════════════════════════════════════════════

    def _activate(self):
        self._apply_config(silent=True)
        self._is_active=True; self._update_status(True)
        self._engine=DetectionEngine(
            config=self._cfg, log_fn=self._post_log,
            stats_fn=self._update_stats, preview_fn=self._update_preview)
        self._engine.start()
        self._btn_act.configure(state="disabled",bg=BG_RAISED,fg=TEXT_MUTED)
        self._btn_dea.configure(state="normal",bg=RED_OFF,fg="#0d1117",activebackground="#b91c1c")
        self._post_log("Session started.","info")

    def _deactivate(self):
        if self._engine: self._engine.stop(); self._engine=None
        self._is_active=False; self._update_status(False)
        self._btn_act.configure(state="normal",bg=ACCENT,fg="#0d1117",activebackground=ACCENT_DARK)
        self._btn_dea.configure(state="disabled",bg=BG_RAISED,fg=TEXT_MUTED)
        self._post_log("Session stopped.","info")

    def _toggle(self):
        if self._is_active: self.after(0,self._deactivate)
        else:               self.after(0,self._activate)

    def _update_status(self,active:bool):
        if active:
            self._dot.itemconfig(self._dot_oval,fill=GREEN_ACTIVE)
            self._status_lbl.configure(text="ACTIVE",fg=GREEN_ACTIVE)
        else:
            self._dot.itemconfig(self._dot_oval,fill=RED_OFF)
            self._status_lbl.configure(text="INACTIVE",fg=RED_OFF)

    # ══════════════════════════════════════════════════════════════════════
    #  GLOBAL HOTKEY
    # ══════════════════════════════════════════════════════════════════════

    def _start_hotkey_listener(self):
        from pynput import keyboard as pynkb
        app=self
        def get_key(n):
            n=n.strip().lower()
            try: return pynkb.Key[n]
            except: return pynkb.KeyCode.from_char(n[0]) if n else pynkb.Key.f8
        self._hk_key    = get_key(self._cfg.get("hotkey","f8"))
        self._rr_hk_key = get_key(self._cfg.get("rr_hotkey","f7"))

        def on_press(key):
            # Main toggle
            if key == app._hk_key:
                app._toggle()
            # Recoil reducer toggle
            rr_key = get_key(app._cfg.get("rr_hotkey","f7"))
            if key == rr_key:
                if app._rr_engine and app._rr_engine.is_active:
                    app.after(0, app._rr_disarm)
                else:
                    app.after(0, app._rr_arm)

        self._hk_listener=pynkb.Listener(on_press=on_press,daemon=True)
        self._hk_listener.start()

    # ══════════════════════════════════════════════════════════════════════
    #  LOG
    # ══════════════════════════════════════════════════════════════════════

    def _post_log(self,msg:str,tag:str="trigger"):
        ts=time.strftime("%H:%M:%S")
        self.after(0,self._append_log,f"{ts}  {msg}\n",tag)

    def _append_log(self,line:str,tag:str):
        self._log_txt.configure(state="normal")
        self._log_txt.insert("end",line,tag)
        self._log_txt.configure(state="disabled")
        self._log_txt.see("end")

    def _export_log(self):
        path=filedialog.asksaveasfilename(defaultextension=".txt",
             filetypes=[("Text","*.txt"),("All","*.*")],title="Export Log")
        if path:
            with open(path,"w",encoding="utf-8") as f:
                f.write(self._log_txt.get("1.0","end"))

    # ══════════════════════════════════════════════════════════════════════
    #  STATS CALLBACKS
    # ══════════════════════════════════════════════════════════════════════

    def _update_stats(self,triggers:int,scans:int,elapsed:float,rate_hist:list):
        rate_pm=0.0
        if len(rate_hist)>=2:
            now=time.monotonic()
            wind=[(t,v) for t,v in rate_hist if t>=now-60]
            if len(wind)>=2:
                dt=wind[-1][0]-wind[0][0]; dv=wind[-1][1]-wind[0][1]
                rate_pm=(dv/max(dt,0.001))*60
        avg_pm=(triggers/max(elapsed,1))*60
        self._peak_rate=max(self._peak_rate,rate_pm)
        es=f"{int(elapsed//60):02d}:{int(elapsed%60):02d}"

        def u(w,t): w.configure(text=t)
        self.after(0,u,self._sv_trg,   str(triggers))
        self.after(0,u,self._sv_scn,   f"{scans:,}")
        self.after(0,u,self._sv_rate,  f"{rate_pm:.1f}")
        self.after(0,u,self._sv_upt,   es)
        self.after(0,u,self._st_total, str(triggers))
        self.after(0,u,self._st_sess,  es)
        self.after(0,u,self._st_avg,   f"{avg_pm:.1f}")
        self.after(0,u,self._st_peak,  f"{self._peak_rate:.1f}")

        self._chart_pts.append((elapsed,rate_pm))
        if len(self._chart_pts)>200: self._chart_pts=self._chart_pts[-200:]
        self.after(0,self._draw_chart)

    def _draw_chart(self):
        c=self._chart; c.delete("all")
        W=c.winfo_width() or 640; H=c.winfo_height() or 130; pad=28
        if len(self._chart_pts)<2:
            c.create_text(W//2,H//2,text="Waiting for data…",fill=TEXT_MUTED,font=FONT_MONO_SM)
            return
        pts=self._chart_pts
        mx=max(p[0] for p in pts) or 1
        my=max(p[1] for p in pts) or 1
        for i in range(5):
            y=pad+(H-pad*2)*i//4
            c.create_line(pad,y,W-pad,y,fill=CHART_GRID,dash=(2,4))
            c.create_text(pad-2,y,text=f"{my*(4-i)/4:.0f}",
                          anchor="e",fill=TEXT_MUTED,font=FONT_MONO_SM)
        def px(pt):
            return (pad+(pt[0]/mx)*(W-pad*2),
                    H-pad-(pt[1]/my)*(H-pad*2))
        coords=[]
        for pt in pts: coords.extend(px(pt))
        if len(coords)>=4:
            c.create_line(*coords,fill=CHART_LINE,width=2,smooth=True)
        lx,ly=px(pts[-1])
        c.create_oval(lx-3,ly-3,lx+3,ly+3,fill=ACCENT,outline="")
        c.create_text(lx+6,ly,text=f"{pts[-1][1]:.1f}",anchor="w",fill=ACCENT,font=FONT_MONO_SM)
        c.create_text(W//2,H-5,text="elapsed seconds",fill=TEXT_MUTED,font=FONT_MONO_SM)

    # ══════════════════════════════════════════════════════════════════════
    #  LIVE PREVIEW
    # ══════════════════════════════════════════════════════════════════════

    def _update_preview(self,pixels,w,h,match_idx):
        self.after(0,self._draw_preview,pixels,w,h,match_idx)

    def _draw_preview(self,pixels,w,h,match_idx):
        zoom=self._zoom_var.get()
        pw,ph=min(w*zoom,480),min(h*zoom,240)
        self._prev_cv.configure(width=pw,height=ph)
        if HAS_PIL:
            img=PILImage.new("RGB",(w,h))
            raw=[]
            for px in pixels:
                b=px&0xFF; g=(px>>8)&0xFF; r=(px>>16)&0xFF
                raw.append((r,g,b))
            img.putdata(raw)
            img=img.resize((pw,ph),PILImage.NEAREST)
            if match_idx>=0:
                draw=ImageDrawModule.Draw(img)
                mx=(match_idx%w)*zoom; my=(match_idx//w)*zoom
                draw.rectangle([mx,my,mx+zoom-1,my+zoom-1],outline="#f0a500",width=2)
            self._tk_img=ImageTk.PhotoImage(img)
            self._prev_cv.create_image(0,0,anchor="nw",image=self._tk_img)
        else:
            self._prev_cv.delete("all")
            for i,px in enumerate(pixels[:w*h]):
                b=px&0xFF; g=(px>>8)&0xFF; r=(px>>16)&0xFF
                col=f"#{r:02x}{g:02x}{b:02x}"
                x0=(i%w)*zoom; y0=(i//w)*zoom
                self._prev_cv.create_rectangle(x0,y0,x0+zoom,y0+zoom,fill=col,outline="")
            if match_idx>=0:
                mx=(match_idx%w)*zoom; my=(match_idx//w)*zoom
                self._prev_cv.create_rectangle(mx,my,mx+zoom,my+zoom,
                                                outline="#f0a500",width=2)
        matched=match_idx>=0
        self._prev_lbl.configure(
            text="◈  MATCH DETECTED" if matched else "Scanning…",
            fg=ACCENT if matched else TEXT_MUTED)

    # ══════════════════════════════════════════════════════════════════════
    #  CONFIG APPLY / LOAD
    # ══════════════════════════════════════════════════════════════════════

    def _apply_config(self,silent=False):
        keys=self._cv_keys.get().strip().split() or ["space"]
        self._cfg.update({
            "capture_width":      self._int(self._cv_w,  DEFAULT["capture_width"]),
            "capture_height":     self._int(self._cv_h,  DEFAULT["capture_height"]),
            "position_mode":      self._pos_mode.get(),
            "capture_x":          self._int(self._cv_px, 0),
            "capture_y":          self._int(self._cv_py, 0),
            "key_sequence":       keys,
            "sequence_gap_ms":    self._int(self._cv_gap,  DEFAULT["sequence_gap_ms"]),
            "hotkey":             self._cv_hotkey.get().strip() or DEFAULT["hotkey"],
            "auto_stop_triggers": self._int(self._cv_ast, 0),
            "auto_stop_seconds":  self._int(self._cv_ass, 0),
            "pre_min":  self._int(self._cv_pre_mn, DEFAULT["pre_min"]),
            "pre_max":  self._int(self._cv_pre_mx, DEFAULT["pre_max"]),
            "hold_min": self._int(self._cv_hld_mn, DEFAULT["hold_min"]),
            "hold_max": self._int(self._cv_hld_mx, DEFAULT["hold_max"]),
            "cool_min": self._int(self._cv_cld_mn, DEFAULT["cool_min"]),
            "cool_max": self._int(self._cv_cld_mx, DEFAULT["cool_max"]),
            "capture_sleep_ms":   self._int(self._cv_slp, DEFAULT["capture_sleep_ms"]),
            "tolerance":          self._tol_var.get(),
            "sound_alert":        self._sound_var.get(),
        })
        self._hk_badge.configure(text=f"  {self._cfg['hotkey'].upper()} = toggle  ")
        if not silent:
            self._cfg_msg.configure(text="✓ Applied",fg=GREEN_ACTIVE)
            self.after(2000,lambda:self._cfg_msg.configure(text=""))

    def _load_cfg_to_ui(self):
        def sv(w,k): w.set(str(self._cfg.get(k,"")))
        sv(self._cv_w,"capture_width"); sv(self._cv_h,"capture_height")
        sv(self._cv_px,"capture_x");   sv(self._cv_py,"capture_y")
        self._cv_keys.set(" ".join(self._cfg.get("key_sequence",["space"])))
        sv(self._cv_gap,"sequence_gap_ms"); sv(self._cv_hotkey,"hotkey")
        sv(self._cv_ast,"auto_stop_triggers"); sv(self._cv_ass,"auto_stop_seconds")
        sv(self._cv_pre_mn,"pre_min"); sv(self._cv_pre_mx,"pre_max")
        sv(self._cv_hld_mn,"hold_min"); sv(self._cv_hld_mx,"hold_max")
        sv(self._cv_cld_mn,"cool_min"); sv(self._cv_cld_mx,"cool_max")
        sv(self._cv_slp,"capture_sleep_ms")
        self._pos_mode.set(self._cfg.get("position_mode","center"))
        self._tol_var.set(self._cfg.get("tolerance",10))
        self._sound_var.set(self._cfg.get("sound_alert",False))
        self._refresh_colors()

    # ══════════════════════════════════════════════════════════════════════
    #  TIMER TICK
    # ══════════════════════════════════════════════════════════════════════

    def _tick_timer(self):
        if self._is_active and self._engine:
            e=self._engine.elapsed()
            self._timer_lbl.configure(text=f"{int(e//60):02d}:{int(e%60):02d}")
        self.after(500,self._tick_timer)

    # ══════════════════════════════════════════════════════════════════════
    #  SYSTEM TRAY
    # ══════════════════════════════════════════════════════════════════════

    def _build_tray(self):
        img=PILImage.new("RGBA",(64,64),(0,0,0,0))
        draw=ImageDrawModule.Draw(img)
        draw.ellipse([4,4,60,60],fill="#f0a500")
        draw.text((18,18),"CT",fill="#0d1117")
        menu=pystray.Menu(
            pystray.MenuItem("Show",self._tray_show,default=True),
            pystray.MenuItem("Activate",  lambda:self.after(0,self._activate)),
            pystray.MenuItem("Deactivate",lambda:self.after(0,self._deactivate)),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit",self._tray_quit),
        )
        self._tray_icon=pystray.Icon("ColorTrigger",img,"ColorTrigger",menu)
        threading.Thread(target=self._tray_icon.run,daemon=True).start()

    def _tray_show(self): self.after(0,self.deiconify); self.after(0,self.lift)
    def _tray_quit(self): self._on_close()

    # ══════════════════════════════════════════════════════════════════════
    #  WIDGET HELPERS
    # ══════════════════════════════════════════════════════════════════════

    def _card(self,parent):
        return tk.Frame(parent,bg=BG_PANEL,
                        highlightbackground=BORDER_MID,highlightthickness=1)

    def _btn(self,parent,text,bg,fg,cmd,state="normal"):
        return tk.Button(parent,text=text,font=FONT_HEADING,bg=bg,fg=fg,
                         activebackground=BORDER_MID,activeforeground=TEXT_PRIMARY,
                         relief="flat",bd=0,cursor="hand2",padx=14,pady=7,
                         state=state,command=cmd)

    def _lbtn_small(self,text,parent,cmd):
        l=tk.Label(parent,text=text,font=FONT_MONO_SM,bg=BG_BASE,fg=TEXT_MUTED,cursor="hand2")
        l.bind("<Button-1>",lambda _:cmd()); return l

    def _scrollable(self,parent):
        c=tk.Canvas(parent,bg=BG_BASE,highlightthickness=0)
        vsb=ttk.Scrollbar(parent,orient="vertical",command=c.yview,style="D.Vertical.TScrollbar")
        c.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right",fill="y"); c.pack(side="left",fill="both",expand=True)
        return c,vsb

    def _sec(self,parent,title):
        tk.Frame(parent,bg=BORDER_DARK,height=1).pack(fill="x",padx=16,pady=(12,0))
        tk.Label(parent,text=title.upper(),font=("Segoe UI Semibold",8),
                 bg=BG_BASE,fg=ACCENT,anchor="w",padx=20,pady=5).pack(fill="x")

    def _row(self,parent):
        f=tk.Frame(parent,bg=BG_BASE); f.pack(fill="x",padx=16,pady=2); return f

    def _field(self,parent,label,default,width=9):
        f=tk.Frame(parent,bg=BG_BASE); f.pack(side="left",padx=(0,16),pady=2)
        tk.Label(f,text=label,font=FONT_LABEL,bg=BG_BASE,fg=TEXT_LABEL,anchor="w").pack(anchor="w")
        var=tk.StringVar(value=str(default))
        tk.Entry(f,textvariable=var,width=width,font=FONT_MONO,bg=BG_INPUT,
                 fg=TEXT_PRIMARY,relief="flat",insertbackground=ACCENT,bd=0,
                 selectbackground=BORDER_MID).pack(ipady=4,ipadx=4)
        tk.Frame(f,bg=BORDER_MID,height=1).pack(fill="x")
        f.get=var.get; f.set=var.set; return f

    def _int(self,field,default):
        try: return max(0,int(field.get()))
        except: return default

    # ══════════════════════════════════════════════════════════════════════
    #  CLEANUP
    # ══════════════════════════════════════════════════════════════════════

    def _on_close(self):
        if HAS_TRAY and self._tray_icon:
            if messagebox.askyesno("Minimize?","Minimize to system tray instead of quitting?"):
                self.withdraw(); return
        if self._engine:    self._engine.stop()
        if self._rr_engine: self._rr_engine.stop()
        try:
            if self._tray_icon: self._tray_icon.stop()
        except: pass
        try:
            if hasattr(self,"_hk_listener"): self._hk_listener.stop()
        except: pass
        self.destroy()


# ═══════════════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    app = App()
    app.mainloop()