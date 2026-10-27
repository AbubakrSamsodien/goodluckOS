# AGENTS.md — goodluckOS

Custom firmware (Buildroot + mainline Linux 7.2) for Allwinner A23/A33 handhelds (GA36-MB). No test suite, linter, or CI — verification is a successful containerized build plus, ideally, a boot/flash test on hardware.

## Layout (4 build stages)

- `kernel/` — kernel Docker build. Sources of truth: `Dockerfile`, `drivers/` (custom `jd9366-ga36mbv1-2` panel + `ga36mb-gamepad` drivers), `dts/` (a23/a33 device trees), `patches/`.
- `rootfs/` — containerized Buildroot. Custom packages in `rootfs/package/<name>/`, board config in `board/`, `configs/goodluck_defconfig`.
- `home/` — HOME-partition overlay. Edit `home/overlay/` (`apps.puppy` = Puppy launcher entries), bundle with `home/build.sh`.
- `image/` — assembles flashable `goodluck_a33.img` / `goodluck_a23.img` (1 GB, p1 ext4 `linux` + p2 vfat `HOME`) via parted + guestfish.

## Build (all require Docker or Podman; scripts prefer Podman, fall back to `docker buildx`)

Build order: kernel, rootfs, home in any order — **image last**. Full builds are slow; rebuild only the stage you touched and flash it over an existing card (see below).

```sh
# 1. Kernel (from kernel/) -> kernel/out/android_boot_a33.img + android_boot_a23.img
./build.sh

# 2. Rootfs (from rootfs/): enters container, auto-runs scripts/configure.sh (goodluck_defconfig)
./start.sh
# then INSIDE the container:
./scripts/build.sh                 # full build -> out/images/rootfs.tar
./scripts/build.sh <pkg>-rebuild   # e.g. puppy-rebuild — fast single-package rebuild
./scripts/menuconfig.sh            # Buildroot config; ./scripts/busybox-menuconfig.sh for BusyBox
./scripts/clean.sh                 # wipes all build artifacts (slow next build)

# 3. Home overlay (from home/) -> home/out/home.tar (untarred to /home/player on HOME partition)
./build.sh

# 4. Image (from image/) — needs kernel/out/*.img + rootfs/out/images/rootfs.tar + home/out/home.tar
./build.sh
```

Notes: `BUILD.md` still mentions `image/sdcard.img` (first 128 MB of stock card) and `rootfs/out` vs `output` — stale. `image/Dockerfile` currently zeroes the bootloader region instead of requiring the dump, and the real rootfs output is `rootfs/out/images/rootfs.tar`. The `a33`/`a23` suffixed boot images are both required (BUILD.md/README show a generic `android_boot.img`).

## Fast iteration without full rebuilds

- Kernel-only flash: `sudo dd if=out/android_boot_a33.img bs=512 seek=172032 conv=notrunc status=progress of=/dev/sdX && sync` (use `a23` image for A23 units; target the whole disk, not a partition).
- Rootfs-only update: mount the card's `linux` partition, delete contents, untar `rootfs/out/images/rootfs.tar` into it.
- Home-only update: mount `HOME`, clear `player/`, untar `home/out/home.tar` there.
- Native Puppy iteration: `rootfs/package/puppy/build-local.sh` builds with host `g++` + SDL2/SDL2_image/SDL2_ttf into `local-out/` — no Buildroot needed. Same pattern (`build-local.sh`) exists for `system-settings`.

## Conventions

- New rootfs package = directory `rootfs/package/<name>/` with `<name>.mk` (generic-package) + `Config.in`, **plus** a `source` line in `rootfs/package/Config.in`. See `package/puppy/` as the template.
- Keep local build artifacts in `local-out/` or `out/` — both gitignored (`*/out/*`, `*/local-out/*`, `*/staging/*`). Never commit built images/tars.
- `kernel/Dockerfile` caches the vanilla `zImage` build *before* applying `patches/` + custom drivers — don't reorder those layers casually or every kernel build becomes a full rebuild.
- Runtime quirks baked into `board/my-device/`: USB serial console on `ttyGS0` (not `tty1`), triggerhappy forced to root and moved to `S99` (breaks if started early). Device scripts live in `board/my-device/rootfs-overlay/usr/local/bin/`.
- Design philosophy (README): at most one tool per job, battery efficiency over pretty UI, reuse existing packages, niche features ship as installable packages not core OS. AI-generated code is welcome but large untested/undocumented systems won't merge.

## PortMaster (in progress)

32-bit armhf (Cortex-A7, 512 MB RAM, 640x480, no WiFi) — only `armhf` ports work; Mono/DotNet/GameMaker-new-toolchain ports are aarch64-only and out. Verified against the live catalog: 245 armhf ports, 98 RTR; smoke tests are `2048.zip` (0.1 MB, native) then `DevilutionX` (native) then `Cats on Mars` (needs `frt_3.2.3` armhf runtime).

- `rootfs/configs/goodluck_defconfig` has a "PortMaster support" block (bash, GNU coreutils, python3+XZ/SSL/SQLITE/ZLIB, mount/losetup/taskset/zramctl, squashfs-tools, e2fsprogs, strace…). After `configure.sh`, grep `out/` `.config` to confirm every symbol took — unknown BR2 symbols are silently ignored.
- Ports live in `ports.img` (ext4 loopback on HOME), mounted at `/roms/ports` by `board/my-device/rootfs-overlay/etc/init.d/S12ports`, which also seeds `PortMaster.zip` from `~/.seed/` and stages `~/autoinstall/*.zip|*.squashfs`. No WiFi: sideload is the only install path.
- `image/build.sh` downloads the seed (`PortMaster.zip` from latest release) into `staging/` (gitignored) — never commit seed files. Full PortMaster installers are aarch64/x86_64-only; always use `PortMaster.zip` + individual armhf `.squashfs` runtimes.
- gptokeyb/innoextract/7zzs/xdelta3/sdl_resolution all ship as `.armhf` binaries inside `PortMaster.zip` — do NOT create Buildroot packages for them.
- `usr/share/portmaster/mod_goodluckOS.txt` is the CFW profile (ESUDO=doas, RetroArch path, Godot opts). `control.txt` only detects `sudo`, hence the explicit `ESUDO=doas` + blanket permit in `etc/doas.conf`.
- Hardware TODOs before ports work: confirm SDL GUID in `mod_goodluckOS.txt` via `evtest`, append the gamepad mapping line to `gamecontrollerdb.txt` (template in the mod file), add the `/dev/input/by-path/` stanza to `get_controls`. Triggerhappy uses FN-combos only, so it coexists with gptokeyb — leave it running.
- `usr/bin/systemctl` is a no-op shim (no systemd); `etc/udev/rules.d/99-portmaster.rules` opens `/dev/uinput`.
- Puppy: `usr/share/puppy/apps.puppy` has the PortMaster entry + Ports archive (`bash %s`, non-recursive scan = top-level `.sh` only, which matches port layout).
