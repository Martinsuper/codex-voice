import Foundation
import Network
import AppKit

/// LAN service for the Piko Passport firmware: answers its UDP discovery
/// broadcast on 19389, accepts one authenticated WebSocket device on 19388,
/// pushes reminder state, announces alerts through server-side TTS and routes
/// device button actions to the reminder engine. Mutable state lives on
/// `queue`; dictation, UI and engine callbacks hop out.
enum PikoAnnounceError: Error { case unavailable }

final class PikoLink: NSObject, AccessoryCommandSink {
    var voiceSink: PikoVoiceSink?
    var onEnter: () -> Bool = { false }
    var onStatus: ([String: Any]) -> Void = { _ in }
    let sendAction: ([String: Any]) -> Void
    var dictationBusy: () -> Bool = { false }
    var speechSynthesizer: (_ text: String, _ completion: @escaping (Result<Data, Error>) -> Void) -> Void = { _, completion in
        completion(.failure(PikoAnnounceError.unavailable))
    }

    private let queue = DispatchQueue(label: "codex-voice.piko-link")
    private var wsPort: UInt16
    private var discoveryPort: UInt16
    private var credentialStore: PikoCredentialStore?
    private var pairing = PikoPairingState()
    private var enabled = false
    private var running = false
    private var wsListener: NWListener?
    private var udpListener: NWListener?
    private var deviceConnection: NWConnection?
    private var authenticated = false
    private var lastReceived = Date.distantPast
    private var helloTimeout: DispatchWorkItem?
    private var tickTimer: DispatchSourceTimer?
    private var voiceActive = false
    private var lastVoiceID = ""
    private var deviceID = ""
    private var lastAudio = Date.distantPast
    private var battery = -1
    private var firmware = ""
    private var statusError = ""
    private var boundWSPort: UInt16 = 0
    // Reminder state push and announce playback.
    private let epoch = PassportProtocol.makeEpoch()
    private var snapshot: [String: Any] = [:]
    private var codexForeground = false

    func setCodexForeground(_ value: Bool) {
        queue.async { [weak self] in
            guard let self, self.codexForeground != value else { return }
            self.codexForeground = value
            self.sendStateNow()
        }
    }
    private var lastState = Date.distantPast
    private var announce: (id: String, pcm: Data, offset: Int, consumed: Int, started: Bool, ended: Bool, at: Date)?
    private var synthesis: (id: String, generation: UUID, at: Date)?
    // Device button actions mirror the BLE link: one outstanding action with a
    // bounded wait, deduplicated results and engine reconcile on every snapshot.
    private var pending: [String: (String, String, Int, Date)] = [:]
    private var completed: [String: [String: Any]] = [:]

    init(wsPort: UInt16 = PassportPiko.wsPort, discoveryPort: UInt16 = PassportPiko.discoveryPort,
         credentialStore: PikoCredentialStore? = nil, paired: (id: String, tokenHash: String)? = nil,
         sendAction: @escaping ([String: Any]) -> Void = { _ in }) {
        self.wsPort = wsPort
        self.discoveryPort = discoveryPort
        self.credentialStore = credentialStore
        self.sendAction = sendAction
        if let paired { pairing.pairedID = paired.id; pairing.pairedTokenHash = paired.tokenHash }
        super.init()
    }

    func update(_ value: [String: Any]) {
        let wanted = (value["passport"] as? [String: Any])?["enabled"] as? Bool == true
        queue.async { [weak self] in
            guard let self else { return }
            self.snapshot = value
            self.reconcileActions()
            guard wanted != self.enabled else { return }
            self.enabled = wanted
            wanted ? self.start() : self.stop()
        }
    }

    func sendVoice(_ frame: [String: Any]) {
        queue.async { [weak self] in
            guard let self, self.authenticated, let connection = self.deviceConnection else { return }
            self.send(frame: frame, on: connection)
        }
    }

