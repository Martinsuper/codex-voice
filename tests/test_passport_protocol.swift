import Foundation

@main struct PassportProtocolTests {
    static func main() throws {
        for _ in 0..<100 {
            let epoch = PassportProtocol.makeEpoch()
            precondition(epoch.count == 16)
            precondition(epoch.utf8.allSatisfy { (48...57).contains($0) || (97...102).contains($0) })
        }
        let alerts: [[String: Any]] = (0..<12).map {
            ["id": "private-thread-\($0)", "kind": $0 == 11 ? "approval" : "result",
             "title": "测试中文任务 \($0) 😀", "createdAt": Double($0)]
        }
        let snapshot: [String: Any] = ["alerts": alerts, "enabled": true,
            "at": Date().timeIntervalSince1970, "monitor": ["state": "connected"],
            "usage": ["state": "ready", "remainingPercent": 42,"fetchedAt":Date().timeIntervalSince1970,
                "windows":[["id":"primary","remainingPercent":42,"windowMinutes":300,"resetsAt":Date().timeIntervalSince1970+3600],
                           ["id":"secondary","remainingPercent":81,"windowMinutes":10080,"resetsAt":Date().timeIntervalSince1970+86400]]],
            "account": ["email": "private@example.invalid"], "speech": ["voices": ["private voice data"]]]
        let state = PassportProtocol.state(snapshot, epoch: "0123456789abcdef")
        precondition(state["codexForeground"] as? Bool == false)
        let foreground = PassportProtocol.state(snapshot, epoch: "0123456789abcdef", codexForeground: true)
        precondition(foreground["codexForeground"] as? Bool == true)
        let visible = state["alerts"] as! [[String: Any]]
        precondition(visible.count == 8)
        precondition(visible[0]["kind"] as? String == "approval")
        precondition((visible[0]["id"] as! String).count == 16)
        precondition(state["total"] as? Int == 12)
        precondition(state["usage"] as? Int == 42)
        let encoded = try JSONSerialization.data(withJSONObject: state)
        let text = String(data: encoded, encoding: .utf8)!
        precondition(!text.contains("private-thread"))
        precondition(!text.contains("email"))
        precondition(!text.contains("voice data"))
        precondition(encoded.count < 4096)
        precondition(PassportProtocol.title(String(repeating: "中", count: 100)).count == 24)
        precondition(PassportProtocol.title("A😀B") == "A□B")
        precondition(PassportProtocol.title(String(repeating: "👩‍👩‍👧‍👦", count: 24)).utf8.count <= 96)
        let unknown = PassportProtocol.state(["usage": ["state": "stale", "remainingPercent": 90]], epoch: "0123456789abcdef")
        precondition(unknown["usage"] as? Int == -1)
        precondition((state["quotas"] as! [[String:Any]]).count == 2)
        let missing = PassportProtocol.state(["usage":["state":"ready","remainingPercent":99]],epoch:"0123456789abcdef")
        precondition(missing["usage"] as? Int == -1)
        let passed = PassportProtocol.state(["usage":["state":"ready","fetchedAt":Date().timeIntervalSince1970,"windows":[["remainingPercent":60,"resetsAt":Date().timeIntervalSince1970-1]]]],epoch:"0123456789abcdef")
        precondition(passed["usage"] as? Int == -1)
        let accessory = PassportProtocol.state(["enabled":true,"passport":["enabled":true,"voiceEnabled":false,"petName":"那个谁"]],epoch:"0123456789abcdef")
        precondition(accessory["enabled"] as? Bool == false)
        precondition(accessory["petName"] as? String == "那个谁")
        precondition(state["petName"] as? String == "Codex")
        print("Passport protocol, fresh quota windows and privacy tests: PASS")
    }
}
