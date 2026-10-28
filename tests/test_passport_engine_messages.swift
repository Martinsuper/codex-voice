import Foundation

@main
struct EngineMessagesTests {
    static func main() {
        var decoder = EngineMessages()
        let bytes = Data("{\"text\":\"你好\"}\ninvalid\n[]\n{\"error\":\"failed\"}\n".utf8)
        var messages: [[String: Any]] = []
        for byte in bytes { messages += decoder.append(Data([byte])) }
        precondition(messages.count == 2)
        precondition(messages[0]["text"] as? String == "你好")
        precondition(messages[1]["error"] as? String == "failed")
        if case .error("failed") = EngineMessage(messages[1]) {} else { preconditionFailure() }
        if case .accessoryCommand = EngineMessage(["passportCommand": [:], "error": "ignored"]) {} else { preconditionFailure() }
        if case .snapshot = EngineMessage(["alerts": [[String: Any]]()]) {} else { preconditionFailure() }
        if case .invalid = EngineMessage(messages[0]) {} else { preconditionFailure() }
        precondition(AccessoryTransport(command: ["transport": "piko"]) == .piko)
        precondition(AccessoryTransport(command: [:]) == .passport)
        precondition(decoder.append(Data("{\"partial\":true}".utf8)).isEmpty)
        decoder = EngineMessages()
        precondition(decoder.append(Data("\n{\"fresh\":true}\n".utf8)).count == 1)
        var bounded = EngineMessages(maximumLineBytes: 20)
        precondition(bounded.append(Data(String(repeating: "x", count: 20).utf8)).isEmpty)
        precondition(bounded.append(Data("x\n{\"ok\":true}\n".utf8)).count == 1)
        precondition(bounded.append(Data("{\"ok\":true}\n".utf8)).count == 1)
        print("engine messages: PASS")
    }
}
