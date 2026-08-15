"""Minimal Windows HID access via ctypes (setupapi + hid.dll).

Deliberately dependency-free: no hidapi wheel, and no reliance on the vendor's
HIDUsb.dll. Enumerates HID interfaces, reports their capabilities, and sends or
receives feature reports.

On Windows a feature report buffer always begins with the report ID, so a device
whose FeatureReportByteLength is 65 carries 64 bytes of payload after the ID.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from typing import Iterator, NamedTuple

setupapi = ctypes.WinDLL("setupapi", use_last_error=True)
hid = ctypes.WinDLL("hid", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
FILE_SHARE_READ = 0x00000001
FILE_SHARE_WRITE = 0x00000002
OPEN_EXISTING = 3
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

DIGCF_PRESENT = 0x02
DIGCF_DEVICEINTERFACE = 0x10
ERROR_INSUFFICIENT_BUFFER = 122
ERROR_NO_MORE_ITEMS = 259

FILE_FLAG_OVERLAPPED = 0x40000000
ERROR_IO_PENDING = 997
WAIT_OBJECT_0 = 0
WAIT_TIMEOUT = 258


class OVERLAPPED(ctypes.Structure):
    _fields_ = [
        ("Internal", ctypes.c_void_p),
        ("InternalHigh", ctypes.c_void_p),
        ("Offset", wintypes.DWORD),
        ("OffsetHigh", wintypes.DWORD),
        ("hEvent", wintypes.HANDLE),
    ]


class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_ulong),
        ("Data2", ctypes.c_ushort),
        ("Data3", ctypes.c_ushort),
        ("Data4", ctypes.c_ubyte * 8),
    ]


class SP_DEVICE_INTERFACE_DATA(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("InterfaceClassGuid", GUID),
        ("Flags", wintypes.DWORD),
        ("Reserved", ctypes.POINTER(ctypes.c_ulong)),
    ]


class HIDD_ATTRIBUTES(ctypes.Structure):
    _fields_ = [
        ("Size", ctypes.c_ulong),
        ("VendorID", ctypes.c_ushort),
        ("ProductID", ctypes.c_ushort),
        ("VersionNumber", ctypes.c_ushort),
    ]


class HIDP_CAPS(ctypes.Structure):
    _fields_ = [
        ("Usage", ctypes.c_ushort),
        ("UsagePage", ctypes.c_ushort),
        ("InputReportByteLength", ctypes.c_ushort),
        ("OutputReportByteLength", ctypes.c_ushort),
        ("FeatureReportByteLength", ctypes.c_ushort),
        ("Reserved", ctypes.c_ushort * 17),
        ("NumberLinkCollectionNodes", ctypes.c_ushort),
        ("NumberInputButtonCaps", ctypes.c_ushort),
        ("NumberInputValueCaps", ctypes.c_ushort),
        ("NumberInputDataIndices", ctypes.c_ushort),
        ("NumberOutputButtonCaps", ctypes.c_ushort),
        ("NumberOutputValueCaps", ctypes.c_ushort),
        ("NumberOutputDataIndices", ctypes.c_ushort),
        ("NumberFeatureButtonCaps", ctypes.c_ushort),
        ("NumberFeatureValueCaps", ctypes.c_ushort),
        ("NumberFeatureDataIndices", ctypes.c_ushort),
    ]


setupapi.SetupDiGetClassDevsW.restype = wintypes.HANDLE
setupapi.SetupDiGetClassDevsW.argtypes = [
    ctypes.POINTER(GUID), wintypes.LPCWSTR, wintypes.HWND, wintypes.DWORD]
setupapi.SetupDiEnumDeviceInterfaces.argtypes = [
    wintypes.HANDLE, ctypes.c_void_p, ctypes.POINTER(GUID), wintypes.DWORD,
    ctypes.POINTER(SP_DEVICE_INTERFACE_DATA)]
setupapi.SetupDiEnumDeviceInterfaces.restype = wintypes.BOOL
setupapi.SetupDiGetDeviceInterfaceDetailW.argtypes = [
    wintypes.HANDLE, ctypes.POINTER(SP_DEVICE_INTERFACE_DATA), ctypes.c_void_p,
    wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
setupapi.SetupDiGetDeviceInterfaceDetailW.restype = wintypes.BOOL
setupapi.SetupDiDestroyDeviceInfoList.argtypes = [wintypes.HANDLE]

hid.HidD_GetHidGuid.argtypes = [ctypes.POINTER(GUID)]
hid.HidD_GetAttributes.argtypes = [wintypes.HANDLE, ctypes.POINTER(HIDD_ATTRIBUTES)]
hid.HidD_GetAttributes.restype = wintypes.BOOLEAN
hid.HidD_GetPreparsedData.argtypes = [wintypes.HANDLE, ctypes.POINTER(ctypes.c_void_p)]
hid.HidD_GetPreparsedData.restype = wintypes.BOOLEAN
hid.HidD_FreePreparsedData.argtypes = [ctypes.c_void_p]
hid.HidP_GetCaps.argtypes = [ctypes.c_void_p, ctypes.POINTER(HIDP_CAPS)]
hid.HidP_GetCaps.restype = ctypes.c_long
hid.HidD_SetFeature.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_ulong]
hid.HidD_SetFeature.restype = wintypes.BOOLEAN
hid.HidD_GetFeature.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_ulong]
hid.HidD_GetFeature.restype = wintypes.BOOLEAN
hid.HidD_GetProductString.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_ulong]
hid.HidD_GetProductString.restype = wintypes.BOOLEAN

kernel32.CreateFileW.argtypes = [
    wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
    wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
kernel32.CreateFileW.restype = wintypes.HANDLE
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.WriteFile.argtypes = [
    wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
    ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(OVERLAPPED)]
kernel32.WriteFile.restype = wintypes.BOOL
kernel32.ReadFile.argtypes = [
    wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
    ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(OVERLAPPED)]
kernel32.ReadFile.restype = wintypes.BOOL
kernel32.CreateEventW.argtypes = [
    ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
kernel32.CreateEventW.restype = wintypes.HANDLE
kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
kernel32.WaitForSingleObject.restype = wintypes.DWORD
kernel32.GetOverlappedResult.argtypes = [
    wintypes.HANDLE, ctypes.POINTER(OVERLAPPED),
    ctypes.POINTER(wintypes.DWORD), wintypes.BOOL]
kernel32.GetOverlappedResult.restype = wintypes.BOOL
kernel32.CancelIo.argtypes = [wintypes.HANDLE]


class HidError(RuntimeError):
    """Raised when a HID device cannot be opened or a report fails."""


class HidInfo(NamedTuple):
    path: str
    vendor_id: int
    product_id: int
    usage_page: int
    usage: int
    feature_len: int
    input_len: int
    output_len: int
    product: str

    def describe(self) -> str:
        return (
            f"VID_{self.vendor_id:04X}&PID_{self.product_id:04X} "
            f"usage_page=0x{self.usage_page:04X} usage=0x{self.usage:02X} "
            f"feature={self.feature_len} input={self.input_len} "
            f"output={self.output_len}  {self.product}"
        )


def _interface_paths() -> Iterator[str]:
    guid = GUID()
    hid.HidD_GetHidGuid(ctypes.byref(guid))
    dev_info = setupapi.SetupDiGetClassDevsW(
        ctypes.byref(guid), None, None, DIGCF_PRESENT | DIGCF_DEVICEINTERFACE)
    if dev_info == INVALID_HANDLE_VALUE:
        raise HidError("SetupDiGetClassDevsW failed")
    try:
        index = 0
        while True:
            iface = SP_DEVICE_INTERFACE_DATA()
            iface.cbSize = ctypes.sizeof(SP_DEVICE_INTERFACE_DATA)
            if not setupapi.SetupDiEnumDeviceInterfaces(
                    dev_info, None, ctypes.byref(guid), index, ctypes.byref(iface)):
                if ctypes.get_last_error() == ERROR_NO_MORE_ITEMS:
                    return
                raise HidError("SetupDiEnumDeviceInterfaces failed")
            index += 1

            needed = wintypes.DWORD(0)
            setupapi.SetupDiGetDeviceInterfaceDetailW(
                dev_info, ctypes.byref(iface), None, 0, ctypes.byref(needed), None)
            if needed.value == 0:
                continue
            buf = ctypes.create_string_buffer(needed.value)
            # cbSize is the size of the fixed part only: 8 on x64, 6 on x86.
            ctypes.memmove(buf, ctypes.byref(wintypes.DWORD(
                8 if ctypes.sizeof(ctypes.c_void_p) == 8 else 6)), 4)
            if not setupapi.SetupDiGetDeviceInterfaceDetailW(
                    dev_info, ctypes.byref(iface), buf, needed.value,
                    ctypes.byref(needed), None):
                continue
            yield ctypes.wstring_at(ctypes.addressof(buf) + 4)
    finally:
        setupapi.SetupDiDestroyDeviceInfoList(dev_info)


def _open(path: str, access: int, flags: int = 0) -> int:
    handle = kernel32.CreateFileW(
        path, access, FILE_SHARE_READ | FILE_SHARE_WRITE, None,
        OPEN_EXISTING, flags, None)
    if handle == INVALID_HANDLE_VALUE:
        raise HidError(f"cannot open {path}: error {ctypes.get_last_error()}")
    return handle


def enumerate_hid(vendor_id: int | None = None,
                  product_id: int | None = None) -> list[HidInfo]:
    """Return every present HID interface, optionally filtered by VID/PID.

    Opened with access 0 (query only) so devices held open by vendor software
    are still enumerable.
    """
    found: list[HidInfo] = []
    for path in _interface_paths():
        try:
            handle = _open(path, 0)
        except HidError:
            continue
        try:
            attrs = HIDD_ATTRIBUTES()
            attrs.Size = ctypes.sizeof(HIDD_ATTRIBUTES)
            if not hid.HidD_GetAttributes(handle, ctypes.byref(attrs)):
                continue
            if vendor_id is not None and attrs.VendorID != vendor_id:
                continue
            if product_id is not None and attrs.ProductID != product_id:
                continue

            preparsed = ctypes.c_void_p()
            if not hid.HidD_GetPreparsedData(handle, ctypes.byref(preparsed)):
                continue
            try:
                caps = HIDP_CAPS()
                if hid.HidP_GetCaps(preparsed, ctypes.byref(caps)) != 0x00110000:
                    continue  # HIDP_STATUS_SUCCESS
            finally:
                hid.HidD_FreePreparsedData(preparsed)

            name = ctypes.create_unicode_buffer(128)
            product = (name.value
                       if hid.HidD_GetProductString(handle, name, 256) else "")

            found.append(HidInfo(
                path=path,
                vendor_id=attrs.VendorID,
                product_id=attrs.ProductID,
                usage_page=caps.UsagePage,
                usage=caps.Usage,
                feature_len=caps.FeatureReportByteLength,
                input_len=caps.InputReportByteLength,
                output_len=caps.OutputReportByteLength,
                product=product,
            ))
        finally:
            kernel32.CloseHandle(handle)
    return found


class HidDevice:
    """An open HID interface.

    `overlapped=True` is required for write_output/read_input so a sleeping or
    unplugged device can never block the caller indefinitely. Feature-report
    helpers need a synchronous handle, so they require overlapped=False.
    """

    def __init__(self, info: HidInfo, overlapped: bool = False):
        self.info = info
        self.overlapped = overlapped
        self._handle = _open(
            info.path, GENERIC_READ | GENERIC_WRITE,
            FILE_FLAG_OVERLAPPED if overlapped else 0)

    def _io(self, func, buf, size: int, timeout_ms: int) -> int:
        """Run an overlapped ReadFile/WriteFile, cancelling it on timeout."""
        ov = OVERLAPPED()
        ov.hEvent = kernel32.CreateEventW(None, True, False, None)
        if not ov.hEvent:
            raise HidError("CreateEventW failed")
        try:
            transferred = wintypes.DWORD(0)
            ok = func(self._handle, buf, size, ctypes.byref(transferred),
                      ctypes.byref(ov))
            if not ok:
                err = ctypes.get_last_error()
                if err != ERROR_IO_PENDING:
                    raise HidError(f"I/O failed: error {err}")
                if kernel32.WaitForSingleObject(ov.hEvent, timeout_ms) != WAIT_OBJECT_0:
                    kernel32.CancelIo(self._handle)
                    raise HidError(f"timed out after {timeout_ms} ms "
                                   "(mouse asleep or dongle unplugged?)")
                if not kernel32.GetOverlappedResult(
                        self._handle, ctypes.byref(ov),
                        ctypes.byref(transferred), False):
                    raise HidError(
                        f"GetOverlappedResult failed: error {ctypes.get_last_error()}")
            return transferred.value
        finally:
            kernel32.CloseHandle(ov.hEvent)

    def write_output(self, payload: bytes, timeout_ms: int = 1000) -> None:
        """Send an output report. `payload` includes the report ID as byte 0."""
        size = self.info.output_len
        if size == 0:
            raise HidError("device has no output reports")
        buf = ctypes.create_string_buffer(bytes(payload).ljust(size, b"\0"), size)
        self._io(kernel32.WriteFile, buf, size, timeout_ms)

    def read_input(self, timeout_ms: int = 1000) -> bytes:
        """Read one input report, including the report ID as byte 0."""
        size = self.info.input_len
        if size == 0:
            raise HidError("device has no input reports")
        buf = ctypes.create_string_buffer(size)
        got = self._io(kernel32.ReadFile, buf, size, timeout_ms)
        return buf.raw[:got]

    def set_feature(self, payload: bytes, report_id: int = 0) -> None:
        """Send a feature report. `payload` is zero-padded to the device length."""
        size = self.info.feature_len or (len(payload) + 1)
        buf = ctypes.create_string_buffer(size)
        buf[0] = bytes([report_id])
        for i, byte in enumerate(payload[: size - 1]):
            buf[i + 1] = bytes([byte])
        if not hid.HidD_SetFeature(self._handle, buf, size):
            raise HidError(f"HidD_SetFeature failed: error {ctypes.get_last_error()}")

    def get_feature(self, report_id: int = 0) -> bytes:
        """Read a feature report; returns the payload with the report ID stripped."""
        size = self.info.feature_len
        buf = ctypes.create_string_buffer(size)
        buf[0] = bytes([report_id])
        if not hid.HidD_GetFeature(self._handle, buf, size):
            raise HidError(f"HidD_GetFeature failed: error {ctypes.get_last_error()}")
        return buf.raw[1:]

    def close(self) -> None:
        if self._handle:
            kernel32.CloseHandle(self._handle)
            self._handle = None

    def __enter__(self) -> "HidDevice":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


if __name__ == "__main__":
    import sys

    vid = int(sys.argv[1], 16) if len(sys.argv) > 1 else None
    pid = int(sys.argv[2], 16) if len(sys.argv) > 2 else None
    for entry in enumerate_hid(vid, pid):
        print(entry.describe())
        print(f"    {entry.path}")
