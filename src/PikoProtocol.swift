import Foundation
import CryptoKit
import Security

/// Wire protocol for the Piko Passport firmware (plain LAN WebSocket, JSON
/// frames capped at 4096 bytes, raw PCM s16le audio). Pairing and token
/// validation mirror the reference desktop implementation so the same flashed
/// device pairs with either host.
enum PassportPiko {
    static let wsPort: UInt16 = 19388
    static let discoveryPort: UInt16 = 19389
    static let pairingTTL: TimeInterval = 300
    static let discoveryTTL: TimeInterval = 30
    static let maxMessageBytes = 4096
    // "voice-long-upload-v1" removes the firmware's 12 s upload cap; this
    // bounds memory and the offline Paraformer latency instead.
    static let maxAudioBytes = 16000 * 2 * 60
    static let minUtteranceSamples = 3200
    static let capabilities = ["voice-long-upload-v1"]

    static func tokenHash(_ token: String) -> String {
        SHA256.hash(data: Data(token.utf8)).map { String(format: "%02x", $0) }.joined()
    }
    static func randomHex(_ bytes: Int) -> String {
        var data = [UInt8](repeating: 0, count: bytes)
        guard SecRandomCopyBytes(kSecRandomDefault, bytes, &data) == errSecSuccess else { return "" }
        return data.map { String(format: "%02x", $0) }.joined()
    }
    static func isHex(_ value: String) -> Bool {
        value.utf8.allSatisfy { (48...57).contains($0) || (65...70).contains($0) || (97...102).contains($0) }
    }
    static func validID(_ id: String) -> Bool {
        !id.isEmpty && id.count <= 64 && id.utf8.allSatisfy {
            (48...57).contains($0) || (65...90).contains($0) || (97...122).contains($0) || $0 == 45 || $0 == 95
        }
    }

    static func welcome(token: String?) -> [String: Any] {
        var frame: [String: Any] = ["v": 1, "type": "welcome", "capabilities": capabilities]
        if let token, !token.isEmpty { frame["token"] = token }
        return frame
    }
    static func unpaired() -> [String: Any] { ["v": 1, "type": "unpaired"] }
    static func voiceStatus(_ id: String, _ stage: String, message: String = "") -> [String: Any] {
        var frame: [String: Any] = ["v": 1, "type": "voice_status", "id": id, "stage": stage]
        if !message.isEmpty { frame["message"] = String(message.prefix(240)) }
        return frame
    }
    static func voiceError(_ id: String, _ message: String) -> [String: Any] {
        ["v": 1, "type": "voice_error", "id": id, "message": String(message.prefix(240))]
    }
    static func voiceTranscript(_ id: String, _ text: String) -> [String: Any] {
        ["v": 1, "type": "voice_transcript", "id": id, "text": String(text.prefix(1200))]
    }
    static func announce(id: String, bytes: Int, text: String) -> [String: Any] {
        var frame: [String: Any] = ["v": 1, "type": "announce", "id": id, "bytes": bytes]
        if !text.isEmpty { frame["text"] = String(text.prefix(1200)) }
        return frame
    }
    static func announceCancel(id: String) -> [String: Any] {
        ["v": 1, "type": "announce_cancel", "id": id]
    }

    static func pcmSamples(_ data: Data) -> [Int16]? {
        guard data.count % 2 == 0 else { return nil }
        var samples = [Int16]()
        samples.reserveCapacity(data.count / 2)
        data.withUnsafeBytes { buffer in
            for offset in stride(from: 0, to: data.count, by: 2) {
                samples.append(Int16(bitPattern: UInt16(buffer.loadUnaligned(fromByteOffset: offset, as: UInt16.self)).littleEndian))
            }
        }
        return samples
    }
    static func validateUtterance(_ samples: [Int16]) -> Bool {
        samples.count >= minUtteranceSamples && samples.contains { abs(Int($0)) > 180 }
    }
}

/// Handoff from the link to the dictation engine; always invoked on the main queue.
struct PikoVoiceSink {
    var start: (String, Int, Int, String) -> Void
    var audio: (Data) -> Void
    var end: (String) -> Void
    var cancel: (String) -> Void
    var fail: (String, String) -> Void
}

struct PikoPairingState {
    var pairedID = ""
    var pairedTokenHash = ""
    var approved: (id: String, nonce: String)?
    var pairing: (code: String, at: Date)?
    var pending: (id: String, nonce: String, at: Date)?

    enum AuthError: Error, LocalizedError {
        case version, identity, token, pairing, mismatch
        var errorDescription: String? {
            switch self {
            case .version: return "设备协议版本不支持"
            case .identity: return "设备 ID 无效"
            case .token: return "设备认证失败，请在工牌上重新配对"
            case .pairing: return "配对码错误或已过期"
            case .mismatch: return "设备与已确认的配对请求不一致"
            }
        }
    }

