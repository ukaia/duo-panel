"""System stats for the Duo panel: plain reads of /proc and /sys (no psutil), so it is cheap and testable
against a fake tree. `root` lets the tests point it at a temp directory."""
from __future__ import annotations

import glob
import os
import re
import time


def _read(path, default=None):
    try:
        with open(path) as f:
            return f.read().strip()
    except (OSError, ValueError):
        return default


def _int(path, default=None):
    value = _read(path)
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def parse_cpu_stat(text):
    """/proc/stat -> {name: (busy, total)} for 'cpu' and each 'cpuN'."""
    result = {}
    for line in text.splitlines():
        if not line.startswith("cpu"):
            continue
        parts = line.split()
        nums = [int(x) for x in parts[1:9]] + [0] * (8 - len(parts[1:9]))
        idle = nums[3] + nums[4]
        total = sum(nums)
        result[parts[0]] = (total - idle, total)
    return result


def parse_meminfo(text):
    out = {}
    for line in text.splitlines():
        key, _, rest = line.partition(":")
        m = re.match(r"\s*(\d+)", rest)
        if m:
            out[key] = int(m.group(1)) * 1024
    return out


def parse_net_dev(text, iface):
    for line in text.splitlines():
        name, _, rest = line.partition(":")
        if name.strip() == iface:
            nums = rest.split()
            return int(nums[0]), int(nums[8])
    return None


