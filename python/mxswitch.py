#!/usr/bin/env python3
"""
mxswitch.py - switch Logitech Easy-Switch devices (MX Master 3S, MX Keys, ...)
to another channel via HID++ 2.0 feature 0x1814 (ChangeHost).

Switches every ChangeHost-capable device on this host (keyboard and mouse).

On Windows this needs nothing but a Python 3 interpreter: the HID plumbing goes
straight through hid.dll and setupapi.dll via ctypes. No admin rights. This
Windows build always targets channel 2, then asks BetterDisplay on the Mac to
select the HDMI input.

On macOS/Linux it falls back to hidapi (pip install hidapi).

    python mxswitch.py --info        # show channels and which one is active
    python mxswitch.py               # Windows: switch all to channel 2 + display
    python mxswitch.py 2             # non-Windows: switch all to channel 2
    python mxswitch.py --list        # dump candidate HID interfaces

Exit codes: 0 ok, 1 device not found / switch failed, 2 bad usage.
"""

from __future__ import annotations

import argparse
import sys
import time
import urllib.error
import urllib.request

LOGITECH_VID = 0x046D
SW_ID = 0x0A                  # software id, any value 1..15
ROOT_FEATURE = 0x00
FEAT_CHANGE_HOST = 0x1814

SHORT, LONG = 0x10, 0x11      # HID++ report ids
FRAME_LEN = {SHORT: 7, LONG: 20}

# 0xFF for a directly-connected device (Bluetooth/USB), 1..6 via a receiver.
DEVICE_INDICES = (0xFF, 1, 2, 3, 4, 5, 6)

# Windows KVM defaults (same as windows/mxswitch.ps1).
FIXED_CHANNEL_WIN = 2
BETTERDISPLAY_URL = (
    "http://192.168.129.25:55777/set?ddcAlt=144&vcp=inputSelectAlt"
)

# Bluetooth PIDs when the product string is unhelpful.
KNOWN_MICE = {0xB034, 0xB035, 0xB023, 0xB019}
KNOWN_KBDS = {0xB380, 0xB35B, 0xB35F, 0xB361, 0xB37C, 0xB36A}


def device_rank(usage_page, usage, name, product_id=0):
    """Higher = try first. Keyboards before mice; vendor pages before others."""
    name = (name or "").lower()
    mouse = ((usage_page == 0x0001 and usage == 0x0002)
             or any(w in name for w in ("master", "anywhere", "mouse", "ergo"))
             or product_id in KNOWN_MICE)
    kbd = ((usage_page == 0x0001 and usage == 0x0006)
           or any(w in name for w in ("keys", "keyboard", "mechanical"))
           or product_id in KNOWN_KBDS)
    tier = 2 if (kbd and not mouse) else (0 if mouse else 1)
    non_vendor = 0 if usage_page >= 0xFF00 else 1
    return tier * 10 + (1 - non_vendor)


# ---------------------------------------------------------------------------
# Windows backend: ctypes over the Win32 HID API. No third-party packages.
# ---------------------------------------------------------------------------

