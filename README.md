![Logo](/logo.png?raw=true "Title")

# Attack Shark V8 — automatic profile switcher

For Attack Shark mouse, tested and working on Attack Shark V8 mouse.

This script add a missing feature to the Attack Shark mouse software: 
automatic profile switching. To get the most of your mouse, you often want the best 
gaming performance (e.g. 8KHz polling rate) when using your game, but best battery life
(e.g. 125Hz polling rate) when using it for desktop use. The automatic profile switcher 
feature allows for that to happen automatically whenever you enter or leave a game.

The utility switches the mouse's onboard profile when a game starts, and switches back when
it exits. Profile 1 on the desktop, Profile 2 in game, by default.

It talks to the mouse directly over USB HID. The Attack Shark Hub does **not**
need to be running — use it to *define* what each profile contains, then close it.

## Requirements

- Windows 10 or 11
- Python **3.9+, 64-bit**, including **tkinter** (ticked by default in the
  python.org installer as "tcl/tk and IDLE")
- Packages: `psutil`, `pystray`, `Pillow` — see `requirements.txt`
- An Attack Shark V8 with its 8K wireless dongle

64-bit matters: the mouse is driven through the 64-bit Windows HID API. There is
no `hidapi` dependency and nothing to compile — `winhid.py` is pure `ctypes`.

## Install

On a new machine, double-click **`install.bat`** (or run
`powershell -ExecutionPolicy Bypass -File install.ps1`). It:

1. finds a suitable Python, offering to install one with winget if there isn't one;
2. checks tkinter is present;
3. installs everything in `requirements.txt`;
4. verifies the imports and that the mouse is actually reachable;
5. **enables start at boot**;
6. **adds a desktop shortcut**, using `logo.ico`, that runs `run_now.bat`;
7. **adds the same shortcut to the Start Menu**;
8. **starts the app**;
9. prints the remaining steps.

It's safe to re-run — anything already in place is skipped or overwritten in
place (never duplicated), and starting it again while it's already running is a
harmless no-op (see *single copy* below).

| Flag | Effect |
|---|---|
| `-Yes` | Don't prompt before installing Python. |
| `-SkipPython` | Never install Python; fail with instructions instead. |
| `-WithCapture` | Also install `frida`, needed only to re-capture the mouse protocol. |
| `-NoStartAtBoot` | Install the dependencies but don't enable start at boot. |
| `-NoDesktopShortcut` | Install the dependencies but don't add the desktop shortcut. |
| `-NoStartMenuShortcut` | Install the dependencies but don't add the Start Menu shortcut. |
| `-NoRun` | Install the dependencies but don't start the app. |

If enabling start at boot fails, the install is still reported as successful —
the dependencies are in place, and `enable_start_at_boot.bat` will retry it. The
same applies if a shortcut or the run fails: `run_now.bat` covers all three.

Doing it by hand instead:

```bash
python -m pip install -r requirements.txt
```

If `import tkinter` fails, pip can't fix it — re-run the Python installer, choose
Modify, and tick *tcl/tk and IDLE*.

## Setup

1. In the ATTACK SHARK MOUSE HUB, configure Profile 1 (desktop) and Profile 2
   (gaming) the way you want them — DPI, polling rate, button mapping.
2. Fill in your games — from the tray menu's **Detect games**, or:

   ```bash
   python detect_games.py --write
   ```

   That scans installed Steam and Epic titles and guesses each main executable.
   **Review `config.json` afterwards** — the guess is a heuristic and can pick the
   wrong binary. Add anything it missed by hand.
3. Test it:

   ```bash
   python sharkctl.py 2
   ```

   The pointer speed should change if your profiles differ. `python sharkctl.py 1`
   puts it back.

`install.bat` has already started it, set it to start at every login, and put a
shortcut on your desktop and in the Start Menu. To change any of that, see
*Start at boot* below, or run `run_now.bat` by hand.

## Daily use

A tray icon shows the active profile — grey on the desktop, green in a game.
Right-click it for:

- **Auto (game-aware)** — the normal mode.
- **Pin to Profile 1–4** — hold one profile and suspend automatic switching.
- **Show popups** — mute or unmute the popup for this session.
- **Start at boot** — a checkbox showing whether the login shortcut is currently
  installed. The checkbox flips the instant you click it and the label reads
  *(applying...)* until the change lands a second or two later, so reopening the
  menu straight away shows the state you asked for, not the old one.
- **Detect games** — the same scan as `detect_games.py --write`, run from a
  background thread. New games are added to `config.json` and picked up
  immediately, no restart needed; you'll get a system notification with the
  result.
- **Edit games list** / **Open log**.
- **Quit** — reverts to Profile 1 on the way out.

## The popup

When a game starts or exits, a small card appears for ~1.8 s in the bottom-right
corner of **the primary monitor**, naming the new profile and either the game's
executable or `Desktop`.

It fires on game transitions only. Signing in is silent, quitting is silent, and
pinning a profile from the tray menu is silent — including un-pinning while a game
is running.

It cannot take focus: the window is marked `WS_EX_NOACTIVATE`, so it never pulls
focus away from a game or interrupts typing.

Preview it without launching the app:

```bash
python overlay.py "Profile 2" "cs2.exe"
```

## config.json

```json
{
  "default_profile": 1,
  "game_profile": 2,
  "poll_seconds": 2,
  "popup_enabled": true,
  "popup_duration_ms": 1800,
  "games": ["cs2.exe"]
}
```

