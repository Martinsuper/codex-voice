<p align="right"><a href="codex-companion-validation.zh_CN.md">简体中文</a> · <strong>English</strong></p>

# Codex companion validation — 2026-10-24

Build: PASS  
Host tests: PASS  
Device tests: PASS (basic interaction only)  
Unverified: physical snooze/pause menu acceptance, sustained heap behavior, battery runtime and radio range.

## Exact firmware

- Version: 0.1.0-codex; ESP32-C3, ESP-IDF 5.5.3, 8 MB Flash.
- Verified merged image: full.bin (`../build/firmware/07400e491bff8e171c1f24bb184efe24c02d30f14e8085bdd0e84349babb8ba7/FoloToy-AI-Passport-full.bin`; retained locally; not included in public source).
- Archive directory: build/firmware/07400e491bff8e171c1f24bb184efe24c02d30f14e8085bdd0e84349babb8ba7/.
- Full-image SHA-256: 07400e491bff8e171c1f24bb184efe24c02d30f14e8085bdd0e84349babb8ba7.
- Matching ELF SHA-256: 6358d2012f1239c1e299d39903823a5df6313d605bee49674f84b66632a03ffc.
- Application: 3,980,960 bytes in an 8,323,072-byte application partition; merged image: 4,046,496 bytes.
- The complete shared validation gate and separate archive verification passed. The verified bundle binds bootloader, application, partition table, ELF and MAP.

## Mac evidence

- Local prototype version: 0.6.0-passport.2; application package in the adjacent codex-voice/.build directory.
- Application binary SHA-256: 877c1dcf4c34501980f028d4cb5b7a0851110322a7dd95a2b37cebb844894896.
- 167 Python unit tests passed, including device-start confirmation, timeout/failure accounting, acknowledgement and observed activity.
- Native protocol tests passed: compact state, priority, title-byte bounds including joined emoji, unknown quota handling and metadata filtering.
- arm64 and x86_64 slices were built; deep signature verification and moved-path bundled-Python checks passed. Only this Apple Silicon Mac was used; Intel execution is unverified.
- Simulated BLE feedback against the packaged engine passed: playback start confirmation, acknowledgement stopping playback, and disconnection preserving the counter. No actual radio or speaker output is implied.
- Isolated hook installation, unchanged trust policy, existing settings validation and persistence/restart checks passed.

## Physical results and handoff

After explicit user approval, the exact image above was written from 0x0. Write verification passed and the startup ELF prefix matches the archived image. Display, ES8311, ADC keys, fuel gauge and BLE initialized normally.

- The user confirmed a clear CODEX and Chinese interface.
- The user completed six-digit BLE pairing. A later desktop-app restart reconnected automatically.
- The first audio test failed because desktop UUID epochs were uppercase while the device accepts lowercase hexadecimal. The desktop fix includes a regression test and did not require reflashing.
- On retest the user heard the phrase and pressed the device confirmation key. The Mac recorded two actual playback starts followed by acknowledgement, removal of the test reminder and stopped speech.
- The temporary desktop variant uses its own application name and identifier, local.rico.CodexVoice.Passport, and remains running. The installed original app was not overwritten. Its local package is in the adjacent codex-voice/.build directory.
- Opening USB serial was observed to cause USB_UART_CHIP_RESET, so serial monitoring was stopped during pairing. Acceptance then used BLE feedback and user observations.

PASS covers the basic interaction, not all menu actions, battery runtime, range or extended stability. No commit, push or release was performed.

See [the behavior and controls](codex-companion.md). Machine-readable evidence is in the local validation record (`../build/companion-validation.json`; retained locally; not included in public source).