class Sampler:
    def __init__(self, root="/", mounts=None, iface="wlan0", clock=time.monotonic):
        self.root = root
        self.iface = iface
        self.clock = clock
        self.mounts = mounts if mounts is not None else [("Internal", "/var/home"), ("SD card", "/run/media/armada/ROMS")]
        self._cpu_prev = None
        self._net_prev = None

    def p(self, *parts):
        return os.path.join(self.root, *parts)

    # ---- sections ------------------------------------------------------
    def cpu(self):
        text = _read(self.p("proc/stat"), "")
        now = parse_cpu_stat(text)
        usage = {"total": 0.0, "cores": []}
        if self._cpu_prev:
            def pct(name):
                if name not in now or name not in self._cpu_prev:
                    return 0.0
                db = now[name][0] - self._cpu_prev[name][0]
                dt = now[name][1] - self._cpu_prev[name][1]
                return round(100.0 * db / dt, 1) if dt > 0 else 0.0
            usage["total"] = pct("cpu")
            cores = sorted((int(n[3:]) for n in now if n != "cpu"))
            usage["cores"] = [pct(f"cpu{i}") for i in cores]
        else:
            usage["cores"] = [0.0 for n in now if n != "cpu"]
        self._cpu_prev = now
        clusters = []
        for policy in sorted(glob.glob(self.p("sys/devices/system/cpu/cpufreq/policy*")), key=lambda x: int(re.sub(r"\D", "", os.path.basename(x)))):
            cur = _int(os.path.join(policy, "scaling_cur_freq"))
            mx = _int(os.path.join(policy, "cpuinfo_max_freq"))
            cpus = (_read(os.path.join(policy, "related_cpus"), "") or "").split()
            if cur is None or not mx:
                continue
            label = cpus[0] if len(cpus) == 1 else f"{cpus[0]}-{cpus[-1]}" if cpus else os.path.basename(policy)
            clusters.append({"cpus": f"CPU {label}", "mhz": round(cur / 1000), "max_mhz": round(mx / 1000)})
        load = (_read(self.p("proc/loadavg"), "") or "").split()
        usage["clusters"] = clusters
        usage["load1"] = float(load[0]) if load else None
        return usage

    def gpu(self):
        for d in sorted(glob.glob(self.p("sys/class/devfreq/*gpu*"))):
            cur, mx = _int(os.path.join(d, "cur_freq")), _int(os.path.join(d, "max_freq"))
            if cur is not None and mx:
                return {"mhz": round(cur / 1e6), "max_mhz": round(mx / 1e6), "pct": round(100.0 * cur / mx, 1)}
        return None

    def temps(self):
        zones = {}
        for z in glob.glob(self.p("sys/class/thermal/thermal_zone*")):
            name, raw = _read(os.path.join(z, "type")), _int(os.path.join(z, "temp"))
            if name and raw is not None:
                zones[name] = raw / 1000.0

        def top(pattern):
            vals = [v for k, v in zones.items() if re.match(pattern, k)]
            return round(max(vals), 1) if vals else None
        battery = _int(self.p("sys/class/power_supply/battery/temp"))
        return {
            "cpu": top(r"^cpu\d+(-(top|bottom))?-thermal$"),
            "gpu": top(r"^gpuss\d+-thermal$"),
            "memory": top(r"^ddr-thermal$"),
            "battery": round(battery / 10.0, 1) if battery is not None else None,
        }

    def memory(self):
        info = parse_meminfo(_read(self.p("proc/meminfo"), "") or "")
        total = info.get("MemTotal", 0)
        avail = info.get("MemAvailable", 0)
        swap_total, swap_free = info.get("SwapTotal", 0), info.get("SwapFree", 0)
        return {"total": total, "used": max(0, total - avail),
                "pct": round(100.0 * (total - avail) / total, 1) if total else 0.0,
                "swap_total": swap_total, "swap_used": max(0, swap_total - swap_free)}

    def battery(self):
        base = self.p("sys/class/power_supply/battery")
        cap = _int(os.path.join(base, "capacity"))
        if cap is None:
            return None
        status = _read(os.path.join(base, "status"), "Unknown")
        volts = (_int(os.path.join(base, "voltage_now"), 0) or 0) / 1e6
        amps = (_int(os.path.join(base, "current_now"), 0) or 0) / 1e6   # negative while discharging on this device
        watts = volts * amps
        eta_key = "time_to_full_avg" if status == "Charging" else "time_to_empty_avg"
        eta = _int(os.path.join(base, eta_key))
        return {"pct": cap, "status": status, "volts": round(volts, 2), "amps": round(amps, 2), "watts": round(watts, 1),
                "minutes": round(eta / 60) if eta and eta > 0 else None,
                "health": _int(os.path.join(base, "state_of_health")), "cycles": _int(os.path.join(base, "cycle_count"))}

    def fan(self):
        for h in glob.glob(self.p("sys/class/hwmon/hwmon*")):
            if _read(os.path.join(h, "name")) == "pwmfan":
                rpm, pwm = _int(os.path.join(h, "fan1_input")), _int(os.path.join(h, "pwm1"))
                return {"rpm": rpm, "pct": round(100.0 * pwm / 255) if pwm is not None else None}
        return None

    def network(self):
        pair = parse_net_dev(_read(self.p("proc/net/dev"), "") or "", self.iface)
        now = self.clock()
        out = {"rx_bps": 0.0, "tx_bps": 0.0}
        if pair and self._net_prev:
            dt = now - self._net_prev[0]
            if dt > 0:
                out = {"rx_bps": max(0.0, (pair[0] - self._net_prev[1]) / dt), "tx_bps": max(0.0, (pair[1] - self._net_prev[2]) / dt)}
        if pair:
            self._net_prev = (now, pair[0], pair[1])
        return out

    def disks(self):
        result = []
        for label, path in self.mounts:
            try:
                if label != "Internal" and not os.path.ismount(path):
                    continue
                st = os.statvfs(path)
            except OSError:
                continue
            total, free = st.f_blocks * st.f_frsize, st.f_bavail * st.f_frsize
            if total:
                result.append({"label": label, "total": total, "free": free, "pct": round(100.0 * (total - free) / total, 1)})
        return result

    def uptime(self):
        raw = (_read(self.p("proc/uptime"), "") or "").split()
        return int(float(raw[0])) if raw else None

    def sample(self):
        return {"cpu": self.cpu(), "gpu": self.gpu(), "temps": self.temps(), "memory": self.memory(), "battery": self.battery(),
                "fan": self.fan(), "network": self.network(), "disks": self.disks(), "uptime": self.uptime()}
