![Logo](/assets/logo.png?raw=true "Title")

# Attack Shark V8 — automatic profile switcher

For Attack Shark mice, tested and working on the Attack Shark V8.

Your mouse can store several onboard profiles (DPI, polling rate, button
mapping), but switching between them by hand is a hassle. This tool switches
automatically: it watches for a game to start, flips the mouse to your gaming
profile (e.g. 8KHz polling), and flips it back to your desktop profile (e.g.
125Hz, for battery life) when you quit.

It talks to the mouse directly over USB. The Attack Shark Hub only needs to
be open when you're *setting up* what each profile contains — close it
before you play.

## Requirements

- Windows 10 or 11
- Python **3.9+, 64-bit**, including **tkinter** (ticked by default in the
  python.org installer as "tcl/tk and IDLE")
- An Attack Shark V8 with its 8K wireless dongle

## Install

Double-click **`install.bat`**. It installs everything needed, sets the app
to start automatically when you log in, adds a shortcut to your desktop and
Start Menu, and launches it.

It's safe to re-run any time — nothing gets duplicated, and running it while
the app is already open is a harmless no-op.

Prefer not to auto-start at login, or skip the shortcuts? Run from a terminal
instead:

```bash
powershell -ExecutionPolicy Bypass -File install.ps1 -NoStartAtBoot -NoDesktopShortcut -NoStartMenuShortcut
```

## Setup

1. In the ATTACK SHARK MOUSE HUB, configure Profile 1 (desktop) and Profile 2
   (gaming) the way you want them — DPI, polling rate, button mapping.
2. Add your games from the tray menu's **Detect games** — it scans your
   installed Steam and Epic library and fills in `config.json` for you.
   **Double-check the result**: the guess is a heuristic and can occasionally
   pick the wrong `.exe`. Add anything it missed by hand.
3. Launch a game and confirm the popup appears and your pointer feels
   different. If not, see *Notes and limitations* below.

## How to use

A tray icon shows the active profile — grey on the desktop, green in a game.
Right-click it for the menu:

![Tray menu](/assets/screenshot1.png?raw=true "Tray menu")

- **Auto (game-aware)** — the normal mode.
- **Pin to Profile 1–4** — hold one profile and suspend automatic switching.
- **Show popups** — mute or unmute the popup for this session.
- **Start at boot** — check or uncheck to control whether it launches at login.
- **Detect games** — rescan for installed games and add any new ones.
- **Edit games list** — opens `config.json`.
- **Open log** — for troubleshooting.
- **Quit** — also puts the mouse back on your desktop profile.

## The popup

When a game starts or exits, a small card appears briefly in the corner of
your screen, naming the new profile and the game (or "Desktop"):

![Profile switch popup](/assets/screenshot2.png?raw=true "Profile switch popup")

It only appears on an actual game transition — not at sign-in, not on quit,
not when you pin a profile from the tray menu — and it's designed to never
steal focus from your game.

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

`games` are executable names, matched case-insensitively — no paths. To find
a game's executable, launch it and look in Task Manager → Details.

Save the file as UTF-8.

## Notes and limitations

- **Reading the current profile needs the mouse awake.** Switching always
  works, but `sharkctl.py get` may report "unknown" if the mouse has gone to
  sleep — that's just the read-back, not the switch itself.
- **Detection checks every 2 seconds**, so a switch lands within a couple of
  seconds of the game starting.
- **Only one copy runs at a time.** Launching it again while it's already
  running (e.g. double-clicking the shortcut twice) is harmless.
- **Close the Attack Shark Hub while playing** — if left open, it can
  reassert its own profile over this tool's.
- **The popup won't draw over exclusive-fullscreen games** — borderless
  windowed (what most games default to) is fine.
- Logs are at `%LOCALAPPDATA%\shark-profile-switcher\switcher.log`, also
  reachable from the tray menu's **Open log**.

## Start at boot

Toggle this any time from the tray menu's **Start at boot** checkbox. It only
adds or removes a shortcut in your Windows Startup folder — no admin rights
needed, and no scheduled task or registry entry left behind.

## If it stops working after a mouse/Hub update

This tool doesn't use an official API — it was built by observing what the
Attack Shark Hub sends to the mouse. A firmware or Hub update could change
that and break switching. If that happens, open an issue; recapturing the
protocol is documented in `capture/FINDINGS.md`.

## Command line

For scripting or troubleshooting:

```bash
python sharkctl.py 3          # switch to Profile 3
python sharkctl.py get        # read the active profile
python switcher.py --dry-run  # log decisions without touching the mouse
python switcher.py --no-tray  # run headless (popups still shown)
```
