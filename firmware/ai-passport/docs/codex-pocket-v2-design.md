<p align="right"><a href="codex-pocket-v2-design.zh_CN.md">简体中文</a> · <strong>English</strong></p>

# Codex Pocket: product and interaction proposal

Status: firmware 0.2.0-pocket and Mac companion 0.7.0-pocket.2 are implemented and pass compilation, host checks and actual LVGL rendering. The exact new firmware has been approved and flashed. Startup, UI, BLE and live recognition pass; Mac insertion compatibility is being retested. Physical dictation, insertion, cues, runtime and radio range remain device acceptance checks. See the [implementation record](codex-pocket-v2-validation.md). No new flash, commit, push or release is implied.

## Product intent

A useful wearable companion near the Mac: a familiar pet when idle, an immediate quota glance when awakened, a focused next action when attention is needed, and hold-to-dictate when the user wants to enter text. Product polish comes from legibility, hierarchy, restraint and predictable physical controls. The 240 x 320 display should prioritize one primary action at a time.

## Accepted input and assumptions

The user's four directions are a personal Codex pet as screensaver; a large remaining-quota number surrounded by a ring; professional task reminders; and holding OK to use the badge microphone as computer text input. The Chinese wording for quota is interpreted as remaining Codex allowance. The usage remains near this Mac over BLE. The preview uses illustrative values and simulated transcription, not live microphone capture.

The selected NOMI-style pet was resolved through the local desktop selection and Pets connector. Its actual v2 sheet is 1536 x 2288, with nine action rows and sixteen look directions. The original and a deterministic reduced preview copy are in [assets/pets/nomi](../assets/pets/nomi/source.json). The pet was not recreated and the account selection was not changed. Initial firmware can embed this imported pet; automatically tracking future cloud pet changes requires a stable authorized resource integration, which has not been established.

## Experience and state priority

| State | Screen and interaction |
| --- | --- |
| Pet screensaver | A low-distraction idle/blink animation. Any short key wakes the device and consumes that key. Show the quota home when no reminder is pending; otherwise show the priority reminder. |
| Quota home | A large tabular number and a single custom remaining-value ring; period, reset countdown and synchronization status are secondary. UP/DOWN inspects the reported quota windows. Default to the most constrained valid window. |
| Attention | One task at a time: category, project/chat title (up to two lines), a concise next action and position in the queue. Short OK acknowledges the reminder and locates its verified chat on the Mac. Actual tool approvals still happen in Codex. |
| Hold to dictate | Holding OK starts a preparation/listening state; release ends capture. Show the destination and distinguish preparing, capturing, processing, inserted and retained-draft states. Do not send the prompt automatically. |

Voice capture owns the current interaction until it stops or is cancelled; new ordinary reminders queue behind it. Attention priority follows needs-input, blocked, ready and running. Selecting a task is stable during a key gesture: a queue reorder must not change the task acknowledged on release.

Idle is not proof that all projects are complete. A turn finishing means a reply/result is ready, not that deployment or the whole project succeeded. Unknown or stale quota remains explicitly unknown; it is not rendered as zero or a complete ring. Use the actual returned window durations and reset timestamps rather than assuming every account always has the same periods.

## Physical controls

- Any short key from the screensaver: wake only.
- UP/DOWN: period selection on the quota home; task selection on reminders.
- Short OK on a reminder: acknowledge and locate that task. Other normal pages use it for the relevant primary action.
- Hold OK, including from screensaver: voice input. The current long-OK menu must move to long-UP or an equally explicit quick-action entry.
- Short-wake suppression must not suppress a later long-press or release event. Add gesture-state tests for wake/hold/release, arriving reminders, repeats and cancellation.

Use instant visual key-down feedback, then a clear ready cue when capture and the Mac channel are usable. Measure the threshold and perceived delay on hardware. A bounded preparation timeout returns to a usable state. Record only during the deliberate voice interaction.

## Dictation sounds and acknowledgements — proposed contract

Confirmed sound form: the ready and completion cues are distinct, short, non-speech sound effects. Do not speak phrases such as ready to speak or draft ready; those are screen labels describing each cue's meaning. Use a gentle single cue for readiness and a distinguishable rising two-note cue for completion, with final sound design tuned on the badge speaker. Pair them with text and NOMI expressions. This decision concerns dictation cues; the existing task-reminder speech is a separate feature.

The user proposed two cues: a start cue after holding OK, and another after the audio is transferred to the computer. Keep two cues in the normal flow. The recommended refinement is to reserve the normal success cue for final text inserted into the intended draft; complete audio reception is an intermediate visual state. This aligns the audible promise with the user's intended result. If transfer-only feedback is chosen instead, name it received, never input complete, and continue showing transcription status.