    /// Engine playback request; transport "piko" synthesizes the phrase and
    /// streams it to the device with the announce credit protocol.
    func command(_ command: [String: Any]) {
        queue.async { [weak self] in
            guard let self else { return }
            let id = command["id"] as? String ?? ""
            guard self.authenticated, let connection = self.deviceConnection else {
                self.feedbackAudio(id: id, phase: "failed")
                return
            }
            let op = command["op"] as? String ?? ""
            if op == "stop" {
                if self.synthesis?.id == id { self.synthesis = nil }
                if let active = self.announce, active.id == id {
                    self.announce = nil
                    self.send(frame: PassportPiko.announceCancel(id: id), on: connection)
                }
                return
            }
            guard op == "play", self.announce == nil, self.synthesis == nil, !self.dictationBusy() else {
                self.feedbackAudio(id: id, phase: "failed")
                return
            }
            let phrase = command["phrase"] as? String ?? "test"
            let alertId = command["alertId"] as? String ?? ""
            let text = PassportAnnouncement.text(
                for: phrase, alertId: alertId,
                alerts: self.snapshot["alerts"] as? [[String: Any]] ?? [])
            let generation = UUID()
            self.synthesis = (id, generation, Date())
            self.speechSynthesizer(text) { [weak self] result in
                self?.queue.async {
                    guard let self else { return }
                    guard self.synthesis?.generation == generation else { return }
                    self.synthesis = nil
                    guard self.authenticated, let connection = self.deviceConnection,
                          self.announce == nil, !self.dictationBusy(), case .success(let pcm) = result,
                          pcm.count > 0, pcm.count % 2 == 0, pcm.count <= PassportPiko.maxAudioBytes else {
                        self.feedbackAudio(id: id, phase: "failed")
                        return
                    }
                    self.announce = (id, pcm, 0, 0, false, false, Date())
                    self.send(frame: PassportPiko.announce(id: id, bytes: pcm.count, text: text), on: connection)
                    self.pumpAnnounce(on: connection)
                }
            }
        }
    }

    /// Manual approval for the portal flow where the user types host and code
    /// into the device's setup page; device-initiated requests self-approve.
    func beginPairing() {
        queue.async { [weak self] in
            guard let self else { return }
            let code = self.pairing.beginPairing(now: Date())
            self.emitStatus(code == nil ? "已有配对的工牌，请先解绑" : nil)
        }
    }

    func forget() {
        queue.async { [weak self] in
            guard let self else { return }
            self.pairing = PikoPairingState()
            self.credentialStore?.save(nil)
            self.deviceConnection?.cancel()
            self.emitStatus()
        }
    }

    func stop() {
        queue.async { [weak self] in
            guard let self else { return }
            self.enabled = false
            self.teardown()
            self.emitStatus()
        }
    }

    private func start() {
        guard !running else { return }
        running = true
        statusError = ""
        if let credentialStore, pairing.pairedID.isEmpty, let loaded = credentialStore.load() {
            pairing.pairedID = loaded.id
            pairing.pairedTokenHash = loaded.tokenHash
        }
        startWebSocketListener()
        startDiscoveryListener()
        let timer = DispatchSource.makeTimerSource(queue: queue)
        timer.schedule(deadline: .now() + 1, repeating: 1)
        timer.setEventHandler { [weak self] in self?.tick() }
        timer.resume()
        tickTimer = timer
        emitStatus()
    }

    private func teardown() {
        running = false
        wsListener?.cancel(); wsListener = nil
        udpListener?.cancel(); udpListener = nil
        tickTimer?.cancel(); tickTimer = nil
        deviceConnection?.cancel(); deviceConnection = nil
        authenticated = false
        voiceActive = false
        if let active = synthesis {
            synthesis = nil
            feedbackAudio(id: active.id, phase: "failed")
        }
        if let active = announce {
            announce = nil
            feedbackAudio(id: active.id, phase: "failed")
        }
        boundWSPort = 0
        helloTimeout?.cancel()
    }

