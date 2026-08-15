"""Transient popup confirming a mouse profile switch.

Appears in the bottom-right corner of the primary monitor, then fades out.
Deliberately never takes focus - this pops up while a game is running, and
stealing focus could minimise it.

Standalone preview:

    python overlay.py "Profile 2" "cs2.exe"
"""

from __future__ import annotations

import ctypes
import logging
import os
import queue
import threading
import tkinter as tk
from ctypes import wintypes

from PIL import Image, ImageDraw, ImageFont, ImageTk

# Child of the switcher's logger, so records propagate to its handlers.
log = logging.getLogger("switcher.overlay")

# -- card appearance ---------------------------------------------------------

CARD_H = 84
CARD_W_MIN, CARD_W_MAX = 268, 440
RADIUS = 14
MARGIN = 24                     # gap from the screen's working-area corner
LOGO_PX = 48

# Any pixel of this exact colour is punched out by Windows, which is what gives
# the card real rounded corners. Chosen to be a colour nothing else would use.
KEY_COLOR = "#ff00fe"
KEY_RGB = (255, 0, 254)

BG_RGB = (30, 31, 34)
BORDER_RGB = (58, 61, 66)
TEXT_RGB = (255, 255, 255)
SUBTEXT_RGB = (154, 160, 166)

# -- win32 -------------------------------------------------------------------

user32 = ctypes.WinDLL("user32", use_last_error=True)

SPI_GETWORKAREA = 0x0030
GWL_EXSTYLE = -20
WS_EX_NOACTIVATE = 0x08000000
WS_EX_TOOLWINDOW = 0x00000080
GA_ROOT = 2
HWND_TOPMOST = -1
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOACTIVATE = 0x0010
SWP_SHOWWINDOW = 0x0040


class RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


user32.SystemParametersInfoW.argtypes = [
    ctypes.c_uint, ctypes.c_uint, ctypes.c_void_p, ctypes.c_uint]
user32.GetAncestor.argtypes = [wintypes.HWND, ctypes.c_uint]
user32.GetAncestor.restype = wintypes.HWND
user32.SetWindowPos.argtypes = [
    wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
    ctypes.c_int, ctypes.c_int, ctypes.c_uint]

# SetWindowLongPtrW only exists on 64-bit; 32-bit builds export SetWindowLongW.
if hasattr(user32, "SetWindowLongPtrW"):
    _get_style = user32.GetWindowLongPtrW
    _set_style = user32.SetWindowLongPtrW
else:
    _get_style = user32.GetWindowLongW
    _set_style = user32.SetWindowLongW
_get_style.argtypes = [wintypes.HWND, ctypes.c_int]
_get_style.restype = ctypes.c_ssize_t
_set_style.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
_set_style.restype = ctypes.c_ssize_t


def primary_work_area() -> RECT:
    """Working area (taskbar excluded) of the primary monitor.

    Always the primary, regardless of which screen the cursor or a game is on -
    the popup should be findable in a fixed place, not chase the mouse across a
    multi-monitor setup.
    """
    rect = RECT()
    user32.SystemParametersInfoW(SPI_GETWORKAREA, 0, ctypes.byref(rect), 0)
    return rect


# -- rendering ---------------------------------------------------------------


def _load_font(size: int, bold: bool = False):
    names = (("segoeuib.ttf", "arialbd.ttf", "seguisb.ttf") if bold
             else ("segoeui.ttf", "arial.ttf"))
    for name in names:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


FONT_HEAD = _load_font(23, bold=True)
FONT_SUB = _load_font(13)


