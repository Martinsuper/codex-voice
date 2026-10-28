import Foundation

/// Constructs the engine process and its pipes; recovery policy belongs to the app.
struct EngineProcess {
    let process: Process
    let input: Pipe
    let output: Pipe
    let errors: Pipe

    init(executable: URL, script: URL, environment: [String: String], stateDirectory: URL, codexDirectory: URL) {
        process = Process()
        input = Pipe()
        output = Pipe()
        errors = Pipe()
        process.executableURL = executable
        process.environment = environment
        process.arguments = ["-s", script.path, "--state-dir", stateDirectory.path,
                             "--codex-dir", codexDirectory.path, "--usage"]
        process.standardInput = input
        process.standardOutput = output
        process.standardError = errors
    }
}
