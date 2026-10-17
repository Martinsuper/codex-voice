import AppKit
import Foundation

enum StartupError: LocalizedError {
    case failed(String)
    var errorDescription: String? { if case .failed(let message) = self { return message }; return nil }
}

enum LoginStartup {
    static let label = "local.rico.CodexVoice.login"
    static var domain: String { "gui/\(getuid())" }
    static var service: String { "\(domain)/\(label)" }
    static var path: URL { FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/LaunchAgents/\(label).plist") }
    static func run(_ arguments: [String]) -> (Int32, String) {
        let p = Process(); p.executableURL = URL(fileURLWithPath: "/bin/launchctl"); p.arguments = arguments
        let out = Pipe(); p.standardOutput = out; p.standardError = out
        do {
            try p.run()
            let data = out.fileHandleForReading.readDataToEndOfFile(); p.waitUntilExit()
            return (p.terminationStatus, String(data: data, encoding: .utf8) ?? "")
        } catch { return (-1, error.localizedDescription) }
    }
    static func status() -> [String: Any] {
        let exists = FileManager.default.fileExists(atPath: path.path)
        let disabledText = run(["print-disabled", domain]).1
        let escaped = NSRegularExpression.escapedPattern(for: label)
        let disabled = disabledText.range(of: "\"\(escaped)\"\\s*=>\\s*(?:true|disabled)\\b", options: .regularExpression) != nil
        let registered = run(["print", service]).0 == 0
        return ["enabled": exists && !disabled, "registered": registered, "plist": path.path]
    }
    static func setEnabled(_ enabled: Bool) throws {
        if enabled {
            let executable = Bundle.main.bundleURL.appendingPathComponent("Contents/MacOS/CodexVoice").path
            guard FileManager.default.isExecutableFile(atPath: executable) else { throw StartupError.failed("找不到提醒应用，请从完整的 CodexVoice.app 打开。") }
            let config: [String: Any] = ["Label": label, "ProgramArguments": [executable, "--background"], "RunAtLoad": true, "KeepAlive": false, "LimitLoadToSessionType": "Aqua", "ProcessType": "Interactive", "AssociatedBundleIdentifiers": ["local.rico.CodexVoice"]]
            try FileManager.default.createDirectory(at: path.deletingLastPathComponent(), withIntermediateDirectories: true)
            let data = try PropertyListSerialization.data(fromPropertyList: config, format: .xml, options: 0)
            try data.write(to: path, options: .atomic)
            try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: path.path)
            let enabledResult = run(["enable", service])
            guard enabledResult.0 == 0 else { throw StartupError.failed(enabledResult.1) }
            if run(["print", service]).0 != 0 {
                let result = run(["bootstrap", domain, path.path])
                guard result.0 == 0 else { throw StartupError.failed(result.1) }
            }
        } else {
            let result = run(["disable", service])
            guard result.0 == 0 else { throw StartupError.failed(result.1) }
        }
    }
}

@main
struct VoiceLauncher {
    static func main() {
        if CommandLine.arguments.contains("--hook") {
            // Fail open: a reminder must never block or approve a Codex action.
            _ = try? AppPaths.runPython("voice_bridge.py", ["--state-dir", AppPaths.runtime.path, "hook"], forwardInput: true, quiet: true)
            return
        }
        if CommandLine.arguments.contains("--runtime-info") {
            do {
                let (status, data) = try AppPaths.runPython("runtime_info.py", [])
                FileHandle.standardOutput.write(data); exit(status)
            } catch { fputs(error.localizedDescription + "\n", stderr); exit(1) }
        }
        if CommandLine.arguments.contains("--connection-status") {
            let data = try? JSONSerialization.data(withJSONObject: CodexConnection.run("--status"), options: [.sortedKeys])
            if let data { FileHandle.standardOutput.write(data) }; return
        }
        if CommandLine.arguments.contains("--startup-status") || CommandLine.arguments.contains("--startup-enable") || CommandLine.arguments.contains("--startup-disable") {
            do {
                if CommandLine.arguments.contains("--startup-enable") { try LoginStartup.setEnabled(true) }
                if CommandLine.arguments.contains("--startup-disable") { try LoginStartup.setEnabled(false) }
                let data = try JSONSerialization.data(withJSONObject: LoginStartup.status(), options: [.sortedKeys])
                print(String(data: data, encoding: .utf8) ?? "{}")
            } catch { fputs(error.localizedDescription + "\n", stderr); exit(1) }
        } else {
            let application = NSApplication.shared
            let delegate = AppDelegate()
            application.delegate = delegate
            application.run()
        }
    }
}
