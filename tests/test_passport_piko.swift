import Foundation

@main struct PikoProtocolTests {
    static func main() throws {
        let now = Date(timeIntervalSince1970: 1_000_000)
        let nonce = String(repeating: "a", count: 32)

        // Device-initiated pairing self-approves and binds identity and nonce.
        var state = PikoPairingState()
        let request: [String: Any] = ["v": 1, "type": "piko-discover", "deviceId": "passport-one", "nonce": nonce, "pairRequested": true]
        let reply = state.discoveryReply(request, wsPort: 19388, now: now)!
        let code = reply["pairingCode"] as! String
        precondition(code.count == 8 && PassportPiko.isHex(code))
        precondition(reply["nonce"] as? String == nonce)
        precondition(reply["port"] as? Int == 19388)
        let hello: [String: Any] = ["v": 1, "type": "hello", "deviceId": "passport-one", "discoveryNonce": nonce, "pairingCode": code]
        if case .success(let id) = state.validateHello(hello, now: now) { precondition(id == "passport-one") }
        else { precondition(false, "matching pairing must authenticate") }
        var other = request
        other["deviceId"] = "passport-two"; other["nonce"] = String(repeating: "b", count: 32)
        precondition(state.discoveryReply(other, wsPort: 19388, now: now) == nil)
        var stale = hello
        stale["discoveryNonce"] = String(repeating: "c", count: 32)
        if case .failure = state.validateHello(stale, now: now) {} else { precondition(false, "nonce must bind") }
        state.pairing = (state.pairing!.code, now.addingTimeInterval(-PassportPiko.pairingTTL - 1))
        precondition(state.discoveryReply(request, wsPort: 19388, now: now) != nil)
        if case .failure = state.validateHello(hello, now: now) {} else { precondition(false, "expired code rejected") }

        // A paired device needs its token; discovery never re-issues a code.
        let token = String(repeating: "ab", count: 32)
        state.pairedID = "passport-one"
        state.pairedTokenHash = PassportPiko.tokenHash(token)
        state.pairing = nil; state.approved = nil
        let pairedReply = state.discoveryReply(request, wsPort: 19388, now: now)!
        precondition(pairedReply["pairingCode"] == nil)
        precondition(state.discoveryReply(other, wsPort: 19388, now: now) == nil)
        let tokenHello: [String: Any] = ["v": 1, "type": "hello", "deviceId": "passport-one", "token": token]
        if case .success = state.validateHello(tokenHello, now: now) {} else { precondition(false, "token must authenticate") }
        if case .failure = state.validateHello(["v": 1, "type": "hello", "deviceId": "passport-one", "disconnectRequested": true], now: now) {}
        else { precondition(false, "disconnect intent cannot bypass token auth") }
        var wrong = tokenHello; wrong["deviceId"] = "passport-two"
        if case .failure = state.validateHello(wrong, now: now) {} else { precondition(false) }
        var v2 = tokenHello; v2["v"] = 2
        if case .failure = state.validateHello(v2, now: now) {} else { precondition(false) }
        var short = tokenHello; short["token"] = "a"
        if case .failure = state.validateHello(short, now: now) {} else { precondition(false) }

        // Malformed discovery never leaves a pending request behind.
        var pendingState = PikoPairingState()
        let invalid: [[String: Any]] = [
            [:],
            ["v": 2, "type": "piko-discover", "deviceId": "passport-one", "nonce": nonce],
            ["v": 1, "type": "piko-discover", "deviceId": "../bad", "nonce": nonce],
            ["v": 1, "type": "piko-discover", "deviceId": "passport-one", "nonce": "short"],
        ]
        for request in invalid {
            precondition(pendingState.discoveryReply(request, wsPort: 19388, now: now) == nil)
            precondition(pendingState.pending == nil)
        }
        // The portal flow may need a code before the device is on the LAN: an
        // unbound code is issued without a pending request and any hello nonce
        // may redeem it within the pairing TTL.
        let portalCode = pendingState.beginPairing(now: now)!
        precondition(portalCode.count == 8)
        if case .success = pendingState.validateHello(["v": 1, "type": "hello", "deviceId": "passport-one",
                                                       "discoveryNonce": String(repeating: "d", count: 32),
                                                       "pairingCode": portalCode], now: now) {}
        else { precondition(false, "unbound code must accept any nonce") }
        // Manual approval needs a live discovery request and expires with it.
        let announce: [String: Any] = ["v": 1, "type": "piko-discover", "deviceId": "passport-one", "nonce": nonce]
        precondition(pendingState.discoveryReply(announce, wsPort: 19388, now: now) == nil)
        precondition(pendingState.pending?.id == "passport-one")
        let manualCode = pendingState.beginPairing(now: now.addingTimeInterval(10))!
        precondition(manualCode != portalCode, "a fresh approval replaces the earlier code")
        precondition(pendingState.discoveryReply(announce, wsPort: 19388, now: now.addingTimeInterval(10))?["pairingCode"] as? String == manualCode)
        if case .success = pendingState.validateHello(["v": 1, "type": "hello", "deviceId": "passport-one",
                                                       "discoveryNonce": nonce, "pairingCode": manualCode], now: now.addingTimeInterval(10)) {}
        else { precondition(false, "manual pairing must authenticate") }
        pendingState.pairing = (manualCode, now.addingTimeInterval(10))
        if case .failure = pendingState.validateHello(["v": 1, "type": "hello", "deviceId": "passport-one",
                                                       "discoveryNonce": nonce, "pairingCode": manualCode],
                                                      now: now.addingTimeInterval(10 + PassportPiko.pairingTTL + 1)) {}
        else { precondition(false, "expired code rejected") }
        let refreshed = pendingState.beginPairing(now: now.addingTimeInterval(10 + PassportPiko.pairingTTL + 1))!
        precondition(refreshed.count == 8)
        // A fresh announcement re-arms the pending request after expiry.
        precondition(pendingState.discoveryReply(announce, wsPort: 19388, now: now.addingTimeInterval(10 + PassportPiko.pairingTTL + 1)) == nil)
        precondition(pendingState.pending?.id == "passport-one")

        // Frame shapes and caps.
        precondition(PassportPiko.welcome(token: String(repeating: "f", count: 64))["token"] != nil)
        precondition(PassportPiko.welcome(token: nil)["token"] == nil)
        precondition((PassportPiko.welcome(token: nil)["capabilities"] as? [String]) == ["voice-long-upload-v1"])
        let status = PassportPiko.voiceStatus("t-voice-1", "done", message: String(repeating: "长", count: 300))
        precondition((status["message"] as! String).count == 240)
        precondition((PassportPiko.voiceError("t", "报错")["message"] as! String) == "报错")
        precondition((PassportPiko.voiceTranscript("t", String(repeating: "字", count: 2000))["text"] as! String).count == 1200)

        // PCM decoding and the local utterance floor.
        let samples: [Int16] = [0, 100, -200, 32767, -32768]
        var bytes = Data()
        for sample in samples {
            var value = UInt16(bitPattern: sample).littleEndian
            withUnsafeBytes(of: &value) { bytes.append(contentsOf: $0) }
        }
        precondition(PassportPiko.pcmSamples(bytes)! == samples)
        precondition(PassportPiko.pcmSamples(Data([1, 2, 3])) == nil)
        precondition(!PassportPiko.validateUtterance([Int16](repeating: 0, count: 8000)), "silence rejected")
        precondition(PassportPiko.validateUtterance([Int16](repeating: 200, count: PassportPiko.minUtteranceSamples)))
        precondition(!PassportPiko.validateUtterance([Int16](repeating: 200, count: PassportPiko.minUtteranceSamples - 1)))

        // Credential store round trip.
        let directory = NSTemporaryDirectory() + "piko-store-test-" + UUID().uuidString
        try FileManager.default.createDirectory(atPath: directory, withIntermediateDirectories: true)
        let store = PikoCredentialStore(directory: directory)
        precondition(store.load() == nil)
        store.save(("passport-one", PassportPiko.tokenHash(token)))
        precondition(store.load()?.id == "passport-one")
        let attributes = try FileManager.default.attributesOfItem(atPath: store.path)
        precondition((attributes[.posixPermissions] as? NSNumber) == 0o600)
        store.save(nil)
        precondition(store.load() == nil)
        try? FileManager.default.removeItem(atPath: directory)
        print("Piko protocol pairing, frames and PCM tests: PASS")
    }
}