if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    setupapi = ctypes.WinDLL("setupapi", use_last_error=True)
    hid_dll = ctypes.WinDLL("hid", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    DIGCF_PRESENT, DIGCF_DEVICEINTERFACE = 0x02, 0x10
    GENERIC_READ, GENERIC_WRITE = 0x80000000, 0x40000000
    FILE_SHARE_READ, FILE_SHARE_WRITE = 0x01, 0x02
    OPEN_EXISTING, FILE_FLAG_OVERLAPPED = 3, 0x40000000
    INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
    ERROR_IO_PENDING, WAIT_OBJECT_0 = 997, 0
    HIDP_STATUS_SUCCESS = 0x00110000

    class GUID(ctypes.Structure):
        _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                    ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]

    class SP_DEVICE_INTERFACE_DATA(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("InterfaceClassGuid", GUID),
                    ("Flags", wintypes.DWORD), ("Reserved", ctypes.c_void_p)]

    class SP_DEVICE_INTERFACE_DETAIL_DATA_W(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("DevicePath", ctypes.c_wchar * 512)]

    class HIDD_ATTRIBUTES(ctypes.Structure):
        _fields_ = [("Size", wintypes.ULONG), ("VendorID", wintypes.USHORT),
                    ("ProductID", wintypes.USHORT), ("VersionNumber", wintypes.USHORT)]

    class HIDP_CAPS(ctypes.Structure):
        _fields_ = [("Usage", wintypes.USHORT), ("UsagePage", wintypes.USHORT),
                    ("InputReportByteLength", wintypes.USHORT),
                    ("OutputReportByteLength", wintypes.USHORT),
                    ("FeatureReportByteLength", wintypes.USHORT),
                    ("Reserved", wintypes.USHORT * 17),
                    ("NumberLinkCollectionNodes", wintypes.USHORT),
                    ("NumberInputButtonCaps", wintypes.USHORT),
                    ("NumberInputValueCaps", wintypes.USHORT),
                    ("NumberInputDataIndices", wintypes.USHORT),
                    ("NumberOutputButtonCaps", wintypes.USHORT),
                    ("NumberOutputValueCaps", wintypes.USHORT),
                    ("NumberOutputDataIndices", wintypes.USHORT),
                    ("NumberFeatureButtonCaps", wintypes.USHORT),
                    ("NumberFeatureValueCaps", wintypes.USHORT),
                    ("NumberFeatureDataIndices", wintypes.USHORT)]

    class OVERLAPPED(ctypes.Structure):
        _fields_ = [("Internal", ctypes.c_void_p), ("InternalHigh", ctypes.c_void_p),
                    ("Offset", wintypes.DWORD), ("OffsetHigh", wintypes.DWORD),
                    ("hEvent", wintypes.HANDLE)]

    # Setting restype matters: the default c_int silently truncates 64-bit handles.
    setupapi.SetupDiGetClassDevsW.restype = wintypes.HANDLE
    setupapi.SetupDiGetClassDevsW.argtypes = [ctypes.POINTER(GUID), wintypes.LPCWSTR,
                                              wintypes.HWND, wintypes.DWORD]
    kernel32.CreateFileW.restype = wintypes.HANDLE
    kernel32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                     ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD,
                                     wintypes.HANDLE]
    kernel32.CreateEventW.restype = wintypes.HANDLE
    kernel32.CancelIo.argtypes = [wintypes.HANDLE]
    hid_dll.HidP_GetCaps.argtypes = [ctypes.c_void_p, ctypes.POINTER(HIDP_CAPS)]

    def _query(path):
        """Open briefly, read VID/usage/report lengths, close. None if unusable."""
        h = kernel32.CreateFileW(path, 0, FILE_SHARE_READ | FILE_SHARE_WRITE,
                                 None, OPEN_EXISTING, 0, None)
        if h == INVALID_HANDLE_VALUE:
            return None
        try:
            attrs = HIDD_ATTRIBUTES()
            attrs.Size = ctypes.sizeof(attrs)
            if not hid_dll.HidD_GetAttributes(h, ctypes.byref(attrs)):
                return None
            if attrs.VendorID != LOGITECH_VID:
                return None

            pp = ctypes.c_void_p()
            if not hid_dll.HidD_GetPreparsedData(h, ctypes.byref(pp)):
                return None
            try:
                caps = HIDP_CAPS()
                if hid_dll.HidP_GetCaps(pp, ctypes.byref(caps)) != HIDP_STATUS_SUCCESS:
                    return None
            finally:
                hid_dll.HidD_FreePreparsedData(pp)

            # Include non-vendor collections: Bluetooth HID++ sometimes lives there.
            if caps.OutputReportByteLength == 0:
                return None

            name = ctypes.create_unicode_buffer(128)
            hid_dll.HidD_GetProductString(h, name, ctypes.sizeof(name))
            return {"path": path, "usage_page": caps.UsagePage, "usage": caps.Usage,
                    "product_id": attrs.ProductID, "product_string": name.value,
                    "in_len": caps.InputReportByteLength,
                    "out_len": caps.OutputReportByteLength}
        finally:
            kernel32.CloseHandle(h)

    def enumerate_interfaces():
        guid = GUID()
        hid_dll.HidD_GetHidGuid(ctypes.byref(guid))
        hdev = setupapi.SetupDiGetClassDevsW(ctypes.byref(guid), None, None,
                                             DIGCF_PRESENT | DIGCF_DEVICEINTERFACE)
        if hdev == INVALID_HANDLE_VALUE:
            return
        found = []
        try:
            iface = SP_DEVICE_INTERFACE_DATA()
            iface.cbSize = ctypes.sizeof(iface)
            index = 0
            while setupapi.SetupDiEnumDeviceInterfaces(hdev, None, ctypes.byref(guid),
                                                       index, ctypes.byref(iface)):
                index += 1
                detail = SP_DEVICE_INTERFACE_DETAIL_DATA_W()
                # Documented fixed value, NOT sizeof(): 8 on x64, 6 on x86.
                detail.cbSize = 8 if ctypes.sizeof(ctypes.c_void_p) == 8 else 6
                if setupapi.SetupDiGetDeviceInterfaceDetailW(
                        hdev, ctypes.byref(iface), ctypes.byref(detail),
                        ctypes.sizeof(detail), None, None):
                    info = _query(detail.DevicePath)
                    if info:
                        found.append(info)
        finally:
            setupapi.SetupDiDestroyDeviceInfoList(hdev)
        found.sort(key=lambda i: -device_rank(i["usage_page"], i["usage"],
                                              i["product_string"], i["product_id"]))
        yield from found

    class Device:
        """Overlapped I/O, because a blocking ReadFile on a HID device that has
        nothing to say will simply never return. Timeouts always CancelIo."""

        def __init__(self, info):
            self.in_len, self.out_len = info["in_len"], info["out_len"]
            self.h = kernel32.CreateFileW(
                info["path"], GENERIC_READ | GENERIC_WRITE,
                FILE_SHARE_READ | FILE_SHARE_WRITE, None, OPEN_EXISTING,
                FILE_FLAG_OVERLAPPED, None)
            if self.h == INVALID_HANDLE_VALUE:
                raise OSError(ctypes.get_last_error(), "CreateFileW failed")
            self.event = kernel32.CreateEventW(None, True, False, None)

        def _wait(self, ov, timeout_ms):
            transferred = wintypes.DWORD()
            if kernel32.WaitForSingleObject(self.event, timeout_ms) != WAIT_OBJECT_0:
                kernel32.CancelIo(self.h)
                return None
            if not kernel32.GetOverlappedResult(self.h, ctypes.byref(ov),
                                                ctypes.byref(transferred), False):
                return None
            return transferred.value

        def write(self, data):
            """Return True if the driver accepted the frame."""
            buf = ctypes.create_string_buffer(
                bytes(data).ljust(self.out_len, b"\x00"), self.out_len)
            ov = OVERLAPPED()
            ov.hEvent = self.event
            kernel32.ResetEvent(self.event)
            if not kernel32.WriteFile(self.h, buf, self.out_len, None, ctypes.byref(ov)):
                err = ctypes.get_last_error()
                if err != ERROR_IO_PENDING:
                    return False
                return self._wait(ov, 1000) is not None
            return True

        def read(self, timeout_ms=100):
            buf = ctypes.create_string_buffer(self.in_len)
            ov = OVERLAPPED()
            ov.hEvent = self.event
            kernel32.ResetEvent(self.event)
            if not kernel32.ReadFile(self.h, buf, self.in_len, None, ctypes.byref(ov)):
                if ctypes.get_last_error() != ERROR_IO_PENDING:
                    return b""
            n = self._wait(ov, timeout_ms)
            return buf.raw[:n] if n else b""

        def close(self):
            kernel32.CloseHandle(self.event)
            kernel32.CloseHandle(self.h)


