"""Switch the Attack Shark V8's profile automatically when a game is running.

Watches for the executables listed in config.json. While any of them is running
the mouse sits on `game_profile`; otherwise it returns to `default_profile`.
Runs from the system tray.

    python switcher.py              # normal run, with tray icon
    python switcher.py --dry-run    # log decisions, never touch the mouse
    python switcher.py --no-tray    # headless, for testing
"""

from __future__ import annotations

import argparse
import atexit
import ctypes
import json
import logging
import os
import subprocess
import sys
import threading
import time
from logging.handlers import RotatingFileHandler
from PIL import Image

import psutil

import detect_games
import overlay as overlay_module
import sharkctl
from winhid import HidError

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(HERE, "config.json")
LOG_DIR = os.path.join(os.environ.get("LOCALAPPDATA", HERE), "shark-profile-switcher")
LOG_PATH = os.path.join(LOG_DIR, "switcher.log")

DEFAULT_CONFIG = {
    "default_profile": 1,
    "game_profile": 2,
    "poll_seconds": 2,
    "games": [],
    # Flat keys, not a nested "popup" object: load_config merges shallowly, so a
    # nested dict in a user's config would replace these defaults wholesale.
    "popup_enabled": True,
    "popup_duration_ms": 1800,
}

log = logging.getLogger("switcher")

# "Local\" scopes the lock to the logon session, so separate users can each run
# their own copy while a single user cannot start two.
MUTEX_NAME = r"Local\shark-profile-switcher-single-instance"
_instance_mutex = None          # module-level: the handle must outlive this call


def acquire_single_instance() -> bool:
    """Claim the single-instance lock. False means a copy is already running.

    A named mutex rather than a PID or lock file: Windows drops it when the
    process ends by any route - clean exit, crash, or Stop-Process - so there is
    never a stale lock to detect and clean up.
    """
    global _instance_mutex
    error_already_exists = 183

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int,
                                      ctypes.c_wchar_p]
    kernel32.CreateMutexW.restype = ctypes.c_void_p

    handle = kernel32.CreateMutexW(None, False, MUTEX_NAME)
    if not handle:
        # Never block startup over a failure to create the lock itself.
        log.warning("could not create the instance lock (error %d); continuing",
                    ctypes.get_last_error())
        return True
    if ctypes.get_last_error() == error_already_exists:
        kernel32.CloseHandle(handle)
        return False

    _instance_mutex = handle
    return True


# The one path enable_start_at_boot.ps1 creates the shortcut at - kept in sync
# with that script rather than queried from it, since it never changes.
BOOT_SHORTCUT_PATH = os.path.join(
    os.environ.get("APPDATA", ""), "Microsoft", "Windows", "Start Menu",
    "Programs", "Startup", "Attack Shark Profile Switcher.lnk")


def is_boot_enabled() -> bool:
    """Whether the login shortcut exists.

    Only checks that one shortcut, not the other locations
    disable_start_at_boot.ps1 also cleans up (registry Run keys, Scheduled
    Tasks) - this tool only ever creates the shortcut, so those other locations
    only matter if something else put an entry there, which this checkbox
    can't speak to anyway.
    """
    return os.path.exists(BOOT_SHORTCUT_PATH)


def set_boot_enabled(enable: bool) -> tuple[bool, str]:
    """Enable or disable start at boot via the PowerShell scripts.

    Delegated rather than reimplemented here so there is exactly one place -
    enable_start_at_boot.ps1 / disable_start_at_boot.ps1 - that knows how to
    create or remove the shortcut, matching install.ps1 and manual use.
    """
    script = os.path.join(
        HERE, "enable_start_at_boot.ps1" if enable else "disable_start_at_boot.ps1")
    # -NoProfile matters here: loading the user's PowerShell profile is most of
    # the startup cost, and this is on the path of a menu click.
    args = ["powershell", "-NoProfile", "-NonInteractive",
            "-ExecutionPolicy", "Bypass", "-File", script]
    if enable:
        # sys.executable is pythonw.exe under the tray, which the script
        # accepts fine - it derives pythonw.exe from whatever it's given.
        args += ["-PythonPath", sys.executable]
    try:
        result = subprocess.run(
            args, capture_output=True, text=True, timeout=30,
            creationflags=subprocess.CREATE_NO_WINDOW)
        return result.returncode == 0, (result.stdout or result.stderr or "").strip()
    except Exception as exc:
        return False, str(exc)