    private func startWebSocketListener() {
        let options = NWProtocolWebSocket.Options()
        options.autoReplyPing = true
        // A bare NWParameters() carries no transport and fails to listen;
        // the WebSocket stack rides on plain TCP for ws://.
        let parameters = NWParameters.tcp
        parameters.defaultProtocolStack.applicationProtocols.insert(options, at: 0)
        guard let port = NWEndpoint.Port(rawValue: wsPort), let listener = try? NWListener(using: parameters, on: port) else {
            statusError = "无法监听工牌端口 \(wsPort)，可能被其他程序占用"
            return
        }
        listener.newConnectionHandler = { [weak self] connection in
            self?.queue.async { self?.accept(connection) }
        }
        listener.stateUpdateHandler = { [weak self, weak listener] state in
            guard let self else { return }
            switch state {
            case .ready:
                if let port = listener?.port?.rawValue {
                    self.queue.async { self.boundWSPort = port; self.emitStatus() }
                }
            case .failed:
                self.queue.async { self.emitStatus("工牌服务异常，正在重试") }
            default: break
            }
        }
        listener.start(queue: queue)
        wsListener = listener
    }

    private func startDiscoveryListener() {
        guard let port = NWEndpoint.Port(rawValue: discoveryPort), let listener = try? NWListener(using: .udp, on: port) else {
            statusError = "无法监听工牌发现端口 \(discoveryPort)"
            return
        }
        listener.newConnectionHandler = { [weak self] connection in
            self?.queue.async { self?.answerDiscovery(connection) }
        }
        listener.start(queue: queue)
        udpListener = listener
    }