`games` are executable names, matched case-insensitively — no paths. To find a
game's executable, launch it and look in Task Manager → Details.

Save the file as UTF-8. A BOM is tolerated, but other encodings are not.

## Command line

```bash
python sharkctl.py 3          # switch to Profile 3
python sharkctl.py get        # read the active profile
python sharkctl.py list       # show the mouse's HID collections
python switcher.py --dry-run  # log decisions without touching the mouse
python switcher.py --no-tray  # run headless (popups still shown)
python switcher.py --allow-multiple   # bypass the single-instance lock
python overlay.py "Profile 2" "cs2.exe"   # preview the popup
```

## Notes and limitations

- **`get` needs the mouse awake.** Writes are always accepted by the dongle, but
  the read-back query goes unanswered while the V8 is asleep, so `get` may report
  "unknown" after a period of inactivity. Switching itself is unaffected, and
  nothing in the switcher depends on read-back — it tracks its own state.
- **Detection is by process name**, polled every 2 s, so a switch lands within a
  couple of seconds of the game starting. Nothing is injected into any game; the
  tool only writes a HID report to your own mouse.
- **Only one copy runs at a time.** Launching it again while it's already running
  just exits the new process (quietly, with status 0) and leaves the existing one
  alone, so double-clicking the desktop shortcut or `run_now.bat` twice, or having
  it start at login while you're already running it, is harmless. The lock is a
  named Windows mutex, which the OS releases even if the process is killed —
  there's no stale lock file to clear. `--allow-multiple` overrides it for testing.
- **The Hub may fight it.** If you leave the Attack Shark Hub open it can reassert
  its own profile. Close it while playing.
- **The popup won't draw over exclusive-fullscreen games.** Borderless windowed —
  what most games default to — is fine. Showing over true exclusive fullscreen
  would mean hooking the game's present loop, which is exactly what anti-cheat
  objects to, so it is deliberately not done. In practice you'll see the popup
  when switching in, before the game takes the screen, and again on the way out.
- **Startup, not Task Scheduler** — deliberately, so no admin rights are needed.
  See *Start at boot* below.
- Logs rotate at `%LOCALAPPDATA%\shark-profile-switcher\switcher.log`.

## Start at boot

`install.bat` turns this on for you, so normally there's nothing to do. Toggle
it any time from the tray menu's **Start at boot** checkbox, or:

| To | Double-click |
|---|---|
| Turn it off | **`disable_start_at_boot.bat`** |
| Turn it back on | **`enable_start_at_boot.bat`** |

Or from a shell:

```bash
powershell -ExecutionPolicy Bypass -File disable_start_at_boot.ps1
powershell -ExecutionPolicy Bypass -File enable_start_at_boot.ps1
```

The tray checkbox reflects whether the login shortcut exists — the one thing
this tool ever creates. If something else somehow put an autostart entry
elsewhere (a registry key, a scheduled task), the checkbox won't know about it;
`disable_start_at_boot.bat` checks those other locations too.

Disabling removes the autostart entry only. Your files, `config.json` and the
mouse's profiles are all left alone — to remove the tool entirely, delete the
folder afterwards.

`disable_start_at_boot.ps1` takes these flags:

| Flag | Effect |
|---|---|
| *(none)* | Removes the autostart entry. Anything already running keeps running until you quit it from the tray. |
| `-StopNow` | Also stops the running instance, putting the mouse back on its default profile first — a killed process never runs its own revert, which would otherwise strand you on a game profile. |
| `-DryRun` | Reports what would be removed, changes nothing. |

It checks every place a startup entry can hide — the per-user and All Users
Startup folders, the `Run`/`RunOnce` registry keys under HKCU and HKLM, and
Scheduled Tasks — and matches strictly on `switcher.py` or this tool's own
directory. That precision is deliberate: the Attack Shark Hub registers its own
autostart entry, and a looser match would switch off the vendor software too.
Removing an All Users or HKLM entry needs an elevated prompt; it will tell you if
that ever applies.

`enable_start_at_boot.ps1 -Uninstall` also removes it, but only looks in the
Startup folder — prefer `disable_start_at_boot.bat`.

## If it stops working after an update

The protocol was recovered by observing the vendor Hub; a firmware or Hub update
could change it. `capture/FINDINGS.md` documents the full frame format, and the
capture can be repeated:

```bash
python capture/capture.py --seconds 180
```

Click through Profile 1 → 2 → 3 → 4 while it records, then diff the `08 0f` lines
against `FINDINGS.md`.

## Files

| File | Purpose |
|---|---|
| `winhid.py` | ctypes wrapper over setupapi + hid.dll — enumeration and report I/O |
| `sharkctl.py` | Profile get/set and the CLI |
| `switcher.py` | Process watcher and tray app |
| `overlay.py` | The profile-switch popup (also runnable standalone to preview it) |
| `detect_games.py` | Builds a games list from installed Steam/Epic titles (tray: "Detect games") |
| `install.ps1` / `install.bat` | First-time install: Python, packages, start at boot, desktop + Start Menu shortcuts, then run |
| `requirements.txt` | The package list |
| `enable_start_at_boot.ps1` / `.bat` | Adds the login shortcut |
| `disable_start_at_boot.ps1` / `.bat` | Removes every autostart entry pointing at this tool |
| `run_now.bat` | Starts it now, without waiting for a login (what the desktop shortcut runs) |
| `logo.ico` | Desktop-shortcut icon |
| `capture/` | The Frida tooling used to recover the protocol, plus `FINDINGS.md` |