# ---------------------------------------------------------------------------
# Everything else: hidapi.
# ---------------------------------------------------------------------------

else:
    try:
        import hid
    except ImportError:
        sys.exit("On this platform mxswitch needs hidapi:  pip install hidapi")

    def enumerate_interfaces():
        seen = set()
        found = []
        for info in hid.enumerate(LOGITECH_VID, 0):
            if info["path"] in seen:
                continue
            seen.add(info["path"])
            found.append({"path": info["path"], "usage_page": info["usage_page"],
                          "usage": info["usage"], "product_id": info["product_id"],
                          "product_string": info["product_string"] or "",
                          "in_len": FRAME_LEN[LONG], "out_len": 0})
        found.sort(key=lambda i: -device_rank(i["usage_page"], i["usage"],
                                              i["product_string"], i["product_id"]))
        yield from found

    class Device:
        def __init__(self, info):
            self.out_len = 0                 # hidapi sizes the frame itself
            self.dev = hid.device()
            self.dev.open_path(info["path"])
            self.dev.set_nonblocking(0)

        def write(self, data):
            try:
                self.dev.write(bytes(data))
                return True
            except OSError:
                return False

        def read(self, timeout_ms=100):
            return bytes(self.dev.read(FRAME_LEN[LONG], timeout_ms=timeout_ms))

        def close(self):
            self.dev.close()