| Moment | Audible feedback | Visual feedback / required condition |
| --- | --- | --- |
| Hold recognized | None yet | Preparing; bind the target and initialize capture and the Mac receiving/transcription session. |
| Ready to speak | A short, gentle single cue | Both ends are ready. After the cue finishes, admit speech into the effective recording and show Listening with actual capture feedback. Keep holding while speaking. |
| Release | No additional routine cue | Stop capture locally immediately; close the recording stream and show Processing. |
| Computer receives all audio | None | The Mac confirms this recording's complete sequence/tail, then shows Received / transcribing. |
| Final text inserted | A distinct short rising completion cue | Only after the Mac confirms nonempty final text was inserted into the intended field. Show Draft ready; sending remains manual. |

Initial cue-length candidates are approximately 80–120 ms for ready and 150–250 ms for completion; tune timbre, loudness and acoustic tail on the real speaker. The two cues should differ in rhythm/contour, not merely volume. Never start with a successful cue just because the button was held; never complete from a fixed timer or a successful send call.

A separate soft attention cue means look at the device: unavailable connection, no effective speech, incomplete audio, recognition failure, or text retained but not inserted. Pair it with specific text and a NOMI expression. Do not play the normal success cue for retained-only text. Show slower processing calmly; a bounded failure reports the actual stage and preserves only data the computer has really received. The badge's bounded buffers cannot guarantee recovery of all speech after a disconnect.

The ready sound must not be transcribed as user speech. Gate the transmitted capture around playback completion and measured acoustic settling, then test first/last-word retention. Defer ordinary reminder audio during recording. In the first implementation, serialize capture/finalization; another hold while a prior utterance is still completing reports that status without a new ready cue.

All ready/received/transcribed/inserted acknowledgements carry the recording identity. Ignore stale or mismatched replies. Input insertion is idempotent: reconnection may recover status but must not insert the same utterance twice. A missing final acknowledgement must not be reported as success. Muted operation still provides complete text/icon feedback; active dictation cues can have their own simple sound preference.

## Speech implementation

Recommended pipeline: ES8311 microphone -> fixed-size capture chunks -> compressed BLE audio frames -> Mac decoder -> Apple SpeechAnalyzer/SpeechTranscriber -> final text -> the intended input field or a retained draft.

A read-only check on this Mac found SpeechTranscriber available, 45 supported locales and 11 installed locales; installed Chinese locales include zh_CN and zh_TW. No audio was recorded, no models were downloaded and no permission state was changed. This establishes available resources, not accuracy or end-to-end latency. System transcription is the first candidate; whisper.cpp is a local fallback for compatibility or evaluation if needed. A paid cloud transcription service is not required for the initial design.

The AI Passport repository documents Opus uplink on one AI Passport plus Android phone: 16 kHz mono, 60 ms frames and about 3 KB/s, with a 24 KB static encoder stack. It is a feasibility reference, not a measurement for this Mac. Measure current MTU, sustained throughput, packet gaps and latency before choosing final buffers and codec settings. Keep audio separate from the current JSON reminder stream, with recording IDs, sequence numbers, bounded buffers, flow control, cancellation and explicit start/end acknowledgements.

On the Mac, bind the destination before capture: the relevant verified Codex task where available, otherwise the intended editable field. Preserve cursor/selection and existing draft text. A target or content change retains a separate transcript for explicit insertion instead of overwriting another field. Missing targets, denied permissions, disconnects and recognition failures must preserve a recoverable draft. Guide the necessary accessibility/recognition permissions at setup. Do not implement this by simply selecting the badge as a normal Bluetooth microphone: the present link is a BLE data service.

Serialize playback and capture through one audio owner; pause/defer spoken reminders while dictating. Keep blocking reads, codec changes and sleep/wake operations out of key callbacks and LVGL. Protect release and cancel events from backpressure. Real speech, recognition accuracy, clipping of initial/final words, interrupted capture and cross-app focus changes need physical acceptance.

## Resource and power design

The measured first prototype boot reported about 101 KB free heap. This is a starting measurement, not a guaranteed steady-state budget. A 96 x 104 RGB565 frame uses 19,968 bytes; decoding an entire 240 x 320 frame would need 153,600 bytes before alpha and other allocations. Store pet frames in flash, crop to a bounded region, use one small buffer and reuse the existing partial display path. Do not enable full-screen compositing merely for shadows or translucency.

