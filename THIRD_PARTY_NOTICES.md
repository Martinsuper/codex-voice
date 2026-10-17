# Third-party components

The distributable app embeds the standard CPython 3.14.8 macOS universal2 framework obtained from the Python Software Foundation's official macOS installer.

- Upstream: https://www.python.org/downloads/release/python-3148/
- Installer URL and SHA-256: `scripts/python-runtime.json`
- CPython and bundled component notices are preserved in the application under `Contents/Resources/ThirdPartyLicenses/`, including the upstream distribution's complete `License.rtf` and `LICENSE.txt`.
- The build relocates framework load paths, removes development tools, test data, pip bootstrap, caches and unused example / GUI Python modules, then signs the resulting application. The app's own interface uses native AppKit / SwiftUI, not Tk.
- No third-party font is bundled. MiSans is used if already installed by the user; otherwise the native system font is used.

The app is an independent third-party companion and is not an OpenAI product.