# ---------------------------------------------------------------------------
# HID++ protocol
# ---------------------------------------------------------------------------

def request(dev, report_id, dev_idx, feature_idx, function, params=b"", timeout_ms=500):
    """Send one HID++ call and wait for its matching reply. None on timeout/error."""
    frame = bytes([report_id, dev_idx, feature_idx, (function << 4) | SW_ID]) + params
    if not dev.write(frame.ljust(FRAME_LEN[report_id], b"\x00")):
        return None

    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        reply = dev.read(timeout_ms=100)
        if len(reply) < 5 or reply[1] != dev_idx:
            continue
        if reply[2] in (0xFF, 0x8F):
            return None                      # HID++ 2.0 / 1.0 error reply
        if reply[2] != feature_idx or (reply[3] & 0x0F) != SW_ID:
            continue                         # unsolicited notification
        return reply
    return None


def find_devices():
    """Return a list of dicts: dev, dev_idx, report_id, feat_idx, info.

    One entry per physical Easy-Switch device (deduped by product_id + HID++
    device index). Keyboards are listed before mice.
    """
    probe = bytes([FEAT_CHANGE_HOST >> 8, FEAT_CHANGE_HOST & 0xFF, 0x00])
    seen = set()
    results = []

    for info in enumerate_interfaces():
        try:
            probe_dev = Device(info)
        except OSError:
            continue

        report_ids = [r for r in (LONG, SHORT)
                      if not info["out_len"] or FRAME_LEN[r] <= info["out_len"]]
        hits = []
        for dev_idx in DEVICE_INDICES:
            ident = (info["product_id"], dev_idx)
            if ident in seen:
                continue
            for report_id in report_ids:
                reply = request(probe_dev, report_id, dev_idx, ROOT_FEATURE, 0,
                                probe, timeout_ms=400)
                if reply and reply[4] != 0x00:
                    hits.append((dev_idx, report_id, reply[4]))
                    break
        probe_dev.close()

        for dev_idx, report_id, feat_idx in hits:
            ident = (info["product_id"], dev_idx)
            if ident in seen:
                continue
            try:
                dev = Device(info)
            except OSError:
                continue
            seen.add(ident)
            results.append({
                "dev": dev,
                "dev_idx": dev_idx,
                "report_id": report_id,
                "feat_idx": feat_idx,
                "info": info,
            })

    return results


