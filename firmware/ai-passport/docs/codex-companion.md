<p align="right"><a href="codex-companion.zh_CN.md">简体中文</a> · <strong>English</strong></p>

# Codex Passport companion, first prototype

The agreed use is a wearable reminder near the user's Mac. The Mac owns Codex event collection, reminder scheduling, quiet hours, quota reads and acknowledgements. The Passport displays a bounded snapshot, plays seven embedded fixed phrases and returns button actions over encrypted BLE. No phone, Wi-Fi configuration or new model API is required.

## Controls and behavior

- UP / DOWN: previous / next visible reminder. At most eight are shown, ordered by attention priority; the Mac retains all reminders and the total count. Handling visible reminders exposes subsequent items.
- OK short press: acknowledge this reminder. It does not approve a Codex tool or answer a question.
- OK long press: open the menu. Menu actions are back, snooze five minutes, replay, pause fifteen minutes, and reset pairing. Reset pairing has a second on-device confirmation.
- First pairing: select AI Passport in the Mac application's output picker; grant macOS Bluetooth permission and enter the six-digit code shown on the Passport when macOS asks.
- The display dims after thirty seconds; a wake press is consumed to prevent accidentally acknowledging a reminder.
- A missing heartbeat clears stale tasks and stops playback. Reconnection synchronizes the current Mac state. Buttons report success only after the Mac snapshot confirms the change.
- Battery readings attach to the existing active CW2017 configuration without replacing its cell profile. Missing/unready readings display dashes.
- A newly observed active Codex turn is shown as running; no pending reminders is presented as no pending reminders, not proof that every project is finished. Events retain the current desktop application's local-session coverage limits.

## Audio

This prototype uses fixed Tingting phrases generated on the Mac and embedded as signed 16-bit, 16 kHz mono PCM. Task names are displayed but are not spoken in the fixed phrases. The Passport output does not follow the Mac's voice/address/rate settings. Full generated task-name speech is a later increment.

The existing Python engine remains the only scheduler. It waits for a matching device playback-start acknowledgement before advancing a reminder's count. Disconnection, timeout and playback failure do not count as successful playback. Selecting the Passport routes audio exclusively to it; selecting a Mac output returns to existing behavior.

## Protocol and ownership

Service UUID: EA37F001-4E2B-47EF-9501-6D79B932A001. RX and TX replace F001 with F002 and F003. Frames are bounded newline-delimited UTF-8 JSON, version 1. Long writes/notifications are reassembled and oversized frames are dropped until a newline.

The native Mac component owns CoreBluetooth and sends hello, state, play, stop and action_result. The device sends hello, pong, audio and action. State uses a per-application random epoch and hashed reminder IDs. Only selected task titles, kinds, counts, mute state and fresh quota percentages are sent, not transcripts, credentials or raw account data. The bridge permits only ack, snooze, replay and pause actions.

The device expires state after ten seconds without updates. Native link liveness expires after twelve seconds. Stale computer-engine snapshots disable playback. Playback has a dedicated worker, bounded DMA chunks and a cancellation generation; BLE and button callbacks never run audio or LVGL work.

## Development and validation

Firmware source is based on official main 006c2279852e352a8433b2c21e5e09be2ca36f77 and uses ESP-IDF 5.5.3. The Mac checkout is the adjacent codex-voice repository on feature/passport-companion, based on 5bc4c097699be224cfd5a2ee9dfbe2658d57e3f2. No commit, push or release has been requested.

Run the existing unified firmware gate with ESP-IDF activated: ./tools/validate.sh. It includes the new pure state/framing test and read-only fuel-gauge tests. The Mac checkout uses its Python unit suite, the native PassportProtocol test, a universal app build and scripts/verify_app.py. Final evidence and the exact merged image identity must be recorded after successful runs.

Hardware identification completed: ESP32-C3 revision 1.1, 8 MB flash, USB Serial/JTAG; the user confirmed that the original badge restarted normally after read-only inspection. The user approved and flashed this image. Basic pairing, Chinese display, audible speech, confirmation-key synchronization and automatic reconnection after a desktop restart passed. Other menu actions, runtime, range and extended stability remain unverified; see the [physical validation record](codex-companion-validation.md).

## Flashing impact

Follow the approval handoff in [the AI guide](development/ai-guide.md#offer-on-device-testing). Flash only an explicitly approved, verified merged image from 0x0. It replaces the current badge application and may reset its stored name-card settings. Whole-chip erasure is not part of this plan. No restore or battery-runtime claim is made without evidence.

## Assets

Fonts are Noto Sans SC, weight 500, under the bundled SIL Open Font License. See [the source font](../assets/fonts/NotoSansSC-wght.ttf), [license](../assets/fonts/NotoSansSC-OFL.txt), and [asset manifest](../assets/music/codex/manifest.json). The generated 16 px font covers common CJK and punctuation; unsupported title characters are deliberately shown as squares. Fixed UI source glyphs are checked during generation. Regenerate using tools/make_companion_assets.py with fontTools and lv_font_conv 1.5.3; --audio-only and --fonts-only allow independent generation. Screen rendering and acoustic quality still require the real device.

## Current use and restoring the original desktop app

The independently identified temporary Passport app is currently running with the Passport output selected. The installed original application was not overwritten. Short OK acknowledges a reminder; actual Codex approvals and answers still happen in Codex. The display dims after thirty seconds; the first key wakes it, then a subsequent press performs the action.

To return to the original application, select the original Follow System Output in the temporary app, quit it, then open the installed original app. The pre-test settings snapshot is local-only at build/mac-settings-before-passport.json and must not be uploaded.
