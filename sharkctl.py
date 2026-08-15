"""Switch the Attack Shark V8's active onboard profile.

Protocol captured from the vendor Hub - see capture/FINDINGS.md.

    17-byte output report on the MI_01 / usage-page 0xFF02 collection:
        08 0F 00 00 00 01 <idx> 00 x9 <cksum>
    <idx> is 0-based (Profile 1 = 0x00), cksum = (0x55 - sum(bytes[0..15])) & 0xFF
"""

from __future__ import annotations

import sys

from winhid import HidDevice, HidError, HidInfo, enumerate_hid

VID = 0x3554
PID = 0xF517

VENDOR_USAGE_PAGE = 0xFF02
VENDOR_USAGE = 0x02
REPORT_LEN = 17

REPORT_ID = 0x08
CMD_SET_PROFILE = 0x0F
CMD_GET_PROFILE = 0x0E

PROFILE_COUNT = 4


class DeviceNotFound(HidError):
    """The dongle is not plugged in, or the config collection is missing."""


def checksum(data: bytes) -> int:
    return (0x55 - sum(data)) & 0xFF


def build_frame(command: int, args: bytes = b"") -> bytes:
    """Build a 17-byte report: ID, command, arguments, trailing checksum."""
    frame = bytearray(REPORT_LEN)
    frame[0] = REPORT_ID
    frame[1] = command
    frame[2:2 + len(args)] = args
    frame[REPORT_LEN - 1] = checksum(frame[:REPORT_LEN - 1])
    return bytes(frame)


def find_device() -> HidInfo:
    """Locate the vendor config collection.

    Selected by usage page rather than by 'col05' in the path: the collection
    index is assigned by Windows and the instance part of the path changes with
    the USB port, but the usage page comes from the device's report descriptor.
    """
    candidates = enumerate_hid(VID, PID)
    if not candidates:
        raise DeviceNotFound(
            f"No VID_{VID:04X}/PID_{PID:04X} device. Is the dongle plugged in?")

    for info in candidates:
        if (info.usage_page == VENDOR_USAGE_PAGE
                and info.usage == VENDOR_USAGE
                and info.output_len == REPORT_LEN):
            return info

    raise DeviceNotFound(
        f"Dongle found but no usage-page 0x{VENDOR_USAGE_PAGE:04X} collection "
        f"with {REPORT_LEN}-byte output reports. Firmware may have changed - "
        "re-run capture/capture.py.")


def set_profile(profile: int, info: HidInfo | None = None) -> None:
    """Select profile 1..4 (as numbered in the Hub UI)."""
    if not 1 <= profile <= PROFILE_COUNT:
        raise ValueError(f"profile must be 1..{PROFILE_COUNT}, got {profile}")
    info = info or find_device()
    frame = build_frame(CMD_SET_PROFILE,
                        bytes([0x00, 0x00, 0x00, 0x01, profile - 1]))
    with HidDevice(info, overlapped=True) as dev:
        dev.write_output(frame)


def get_profile(info: HidInfo | None = None, attempts: int = 3) -> int | None:
    """Best-effort read of the active profile; None if the device doesn't answer.

    Only answers while the mouse is awake - a sleeping V8 leaves the query
    unacknowledged even though the dongle still accepts writes. The query is
    therefore re-sent a few times before giving up, and callers must treat None
    as "unknown" rather than as an error. Nothing in the switcher depends on it;
    it exists for manual checks and the tray display.

    Reads on this collection also see unrelated traffic, because Windows
    delivers every input report to all open handles - the Hub's ~1 Hz status
    poll shows up here too, hence the explicit command-byte match.
    """
    info = info or find_device()
    query = build_frame(CMD_GET_PROFILE)
    try:
        with HidDevice(info, overlapped=True) as dev:
            for _ in range(attempts):
                dev.write_output(query)
                for _ in range(6):
                    try:
                        reply = dev.read_input(timeout_ms=250)
                    except HidError:
                        break               # nothing pending; re-send the query
                    if len(reply) >= 7 and reply[1] == CMD_GET_PROFILE:
                        return reply[6] + 1
    except HidError:
        return None
    return None


def main() -> int:
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print(__doc__)
        print("Usage:\n"
              "  python sharkctl.py <1-4>   select a profile\n"
              "  python sharkctl.py get     read the active profile\n"
              "  python sharkctl.py list    show matching HID collections")
        return 0

    try:
        if args[0] == "list":
            for info in enumerate_hid(VID, PID):
                mark = ""
                if (info.usage_page == VENDOR_USAGE_PAGE
                        and info.usage == VENDOR_USAGE
                        and info.output_len == REPORT_LEN):
                    mark = "  <-- config channel"
                print(info.describe() + mark)
            return 0

        if args[0] == "get":
            current = get_profile()
            print(f"active profile: {current}" if current
                  else "active profile: unknown (device did not answer)")
            return 0

        profile = int(args[0])
        set_profile(profile)
        print(f"switched to Profile {profile}")
        return 0

    except (HidError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
