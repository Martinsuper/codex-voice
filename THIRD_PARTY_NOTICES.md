# Third-party components

The distributable app embeds the standard CPython 3.14.8 macOS universal2 framework obtained from the Python Software Foundation's official macOS installer.

- Upstream: https://www.python.org/downloads/release/python-3148/
- Installer URL and SHA-256: `scripts/python-runtime.json`
- CPython and bundled component notices are preserved in the application under `Contents/Resources/ThirdPartyLicenses/`, including the upstream distribution's complete `License.rtf` and `LICENSE.txt`.
- The build relocates framework load paths, removes development tools, test data, pip bootstrap, caches and unused example / GUI Python modules, then signs the resulting application. The app's own interface uses native AppKit / SwiftUI, not Tk.
- No third-party font is bundled. MiSans is used if already installed by the user; otherwise the native system font is used.

The distributable app also embeds the sherpa-onnx speech recognition runtime and a bundled offline Chinese Paraformer ASR model, both used entirely on-device for badge dictation; audio never leaves the machine.

- sherpa-onnx shared libraries (`libsherpa-onnx-c-api`, `libsherpa-onnx-cxx-api`, `libonnxruntime`), Apache License 2.0, Copyright (c) 2023 Xiaomi Corporation. Upstream: https://github.com/k2-fsa/sherpa-onnx — ONNX Runtime is Copyright (c) Microsoft Corporation, MIT License. Archive URL and SHA-256: `scripts/sherpa-runtime.json`.
- Offline Chinese Paraformer model `sherpa-onnx-paraformer-zh-2023-09-14` (`model.int8.onnx`, `tokens.txt`), Apache License 2.0, converted from FunASR / ModelScope `speech_paraformer-large-vad-punc_asr_nat-zh-cn-16k-common-vocab8404`. Upstream: https://github.com/k2-fsa/sherpa-onnx/releases/tag/asr-models — archive URL and SHA-256: `scripts/sherpa-runtime.json`.

The app is an independent third-party companion and is not an OpenAI product.
