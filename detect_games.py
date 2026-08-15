"""Propose a games list for config.json from installed Steam and Epic titles.

Executable names are guessed from each game's install directory, so review the
output before trusting it - a wrong guess just means the profile won't switch
for that game.

    python detect_games.py            # print proposed entries
    python detect_games.py --write    # merge them into config.json

Also importable: switcher.py's "Detect games" tray menu item calls
find_all_games() / merge_into_config() directly rather than shelling out.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys

STEAM_ROOTS = [
    r"C:\Program Files (x86)\Steam",
    r"C:\Program Files\Steam",
    os.path.expandvars(r"%LOCALAPPDATA%\Steam"),
]
EPIC_MANIFESTS = r"C:\ProgramData\Epic\EpicGamesLauncher\Data\Manifests"

# Helper binaries that ship alongside games but are never the game itself.
# The SDK/tool words matter as much as the installer ones: Valve ships
# source1import.exe at 18 MB next to a 2.8 MB cs2.exe, so size alone misleads.
SKIP_PATTERNS = re.compile(
    r"(unitycrashhandler|unins|setup|vcredist|dxsetup|dotnet|directx|"
    r"crashhandler|crashreport|easyanticheat|battleye|launcher_helper|"
    r"redist|installer|updater|report|helper|service|activation|"
    r"benchmark|editor|server|dedicated|"
    r"import|convert|compile|resource|console|cfg|vbsp|vrad|vvis|"
    r"workshop|legacy|tool|shader|_build_|cache|dump|test)",
    re.IGNORECASE)

PREFERRED_DIRS = ("binaries\\win64", "binaries\\win32", "bin\\win64", "bin")


def steam_libraries() -> list[str]:
    """Read library paths out of libraryfolders.vdf."""
    libraries: list[str] = []
    for root in STEAM_ROOTS:
        vdf = os.path.join(root, "steamapps", "libraryfolders.vdf")
        if not os.path.exists(vdf):
            continue
        libraries.append(root)
        with open(vdf, encoding="utf-8", errors="ignore") as handle:
            for match in re.finditer(r'"path"\s+"([^"]+)"', handle.read()):
                libraries.append(match.group(1).replace("\\\\", "\\"))
    seen, unique = set(), []
    for lib in libraries:
        if lib.lower() not in seen and os.path.isdir(lib):
            seen.add(lib.lower())
            unique.append(lib)
    return unique


def steam_games() -> list[tuple[str, str]]:
    """Return (display name, install directory) for each installed Steam game."""
    games: list[tuple[str, str]] = []
    for library in steam_libraries():
        steamapps = os.path.join(library, "steamapps")
        if not os.path.isdir(steamapps):
            continue
        for entry in os.listdir(steamapps):
            if not entry.startswith("appmanifest_"):
                continue
            try:
                with open(os.path.join(steamapps, entry), encoding="utf-8",
                          errors="ignore") as handle:
                    text = handle.read()
            except OSError:
                continue
            name = re.search(r'"name"\s+"([^"]+)"', text)
            installdir = re.search(r'"installdir"\s+"([^"]+)"', text)
            if not (name and installdir):
                continue
            path = os.path.join(steamapps, "common", installdir.group(1))
            if os.path.isdir(path):
                games.append((name.group(1), path))
    return games


def epic_games() -> list[tuple[str, str]]:
    """Epic manifests name their launch executable outright."""
    games: list[tuple[str, str]] = []
    if not os.path.isdir(EPIC_MANIFESTS):
        return games
    for entry in os.listdir(EPIC_MANIFESTS):
        if not entry.endswith(".item"):
            continue
        try:
            with open(os.path.join(EPIC_MANIFESTS, entry), encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, ValueError):
            continue
        exe = data.get("LaunchExecutable")
        name = data.get("DisplayName")
        if exe and name:
            games.append((name, os.path.basename(exe)))
    return games


def score(path: str, root: str, game: str = "") -> tuple[int, int]:
    """Rank a candidate executable.

    Name resemblance to the game title outranks location, and location outranks
    size - size is only a tiebreaker, since tool binaries are often the largest
    files in an install.
    """
    relative = os.path.relpath(path, root).lower()
    stem = os.path.splitext(os.path.basename(path))[0].lower()
    normalised = re.sub(r"[^a-z0-9]", "", game.lower())
    flat_stem = re.sub(r"[^a-z0-9]", "", stem)

    name_bonus = 0
    if flat_stem and normalised:
        if flat_stem == normalised:
            name_bonus = 12
        elif flat_stem in normalised or normalised.startswith(flat_stem):
            name_bonus = 8
        elif len(flat_stem) > 3 and flat_stem in normalised.replace(" ", ""):
            name_bonus = 4

    depth_bonus = 2 if os.sep not in relative else 0
    dir_bonus = 3 if any(p in relative for p in PREFERRED_DIRS) else 0
    try:
        size = os.path.getsize(path)
    except OSError:
        size = 0
    return (name_bonus + depth_bonus + dir_bonus, size)


def find_executable(root: str, game: str = "", max_depth: int = 4) -> str | None:
    """Pick the most plausible game executable under an install directory."""
    candidates: list[str] = []
    root_depth = root.rstrip(os.sep).count(os.sep)
    for current, dirs, files in os.walk(root):
        if current.count(os.sep) - root_depth >= max_depth:
            dirs[:] = []
            continue
        dirs[:] = [d for d in dirs if not SKIP_PATTERNS.search(d)]
        for name in files:
            if name.lower().endswith(".exe") and not SKIP_PATTERNS.search(name):
                candidates.append(os.path.join(current, name))
    if not candidates:
        return None
    best = max(candidates, key=lambda p: score(p, root, game))
    return os.path.basename(best)


def find_all_games() -> dict[str, str]:
    """Return {executable: game name} for every installed Steam/Epic title.

    Used directly by switcher.py's "Detect games" tray menu item, which calls
    this instead of shelling out to `python detect_games.py --write`.
    """
    proposals: dict[str, str] = {}
    for name, path in sorted(steam_games()):
        exe = find_executable(path, name)
        if exe:
            proposals.setdefault(exe, name)
    for name, exe in sorted(epic_games()):
        proposals.setdefault(exe, name)
    return proposals


DEFAULT_CONFIG_SHAPE = {"default_profile": 1, "game_profile": 2,
                        "poll_seconds": 2, "games": []}


def merge_into_config(proposals: dict[str, str], config_path: str) -> list[str]:
    """Add any not-already-listed executables to config.json's games list.

    Returns the executables that were actually added. Writes the file only when
    there's something new, so a no-op call never touches its mtime.
    """
    config = dict(DEFAULT_CONFIG_SHAPE)
    if os.path.exists(config_path):
        with open(config_path, encoding="utf-8-sig") as handle:
            config.update(json.load(handle))

    existing = {g.lower() for g in config["games"]}
    added = [exe for exe in sorted(proposals) if exe.lower() not in existing]
    if added:
        config["games"] = sorted(config["games"] + added)
        with open(config_path, "w", encoding="utf-8") as handle:
            json.dump(config, handle, indent=2)
    return added


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true",
                        help="merge the proposals into config.json")
    args = parser.parse_args()

    proposals: dict[str, str] = {}      # exe -> game name

    for name, path in sorted(steam_games()):
        exe = find_executable(path, name)
        if exe:
            proposals.setdefault(exe, name)
        print(f"{name:<45} {exe or '(no executable found)'}")

    for name, exe in sorted(epic_games()):
        proposals.setdefault(exe, name)
        print(f"{name:<45} {exe}   [Epic]")

    if not proposals:
        print("\nNo games found.")
        return 0

    print(f"\n{len(proposals)} candidate executable(s).")

    if not args.write:
        print("Re-run with --write to merge these into config.json.")
        return 0

    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "config.json")
    added = merge_into_config(proposals, config_path)
    print(f"Added {len(added)} entries to {config_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
