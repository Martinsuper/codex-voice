#!/usr/bin/env python3
"""Package verified Passport flash files, excluding private ELF/MAP archives."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
FIRMWARE = ROOT / "firmware/ai-passport"
FILES = ["FoloToy-AI-Passport-full.bin", "FoloToy-AI-Passport.bin",
         "bootloader/bootloader.bin", "partition_table/partition-table.bin", "flash_args"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("archive", type=Path)
    args = parser.parse_args()
    archive = args.archive.resolve()
    subprocess.run([sys.executable, str(FIRMWARE / "tools/archive_firmware.py"),
                    "verify", str(archive)], check=True)
    original = json.loads((archive / "manifest.json").read_text())
    version = original["app_descriptor"]["version"]
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+-[a-z0-9-]+", version):
        raise ValueError("Unexpected firmware version")
    if original["target"] != "esp32c3" or original["flash_size_bytes"] != 8 * 1024 * 1024:
        raise ValueError("Unsupported target")
    output = ROOT / "dist"
    output.mkdir(exist_ok=True)
    name = "AI-Passport-Codex-" + version
    full = output / (name + "-full.bin")
    shutil.copy2(archive / FILES[0], full)
    with tempfile.TemporaryDirectory(prefix="passport-package-", dir=ROOT / ".build") as temporary:
        folder = Path(temporary) / name
        folder.mkdir()
        for relative in FILES:
            target = folder / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(archive / relative, target)
        shutil.copy2(FIRMWARE / "LICENSE", folder / "FoloToy-LICENSE.txt")
        shutil.copy2(FIRMWARE / "assets/fonts/NotoSansSC-OFL.txt", folder / "NotoSansSC-OFL.txt")
        (folder / "FLASH_README.txt").write_text(
            "AI Passport Codex firmware " + version + "\n\n"
            "Target: FoloToy AI Passport, ESP32-C3, 8 MB Flash, no PSRAM.\n"
            "Full image: FoloToy-AI-Passport-full.bin at 0x0.\n"
            "The separately downloadable AI-Passport-Codex-" + version + "-full.bin is identical.\n"
            "A complete merged flash can reset NVS, pairing and settings.\n"
            "Do not routinely erase the whole chip. Segmented upgrades require a verified compatible partition table.\n"
            "flash_args lists the actual segmented offsets. Never write the app-only image at 0x0.\n\n"
            "完整镜像从 0x0 写入，可能重置旧设置和蓝牙配对。\n"
            "分段升级须先核对分区兼容，不要例行整片擦除。\n"
            "完整的中文新手指南：\n"
            "https://github.com/superslash-rico/codex-voice/blob/v" +
            (ROOT / "VERSION").read_text().strip() + "/docs/AI_PASSPORT.md\n")
        files = {}
        for path in sorted(folder.rglob("*")):
            if path.is_file():
                files[path.relative_to(folder).as_posix()] = {
                    "size": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        manifest = {"package_schema": 1, "firmware": version,
                    "source_tag": "v" + (ROOT / "VERSION").read_text().strip(),
                    "target": original["target"], "flash_size_bytes": original["flash_size_bytes"],
                    "app_descriptor": original["app_descriptor"],
                    "image_offsets": original["image_offsets"], "files": files,
                    "debug_files_included": False}
        (folder / "release-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        (folder / "SHA256SUMS.txt").write_text("".join(
            item["sha256"] + "  " + filename + "\n" for filename, item in files.items()))
        package = output / (name + ".zip")
        with zipfile.ZipFile(package, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as writer:
            for path in sorted(folder.rglob("*")):
                if path.is_file():
                    writer.write(path, path.relative_to(folder.parent).as_posix())
        with zipfile.ZipFile(package) as reader:
            if reader.testzip() is not None:
                raise ValueError("Firmware ZIP CRC failed")
        print(json.dumps({"full": str(full), "zip": str(package),
                          "sha256": hashlib.sha256(full.read_bytes()).hexdigest()}))


if __name__ == "__main__":
    main()
