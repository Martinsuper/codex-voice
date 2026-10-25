<p align="right"><a href="README.zh_CN.md">简体中文</a> · <strong>English</strong></p>

# AI Passport for Codex Voice

This is the complete source snapshot for the optional FoloToy AI Passport accessory in [Codex Voice](../../README.md), not the upstream demonstration firmware. Firmware version: **0.3.0-pets**. The matching Mac release is **0.9.1-beta.1**.

Use the [step-by-step accessory guide](../../docs/AI_PASSPORT.md) for download, flashing, pairing, buttons, local dictation and troubleshooting. The root project guide is currently in Simplified Chinese; the engineering documents in this directory are paired in English and Chinese.

## Hardware and behavior

Target: FoloToy AI Passport, ESP32-C3, **8 MB Flash, no PSRAM**, its onboard display, microphone, speaker and three buttons. Task cards, quota rings, pet screensaver, acknowledgement buttons and encrypted BLE services are implemented specifically for Codex Voice. This is not firmware for arbitrary ESP32 boards.

The Mac app independently controls computer and badge speech. It synchronizes the selected Codex pet in the background and only activates verified resources. Local Mandarin dictation requires macOS 26 or later and an installed on-device model; transcription stays on the Mac and does not send messages automatically. The Mac app applies the default nickname `Codex` on first connection and preserves an existing saved nickname when upgraded.

## Build

Read [AGENTS.md](AGENTS.md), activate **ESP-IDF 5.5.3**, and install the prerequisites documented in [environment setup](docs/development/engineering/environment-setup.md).

```sh
source /path/to/esp-idf-v5.5.3/export.sh
idf.py --version
./tools/validate.sh
```

The complete gate runs repository checks, host tests, an isolated firmware build and merged-image verification. It produces `build/FoloToy-AI-Passport-full.bin` and a matching content-addressed archive under `build/firmware/`. It does not flash USB hardware. `idf.py build` alone is not a merged-image delivery check.

For the published package, use `AI-Passport-Codex-0.3.0-pets-full.bin` at **offset `0x0`**. Never flash the application-only image there. A complete merged flash can reset NVS and pairing; segmented upgrades require a verified compatible partition layout. Do not routinely erase the entire chip. See [firmware layout and stored data](docs/development/engineering/firmware-layout.md).

This variant uses factory application `0x10000` / `0x5F0000` and a two-MiB `pet_assets` partition at `0x600000`, with two validated resource slots. NVS and PHY remain at `0x9000` and `0xF000`.

## Source provenance and licenses

The base is [FoloToy/ai-passport](https://github.com/FoloToy/ai-passport) commit `006c2279852e352a8433b2c21e5e09be2ca36f77`. [provenance.json](provenance.json) records the imported source snapshot and modification areas. This directory is included directly, so cloning Codex Voice does not require submodule setup.

Changes add a separate Codex UI, task/quota controls, authenticated BLE control/audio/image channels, clean dictation cues, pet A/B storage, Chinese resources, audio recovery, battery behavior and host tests. Build caches, generated device logs, personal settings, bonding data and matching local debug symbols are excluded.

Retain [LICENSE](LICENSE) for the upstream MIT code and the [font license](assets/fonts/NotoSansSC-OFL.txt). Custom pet artwork is separate from the FoloToy license and does not grant rights to third-party characters or OpenAI marks. The material source descriptions remain in [assets](assets/README.md). Historical design/validation notes under `docs/codex-*` describe their recorded development stage; use the root project guide and current release verification for current installation instructions.