Release optional pet decode memory before capture/encoding, measure largest contiguous blocks and stack high-water marks, and keep voice mode visually simple. Draw the quota ring using native LVGL geometry; regenerate only the needed large digit glyphs. Low-rate pet animation can become a still, dimmed frame after further idle time. This is a TFT display, so backlight and subsystem power matter more than the choice of a black fill. Keep reminder wake responsive. Battery runtime and radio range require measurements; no all-day claim is made.

## Useful extensions, in priority order

1. Locate the exact chat when acknowledging a task; derive navigation only from the Mac's trusted task map and supported deep links.
2. A compact multi-task queue and pet expression mapped to actual task states.
3. Low-allowance/reset cues plus a physical focus/quiet action, reusing the existing Mac schedule rather than creating a second scheduler.
4. A personal dictation terminology list and explicit target selection for Codex versus other input fields.
5. Later, a small local accessory configuration interface so a Codex workflow can help change themes/reminder rules. This requires a defined authorized integration; it is not available merely because Codex Micro supports hardware controls.

## Delivery sequence and acceptance

First confirm the interaction and visual direction, then implement the UI/pet/quota metadata and the recording/uplink/transcription/draft pipeline. Build and test before asking for approval of an exact replacement firmware. Existing approval for 0.1.0-codex does not authorize another build.

Acceptance includes: all four states readable on the real display, wake without accidental acknowledgement, long-OK working from screensaver, stable queue target across reordering, unknown quota rendering, matching pet state, audible-recording readiness, press/release/cancel, local Chinese transcription, text inserted at the intended cursor without auto-send, retained drafts after focus changes or link loss, reconnection, heap/stack soak, battery runtime and range.

## Sources

- [OpenAI: Pets](https://learn.chatgpt.com/docs/pets)
- [OpenAI: Codex Micro](https://learn.chatgpt.com/docs/features/codex-micro) — its push-to-talk key uses the computer microphone.
- [OpenAI: app commands and deep links](https://learn.chatgpt.com/docs/app/commands)
- [OpenAI: app-server](https://learn.chatgpt.com/docs/app-server) — existing event/quota capabilities do not automatically expose every desktop UI action.
- [Apple: designing for watchOS](https://developer.apple.com/design/human-interface-guidelines/designing-for-watchos/)
- [Apple: SpeechAnalyzer](https://developer.apple.com/documentation/speech/speechanalyzer)
- [Apple: SpeechTranscriber](https://developer.apple.com/documentation/speech/speechtranscriber)
- [AI Passport: BLE speech uplink](reference/shinku-chen/ble-voice-uplink-and-pairing.md)
- [whisper.cpp](https://github.com/ggml-org/whisper.cpp)

- [Apple: feedback](https://developer.apple.com/design/human-interface-guidelines/feedback)

## Implementation choices

- Independent IMA-ADPCM blocks at 16 kHz mono: 320 samples / 20 ms per 180-byte packet, about 9 KB/s including headers. Encrypted notification characteristic F004 carries binary audio separately from JSON control. No Opus dependency or 24 KB encoder stack is added. Sustained Mac BLE throughput remains unmeasured.
- The original NOMI provides 32 frames at 144×156; 1,437,696 RGB565 bytes remain in flash without a full-screen or decoded pet buffer. LVGL uses a 32 KB pool; the host renderer measures about 19.6 KB used by the actual widget layout. This is not device heap evidence.
- Maximum utterance: 30 seconds, one at a time. The Mac checks session ID, sequential blocks, frame and sample totals before recognition. Ready: 100 ms single tone; success: two ascending 80 ms tones separated by 30 ms. TX silence drains DMA before RX is restarted. Acoustic tail and first/last words require physical tests.
- The target application, editable AX element, original value and UTF-16 selection are captured before ready. One standard Paste is followed by read-back verification; all readable pasteboard formats are preserved, temporary contents are current-host-only, and a newer user copy is never overwritten during restoration. Changed focus/draft retains the text, ambiguous insertion is never retried automatically, and Return is never sent. App-specific AX compatibility remains an acceptance check.
- Retained text lives in a visible Mac window and memory until copied or the process quits; it is not a durable journal. Incomplete interrupted audio is rejected. No user speech has been recorded or input permission granted during host validation.
- This version uses on-device SpeechAnalyzer and does not request legacy SFSpeechRecognizer server-recognition authorization or Mac microphone permission. Only Accessibility is needed for cross-app insertion. [Apple permission guidance](https://developer.apple.com/documentation/speech/asking-permission-to-use-speech-recognition).
