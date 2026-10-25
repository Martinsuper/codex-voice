<p align="right"><a href="codex-pet-sync.zh_CN.md">简体中文</a> · <strong>English</strong></p>

# Automatic Codex pet artwork synchronization

Firmware `0.3.0-pets` and Mac `0.8.1-pets.3` extend the single Codex Voice app.
The badge nickname remains independent of the selected artwork. This increment
keeps the user's existing nickname and the existing buttons, reminders and clean
dictation cues.

## Selection and image sources

The Mac reads only `desktop.selected-avatar-id` in `config.toml` and necessary
pet entries in `.codex-global-state.json`. It follows built-in pets from the
installed app's ASAR assets, local pets from `pets/*/pet.json` or legacy
`avatars/*/avatar.json`, and cloud pets from the desktop image cache. All reads
are local and read-only. These are private versioned formats; missing or changed
formats retain the previous badge artwork and show a retry status.

The cloud artwork registry intentionally removes URL signatures. The adapter
therefore finds the selected immutable resource URL in the key prefix of its
Chromium image-cache entry, then reads only that image's bounded byte range.
PNG chunk CRCs and dimensions are checked. It does not read Cookies, login
credentials or arbitrary cached response bodies. A cached prepared image is
bound to the selected ID, source fingerprint, output format and complete SHA-256;
it remains reusable after the desktop HTTP cache is evicted. An actual signed
image reference, when present, can also be downloaded using an ephemeral session
with an HTTPS host allowlist, redirect checks and a 20 MiB limit. URLs and
signatures never enter status files or persistent metadata.

Native ImageIO checks the full sprite dimensions before decoding. Version 1
uses `1536 x 1872`; version 2 uses `1536 x 2288`. Six idle, four running, two
ready, two waiting and two blocked frames are converted to `144 x 156` RGB565
without changing the displayed character. Sixteen frames occupy 718,848 bytes.
The badge retains its built-in 32-frame fallback if no downloaded image verifies.

## Protocol and storage

The factory app stays at `0x10000` and shrinks to `0x5f0000` bytes. A two-MiB
`pet_assets` data partition at `0x600000` contains two one-MiB slots. Each slot
has a four-KiB header sector followed by the image data. Header CRC, fixed bounds,
generation and content SHA-256 are verified. Only a final commit word makes a
complete slot valid. An interrupted transfer or commit leaves the old slot
usable; boot validation can fall back to the older verified slot. No filesystem
or full-frame RAM allocation is needed.

`pet_begin` negotiates a transfer and its resume offset; encrypted characteristic
F005 accepts bounded binary packets containing an upload ID, offset and payload.
The Mac sends at most four packets per window. Cumulative device replies provide
backpressure; missing responses renegotiate the offset. `pet_commit` verifies
the complete data before activation. The UI publishes a new mapped slot while
holding its LVGL lock before the previous slot can be overwritten. New pet
selections replace unfinished transfers; stale IDs cannot activate older work.

The storage worker uses a bounded queue and low priority. Both peers defer
transfer work during dictation, speech and urgent reminders. Pairing and input
audio keep priority. Turning off the accessory cancels pending source work.

## Migration and validation

This is a deliberate partition-table migration, not a same-table update. Before
approved segmented flashing, validate the exact old table, confirm unchanged
NVS/PHY ranges and app start, and verify that both old and new applications fit
below `0x600000`. Write only the approved bootloader, table and app. Do not erase
the whole chip or write a padded full image over settings. Future artwork
changes use BLE and do not require another firmware flash.

Automated checks cover A/B storage bounds, resume, duplicate/conflicting chunks,
corrupt data, interrupted commit, corruption fallback and active-slot exclusion;
source selection and image-cache extraction; native image dimensions, orientation,
packet format, transfer pause/resume, offline guard and prepared-cache restart.
Actual device throughput, changing the selected pet and dictation coexistence
remain separate device acceptance checks.

## Local acceptance, 2026-10-25

Build: PASS. The full ESP-IDF 5.5.3 gate and archive verification passed.
The application is 5,418,432 bytes in the 6,225,920-byte factory partition.
Full-image SHA-256:
`fdd0e85cd9dcde727f15147beda848897d3ec795c14322546f2fef66d16d0573`.
Matching ELF SHA-256:
`050a5aeaa8914c778a460f4745a04d53052f672a722f2bff39551574d3905242`.
Verified artifacts:
full image (`../build/firmware/fdd0e85cd9dcde727f15147beda848897d3ec795c14322546f2fef66d16d0573/FoloToy-AI-Passport-full.bin`; retained locally; not included in public source),
matching ELF (`../build/firmware/fdd0e85cd9dcde727f15147beda848897d3ec795c14322546f2fef66d16d0573/FoloToy-AI-Passport.elf`; retained locally; not included in public source).

Host tests: PASS. Firmware storage/fault tests, 192 Python tests, native image
and transport tests including prepared-cache restart, complete conversion of the
current custom pet and all nine installed built-ins, actual LVGL rendering with
a dynamic Dewey resource, packaged engine checks and deep signature verification.

Device tests: PASS for the observed feature. The human approved the exact image
and partition migration. Physical partition checks and all three segmented write
hashes passed, excluding NVS/PHY. The resource worker and mapped storage reported
ready. macOS initially retained the old GATT table without F005; renewing the bond
on the Mac and badge resolved this. The Mac now performs full service discovery.
The original custom artwork transferred and verified, followed automatically by
the built-in Codex pet selected by the user. Its complete device-acknowledged
payload SHA-256 is
`3bd8bcaa3246cdfd48ff13191a2e4b7955959a16a3d9c35bd6023cacc4ba1018`.
The user confirmed that the physical screensaver changed, the requested nickname
was retained, and direct input, absence of a retention panel and cues worked.

During acceptance, a Mac hang sample showed the main thread in the Caps Lock
input-source selection path in HIToolbox/TSM. The existing nonactivating key panel
was replaced with an ordinary activating panel; explicit opening activates before
becoming key, and hiding resigns editing/key focus and returns to the prior app.
Automatic alerts still only order the panel forward. The user repeated input
method switching, panel interaction and dictation and confirmed normal behavior.
This is an observed failure path and tested mitigation, not a claim that Apple
has confirmed a universal platform defect.

Final checks found one launchd-owned GUI, a fresh backend, an authenticated badge
connection, the synchronized payload and the user's requested nickname. The panel
was left hidden. Only the single application at the standard Applications path
remains in daily use, with login startup enabled. Local acceptance and sample
records are in the Mac project's ignored `.build/` directory; no public release
or repository publication was performed.

Unverified: a full Mac reboot, a physical mid-transfer disconnect on this board,
long-duration battery/RF behavior and long-term recurrence of the input-method
problem. The bounded USB monitor received no bytes and is not evidence of a clean
startup log. Host fault tests and simulation are separate from these device checks.