    mutating func expire(_ now: Date) {
        if let at = pairing?.at, now.timeIntervalSince(at) >= PassportPiko.pairingTTL { pairing = nil; approved = nil }
        if let at = pending?.at, now.timeIntervalSince(at) >= PassportPiko.discoveryTTL { pending = nil }
    }

    /// Manual approval for the portal flow where the user types host and code
    /// into the device's setup page. A live discovery request binds the code to
    /// that identity and nonce; without one the code is issued unbound and any
    /// hello nonce may redeem it, matching the reference desktop. Returns nil
    /// when this device is already paired.
    mutating func beginPairing(now: Date) -> String? {
        expire(now)
        guard pairedID.isEmpty else { return nil }
        if let pending, now.timeIntervalSince(pending.at) < PassportPiko.discoveryTTL {
            approved = (pending.id, pending.nonce)
        } else {
            approved = nil
        }
        let code = PassportPiko.randomHex(4)
        guard code.count == 8 else { return nil }
        pairing = (code, now)
        return code
    }

    /// An unpaired device only gets a pairing code after the exact discovery
    /// request was approved; `pairRequested` is the device's own connect
    /// action and approves itself, binding code, identity and nonce together.
    mutating func discoveryReply(_ request: [String: Any], wsPort: UInt16, now: Date) -> [String: Any]? {
        guard request["v"] as? Int == 1, request["type"] as? String == "piko-discover",
              let id = request["deviceId"] as? String, PassportPiko.validID(id),
              let nonce = request["nonce"] as? String, nonce.count == 32, PassportPiko.isHex(nonce) else { return nil }
        var reply: [String: Any] = ["v": 1, "type": "piko-service", "nonce": nonce, "port": Int(wsPort)]
        if !pairedID.isEmpty { return pairedID == id ? reply : nil }
        expire(now)
        if approved?.id == id, approved?.nonce == nonce {
            if var seen = pending { seen.at = now; pending = seen }
            guard let pairing, now.timeIntervalSince(pairing.at) < PassportPiko.pairingTTL else { return nil }
            reply["pairingCode"] = pairing.code
            return reply
        }
        if request["pairRequested"] as? Bool == true, approved == nil || approved?.id == id {
            approved = (id, nonce)
            pairing = (PassportPiko.randomHex(4), now)
            pending = (id, nonce, now)
            return discoveryReply(request, wsPort: wsPort, now: now)
        }
        if pending == nil || now.timeIntervalSince(pending!.at) >= PassportPiko.discoveryTTL
            || (pending?.id == id && pending?.nonce == nonce) {
            pending = (id, nonce, now)
        }
        return nil
    }

    mutating func validateHello(_ hello: [String: Any], now: Date) -> Result<String, AuthError> {
        guard hello["v"] as? Int == 1, hello["type"] as? String == "hello" else { return .failure(.version) }
        guard let id = hello["deviceId"] as? String, PassportPiko.validID(id) else { return .failure(.identity) }
        if !pairedID.isEmpty {
            guard let token = hello["token"] as? String, token.count == 64, PassportPiko.isHex(token),
                  pairedID == id, pairedTokenHash == PassportPiko.tokenHash(token) else { return .failure(.token) }
            return .success(id)
        }
        if let approved, approved.id != id || (hello["discoveryNonce"] as? String) != approved.nonce {
            return .failure(.mismatch)
        }
        guard let pairing, now.timeIntervalSince(pairing.at) < PassportPiko.pairingTTL,
              (hello["pairingCode"] as? String) == pairing.code else { return .failure(.pairing) }
        return .success(id)
    }
}

/// Persists the paired device's identity and token hash (never the token).
struct PikoCredentialStore {
    let path: String
    init(directory: String) { path = directory + "/piko-device.json" }
    func load() -> (id: String, tokenHash: String)? {
        guard let data = try? Data(contentsOf: URL(fileURLWithPath: path)),
              let object = try? JSONSerialization.jsonObject(with: data) as? [String: String],
              let id = object["id"], PassportPiko.validID(id),
              let hash = object["tokenHash"], hash.count == 64, PassportPiko.isHex(hash) else { return nil }
        return (id, hash)
    }
    func save(_ credential: (id: String, tokenHash: String)?) {
        let url = URL(fileURLWithPath: path)
        guard let credential else { try? FileManager.default.removeItem(at: url); return }
        guard let data = try? JSONSerialization.data(withJSONObject: ["id": credential.id, "tokenHash": credential.tokenHash], options: .sortedKeys) else { return }
        try? data.write(to: url, options: .atomic)
        try? FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: path)
    }
}
