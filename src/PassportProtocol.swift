import Foundation
import CryptoKit

enum PassportProtocol {
    static let uid = "codex-passport:ble"
    static func makeEpoch() -> String {
        String(UUID().uuidString.replacingOccurrences(of: "-", with: "").lowercased().prefix(16))
    }
    static func token(_ id: String) -> String {
        SHA256.hash(data: Data(id.utf8)).prefix(8).map { String(format: "%02x", $0) }.joined()
    }
    static func title(_ raw: String) -> String {
        String(String.UnicodeScalarView(raw.unicodeScalars.prefix(24).map { value in
            let n = value.value
            return (0x20...0xFF).contains(n) || (0x3400...0x9FFF).contains(n)
                || (0x3000...0x303F).contains(n) || (0xFF01...0xFF60).contains(n)
                || [0x2014, 0x2026].contains(n) ? value : UnicodeScalar(0x25A1)!
        }))
    }
    static func state(_ raw: [String: Any], epoch: String, codexForeground: Bool = false) -> [String: Any] {
        let all = raw["alerts"] as? [[String: Any]] ?? []
        let ranked = all.sorted {
            let rank: [String: Int] = ["approval": 0, "question": 1, "blocked": 2, "result": 3, "test": 4]
            let a = rank[$0["kind"] as? String ?? ""] ?? 5
            let b = rank[$1["kind"] as? String ?? ""] ?? 5
            return a == b ? ($0["createdAt"] as? Double ?? 0) < ($1["createdAt"] as? Double ?? 0) : a < b
        }
        let alerts: [[String: Any]] = ranked.prefix(8).compactMap { a in
            guard let id = a["id"] as? String else { return nil }
            return ["id": token(id), "title": title(a["title"] as? String ?? "当前任务"),
                    "kind": a["kind"] as? String ?? "result",
                    "snoozed": a["state"] as? String == "snoozed",
                    "verify": a["recoveryPending"] as? Bool ?? false]
        }
        let usage = raw["usage"] as? [String: Any] ?? [:]
        let accessory = raw["passport"] as? [String:Any] ?? [:]
        let monitor = raw["monitor"] as? [String: Any] ?? [:]
        let now = Date().timeIntervalSince1970
        let age = max(0, now - (usage["fetchedAt"] as? Double ?? 0))
        let fresh = usage["state"] as? String == "ready" && age < 180
        let windows = usage["windows"] as? [[String: Any]] ?? []
        let parsedQuotas: [[String: Any]] = fresh ? windows.prefix(2).compactMap { w in
            guard let remaining = w["remainingPercent"] as? Int, (0...100).contains(remaining) else { return nil }
            let reset = w["resetsAt"] as? Double ?? 0
            guard reset == 0 || reset > now else { return nil }
            let minutes = w["windowMinutes"] as? Int ?? 0
            return ["remaining":remaining,"minutes":min(525600,max(0,minutes)),
                    "reset":reset == 0 ? -1 : min(31536000,Int(reset-now))]
        } : []
        let quotas = !windows.isEmpty && windows.count <= 2 && parsedQuotas.count == windows.count ? parsedQuotas : []
        let remaining = quotas.compactMap { $0["remaining"] as? Int }.min() ?? -1
        return ["v": 1, "type": "state", "epoch": epoch, "codexForeground": codexForeground, "enabled": (raw["enabled"] as? Bool ?? true) && (accessory["voiceEnabled"] as? Bool ?? true),
                "petName":title(accessory["petName"] as? String ?? "Codex"),
                "muted": (raw["mutedUntil"] as? Double ?? 0) > Date().timeIntervalSince1970,
                "quiet": (raw["quietHours"] as? [String: Any])?["active"] as? Bool ?? false,
                "monitor": monitor["state"] as? String == "connected",
                "running": (raw["activeTasks"] as? [[String: Any]] ?? []).count,
                "usage": remaining, "usageAge": min(31536000,Int(age)), "quotas":quotas,
                "total": all.count, "alerts": alerts]
    }
}