def render_card(headline: str, subtext: str, logo: Image.Image | None) -> Image.Image:
    """Draw the whole popup as one image, keyed for transparency outside it."""
    text_left = MARGIN // 2 + (LOGO_PX + 14 if logo else 0)

    measure = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    widest = max(measure.textlength(headline, font=FONT_HEAD),
                 measure.textlength(subtext, font=FONT_SUB))
    width = int(min(CARD_W_MAX, max(CARD_W_MIN, text_left + widest + 22)))

    image = Image.new("RGB", (width, CARD_H), KEY_RGB)
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle([0, 0, width - 1, CARD_H - 1], radius=RADIUS,
                           fill=BG_RGB, outline=BORDER_RGB, width=1)

    if logo:
        image.paste(logo, (MARGIN // 2, (CARD_H - LOGO_PX) // 2), logo)

    if subtext:
        draw.text((text_left, 32), headline, font=FONT_HEAD,
                  fill=TEXT_RGB, anchor="lm")
        draw.text((text_left, 56), subtext, font=FONT_SUB,
                  fill=SUBTEXT_RGB, anchor="lm")
    else:
        draw.text((text_left, CARD_H // 2), headline, font=FONT_HEAD,
                  fill=TEXT_RGB, anchor="lm")
    return image


# -- overlay -----------------------------------------------------------------


class Overlay:
    """A reusable popup driven from any thread.

    tkinter owns a thread of its own here: pystray's icon.run() holds the main
    thread and the profile watcher runs in another, so Tk gets a third with its
    own mainloop. Tk is not thread-safe, so show() only enqueues a request and
    the Tk thread drains the queue from a periodic after() callback.
    """

    def __init__(self, duration_ms: int = 1800, logo_path: str | None = None,
                 fade_ms: int = 250, enabled: bool = True):
        self.duration_ms = duration_ms
        self.fade_ms = fade_ms
        self.logo_path = logo_path
        self.enabled = enabled

        self._queue: queue.Queue = queue.Queue()
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._root: tk.Tk | None = None
        self._win: tk.Toplevel | None = None
        self._label: tk.Label | None = None
        self._photo = None          # a live reference, or Tk drops the image
        self._logo: Image.Image | None = None
        self._generation = 0        # invalidates in-flight fade callbacks

    # -- public API ---------------------------------------------------------

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="overlay",
                                        daemon=True)
        self._thread.start()
        if not self._ready.wait(timeout=5):
            log.warning("overlay thread did not start in time")

    def show(self, headline: str, subtext: str = "") -> None:
        """Queue a popup. Safe to call from any thread; returns immediately."""
        if not self.enabled or self._thread is None:
            return
        self._queue.put((headline, subtext))

    def stop(self) -> None:
        if self._thread is not None:
            self._queue.put(None)

    # -- Tk thread ----------------------------------------------------------

    def _run(self) -> None:
        try:
            self._root = tk.Tk()
            self._root.withdraw()
            self._build()
        except Exception:
            log.exception("overlay failed to initialise; popups disabled")
            self.enabled = False
            self._ready.set()
            return
        self._ready.set()
        self._root.after(75, self._poll)
        try:
            self._root.mainloop()
        except Exception:
            log.exception("overlay mainloop crashed")

    def _build(self) -> None:
        if self.logo_path and os.path.exists(self.logo_path):
            logo = Image.open(self.logo_path).convert("RGBA")
            self._logo = logo.resize((LOGO_PX, LOGO_PX), Image.LANCZOS)

        win = tk.Toplevel(self._root)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        win.attributes("-transparentcolor", KEY_COLOR)
        win.configure(bg=KEY_COLOR)
        self._label = tk.Label(win, bd=0, highlightthickness=0, bg=KEY_COLOR)
        self._label.pack()
        win.update_idletasks()
        win.withdraw()
        self._win = win
        self._deny_activation()

    def _deny_activation(self) -> None:
        """Mark the window as never-activating, so it cannot take focus.

        overrideredirect alone does not stop Windows activating the window on
        show; WS_EX_NOACTIVATE does. WS_EX_TOOLWINDOW additionally keeps it out
        of the Alt-Tab list.
        """
        try:
            hwnd = user32.GetAncestor(self._win.winfo_id(), GA_ROOT) \
                or self._win.winfo_id()
            style = _get_style(hwnd, GWL_EXSTYLE)
            _set_style(hwnd, GWL_EXSTYLE,
                       style | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW)
        except Exception:
            log.exception("could not apply no-activate window style")

    def _poll(self) -> None:
        try:
            while True:
                item = self._queue.get_nowait()
                if item is None:
                    self._root.quit()
                    return
                self._display(*item)
        except queue.Empty:
            pass
        except Exception:
            log.exception("overlay failed to display")
        self._root.after(75, self._poll)

    def _display(self, headline: str, subtext: str) -> None:
        self._generation += 1
        generation = self._generation

        image = render_card(headline, subtext, self._logo)
        self._photo = ImageTk.PhotoImage(image)
        self._label.configure(image=self._photo)

        work = primary_work_area()
        x = work.right - image.width - MARGIN
        y = work.bottom - CARD_H - MARGIN
        self._win.geometry(f"{image.width}x{CARD_H}+{x}+{y}")

        self._win.attributes("-alpha", 1.0)
        self._win.deiconify()
        self._deny_activation()

        # Raise to topmost explicitly rather than via lift(), which activates.
        try:
            hwnd = user32.GetAncestor(self._win.winfo_id(), GA_ROOT) \
                or self._win.winfo_id()
            user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                                SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE
                                | SWP_SHOWWINDOW)
        except Exception:
            log.exception("could not raise overlay")

        self._win.after(self.duration_ms, self._begin_fade, generation)

    def _begin_fade(self, generation: int) -> None:
        if generation != self._generation:
            return              # superseded by a newer popup
        steps = max(1, self.fade_ms // 25)
        self._fade_step(generation, steps, steps)

    def _fade_step(self, generation: int, remaining: int, total: int) -> None:
        if generation != self._generation:
            return
        if remaining <= 0:
            self._win.withdraw()
            self._win.attributes("-alpha", 1.0)
            return
        self._win.attributes("-alpha", remaining / total)
        self._win.after(25, self._fade_step, generation, remaining - 1, total)


if __name__ == "__main__":
    import sys
    import time

    head = sys.argv[1] if len(sys.argv) > 1 else "Profile 2"
    sub = sys.argv[2] if len(sys.argv) > 2 else "cs2.exe"

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    overlay = Overlay(logo_path=os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "logo.png"))
    overlay.start()
    overlay.show(head, sub)
    time.sleep((overlay.duration_ms + overlay.fade_ms) / 1000 + 0.6)
