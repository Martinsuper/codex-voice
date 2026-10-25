<p align="right"><a href="codex-accessory-settings.zh_CN.md">简体中文</a> · <strong>English</strong></p>

# Independent Codex accessory settings

The artwork feasibility section records the earlier `0.2.3` increment. Its
implementation is now documented in [automatic pet sync](codex-pet-sync.md).

## Implemented increment

Firmware `0.2.3-accessory` accepts an optional `petName` in the existing state
frame and reports `petNameSupported: true` in its hello frame. The default
nickname is the user's requested three-character Chinese name. It is rendered
with the existing CJK font. A changed name is saved to NVS outside capture and
playback, so it survives a disconnect or restart. The partition table and audio
cue implementation are unchanged. Missing names from an older host preserve the
last saved nickname.

The Mac companion is integrated into the single Codex Voice application.
Hardware connection, badge speech, and computer speech are separate controls.
Disabling badge speech leaves screen synchronization and push-to-talk usable.
The old virtual audio-device preference migrates to badge speech enabled and
computer speech disabled, preserving the user's previous listening behavior.
New installations default to computer speech enabled and the accessory disabled.
One scheduler handles reminder acknowledgement, pause, deduplication and both
speech routes. A computer output change does not replay an already delivered
badge reminder. Dictation temporarily blocks reminder playback on both routes.

## Pet artwork synchronization: feasibility, not delivered

The badge currently renders its built-in 32-frame NOMI artwork. Changing the
pet selected in Codex does not change that artwork. Renaming the badge's pet
does not rename the cloud pet. The settings page says that artwork does not
automatically synchronize.

Read-only inspection found a stable pet identifier, artwork fingerprint and
selection cache in this installed Codex version. These are private versioned
implementation details, not a documented third-party subscription API. The
[official Pets guide](https://learn.chatgpt.com/docs/pets) also distinguishes
local desktop custom pets from web pets. A future adapter should check these
fields narrowly, tolerate schema changes, and provide manual image import.
Do not scrape credentials, persist expiring download URLs, or dump global app
state. A conversation tool cannot serve as a permanent background sync client.

A reliable implementation needs a versioned asset protocol and intentional
storage layout: detect a changed selection, resolve authorized artwork, convert
frames, transfer chunks, check the complete checksum, and activate atomically.
Keep the old resource until the new resource verifies. Defer transfers during
dictation, playback and urgent reminders. This avoids promising instant BLE
updates or requiring a reflash for every later pet change.

The present 8 MB layout has no resource partition. One possible future layout
reserves 2 MiB at `0x600000`, shrinking the factory app to `0x5f0000` bytes.
Two 32-frame `96 x 104` RGB565 resources require 1,277,952 bytes before headers
and fit that space; the current application also fits the proposed app range.
This is capacity analysis only. It changes the partition layout and therefore
requires a separate reviewed migration, flash authorization, resource recovery
tests, rendering checks, and actual BLE throughput measurements. No resource
partition or artwork downloader is added in this increment.

## Local acceptance, 2026-10-25

- Build: PASS. Full ESP-IDF gate and archive verification; app size 5,414,208
  bytes. Full-image SHA-256:
  `7daf043f211bc94d01580039b408a31679cc01dbd69cbae89a743b38d5f3d6cd`.
  Matching ELF SHA-256:
  `7513c785471aa6543aad002fbfaacb79498eb9a5c0605e55d23892b5fcbfe58c`.
  Verified archive:
  full image (`../build/firmware/7daf043f211bc94d01580039b408a31679cc01dbd69cbae89a743b38d5f3d6cd/FoloToy-AI-Passport-full.bin`; retained locally; not included in public source),
  matching ELF (`../build/firmware/7daf043f211bc94d01580039b408a31679cc01dbd69cbae89a743b38d5f3d6cd/FoloToy-AI-Passport.elf`; retained locally; not included in public source).
- Host tests: PASS. Firmware static/host gate, actual LVGL rendering with the
  default nickname, 182 Mac Python tests, native protocol tests, packaged-engine
  migration/persistence tests, relocated bundle and signature verification.
- Device tests: PASS for this increment. The exact approved images were flashed
  in three segments after checking the physical partition table; all write hashes
  verified and NVS/PHY were excluded. The unified Mac app automatically connected
  and reported firmware `0.2.3-accessory`. The user confirmed the nickname, speech
  from both devices, direct text insertion with no panel, and clean completion
  cues. The USB log observation returned no bytes; it is not evidence of a
  clean startup log.
- Unverified: a full Mac reboot, use on a second Mac, long-duration battery/RF
  behavior, and future automatic artwork synchronization. Login-service startup
  with a single GUI/backend and automatic connection was observed; this is not
  an actual reboot test.

Mac `0.8.0-accessory.1` is installed as the single daily application at the
standard Applications location. Old installed/test copies were unregistered
and moved to Trash, with ZIP backups retained locally. The existing login job
now targets the unified bundle; old input permission was removed and the new
bundle registered through System Settings with the user's authentication.
Both speech outputs remain enabled as selected by the user during acceptance.
