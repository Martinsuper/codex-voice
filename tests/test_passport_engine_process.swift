import Foundation

@main
struct EngineProcessTests {
    static func main() throws {
        let process = EngineProcess(executable: URL(fileURLWithPath: "/usr/bin/python3"),
                                    script: URL(fileURLWithPath: "/tmp/engine.py"),
                                    environment: ["TEST": "value"],
                                    stateDirectory: URL(fileURLWithPath: "/tmp/state folder"),
                                    codexDirectory: URL(fileURLWithPath: "/tmp/codex"))
        precondition(process.process.arguments == ["-s", "/tmp/engine.py", "--state-dir", "/tmp/state folder", "--codex-dir", "/tmp/codex", "--usage"])
        precondition(process.process.environment?["TEST"] == "value")
        precondition(process.process.standardInput as? Pipe === process.input)
        precondition(process.process.standardOutput as? Pipe === process.output)
        print("engine process: PASS")
    }
}
