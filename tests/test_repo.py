#!/usr/bin/env python3
"""Host-runnable static tests for goodluckOS.

No Docker, no hardware, no network required. Validates the things this repo
actually breaks: Buildroot symbol typos, Puppy config format drift, lost exec
bits, and PortMaster wiring consistency across stages (rootfs overlay <->
image builder <-> home overlay).

Run:  python3 tests/test_repo.py   (or: pytest tests/)
"""
import re
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OVERLAY = ROOT / "rootfs/board/my-device/rootfs-overlay"
DEFCONFIG = ROOT / "rootfs/configs/goodluck_defconfig"
SYSTEM_PUPPY = OVERLAY / "usr/share/puppy/apps.puppy"
HOME_PUPPY = ROOT / "home/overlay/apps.puppy"


def parse_puppy(path):
    """Parse apps.puppy into [(section, {key: value})]. Ignores # comments."""
    sections = []
    current = None
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            current = (line[1:-1], {})
            sections.append(current)
            continue
        if current is not None and "=" in line:
            k, v = line.split("=", 1)
            current[1][k.strip()] = v.strip()
    return sections


_BASH = None
_BASH_PROBED = False


def find_bash():
    """Return a bash that can actually syntax-check repo files, or None.

    shutil.which("bash") may resolve to WSL's launcher, which cannot read
    repo-relative paths on Windows hosts -- so probe each candidate against
    a known-good script instead of trusting PATH order.
    """
    global _BASH, _BASH_PROBED
    if _BASH_PROBED:
        return _BASH
    _BASH_PROBED = True
    candidates = [
        shutil.which("bash"),
        r"C:\Program Files\Git\bin\bash.exe",
        "/bin/bash",
        "/usr/bin/bash",
    ]
    for bash in candidates:
        if not bash:
            continue
        try:
            r = subprocess.run(
                [bash, "-n", "home/build.sh"],
                cwd=ROOT, capture_output=True, text=True, timeout=60)
            if r.returncode == 0:
                _BASH = bash
                break
        except Exception:
            continue
    return _BASH


def git_modes():
    """{path: mode} from the git index. Skips if git is unavailable."""
    try:
        out = subprocess.run(
            ["git", "ls-files", "-s"], cwd=ROOT,
            capture_output=True, text=True, check=True).stdout
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None
    modes = {}
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 4:
            modes[parts[3]] = parts[0]
    return modes


def defconfig_symbols():
    """{symbol: value} for every BR2_* line set in the defconfig."""
    syms = {}
    dups = []
    for line in DEFCONFIG.read_text().splitlines():
        line = line.strip()
        m = re.match(r"(BR2_\w+)=(.*)", line)
        if m:
            if m.group(1) in syms:
                dups.append(m.group(1))
            syms[m.group(1)] = m.group(2)
    return syms, dups


PORTMASTER_SYMBOLS = [
    # Shell + GNU userland (ports run #!/bin/bash with GNU flags).
    "BR2_PACKAGE_BASH", "BR2_PACKAGE_COREUTILS", "BR2_PACKAGE_FINDUTILS",
    "BR2_PACKAGE_GAWK", "BR2_PACKAGE_GREP", "BR2_PACKAGE_SED",
    "BR2_PACKAGE_PSMISC", "BR2_PACKAGE_PROCPS_NG",
    # Archives / menus / sync.
    "BR2_PACKAGE_UNZIP", "BR2_PACKAGE_XZ", "BR2_PACKAGE_DOS2UNIX",
    "BR2_PACKAGE_DIALOG", "BR2_PACKAGE_RSYNC",
    # squashfs runtimes, ports.img creation, on-device debugging.
    "BR2_PACKAGE_SQUASHFS", "BR2_PACKAGE_E2FSPROGS",
    "BR2_PACKAGE_FILE", "BR2_PACKAGE_STRACE", "BR2_PACKAGE_HTOP",
    # PortMaster GUI (harbourmaster): lzma required, ssl so the vendored
    # requests imports, sqlite for caches, zlib for zip handling.
    "BR2_PACKAGE_PYTHON3", "BR2_PACKAGE_PYTHON3_XZ",
    "BR2_PACKAGE_PYTHON3_SSL", "BR2_PACKAGE_PYTHON3_SQLITE",
    "BR2_PACKAGE_PYTHON3_ZLIB",
    # mount/umount, losetup, taskset ($TASKSET), zramctl.
    "BR2_PACKAGE_UTIL_LINUX_MOUNT", "BR2_PACKAGE_UTIL_LINUX_LOSETUP",
    "BR2_PACKAGE_UTIL_LINUX_SCHEDUTILS", "BR2_PACKAGE_UTIL_LINUX_ZRAMCTL",
]