    private func answerDiscovery(_ connection: NWConnection) {
        connection.start(queue: queue)
        connection.receiveMessage { [weak self] data, _, _, error in
            self?.queue.async {
                guard let self, error == nil, let data, data.count <= 512,
                      let request = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any],
                      let reply = self.pairing.discoveryReply(request, wsPort: self.wsPort, now: Date()),
                      let encoded = try? JSONSerialization.data(withJSONObject: reply) else {
                    connection.cancel(); return
                }
                connection.send(content: encoded, completion: .contentProcessed { _ in connection.cancel() })
            }
        }
    }

    private func accept(_ connection: NWConnection) {
        guard deviceConnection == nil else { connection.cancel(); return }
        deviceConnection = connection
        authenticated = false
        voiceActive = false
        connection.stateUpdateHandler = { [weak self] state in
            self?.queue.async {
                guard let self else { return }
                switch state {
                case .ready: self.scheduleHelloDeadline()
                case .failed, .cancelled: self.sessionClosed(connection)
                default: break
                }
            }
        }
        connection.start(queue: queue)
        receiveNext(connection)
    }

    private func scheduleHelloDeadline() {
        helloTimeout?.cancel()
        let work = DispatchWorkItem { [weak self] in
            guard let self, !self.authenticated, self.deviceConnection != nil else { return }
            self.close(error: "设备认证超时")
        }
        helloTimeout = work
        queue.asyncAfter(deadline: .now() + 10, execute: work)
    }

    private func sessionClosed(_ connection: NWConnection) {
        guard deviceConnection === connection else { return }
        deviceConnection = nil
        helloTimeout?.cancel()
        if authenticated || voiceActive {
            authenticated = false
            let active = voiceActive
            voiceActive = false
            if active {
                let id = lastVoiceID
                DispatchQueue.main.async { [weak self] in self?.voiceSink?.fail(id, "工牌已断开，请重试") }
            }
        }
        if let active = synthesis {
            synthesis = nil
            feedbackAudio(id: active.id, phase: "failed")
        }
        if let active = announce {
            announce = nil
            feedbackAudio(id: active.id, phase: "failed")
        }
        emitStatus()
    }

    private func receiveNext(_ connection: NWConnection) {
        connection.receiveMessage { [weak self] data, context, _, error in
            self?.queue.async { self?.handleMessage(connection, data: data, context: context, error: error) }
        }
    }

    private func handleMessage(_ connection: NWConnection, data: Data?, context: NWConnection.ContentContext?, error: NWError?) {
        guard deviceConnection === connection else { return }
        if error != nil { connection.cancel(); return }
        lastReceived = Date()
        if let metadata = context?.protocolMetadata(definition: NWProtocolWebSocket.definition) as? NWProtocolWebSocket.Metadata {
            switch metadata.opcode {
            case .text:
                guard let data, data.count <= PassportPiko.maxMessageBytes else { close(error: "设备消息过大"); return }
                guard let frame = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any] else { close(error: "设备消息格式错误"); return }
                handleFrame(frame, on: connection)
            case .binary:
                if let data { handleAudio(data) }
            case .close:
                connection.cancel(); return
            default: break
            }
        }
        if deviceConnection === connection { receiveNext(connection) }
    }

    private func handleFrame(_ frame: [String: Any], on connection: NWConnection) {
        guard frame["v"] as? Int == 1 else { close(error: "设备协议版本不支持"); return }
        let type = frame["type"] as? String ?? ""
        if !authenticated {
            guard type == "hello" else { close(error: "等待设备认证"); return }
            if pairing.pairedID.isEmpty, frame["disconnectRequested"] as? Bool == true {
                send(frame: PassportPiko.unpaired(), on: connection)
                connection.cancel()
                return
            }
            switch pairing.validateHello(frame, now: Date()) {
            case .failure(let reason): close(error: reason.localizedDescription)
            case .success(let id):
                deviceID = id
                var token: String?
                if pairing.pairedID.isEmpty {
                    token = PassportPiko.randomHex(32)
                    pairing.pairedID = id
                    pairing.pairedTokenHash = PassportPiko.tokenHash(token ?? "")
                    credentialStore?.save((id, pairing.pairedTokenHash))
                    pairing.pairing = nil; pairing.approved = nil; pairing.pending = nil
                }
                authenticated = true
                helloTimeout?.cancel()
                lastState = Date.distantPast
                send(frame: PassportPiko.welcome(token: token), on: connection)
                emitStatus()
            }
            return
        }
        switch type {
        case "key_enter":
            DispatchQueue.main.async { [weak self, weak connection] in
                guard let self, let connection else { return }
                let ok = self.onEnter()
                self.queue.async {
                    guard self.authenticated, self.deviceConnection === connection else { return }
                    self.send(frame: ["v": 1, "type": "key_result", "ok": ok,
                                      "message": ok ? "已发送回车" : "输入框已变化或没有可提交的文字"], on: connection)
                }
            }
        case "heartbeat":
            let newBattery = frame["battery"] as? Int ?? -1
            let newFirmware = String((frame["firmware"] as? String ?? "").prefix(40))
            if newBattery != battery || newFirmware != firmware {
                battery = newBattery
                firmware = newFirmware
                emitStatus()
            }
        case "state":
            // State only flows outward; a device echoing it back is unsupported.
            break
        case "voice_start":
            guard let id = frame["id"] as? String, PassportPiko.validID(id) else { return }
            guard frame["sampleRate"] as? Int == 16000, frame["channels"] as? Int == 1,
                  frame["format"] as? String == "pcm_s16le" else {
                send(frame: PassportPiko.voiceError(id, "仅支持 16kHz 单声道语音"), on: connection)
                return
            }
            voiceActive = true
            lastVoiceID = id
            lastAudio = Date()
            DispatchQueue.main.async { [weak self] in self?.voiceSink?.start(id, 16000, 1, "pcm_s16le") }
        case "voice_end":
            guard voiceActive, let id = frame["id"] as? String, id == lastVoiceID else { return }
            voiceActive = false
            DispatchQueue.main.async { [weak self] in self?.voiceSink?.end(id) }
        case "voice_cancel":
            guard voiceActive else { return }
            voiceActive = false
            DispatchQueue.main.async { [weak self] in self?.voiceSink?.cancel(self?.lastVoiceID ?? "") }
        case "unpair":
            pairing = PikoPairingState()
            credentialStore?.save(nil)
            send(frame: PassportPiko.unpaired(), on: connection)
            connection.cancel()
            emitStatus()
        case "announce_credit":
            guard let announce, frame["id"] as? String == announce.id,
                  let count = frame["count"] as? Int,
                  count >= announce.consumed, count <= (announce.offset + 2047) / 2048 else { return }
            self.announce?.consumed = count
            if !announce.started {
                self.announce?.started = true
                feedbackAudio(id: announce.id, phase: "started")
            }
            pumpAnnounce(on: connection)
        case "announce_played":
            guard let announce, frame["id"] as? String == announce.id else { return }
            self.announce = nil
            feedbackAudio(id: announce.id, phase: "done")
        case "announce_error":
            guard let announce, frame["id"] as? String == announce.id else { return }
            self.announce = nil
            feedbackAudio(id: announce.id, phase: "failed")
        case "action":
            receivedAction(frame, on: connection)
        default: break
        }
    }

    private func handleAudio(_ data: Data) {
        guard authenticated, voiceActive else { return }
        lastAudio = Date()
        DispatchQueue.main.async { [weak self] in self?.voiceSink?.audio(data) }
    }

    private func tick() {
        let now = Date()
        pairing.expire(now)
        if authenticated, now.timeIntervalSince(lastReceived) > 30 { close(error: "设备心跳超时"); return }
        if voiceActive, now.timeIntervalSince(lastAudio) > 15 {
            voiceActive = false
            let id = lastVoiceID
            DispatchQueue.main.async { [weak self] in self?.voiceSink?.fail(id, "音频上传中断，请重试") }
        }
        if authenticated, let connection = deviceConnection, now.timeIntervalSince(lastState) >= 2,
           let state = try? JSONSerialization.data(withJSONObject: PassportProtocol.state(snapshot, epoch: epoch, codexForeground: codexForeground)),
           state.count < PassportPiko.maxMessageBytes {
            let metadata = NWProtocolWebSocket.Metadata(opcode: .text)
            let context = NWConnection.ContentContext(identifier: "piko-json", metadata: [metadata])
            connection.send(content: state, contentContext: context, isComplete: true, completion: .contentProcessed { _ in })
            lastState = now
        }
        if let active = synthesis, now.timeIntervalSince(active.at) > 30 {
            synthesis = nil
            feedbackAudio(id: active.id, phase: "failed")
        }
        if let active = announce, now.timeIntervalSince(active.at) > 60 {
            announce = nil
            if let connection = deviceConnection {
                send(frame: PassportPiko.announceCancel(id: active.id), on: connection)
            }
            feedbackAudio(id: active.id, phase: "failed")
        }
    }

    /// At most four unacknowledged 2048-byte blocks stay in flight, mirroring
    /// the firmware's playback queue depth.
    private func pumpAnnounce(on connection: NWConnection) {
        guard var active = announce else { return }
        while active.offset < active.pcm.count, (active.offset - active.consumed * 2048) < 4 * 2048 {
            let end = min(active.offset + 2048, active.pcm.count)
            let chunk = active.pcm.subdata(in: active.offset..<end)
            send(binary: chunk, on: connection)
            active.offset = end
        }
        if active.offset == active.pcm.count && !active.ended {
            send(frame: ["v": 1, "type": "announce_end", "id": active.id, "bytes": active.pcm.count], on: connection)
            active.ended = true
        }
        announce = active
    }

    private func receivedAction(_ frame: [String: Any], on connection: NWConnection) {
        guard let id = frame["id"] as? String, id.count == 16,
              id.utf8.allSatisfy({ (48...57).contains($0) || (97...102).contains($0) }),
              Date().timeIntervalSince1970 - (snapshot["at"] as? Double ?? 0) < 8,
              let action = frame["action"] as? String else { return }
        if let result = completed[id] { send(frame: result, on: connection); return }
        if pending[id] != nil { return }
        let alerts = snapshot["alerts"] as? [[String: Any]] ?? []
        let token = frame["alertId"] as? String ?? ""
        let alert = alerts.first { PassportProtocol.token($0["id"] as? String ?? "") == token }
        var command: [String: Any] = ["action": action]
        if ["ack", "snooze", "replay"].contains(action) {
            guard let original = alert?["id"] as? String else {
                finishAction(id, ok: false, message: "提醒已更新"); sendStateNow(); return
            }
            if action == "ack", let thread = alert?["thread"] as? String,
               UUID(uuidString: thread) != nil, let url = URL(string: "codex://threads/" + thread) {
                DispatchQueue.main.async {
                    NSWorkspace.shared.open(url)
                }
            }
            command["id"] = original
            if action == "snooze" { command["seconds"] = 300 }
        } else if action == "pause" { command["minutes"] = 15 }
        else { finishAction(id, ok: false, message: "不支持此操作"); return }
        pending[id] = (action, alert?["id"] as? String ?? "", alert?["count"] as? Int ?? 0, Date().addingTimeInterval(6))
        DispatchQueue.main.async { [weak self] in self?.sendAction(command) }
    }

    private func reconcileActions() {
        let alerts = snapshot["alerts"] as? [[String: Any]] ?? []
        for (id, value) in Array(pending) {
            let alert = alerts.first { $0["id"] as? String == value.1 }
            let ok = value.0 == "ack" ? alert == nil :
                value.0 == "snooze" ? alert?["state"] as? String == "snoozed" :
                value.0 == "pause" ? (snapshot["mutedUntil"] as? Double ?? 0) > Date().timeIntervalSince1970 :
                (alert?["count"] as? Int ?? 0) > value.2 || snapshot["speakingId"] as? String == value.1
            if ok { finishAction(id, ok: true, message: value.0 == "ack" ? "已接手" : "已同步") }
        }
        for (id, value) in Array(pending) where value.3 < Date() {
            finishAction(id, ok: false, message: "尚未同步，请重试")
        }
    }

    private func finishAction(_ id: String, ok: Bool, message: String) {
        pending.removeValue(forKey: id)
        let result: [String: Any] = ["v": 1, "type": "action_result", "id": id, "ok": ok, "message": message]
        if completed.count > 64 { completed.removeAll() }
        completed[id] = result
        if let connection = deviceConnection { send(frame: result, on: connection) }
    }

    private func sendStateNow() {
        guard authenticated, let connection = deviceConnection,
              let encoded = try? JSONSerialization.data(withJSONObject: PassportProtocol.state(snapshot, epoch: epoch, codexForeground: codexForeground)),
              encoded.count < PassportPiko.maxMessageBytes else { return }
        send(frame: PassportProtocol.state(snapshot, epoch: epoch, codexForeground: codexForeground), on: connection)
        lastState = Date()
    }

    private func feedbackAudio(id: String, phase: String) {
        DispatchQueue.main.async { [weak self] in
            self?.sendAction(["action": "passport_feedback", "event": ["kind": "audio", "id": id, "phase": phase]])
        }
    }

    private func send(frame: [String: Any], on connection: NWConnection) {
        guard let data = try? JSONSerialization.data(withJSONObject: frame) else { return }
        let metadata = NWProtocolWebSocket.Metadata(opcode: .text)
        let context = NWConnection.ContentContext(identifier: "piko-json", metadata: [metadata])
        connection.send(content: data, contentContext: context, isComplete: true, completion: .contentProcessed { _ in })
    }

    private func send(binary data: Data, on connection: NWConnection) {
        let metadata = NWProtocolWebSocket.Metadata(opcode: .binary)
        let context = NWConnection.ContentContext(identifier: "piko-pcm", metadata: [metadata])
        connection.send(content: data, contentContext: context, isComplete: true, completion: .contentProcessed { _ in })
    }

    private func close(error message: String) {
        statusError = message
        deviceConnection?.cancel()
        // sessionClosed runs from the state handler and reports the final status.
    }

    private func emitStatus(_ message: String? = nil) {
        if let message { statusError = message }
        let port = boundWSPort > 0 ? boundWSPort : wsPort
        let state: [String: Any] = ["connected": authenticated, "paired": !pairing.pairedID.isEmpty,
                                    "pairingCode": (pairing.pairing?.code ?? ""), "pendingDevice": (pairing.pending?.id ?? ""),
                                    "battery": battery, "firmware": firmware, "error": statusError, "port": Int(port)]
        DispatchQueue.main.async { [weak self] in
            guard let self else { return }
            self.onStatus(state)
            self.sendAction(["action": "passport_feedback", "event": ["kind": "piko",
                "connected": authenticated, "firmware": firmware]])
        }
    }
}
