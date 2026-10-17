import AppKit
import Foundation

enum AppPaths {
    static let identifier = "local.rico.CodexVoice"
    static let observerID = "codex-voice-observer-v1"
    static var resources: URL { Bundle.main.resourceURL! }
    static func argument(_ name: String) -> String? {
        let values = CommandLine.arguments
        guard let index = values.firstIndex(of: name), index + 1 < values.count else { return nil }
        return values[index + 1]
    }
    static var runtime: URL {
        if let custom = argument("--state-dir") { return URL(fileURLWithPath: custom, isDirectory: true) }
        return FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0].appendingPathComponent("CodexVoice", isDirectory: true)
    }
    static var codexHome: URL {
        if let custom = ProcessInfo.processInfo.environment["CODEX_HOME"], !custom.isEmpty { return URL(fileURLWithPath: custom, isDirectory: true) }
        return FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent(".codex", isDirectory: true)
    }
    static var pythonHome: URL { Bundle.main.privateFrameworksURL!.appendingPathComponent("Python.framework/Versions/3.14", isDirectory: true) }
    static var python: URL { pythonHome.appendingPathComponent("bin/python3.14") }
    static var environment: [String: String] {
        var values = ProcessInfo.processInfo.environment.filter { !$0.key.hasPrefix("PYTHON") && $0.key != "__PYVENV_LAUNCHER__" }
        values["PYTHONHOME"] = pythonHome.path
        values["PYTHONNOUSERSITE"] = "1"
        values["PYTHONDONTWRITEBYTECODE"] = "1"
        values["PYTHONSAFEPATH"] = "1"
        values["PYTHONUTF8"] = "1"
        return values
    }
    static func prepare() throws {
        try FileManager.default.createDirectory(at: runtime, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
        guard FileManager.default.isExecutableFile(atPath: python.path) else { throw StartupError.failed("应用内的运行环境不完整，请重新安装完整的 Codex 语音提醒.app。") }
    }
    static func runPython(_ script: String, _ arguments: [String], forwardInput: Bool = false, quiet: Bool = false) throws -> (Int32, Data) {
        try prepare()
        let child = Process(); child.executableURL = python; child.environment = environment
        child.arguments = ["-s", resources.appendingPathComponent(script).path] + arguments
        child.standardInput = forwardInput ? FileHandle.standardInput : FileHandle.nullDevice
        let output = Pipe(); child.standardOutput = quiet ? FileHandle.nullDevice : output
        child.standardError = FileHandle.nullDevice
        try child.run()
        let data = quiet ? Data() : output.fileHandleForReading.readDataToEndOfFile()
        child.waitUntilExit()
        return (child.terminationStatus, data)
    }
}

enum CodexConnection {
    static func run(_ action: String) -> [String: Any] {
        do {
            let (_, data) = try AppPaths.runPython("hook_setup.py", [action, "--app", Bundle.main.bundleURL.path, "--codex-dir", AppPaths.codexHome.path, "--state-dir", AppPaths.runtime.path])
            return (try? JSONSerialization.jsonObject(with: data) as? [String: Any]) ?? ["error":"未能读取提醒连接状态"]
        } catch { return ["error":error.localizedDescription] }
    }
}