class DefconfigTest(unittest.TestCase):
    def test_portmaster_symbols_present_and_enabled(self):
        syms, _ = defconfig_symbols()
        missing = [s for s in PORTMASTER_SYMBOLS if syms.get(s) != "y"]
        self.assertEqual(missing, [],
                         f"PortMaster symbols missing or disabled: {missing}")

    def test_no_duplicate_symbols(self):
        _, dups = defconfig_symbols()
        self.assertEqual(dups, [], f"duplicate symbols: {dups}")


class PuppyConfigTest(unittest.TestCase):
    def check_file(self, path):
        for section, kv in parse_puppy(path):
            with self.subTest(file=path.name, section=section):
                if section == "ENTRY":
                    for field in ("CATEGORY", "NAME", "COMMAND"):
                        self.assertIn(field, kv, f"ENTRY missing {field}")
                        self.assertTrue(kv[field], f"ENTRY has empty {field}")
                elif section == "ARCHIVE":
                    for field in ("NAME", "ENTRY_DIRECTORIES",
                                  "ENTRY_EXTENSIONS", "COMMAND"):
                        self.assertIn(field, kv, f"ARCHIVE missing {field}")
                    self.assertIn("%s", kv["COMMAND"],
                                  "ARCHIVE COMMAND must contain %s")
                    for d in kv["ENTRY_DIRECTORIES"].split(";"):
                        self.assertTrue(d.startswith("/"),
                                        f"ENTRY_DIRECTORIES must be absolute: {d}")

    def test_system_apps_puppy(self):
        self.assertTrue(SYSTEM_PUPPY.exists())
        self.check_file(SYSTEM_PUPPY)

    def test_home_apps_puppy_parses(self):
        # Home overlay file is currently comments-only; must still parse.
        self.assertTrue(HOME_PUPPY.exists())
        self.check_file(HOME_PUPPY)

    def test_referenced_icons_exist(self):
        for path in (SYSTEM_PUPPY, HOME_PUPPY):
            for _, kv in parse_puppy(path):
                for field in ("ICON", "DEFAULT_ICON"):
                    icon = kv.get(field)
                    if icon and icon.startswith("/usr/share/"):
                        full = OVERLAY / icon.lstrip("/")
                        self.assertTrue(full.exists(),
                                        f"{field}={icon} not in overlay")

    def test_portmaster_wiring(self):
        sections = parse_puppy(SYSTEM_PUPPY)
        by_name = {kv.get("NAME"): (s, kv) for s, kv in sections}
        self.assertIn("PortMaster", by_name)
        self.assertIn("Ports", by_name)
        _, pm = by_name["PortMaster"]
        self.assertIn("/roms/ports/PortMaster/PortMaster.sh", pm["COMMAND"])
        _, ports = by_name["Ports"]
        self.assertIn("/roms/ports", ports["ENTRY_DIRECTORIES"].split(";"))
        self.assertIn("sh", [e.lower() for e in
                              ports["ENTRY_EXTENSIONS"].split(";")])


class InitScriptTest(unittest.TestCase):
    INITD = OVERLAY / "etc/init.d"

    def test_shebang_and_stop_handling(self):
        for script in sorted(self.INITD.iterdir()):
            if not script.is_file():
                continue
            with self.subTest(script=script.name):
                first = script.read_text().splitlines()[0]
                self.assertEqual(first, "#!/bin/sh", "must start #!/bin/sh")
                self.assertIn("$1", script.read_text(),
                              "must dispatch on $1 (start/stop)")

    def test_exec_bits_in_git_index(self):
        modes = git_modes()
        if modes is None:
            self.skipTest("git unavailable")
        for script in sorted(self.INITD.iterdir()):
            if not script.is_file():
                continue
            rel = str(script.relative_to(ROOT)).replace("\\", "/")
            with self.subTest(script=script.name):
                self.assertEqual(modes.get(rel), "100755",
                                 f"{rel} lost its exec bit in git")

    def test_ports_runs_before_appd(self):
        def num(p):
            m = re.match(r"S(\d+)", p.name)
            return int(m.group(1)) if m else 999
        names = {p.name for p in self.INITD.iterdir()}
        self.assertIn("S12ports", names)
        self.assertIn("S99appd", names)
        order = {p.name: num(p) for p in self.INITD.iterdir()}
        self.assertLess(order["S12ports"], order["S99appd"],
                        "ports.img must mount before appd starts Puppy")


