#!/usr/bin/env python3
"""Run isolated native Passport tests; no BLE, microphone or personal clipboard."""
from pathlib import Path
import platform
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
CASES = {
    "engine_messages": (["EngineMessages.swift"], ["Foundation"]),
    "engine_process": (["EngineProcess.swift"], ["Foundation"]),
    "protocol": (["PassportProtocol.swift"], ["Foundation"]),
    "audio": (["PassportAudio.swift"], ["Foundation"]),
    "clipboard": (["PassportInput.swift", "PassportAudio.swift"], ["AppKit", "ApplicationServices"]),
    "pet": (["PassportPetAsset.swift", "PassportPetSync.swift", "PassportProtocol.swift", "AppPaths.swift"], ["AppKit", "ImageIO", "CryptoKit"]),
    "piko": (["PikoProtocol.swift"], ["Foundation", "CryptoKit", "Security"]),
    "piko_link": (["PikoProtocol.swift", "PassportProtocol.swift", "PassportAnnouncement.swift", "AppPaths.swift", "EngineMessages.swift", "PikoLink.swift"], ["Foundation", "Network", "AppKit", "CryptoKit", "Security"]),
    "announcement": (["PassportAnnouncement.swift", "PassportProtocol.swift", "PikoProtocol.swift", "AppPaths.swift"], ["Foundation", "AppKit", "CryptoKit"]),
}


def main():
    build = ROOT / ".build"
    build.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="native-tests-", dir=build) as temporary:
        for name, (sources, frameworks) in CASES.items():
            binary = Path(temporary) / name
            command = ["xcrun", "swiftc", "-module-cache-path", str(build / "swift-cache"),
                       "-target", platform.machine() + "-apple-macos13.0",
                       *[str(ROOT / "src" / item) for item in sources],
                       str(ROOT / "tests" / ("test_passport_" + name + ".swift")),
                       "-o", str(binary)]
            for framework in frameworks:
                command.extend(["-framework", framework])
            subprocess.run(command, cwd=ROOT, check=True)
            subprocess.run([str(binary)], cwd=ROOT, check=True)
            print(name + ": PASS", flush=True)


if __name__ == "__main__":
    main()