def setup_logging() -> None:
    os.makedirs(LOG_DIR, exist_ok=True)
    log.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s  %(levelname)-7s %(message)s",
                            "%Y-%m-%d %H:%M:%S")
    handler = RotatingFileHandler(LOG_PATH, maxBytes=512_000, backupCount=3,
                                  encoding="utf-8")
    handler.setFormatter(fmt)
    log.addHandler(handler)
    if sys.stderr:                      # absent under pythonw.exe
        console = logging.StreamHandler()
        console.setFormatter(fmt)
        log.addHandler(console)


def load_config() -> dict:
    if not os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "w", encoding="utf-8") as handle:
            json.dump(DEFAULT_CONFIG, handle, indent=2)
        log.warning("created default %s - add your games to it", CONFIG_PATH)
        return dict(DEFAULT_CONFIG)
    # utf-8-sig, not utf-8: Notepad and PowerShell both write a BOM, which
    # json.load rejects outright.
    with open(CONFIG_PATH, encoding="utf-8-sig") as handle:
        config = json.load(handle)
    log.info("config: %s", CONFIG_PATH)
    merged = dict(DEFAULT_CONFIG)
    merged.update(config)
    return merged


class Switcher:
    """Polls for game processes and drives the mouse profile.

    `override` pins a profile and suspends game-aware switching; None means auto.
    The desired profile is re-asserted whenever a write fails, so an unplugged
    dongle or a sleeping mouse self-heals once the device comes back.
    """

    def __init__(self, config: dict, dry_run: bool = False):
        self.config = config
        self.dry_run = dry_run
        self.games = {name.lower() for name in config["games"]}
        self.override: int | None = None
        self.applied: int | None = None      # last profile confirmed written
        self.active_game: str | None = None
        self.device: sharkctl.HidInfo | None = None
        self._stop = threading.Event()
        self._on_change = lambda: None
        self._on_game_switch = lambda profile, context: None

    # -- device -------------------------------------------------------------

    def _apply(self, profile: int) -> bool:
        if self.dry_run:
            log.info("[dry-run] would switch to Profile %d", profile)
            self.applied = profile
            return True
        try:
            if self.device is None:
                self.device = sharkctl.find_device()
            sharkctl.set_profile(profile, self.device)
        except HidError as exc:
            # Force re-enumeration: the interface path changes across replugs.
            self.device = None
            self.applied = None
            log.warning("switch to Profile %d failed: %s", profile, exc)
            return False
        log.info("switched to Profile %d", profile)
        self.applied = profile
        return True

    # -- detection ----------------------------------------------------------

    def running_game(self) -> str | None:
        if not self.games:
            return None
        for proc in psutil.process_iter(["name"]):
            name = proc.info["name"]
            if name and name.lower() in self.games:
                return name
        return None

    def desired_profile(self) -> int:
        if self.override is not None:
            return self.override
        return (self.config["game_profile"] if self.active_game
                else self.config["default_profile"])

    # -- loop ---------------------------------------------------------------

    def tick(self) -> None:
        found = self.running_game() if self.override is None else None
        transition = found != self.active_game
        if transition:
            if found:
                log.info("game detected: %s", found)
            else:
                log.info("game exited: %s", self.active_game)
            self.active_game = found
            self._on_change()

        want = self.desired_profile()
        if want != self.applied:
            if self._apply(want):
                self._on_change()
                # Announce game transitions only. Pinning from the tray forces
                # `found` to None, which would otherwise look exactly like
                # "game exited" - hence the override check. Announcing only
                # after a successful _apply keeps a failed write silent rather
                # than claiming a switch that never happened.
                if transition and self.override is None:
                    self._on_game_switch(want, self.active_game or "Desktop")

    def run(self) -> None:
        log.info("watching %d game executable(s), poll every %ss",
                 len(self.games), self.config["poll_seconds"])
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception:
                log.exception("unexpected error in watch loop")
            self._stop.wait(self.config["poll_seconds"])

    def stop(self) -> None:
        self._stop.set()

    def revert(self) -> None:
        """Return the mouse to the desktop profile on shutdown."""
        target = self.config["default_profile"]
        if self.applied != target:
            log.info("reverting to Profile %d", target)
            self._apply(target)

    def set_override(self, profile: int | None) -> None:
        self.override = profile
        # Re-sync the game state before ticking. Without this, returning to auto
        # while a game is running looks like the game just started and would pop
        # up the overlay for what was actually a menu click.
        self.active_game = self.running_game() if profile is None else None
        log.info("mode: %s", f"pinned to Profile {profile}" if profile else "auto")
        self.tick()
        self._on_change()


