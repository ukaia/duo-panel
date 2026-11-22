import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from duo_panel.controls import Controls, PROFILES, split_nmcli, syncthing_connected_count  # noqa: E402
from duo_panel.sysinfo import Sampler, parse_cpu_stat, parse_meminfo, parse_net_dev  # noqa: E402

STAT_1 = """cpu  1000 0 500 8000 500 0 0 0 0 0
cpu0 100 0 50 800 50 0 0 0 0 0
cpu1 500 0 100 400 0 0 0 0 0 0
cpu2 0 0 0 1000 0 0 0 0 0 0
intr 1 2 3
"""
STAT_2 = """cpu  1300 0 700 8200 600 0 0 0 0 0
cpu0 130 0 70 860 60 0 0 0 0 0
cpu1 600 0 150 400 0 0 0 0 0 0
cpu2 0 0 0 1200 0 0 0 0 0 0
intr 1 2 3
"""
MEMINFO = """MemTotal:        7328768 kB
MemFree:          578560 kB
MemAvailable:    3279872 kB
SwapTotal:       7327744 kB
SwapFree:        5376000 kB
"""
NETDEV_1 = """Inter-|   Receive                                                |  Transmit
 face |bytes    packets errs drop fifo frame compressed multicast|bytes    packets errs drop fifo colls carrier compressed
    lo:  1000 10 0 0 0 0 0 0  1000 10 0 0 0 0 0 0
 wlan0: 1000000 100 0 0 0 0 0 0 500000 50 0 0 0 0 0 0
"""
NETDEV_2 = NETDEV_1.replace("1000000 100", "3000000 100").replace("500000 50", "600000 50")


def w(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)


class SysinfoTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="duo-sys-")
        self.addCleanup(shutil.rmtree, self.root, True)
        r = self.root
        w(f"{r}/proc/stat", STAT_1)
        w(f"{r}/proc/meminfo", MEMINFO)
        w(f"{r}/proc/loadavg", "1.52 1.10 0.90 2/900 1234\n")
        w(f"{r}/proc/uptime", "73423.55 200000.00\n")
        w(f"{r}/proc/net/dev", NETDEV_1)
        for name, temp in (("cpu0-thermal", 51500), ("cpu7-top-thermal", 63200), ("cpu3-bottom-thermal", 49000), ("gpuss0-thermal", 50300),
                           ("gpuss1-thermal", 55100), ("ddr-thermal", 50300), ("battery", 32000), ("modem0-thermal", 99999)):
            i = len(os.listdir(f"{r}/sys/class/thermal")) if os.path.isdir(f"{r}/sys/class/thermal") else 0
            w(f"{r}/sys/class/thermal/thermal_zone{i}/type", name + "\n")
            w(f"{r}/sys/class/thermal/thermal_zone{i}/temp", f"{temp}\n")
        b = f"{r}/sys/class/power_supply/battery"
        for k, v in (("capacity", 40), ("status", "Discharging"), ("voltage_now", 3768231), ("current_now", -846700), ("temp", 320),
                     ("time_to_empty_avg", 7200), ("time_to_full_avg", 0), ("state_of_health", 97), ("cycle_count", 31)):
            w(f"{b}/{k}", f"{v}\n")
        w(f"{r}/sys/class/hwmon/hwmon34/name", "pwmfan\n")
        w(f"{r}/sys/class/hwmon/hwmon34/fan1_input", "3544\n")
        w(f"{r}/sys/class/hwmon/hwmon34/pwm1", "51\n")
        w(f"{r}/sys/class/hwmon/hwmon5/name", "cpu4_top_thermal\n")
        g = f"{r}/sys/class/devfreq/3d00000.gpu"
        w(f"{g}/cur_freq", "259000000\n")
        w(f"{g}/max_freq", "1150000000\n")
        for pol, cpus, cur, mx in (("policy0", "0 1 2", 1344000, 1843200), ("policy3", "3 4 5 6", 1708800, 2400000), ("policy7", "7", 864000, 2803200)):
            base = f"{r}/sys/devices/system/cpu/cpufreq/{pol}"
            w(f"{base}/related_cpus", cpus + "\n")
            w(f"{base}/scaling_cur_freq", f"{cur}\n")
            w(f"{base}/cpuinfo_max_freq", f"{mx}\n")
        self.now = [100.0]
        self.sampler = Sampler(root=r, mounts=[("Internal", self.root)], clock=lambda: self.now[0])

    def test_parsers(self):
        self.assertEqual(parse_cpu_stat(STAT_1)["cpu1"], (600, 1000))
        self.assertEqual(parse_meminfo(MEMINFO)["MemTotal"], 7328768 * 1024)
        self.assertEqual(parse_net_dev(NETDEV_1, "wlan0"), (1000000, 500000))
        self.assertIsNone(parse_net_dev(NETDEV_1, "wlan9"))

    def test_cpu_usage_is_a_delta_between_samples(self):
        first = self.sampler.cpu()
        self.assertEqual(first["total"], 0.0)
        w(f"{self.root}/proc/stat", STAT_2)
        second = self.sampler.cpu()
        # hand calculation from the two /proc/stat samples:
        #   cpu0 busy 150 -> 200 (+50) of total 1000 -> 1120 (+120)  = 41.7 %
        #   cpu1 busy 600 -> 750 (+150) of total 1000 -> 1150 (+150) = 100 % (no idle time was added)
        #   cpu2 busy 0 -> 0 of total 1000 -> 1200                    = 0 %
        self.assertAlmostEqual(second["cores"][0], 100.0 * 50 / 120, places=1)
        self.assertEqual(second["cores"][1], 100.0)
        self.assertEqual(second["cores"][2], 0.0)
        self.assertEqual([c["cpus"] for c in second["clusters"]], ["CPU 0-2", "CPU 3-6", "CPU 7"])
        self.assertEqual(second["clusters"][2], {"cpus": "CPU 7", "mhz": 864, "max_mhz": 2803})
        self.assertEqual(second["load1"], 1.52)

    def test_total_cpu_matches_hand_calculation(self):
        self.sampler.cpu()
        w(f"{self.root}/proc/stat", STAT_2)
        # cpu line: busy 1500->2000 (+500), idle(8000+500 -> 8200+600) +300 => total +800 => 62.5%
        self.assertAlmostEqual(self.sampler.cpu()["total"], 62.5, places=1)

    def test_temperatures_pick_the_hottest_of_each_group_and_ignore_the_rest(self):
        t = self.sampler.temps()
        self.assertEqual(t, {"cpu": 63.2, "gpu": 55.1, "memory": 50.3, "battery": 32.0})

    def test_gpu_memory_battery_fan(self):
        self.assertEqual(self.sampler.gpu(), {"mhz": 259, "max_mhz": 1150, "pct": 22.5})
        m = self.sampler.memory()
        self.assertEqual(m["pct"], round(100.0 * (7328768 - 3279872) / 7328768, 1))
        self.assertEqual(m["used"], (7328768 - 3279872) * 1024)   # total minus AVAILABLE, not minus free
        self.assertEqual(m["total"], 7328768 * 1024)
        self.assertEqual(m["swap_used"], (7327744 - 5376000) * 1024)
        b = self.sampler.battery()
        self.assertEqual((b["pct"], b["status"], b["minutes"], b["health"]), (40, "Discharging", 120, 97))
        self.assertAlmostEqual(b["watts"], -3.2, places=1)
        self.assertEqual(self.sampler.fan(), {"rpm": 3544, "pct": 20})

    def test_charging_uses_time_to_full_and_missing_values_are_none(self):
        b = f"{self.root}/sys/class/power_supply/battery"
        w(f"{b}/status", "Charging\n")
        w(f"{b}/time_to_full_avg", "5400\n")
        w(f"{b}/current_now", "1500000\n")
        got = self.sampler.battery()
        self.assertEqual((got["minutes"], got["watts"] > 0), (90, True))
        shutil.rmtree(f"{self.root}/sys/class/hwmon/hwmon34")
        self.assertIsNone(self.sampler.fan())
        shutil.rmtree(f"{self.root}/sys/class/devfreq")
        self.assertIsNone(self.sampler.gpu())

    def test_network_rate_needs_two_samples(self):
        self.assertEqual(self.sampler.network(), {"rx_bps": 0.0, "tx_bps": 0.0})
        w(f"{self.root}/proc/net/dev", NETDEV_2)
        self.now[0] += 2.0
        n = self.sampler.network()
        self.assertEqual((n["rx_bps"], n["tx_bps"]), (1000000.0, 50000.0))

    def test_disks_and_uptime_and_full_sample_shape(self):
        d = self.sampler.disks()
        self.assertEqual(d[0]["label"], "Internal")
        self.assertTrue(0 <= d[0]["pct"] <= 100)
        s = self.sampler.sample()
        self.assertEqual(s["uptime"], 73423)
        self.assertEqual(set(s), {"cpu", "gpu", "temps", "memory", "battery", "fan", "network", "disks", "uptime"})

    def test_empty_tree_does_not_crash(self):
        empty = tempfile.mkdtemp(prefix="duo-empty-")
        self.addCleanup(shutil.rmtree, empty, True)
        s = Sampler(root=empty, mounts=[]).sample()
        self.assertIsNone(s["battery"])
        self.assertIsNone(s["gpu"])
        self.assertEqual(s["memory"]["total"], 0)


class FakeRun:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def __call__(self, argv, timeout=8):
        self.calls.append(list(argv))
        for prefix, result in self.responses.items():
            if argv[:len(prefix)] == list(prefix):
                return result
        return 1, "unexpected"


