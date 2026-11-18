import os
import subprocess
from pathlib import Path

from u96_config import BLUETOOTH_ROOT, NET_FLAG_UP, NET_ROOT, RFKILL_ROOT


def _read(path, default=""):
    try:
        return Path(path).read_text().strip()
    except OSError:
        return default


def _write(path, value):
    Path(path).write_text(f"{value}\n")


def _resolved(path):
    try:
        return Path(path).resolve(strict=True)
    except OSError:
        return None


def driver(iface):
    found = _resolved(NET_ROOT / iface / "device" / "driver")
    return found.name if found else ""


def is_wireless(iface):
    return (NET_ROOT / iface / "wireless").exists() or (NET_ROOT / iface / "phy80211").exists()


def is_up(iface):
    return bool(int(_read(NET_ROOT / iface / "flags", "0x0"), 16) & NET_FLAG_UP)


def _ip(*args):
    try:
        done = subprocess.run(["ip", *args], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return done.stdout if done.returncode == 0 else ""


def _dev(text):
    tokens = text.split()
    return tokens[tokens.index("dev") + 1] if "dev" in tokens[:-1] else None


def session_peer():
    parts = os.environ.get("SSH_CONNECTION", "").split()
    return parts[0] if parts else None


def route_device(address):
    return _dev(_ip("-o", "route", "get", address))


def default_device():
    return _dev(_ip("-o", "route", "show", "default"))


class Radio:
    name = ""
    kind = ""
    control = ""
    interfaces = ()

    def controllable(self):
        raise NotImplementedError

    def snapshot(self):
        raise NotImplementedError

    def restore(self, state):
        raise NotImplementedError

    def disable(self):
        raise NotImplementedError

    def enable(self):
        raise NotImplementedError

    def disabled(self):
        raise NotImplementedError

    def label_state(self, state):
        raise NotImplementedError

    def restore_commands(self, state):
        raise NotImplementedError

    def carries(self, devices):
        return sorted(set(self.interfaces) & {d for d in devices if d})


class RfkillRadio(Radio):
    def __init__(self, entry):
        self.entry = Path(entry)
        self.kind = _read(self.entry / "type")
        self.device = _read(self.entry / "name")
        self.name = f"{self.kind} {self.device}"
        self.control = f"rfkill {self.entry.name} soft block"
        phy = _resolved(self.entry / "device")
        self.interfaces = tuple(
            iface.name for iface in (sorted(NET_ROOT.iterdir()) if NET_ROOT.is_dir() else [])
            if (iface / "phy80211").exists() and (
                (phy is not None and _resolved(iface / "phy80211") == phy)
                or _read(iface / "phy80211" / "name") == self.device
            )
        )

    def hard(self):
        return _read(self.entry / "hard", "0") == "1"

    def controllable(self):
        return (self.entry / "soft").exists() and not self.hard()

    def snapshot(self):
        return _read(self.entry / "soft")

    def restore(self, state):
        _write(self.entry / "soft", state)
        return f"{self.control}: {self.label_state(self.snapshot())}"

    def disable(self):
        _write(self.entry / "soft", "1")

    def enable(self):
        _write(self.entry / "soft", "0")

    def disabled(self):
        return self.snapshot() == "1"

    def label_state(self, state):
        return "blocked" if state == "1" else "on"

    def restore_commands(self, state):
        return [f"echo {state} | sudo tee {self.entry / 'soft'} >/dev/null"]


class LinkRadio(Radio):
    def __init__(self, iface):
        self.iface = iface
        self.kind = "wlan"
        self.name = f"wlan {iface}"
        self.control = f"ip link {iface} down"
        self.interfaces = (iface,)

    def controllable(self):
        return (NET_ROOT / self.iface).exists()

    def snapshot(self):
        return is_up(self.iface)

    def _set(self, up):
        subprocess.run(
            ["ip", "link", "set", "dev", self.iface, "up" if up else "down"],
            capture_output=True, timeout=10,
        )

    def restore(self, state):
        self._set(bool(state))
        return f"{self.iface}: {self.label_state(self.snapshot())}"

    def disable(self):
        self._set(False)

    def enable(self):
        self._set(True)

    def disabled(self):
        return not is_up(self.iface)

    def label_state(self, state):
        return "up" if state else "down"

    def restore_commands(self, state):
        return [f"sudo ip link set dev {self.iface} {'up' if state else 'down'}"]


def discover():
    radios, covered = [], set()
    for entry in sorted(RFKILL_ROOT.glob("rfkill*")) if RFKILL_ROOT.is_dir() else []:
        radio = RfkillRadio(entry)
        radios.append(radio)
        covered.update(radio.interfaces)
    for iface in sorted(NET_ROOT.iterdir()) if NET_ROOT.is_dir() else []:
        if is_wireless(iface.name) and iface.name not in covered:
            radios.append(LinkRadio(iface.name))
    return radios


def inventory():
    interfaces = sorted(NET_ROOT.iterdir()) if NET_ROOT.is_dir() else []
    return {
        "rfkill": [
            {
                "entry": entry.name,
                "type": _read(entry / "type"),
                "name": _read(entry / "name"),
                "soft": _read(entry / "soft"),
                "hard": _read(entry / "hard"),
            }
            for entry in (sorted(RFKILL_ROOT.glob("rfkill*")) if RFKILL_ROOT.is_dir() else [])
        ],
        "interfaces": [
            {
                "name": iface.name,
                "driver": driver(iface.name),
                "wireless": is_wireless(iface.name),
                "up": is_up(iface.name),
                "operstate": _read(iface / "operstate"),
            }
            for iface in interfaces if iface.name != "lo"
        ],
        "bluetooth": sorted(p.name for p in BLUETOOTH_ROOT.glob("hci*")) if BLUETOOTH_ROOT.is_dir() else [],
    }


def links():
    peer = session_peer()
    return {
        "peer": peer,
        "session": route_device(peer) if peer else None,
        "default": default_device(),
    }