def host_info(dev, dev_idx, report_id, feat_idx):
    reply = request(dev, report_id, dev_idx, feat_idx, 0)
    return (reply[4], reply[5]) if reply else None


def set_host(dev, dev_idx, report_id, feat_idx, host_0based):
    """setCurrentHost. Never replies - the link is gone by then."""
    frame = bytes([report_id, dev_idx, feat_idx, (1 << 4) | SW_ID, host_0based])
    return bool(dev.write(frame.ljust(FRAME_LEN[report_id], b"\x00")))


def switch_display_hdmi():
    """Ask BetterDisplay on the Mac to select HDMI (Mac input)."""
    try:
        with urllib.request.urlopen(BETTERDISPLAY_URL, timeout=5) as resp:
            ok = 200 <= getattr(resp, "status", 200) < 300
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        print(f"BetterDisplay switch failed: {exc}", file=sys.stderr)
        return False
    if not ok:
        print("BetterDisplay switch failed (bad HTTP status).", file=sys.stderr)
        return False
    print(f"display    : HDMI (Mac) via {BETTERDISPLAY_URL}")
    return True


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("channel", nargs="?", type=int,
                    help="target channel, 1-based (ignored on Windows; always 2)")
    ap.add_argument("--info", action="store_true", help="show host info and exit")
    ap.add_argument("--list", action="store_true", help="dump HID interfaces and exit")
    args = ap.parse_args()

    if args.list:
        for i in enumerate_interfaces():
            print(f"{i['usage_page']:#06x}:{i['usage']:#06x}  pid={i['product_id']:#06x}"
                  f"  out={i['out_len']}  {i['product_string']}")
        return 0

    is_win = sys.platform == "win32"
    if is_win:
        channel = FIXED_CHANNEL_WIN
    else:
        if not args.info and args.channel is None:
            ap.error("give a channel number, or --info")
        channel = args.channel
        if channel is not None and not 1 <= channel <= 3:
            ap.error("channel must be 1, 2 or 3")

    devices = find_devices()
    if not devices:
        print("No Logitech device supporting ChangeHost found.", file=sys.stderr)
        print("Press a key / click the mouse to wake devices, then retry. "
              "See also --list.", file=sys.stderr)
        return 1

    if args.info:
        for i, d in enumerate(devices):
            if i:
                print()
            info = d["info"]
            print(f"device     : {info['product_string']}  "
                  f"(pid={info['product_id']:#06x})")
            print(f"transport  : "
                  f"{'direct (BT/USB)' if d['dev_idx'] == 0xFF else 'receiver'}"
                  f"  index={d['dev_idx']:#04x}  report={d['report_id']:#04x}")
            print(f"ChangeHost : feature index {d['feat_idx']:#04x}")
            hosts = host_info(d["dev"], d["dev_idx"], d["report_id"], d["feat_idx"])
            if hosts:
                print(f"channels   : {hosts[0]}, currently on {hosts[1] + 1}")
            d["dev"].close()
        return 0

    n = len(devices)
    print(f"Switching {n} device{'s' if n != 1 else ''} to channel {channel} ...")
    ok = 0
    for d in devices:
        info = d["info"]
        print(f"  {info['product_string']}  (pid={info['product_id']:#06x})")
        # A couple of quick writes; setCurrentHost never replies.
        landed = False
        for _ in range(3):
            if set_host(d["dev"], d["dev_idx"], d["report_id"], d["feat_idx"],
                        channel - 1):
                landed = True
                time.sleep(0.08)
                break
            time.sleep(0.1)
        if landed:
            ok += 1
        else:
            print(f"  ! {info['product_string']} did not accept ChangeHost",
                  file=sys.stderr)
        d["dev"].close()

    if ok == 0:
        print("No device accepted the channel switch.", file=sys.stderr)
        return 1

    if is_win and not switch_display_hdmi():
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