class ControlsTests(unittest.TestCase):
    def test_read_states(self):
        run = FakeRun({
            ("nmcli", "radio", "wifi"): (0, "enabled\n"),
            ("nmcli", "-t"): (0, " :Guest:70\n*:HomeNet\\:5G:62\n :Other:30\n"),
            ("bluetoothctl", "show"): (0, "Controller AA\n\tPowered: yes\n\tDiscoverable: no\n"),
            ("systemctl", "--user", "is-active", "syncthing.service"): (0, "active\n"),
            ("systemctl", "is-active", "sshd"): (0, "active\n"),
            ("armada-power", "profile"): (0, "Balanced\n"),
        })
        s = Controls(run, syncthing_api=lambda: 1).read_states()
        self.assertEqual(s["wifi"], {"enabled": True, "ssid": "HomeNet:5G", "signal": 62})
        self.assertEqual(s["bluetooth"], {"available": True, "powered": True})
        self.assertEqual(s["syncthing"], {"active": True, "connected": 1})
        self.assertEqual(s["ssh"], {"active": True})
        self.assertEqual(s["profile"]["name"], "Balanced")

    def test_off_and_failure_states(self):
        run = FakeRun({
            ("nmcli", "radio", "wifi"): (0, "disabled\n"),
            ("bluetoothctl", "show"): (1, "no default controller"),
            ("systemctl", "--user", "is-active", "syncthing.service"): (3, "inactive\n"),
            ("systemctl", "is-active", "sshd"): (3, "inactive\n"),
            ("armada-power", "profile"): (1, "boom"),
        })
        s = Controls(run).read_states()
        self.assertEqual(s["wifi"], {"enabled": False, "ssid": None, "signal": None})
        self.assertFalse(s["bluetooth"]["available"])
        self.assertEqual(s["syncthing"], {"active": False, "connected": None})
        self.assertFalse(s["ssh"]["active"])
        self.assertIsNone(s["profile"]["name"])

    def test_syncthing_api_errors_do_not_break_the_read(self):
        def boom():
            raise OSError("down")
        run = FakeRun({("systemctl", "--user", "is-active", "syncthing.service"): (0, "active\n")})
        self.assertEqual(Controls(run, syncthing_api=boom).syncthing(), {"active": True, "connected": None})

    def test_the_commands_sent_are_exactly_the_supported_ones(self):
        run = FakeRun({("nmcli",): (0, ""), ("bluetoothctl",): (0, ""), ("systemctl",): (0, ""), ("pkexec",): (0, '{"active": true}'), ("armada-power",): (0, "")})
        c = Controls(run)
        c.toggle("wifi", True)
        c.toggle("wifi", False)
        c.toggle("bluetooth", False)
        c.toggle("syncthing", True)
        c.toggle("syncthing", False)
        c.toggle("ssh", True)
        c.toggle("ssh", False)
        c.set_profile("Eco")
        self.assertEqual(run.calls, [
            ["nmcli", "radio", "wifi", "on"], ["nmcli", "radio", "wifi", "off"], ["bluetoothctl", "power", "off"],
            ["systemctl", "--user", "start", "syncthing.service"], ["systemctl", "--user", "stop", "syncthing.service"],
            ["pkexec", "--disable-internal-agent", "/usr/libexec/armada/armada-tools-priv", "enable-ssh"],
            ["pkexec", "--disable-internal-agent", "/usr/libexec/armada/armada-tools-priv", "disable-ssh"],
            ["armada-power", "profile", "Eco"]])

    def test_bad_names_never_reach_a_command(self):
        run = FakeRun({})
        c = Controls(run)
        self.assertFalse(c.toggle("rm -rf", True)[0])
        self.assertFalse(c.set_profile("Turbo; reboot")[0])
        self.assertEqual(run.calls, [])
        self.assertEqual(PROFILES, ["Eco", "Balanced", "Performance"])

    def test_failed_command_reports_its_message(self):
        ok, msg = Controls(FakeRun({("nmcli",): (1, "Error: not authorized\n")})).set_wifi(False)
        self.assertFalse(ok)
        self.assertIn("not authorized", msg)

    def test_nmcli_split_and_syncthing_count(self):
        self.assertEqual(split_nmcli("*:Home\\:Net:80"), ["*", "Home:Net", "80"])
        home = tempfile.mkdtemp(prefix="duo-st-")
        self.addCleanup(shutil.rmtree, home, True)
        self.assertIsNone(syncthing_connected_count(home=home))
        w(f"{home}/config.xml", "<configuration><gui><apikey>TESTKEY</apikey></gui></configuration>")
        import io
        import json
        seen = {}

        def fake_open(req, timeout):
            seen["key"] = req.get_header("X-api-key")
            return io.StringIO(json.dumps({"connections": {"A": {"connected": True}, "B": {"connected": False}, "C": {"connected": True}}}))
        self.assertEqual(syncthing_connected_count(home=home, urlopen=fake_open), 2)
        self.assertEqual(seen["key"], "TESTKEY")


if __name__ == "__main__":
    unittest.main()