# -- tray -------------------------------------------------------------------

def run_tray(switcher: Switcher, popup: overlay_module.Overlay) -> None:
    import pystray

    def title() -> str:
        state = (f"pinned to Profile {switcher.override}" if switcher.override
                 else (f"in game: {switcher.active_game}" if switcher.active_game
                       else "desktop"))
        return f"Attack Shark V8 - Profile {switcher.applied or '?'} ({state})"

    logo_path = os.path.join(HERE, "assets", "logo.png")
    icon_image = Image.open(logo_path)

    icon = pystray.Icon(
        "shark-profile-switcher",
        icon_image,
        title())

    def refresh() -> None:
        icon.title = title()
        icon.update_menu()

    switcher._on_change = refresh

    def choose(profile: int | None):
        return lambda _icon, _item: switcher.set_override(profile)

    def is_selected(profile: int | None):
        return lambda _item: switcher.override == profile

    def toggle_popups(_icon, _item) -> None:
        popup.enabled = not popup.enabled
        log.info("popups %s", "enabled" if popup.enabled else "disabled")

    # Applying the change shells out to PowerShell and takes a second or two, so
    # the checkbox cannot be driven off the filesystem alone: pystray bakes the
    # check state into the Win32 menu when update_menu() runs and does not
    # re-evaluate it on right-click, so reopening the menu mid-flight would show
    # the old state and look like the click did nothing. Hold the requested
    # state here, show that immediately, and fall back to disk once it lands.
    boot_pending: list[bool | None] = [None]     # None = nothing in flight
    boot_lock = threading.Lock()

    def boot_state() -> bool:
        pending = boot_pending[0]
        return is_boot_enabled() if pending is None else pending

    def boot_label(_item) -> str:
        return ("Start at boot  (applying...)" if boot_pending[0] is not None
                else "Start at boot")

    def toggle_boot(_icon, _item) -> None:
        boot_pending[0] = not boot_state()
        refresh()               # flips the checkbox now, not in three seconds

        def worker() -> None:
            with boot_lock:     # serialise; rapid clicks converge on the last
                target = boot_pending[0]
                if target is None:
                    return      # a previous worker already applied this
                ok, detail = set_boot_enabled(target)
                verb = "enable" if target else "disable"
                if ok:
                    log.info("start at boot %sd", verb)
                else:
                    log.warning("could not %s start at boot: %s", verb, detail)
                    try:
                        icon.notify(f"Could not {verb} start at boot.",
                                    "Attack Shark profile switcher")
                    except Exception:
                        pass
                # Leave it set if a newer click superseded this one - that
                # worker owns it and will clear it when it finishes.
                if boot_pending[0] == target:
                    boot_pending[0] = None
            refresh()           # drop the "applying" label, resync with disk
        threading.Thread(target=worker, name="toggle-boot", daemon=True).start()

    def detect_games_now(_icon, _item) -> None:
        # Same reasoning as toggle_boot: this walks Steam/Epic install
        # directories on disk, which is not instant.
        def worker() -> None:
            try:
                proposals = detect_games.find_all_games()
                added = detect_games.merge_into_config(proposals, CONFIG_PATH)
            except Exception:
                log.exception("game detection failed")
                return
            if added:
                log.info("game detection: added %d new game(s): %s",
                         len(added), ", ".join(added))
            else:
                log.info("game detection: %d candidate(s) found, nothing new",
                         len(proposals))
            # Pick up the new list without requiring a restart.
            switcher.config = load_config()
            switcher.games = {n.lower() for n in switcher.config["games"]}
            try:
                icon.notify(
                    f"Added {len(added)} new game(s) to config.json." if added
                    else "No new games found.",
                    "Attack Shark profile switcher")
            except Exception:
                pass  # balloon notifications aren't guaranteed everywhere
        threading.Thread(target=worker, name="detect-games", daemon=True).start()

    def quit_app(_icon, _item) -> None:
        switcher.stop()
        switcher.revert()
        popup.stop()
        icon.stop()

    icon.menu = pystray.Menu(
        pystray.MenuItem(lambda _item: title(), None, enabled=False),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Auto (game-aware)", choose(None),
                         checked=is_selected(None), radio=True),
        *[pystray.MenuItem(f"Pin to Profile {n}", choose(n),
                           checked=is_selected(n), radio=True)
          for n in range(1, sharkctl.PROFILE_COUNT + 1)],
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Show popups", toggle_popups,
                         checked=lambda _item: popup.enabled),
        pystray.MenuItem(boot_label, toggle_boot,
                         checked=lambda _item: boot_state()),
        pystray.MenuItem("Detect games", detect_games_now),
        pystray.MenuItem("Edit games list",
                         lambda _i, _it: os.startfile(CONFIG_PATH)),
        pystray.MenuItem("Open log",
                         lambda _i, _it: subprocess.Popen(
                             ["explorer", "/select,", LOG_PATH])),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Quit", quit_app),
    )

    threading.Thread(target=switcher.run, daemon=True).start()
    icon.run()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="log decisions without touching the mouse")
    parser.add_argument("--no-tray", action="store_true",
                        help="run headless instead of in the system tray")
    parser.add_argument("--config", help="use an alternate config file")
    parser.add_argument("--allow-multiple", action="store_true",
                        help="skip the single-instance check (for testing)")
    args = parser.parse_args()

    if args.config:
        global CONFIG_PATH
        CONFIG_PATH = os.path.abspath(args.config)

    setup_logging()

    # Before anything with a side effect: no logging setup beyond the file, no
    # device access, no Tk thread, no tray icon.
    if not args.allow_multiple and not acquire_single_instance():
        log.info("another instance is already running - exiting")
        if sys.stderr:                  # absent under pythonw.exe
            print("Attack Shark profile switcher is already running.",
                  file=sys.stderr)
        return 0

    config = load_config()
    switcher = Switcher(config, dry_run=args.dry_run)
    atexit.register(switcher.revert)

    # Wired here rather than in run_tray so --no-tray runs get popups too.
    # Started unconditionally: the Tk thread is idle when disabled, and this
    # surfaces any initialisation failure at startup instead of mid-game.
    popup = overlay_module.Overlay(
        duration_ms=config["popup_duration_ms"],
        logo_path=os.path.join(HERE, "assets", "logo.png"),
        enabled=config["popup_enabled"])
    popup.start()
    switcher._on_game_switch = lambda profile, context: popup.show(
        f"Profile {profile}", context)

    if not config["games"]:
        log.warning("no games configured - edit %s", CONFIG_PATH)

    if args.no_tray:
        try:
            switcher.run()
        except KeyboardInterrupt:
            pass
        finally:
            switcher.stop()
            switcher.revert()
            popup.stop()
        return 0

    run_tray(switcher, popup)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