class ShellSyntaxTest(unittest.TestCase):
    SCRIPTS = [
        "home/build.sh", "image/build.sh", "kernel/build.sh",
        "rootfs/start.sh",
        "rootfs/scripts/build.sh", "rootfs/scripts/clean.sh",
        "rootfs/scripts/configure.sh", "rootfs/scripts/menuconfig.sh",
        "rootfs/scripts/busybox-menuconfig.sh",
        "rootfs/board/my-device/rootfs-overlay/etc/init.d/S12ports",
        "rootfs/board/my-device/rootfs-overlay/usr/bin/systemctl",
        "rootfs/board/my-device/rootfs-overlay/usr/share/portmaster/mod_goodluckOS.txt",
        "rootfs/board/my-device/rootfs-overlay/usr/local/bin/appctl",
    ]

    def test_bash_n(self):
        bash = find_bash()
        if bash is None:
            self.skipTest("no working bash on this host")
        for rel in self.SCRIPTS:
            p = ROOT / rel
            with self.subTest(script=rel):
                self.assertTrue(p.exists(), f"{rel} missing")
                # Relative POSIX path: absolute Windows paths are not
                # understood by git-bash/msys bash on Windows hosts.
                r = subprocess.run(
                    [bash, "-n", rel.replace("\\", "/")],
                    cwd=ROOT, capture_output=True, text=True)
                self.assertEqual(r.returncode, 0, r.stderr)


class PortMasterWiringTest(unittest.TestCase):
    MOD = OVERLAY / "usr/share/portmaster/mod_goodluckOS.txt"

    def test_mod_file_contents(self):
        text = self.MOD.read_text()
        self.assertIn('ESUDO="doas"', text,
                      "control.txt only detects sudo; ESUDO=doas is required")
        for token in ("raloc", "GODOT_OPTS", "DEVICE", "DISPLAY_WIDTH"):
            self.assertIn(token, text, f"mod file missing {token}")

    def test_doas_permits_portmaster_ops(self):
        doas = (OVERLAY / "etc/doas.conf").read_text()
        self.assertIn("permit nopass player as root", doas,
                      "ports need $ESUDO mount/chmod without a password")

    def test_uinput_rule(self):
        rule = (OVERLAY / "etc/udev/rules.d/99-portmaster.rules").read_text()
        self.assertIn("uinput", rule)
        self.assertIn("0666", rule)

    def test_systemctl_shim(self):
        shim = (OVERLAY / "usr/bin/systemctl").read_text()
        self.assertIn("exit 0", shim)
        self.assertIn("restart", shim)

    def test_seed_path_agreement(self):
        """~/.seed/ must mean the same thing in all three stages."""
        s12 = (OVERLAY / "etc/init.d/S12ports").read_text()
        self.assertIn("SEED_DIR=/home/player/.seed", s12)
        dockerfile = (ROOT / "image/Dockerfile").read_text()
        self.assertEqual(dockerfile.count("tar-in seed.tar /.seed"), 2,
                         "seed must land in /.seed/ of BOTH a33 and a23 images")
        build_sh = (ROOT / "image/build.sh").read_text()
        self.assertIn("PortMaster.zip", build_sh)
        self.assertIn("PortMaster-GUI/releases/latest/download/PortMaster.zip",
                      build_sh)
        home_build = (ROOT / "home/build.sh").read_text()
        self.assertIn("overlay/.seed", home_build)
        self.assertIn("overlay/autoinstall", home_build)

    def test_no_bundled_tool_packages(self):
        """gptokeyb/7zzs/innoextract ship as .armhf in PortMaster.zip;
        a Buildroot package for them would be dead weight."""
        mk_files = list((ROOT / "rootfs/package").rglob("*.mk"))
        names = [p.parent.name for p in mk_files]
        for banned in ("gptokeyb", "p7zip", "innoextract"):
            self.assertNotIn(banned, names)


class ArtifactHygieneTest(unittest.TestCase):
    BANNED = re.compile(r"(\.img$|/out/|/local-out/|/staging/|PortMaster\.zip)")

    def test_no_built_artifacts_tracked(self):
        try:
            out = subprocess.run(["git", "ls-files"], cwd=ROOT,
                                 capture_output=True, text=True,
                                 check=True).stdout.splitlines()
        except (FileNotFoundError, subprocess.CalledProcessError):
            self.skipTest("git unavailable")
        bad = [f for f in out if self.BANNED.search(f)]
        self.assertEqual(bad, [], f"built artifacts tracked in git: {bad}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
