import AppKit
import ApplicationServices
import Speech

final class PassportDictation: NSObject {
    var send: ([String: Any]) -> Void = { _ in }
    var busyChanged: (Bool) -> Void = { _ in }
    private(set) var activeID: String?
    private var target: PassportInputTarget?
    private var enterTarget: PassportInputTarget?
    private var generation = 0
    private var stream = PassportAudioStream()
    private var recording: PassportRecording?
    private var speech: AnyObject?
    private var preparation: Task<Void, Never>?
    private var captureRetry: Task<Void, Never>?
    private var captureDiagnosis = ""
    private var work: Task<Void, Never>?
    private var deadline: Timer?
    private var observer: NSObjectProtocol?
    private var completed: [String: [String: Any]] = [:]
    private var ended: (Int,Int)?
    private var attempting = false
    private var draftWindow: NSWindow?
    private var retained = ""
    private var retainedCount = 0
    private var retainedCopied = false
    private var setupWindow: NSWindow?
    private var setupNote: NSTextField?
    // Piko (Wi-Fi firmware) transport: raw PCM streams in while the key is held.
    var pikoSend: ([String: Any]) -> Void = { _ in }
    private var pcmData = Data()
    private var pikoEnded = false
    private var pikoCaptureError = ""

    override init() {
        super.init()
        observer = NSWorkspace.shared.notificationCenter.addObserver(forName: NSWorkspace.didActivateApplicationNotification, object: nil, queue: .main) { [weak self] _ in self?.generation += 1 }
    }
    private func reply(_ type: String, id: String, ok: Bool, message: String = "", retained: Bool = false) {
        var object: [String: Any] = ["v":1,"type":type,"id":id,"ok":ok,"message":message,"retained":retained]
        if type == "voice_ready", ok, let target { object["target"] = PassportProtocol.title(String(target.appName.prefix(10))) }
        if type == "voice_result" {
            if completed.count >= 32 { completed.removeAll() }
            completed[id] = object
        }
        send(object)
    }
    func receive(_ event: [String: Any]) {
        guard let id = event["id"] as? String, id.count == 16,
              id.utf8.allSatisfy({ (48...57).contains($0) || (97...102).contains($0) }),
              let op = event["op"] as? String else { return }
        if let result = completed[id] { send(result); return }
        if op == "begin" {
            if activeID == id { return }
            guard activeID == nil else { reply("voice_ready",id:id,ok:false,message:"上一段听写仍在处理"); return }
            begin(id); return
        }
        guard activeID == id else { return }
        if op == "cancel" { reply("voice_result",id:id,ok:false,message:"听写已取消"); reset(); return }
        if op == "failed" { fail("工牌音频传输失败，请重试"); return }
        if op == "end" {
            guard ended == nil, let count = event["frames"] as? Int, (0...1500).contains(count),
                  let samples = event["samples"] as? Int, samples == count*320 else { fail("音频不完整，请重试"); return }
            ended = (count,samples)
            // The final control event and audio notifications use separate characteristics.
            // Wait briefly for the final audio block; never transcribe a truncated turn.
            completeIfReady()
            DispatchQueue.main.asyncAfter(deadline:.now()+2) { [weak self] in
                guard let self, self.activeID == id, self.ended != nil, !self.attempting else { return }
                self.fail("音频未完整到达电脑，请重试")
            }
        }
    }
    private func begin(_ id: String) {
        guard AXIsProcessTrusted(), CGPreflightPostEventAccess() else {
            reply("voice_ready",id:id,ok:false,message:"请在电脑开启辅助功能权限"); return
        }
        guard retainedCopied || retainedCount < 50 else {
            reply("voice_ready",id:id,ok:false,message:"请先处理电脑中保留的文字"); return
        }
        guard let target = PassportInputTarget.capture(generation:generation) else {
            reply("voice_ready",id:id,ok:false,message:"请先点选电脑上的输入框"); return
        }
        self.target = target; activeID = id; recording = PassportRecording(id:id)
        stream = PassportAudioStream(); ended = nil; attempting = false; busyChanged(true)
        deadline = Timer.scheduledTimer(withTimeInterval:75,repeats:false) { [weak self] _ in self?.fail("听写超时，请重试") }
        preparation = Task { @MainActor [weak self] in
            do {
                let prepared = try await PassportRecognition.prepare()
                guard let self, self.activeID == id, !Task.isCancelled else { await prepared.cancel(); return }
                self.speech = prepared
                guard target.unchanged(generation:self.generation) else {
                    self.reply("voice_ready",id:id,ok:false,message:"输入框已切换，请重新按住"); self.reset(); return
                }
                self.reply("voice_ready",id:id,ok:true)
            } catch {
                guard let self, self.activeID == id else { return }
                self.reply("voice_ready",id:id,ok:false,message:(error as? LocalizedError)?.errorDescription ?? "本机语音识别暂不可用")
                self.setupNote?.stringValue = error.localizedDescription; self.reset()
            }
        }
    }
    func audio(_ data: Data) {
        guard activeID != nil, !attempting else { return }
        do {
            for block in try stream.feed(data) { try recording?.append(block) }
            completeIfReady()
        } catch { fail("音频顺序异常，请重试") }
    }
    private func completeIfReady() {
        guard !attempting, let (frames,samples) = ended, let recording, recording.frames == frames,
              stream.buffer.isEmpty, let id = activeID else { return }
        do {
            let pcm = try recording.finish(frames:frames,samples:samples)
            guard let speech = speech as? PassportRecognition else { throw PassportSpeechError.unavailable }
            attempting = true
            work = Task { @MainActor [weak self] in
                do {
                    let text = try await speech.transcribe(pcm)
                    guard let self, self.activeID == id, !Task.isCancelled else { return }
                    guard let target = self.target, target.unchanged(generation:self.generation) else {
                        self.retain(text, note:"输入框或光标已改变，原来的内容保持不变。")
                        self.reply("voice_result",id:id,ok:false,message:"输入框已改变，文字保留在电脑",retained:true); self.reset(); return
                    }
                    let inserted = await target.insert(text,generation:{self.generation},diagnostic:self.inputDiagnostic)
                    guard self.activeID == id else { return }
                    if inserted { self.reply("voice_result",id:id,ok:true,message:"已输入到电脑，尚未发送") }
                    else {
                        self.retain(text,note:"无法确认输入结果，请检查输入框。下面保留了本次文字，可手动复制；不会自动重复输入。")
                        self.reply("voice_result",id:id,ok:false,message:"请检查电脑，文字已保留",retained:true)
                    }
                    self.reset()
                } catch {
                    guard let self, self.activeID == id else { return }
                    self.fail((error as? LocalizedError)?.errorDescription ?? "没有识别成功，请靠近工牌重试")
                }
            }
        } catch { fail("没有听清，请靠近麦克风重试") }
    }
    private func fail(_ message: String) {
        guard let id = activeID else { return }
        reply("voice_result",id:id,ok:false,message:message); reset()
    }
    /// The device records before the desktop is ready: capture the focused
    /// field in parallel with the upload and only report failures at the end.
    var pikoSink: PikoVoiceSink {
        PikoVoiceSink(
            start: { [weak self] id, rate, channels, format in self?.pikoStart(id, rate, channels, format) },
            audio: { [weak self] data in self?.pikoAudio(data) },
            end: { [weak self] id in self?.pikoEnd(id) },
            cancel: { [weak self] id in self?.pikoCancel(id) },
            fail: { [weak self] id, message in self?.pikoFail(id, message) })
    }
    private func pikoStart(_ id: String, _ sampleRate: Int, _ channels: Int, _ format: String) {
        enterTarget = nil
        guard PassportPiko.validID(id) else { return }
        guard sampleRate == 16000, channels == 1, format == "pcm_s16le" else {
            pikoSend(PassportPiko.voiceError(id, "仅支持 16kHz 单声道语音")); return
        }
        if activeID != nil { pikoSend(PassportPiko.voiceError(id, "上一段听写仍在处理")); return }
        guard retainedCopied || retainedCount < 50 else {
            pikoSend(PassportPiko.voiceError(id, "请先处理电脑中保留的文字")); return
        }
        activeID = id
        pcmData = Data(); pikoEnded = false; pikoCaptureError = ""
        if !AXIsProcessTrusted() || !CGPreflightPostEventAccess() {
            pikoCaptureError = "请在电脑开启辅助功能权限"
        } else {
            let first = PassportInputTarget.captureDetailed(generation: generation)
            if let target = first.target {
                self.target = target
            } else {
                // 一次快照可能瞬时失败（焦点刚切换、Electron 重建 AX 元素、
                // AX 服务短暂不可用等）：录音期间持续重试，抓到为止。
                pikoCaptureError = "正在定位输入焦点…"
                captureDiagnosis = first.reason
                captureRetry = Task { @MainActor [weak self] in
                    while let self, self.activeID == id, self.target == nil, !Task.isCancelled {
                        try? await Task.sleep(nanoseconds: 300_000_000)
                        guard self.activeID == id, !Task.isCancelled else { return }
                        let attempt = PassportInputTarget.captureDetailed(generation: self.generation)
                        if let target = attempt.target {
                            self.target = target
                            self.pikoCaptureError = ""
                        } else {
                            self.captureDiagnosis = attempt.reason
                        }
                    }
                }
            }
        }
        busyChanged(true)
        deadline = Timer.scheduledTimer(withTimeInterval: 75, repeats: false) { [weak self] _ in
            guard let self, self.activeID == id else { return }
            self.pikoFail(id, "听写超时，请重试")
        }
        preparation = Task { @MainActor [weak self] in
            do {
                let prepared = try await PassportRecognition.prepare()
                guard let self, self.activeID == id, !Task.isCancelled else { await prepared.cancel(); return }
                self.speech = prepared
            } catch {
                guard let self, self.activeID == id, !Task.isCancelled else { return }
                self.pikoFail(id, (error as? LocalizedError)?.errorDescription ?? "本机语音识别暂不可用")
            }
        }
    }
    private func pikoAudio(_ data: Data) {
        guard activeID != nil, !attempting, !pikoEnded else { return }
        guard pcmData.count + data.count <= PassportPiko.maxAudioBytes else {
            if let id = activeID { pikoFail(id, "讲话太长，请分段重试") }
            return
        }
        pcmData.append(data)
    }
    private func pikoEnd(_ id: String) {
        guard activeID == id, !pikoEnded, !attempting else { return }
        pikoEnded = true
        deadline?.invalidate(); deadline = nil
        guard let speech = speech as? PassportRecognition else {
            // The engine is usually ready long before release; wait briefly for
            // the preparation task instead of failing an otherwise good turn.
            work = Task { @MainActor [weak self] in
                let waited = Date().addingTimeInterval(10)
                while self != nil, self?.activeID == id, self?.speech == nil, !Task.isCancelled, Date() < waited {
                    try? await Task.sleep(nanoseconds: 100_000_000)
                }
                guard let self, self.activeID == id, !Task.isCancelled else { return }
                self.pikoFinalize(id)
            }
            return
        }
        pikoFinalize(id, engine: speech)
    }
    private func pikoFinalize(_ id: String, engine: PassportRecognition? = nil) {
        guard !attempting, activeID == id else { return }
        attempting = true
        pikoSend(PassportPiko.voiceStatus(id, "transcribing"))
        work = Task { @MainActor [weak self] in
            guard let self else { return }
            do {
                guard let engine = engine ?? self.speech as? PassportRecognition else { throw PassportSpeechError.unavailable }
                let pcm = PassportPiko.pcmSamples(self.pcmData) ?? []
                guard PassportPiko.validateUtterance(pcm) else { throw PassportSherpaError.empty }
                let text = try await engine.transcribe(pcm)
                guard self.activeID == id, !Task.isCancelled else { return }
                if self.target == nil {
                    let pending = self.pikoCaptureError.isEmpty || self.pikoCaptureError.hasPrefix("正在")
                    let note = pending
                        ? "没有找到电脑上可输入的位置（\(self.captureDiagnosis.isEmpty ? "点选的焦点不可输入" : self.captureDiagnosis)），请点选输入框后重试"
                        : self.pikoCaptureError
                    self.retain(text, note: note + "。已保留本次文字，可手动复制。")
                    self.pikoSend(PassportPiko.voiceStatus(id, "text_only", message: note + "，文字已保留在电脑"))
                    self.reset(); return
                }
                guard self.target!.unchanged(generation: self.generation) else {
                    self.retain(text, note: "输入框或光标已改变，原来的内容保持不变。")
                    self.pikoSend(PassportPiko.voiceStatus(id, "text_only", message: "输入框已改变，文字保留在电脑"))
                    self.reset(); return
                }
                let inserted = await self.target!.insert(text, generation: { self.generation }, diagnostic: self.inputDiagnostic)
                guard self.activeID == id else { return }
                if inserted {
                    if let original = self.target, let current = PassportInputTarget.capture(generation: self.generation),
                       original.generation == self.generation, original.pid == current.pid {
                        // 插入文字后焦点元素可能被应用重建，不强求 CFEqual；
                        // 同一前台进程即可作为回车的目标。
                        self.enterTarget = current
                    }
                    self.pikoSend(PassportPiko.voiceTranscript(id, text))
                    self.pikoSend(PassportPiko.voiceStatus(id, "done"))
                } else {
                    self.retain(text, note: "无法确认输入结果，请检查输入框。下面保留了本次文字，可手动复制；不会自动重复输入。")
                    self.pikoSend(PassportPiko.voiceStatus(id, "text_only", message: "请检查电脑，文字已保留"))
                }
                self.reset()
            } catch {
                guard self.activeID == id, !Task.isCancelled else { return }
                self.pikoFail(id, (error as? LocalizedError)?.errorDescription ?? "没有识别成功，请靠近工牌重试")
            }
        }
    }

    func pikoEnter() -> Bool {
        guard activeID == nil, let target = enterTarget else { return false }
        enterTarget = nil
        guard target.sameField(generation: generation), CGPreflightPostEventAccess(),
              let source = CGEventSource(stateID: .privateState),
              let down = CGEvent(keyboardEventSource: source, virtualKey: 36, keyDown: true),
              let up = CGEvent(keyboardEventSource: source, virtualKey: 36, keyDown: false) else { return false }
        down.post(tap: .cghidEventTap)
        up.post(tap: .cghidEventTap)
        return true
    }
    private func pikoCancel(_ id: String) {
        guard activeID == id else { return }
        pikoSend(PassportPiko.voiceStatus(id, "cancelled"))
        reset()
    }
    private func pikoFail(_ id: String, _ message: String) {
        guard activeID == id else { return }
        pikoSend(PassportPiko.voiceError(id, message))
        reset()
    }
    func reset() {
        activeID = nil; preparation?.cancel(); preparation = nil; work?.cancel(); work = nil
        captureRetry?.cancel(); captureRetry = nil
        captureDiagnosis = ""
        deadline?.invalidate(); deadline = nil
        if let old = speech as? PassportRecognition { Task { await old.cancel() } }
        speech = nil; target = nil; recording = nil; ended = nil; attempting = false; stream = PassportAudioStream()
        pcmData = Data(); pikoEnded = false; pikoCaptureError = ""
        busyChanged(false)
    }
    @objc func showSetup() {
        if setupWindow == nil {
            let w = NSWindow(contentRect:NSRect(x:0,y:0,width:470,height:390),styleMask:[.titled,.closable],backing:.buffered,defer:false)
            w.title = "工牌听写"; w.isReleasedWhenClosed = false
            let title = NSTextField(labelWithString:"按住讲话，松开输入")
            title.font = .systemFont(ofSize:24,weight:.semibold); title.frame = NSRect(x:24,y:332,width:425,height:34)
            w.contentView?.addSubview(title)
            let body = NSTextField(wrappingLabelWithString:"先点选 Codex 或其他应用的输入框，再长按工牌确认键。听到单音后讲话；松开停止。上扬双音表示文字已写入输入框，消息由你发送。\n\n音频只在本机识别，不上传，也不保存录音。识别由应用内置的中文模型完成，无需联网。")
            body.frame = NSRect(x:24,y:190,width:420,height:134); body.font = .systemFont(ofSize:14); w.contentView?.addSubview(body)
            let speechButton = NSButton(title:"检查识别引擎",target:self,action:#selector(checkSpeech))
            speechButton.frame = NSRect(x:20,y:140,width:170,height:34); w.contentView?.addSubview(speechButton)
            let inputButton = NSButton(title:"开启辅助功能权限",target:self,action:#selector(authorizeInput))
            inputButton.frame = NSRect(x:200,y:140,width:235,height:34); w.contentView?.addSubview(inputButton)
            let testButton = NSButton(title:"8秒后测试输入",target:self,action:#selector(testInsertion))
            testButton.frame = NSRect(x:20,y:90,width:180,height:34); w.contentView?.addSubview(testButton)
            let draftsButton = NSButton(title:"查看保留的听写文字",target:self,action:#selector(showRetained))
            draftsButton.frame = NSRect(x:210,y:90,width:225,height:34); w.contentView?.addSubview(draftsButton)
            let note = NSTextField(wrappingLabelWithString:""); note.frame = NSRect(x:24,y:16,width:420,height:64); note.font = .systemFont(ofSize:12)
            w.contentView?.addSubview(note); setupNote = note; setupWindow = w; w.center()
        }
        setupNote?.stringValue = "识别在本机进行 · 辅助功能：\(AXIsProcessTrusted() ? "已允许" : "待允许")"
        setupWindow?.makeKeyAndOrderFront(nil); NSApp.activate(ignoringOtherApps:true)
    }
    @objc private func checkSpeech() {
        setupNote?.stringValue = "正在检查识别引擎…"
        Task { @MainActor [weak self] in
            do {
                let session = try await PassportRecognition.prepare(); await session.cancel()
                self?.setupNote?.stringValue = "\(session.engineName)已就绪 · 辅助功能：\(AXIsProcessTrusted() ? "已允许" : "待允许")"
            } catch { self?.setupNote?.stringValue = error.localizedDescription }
        }
    }
    private func inputDiagnostic(_ values:[String:Any]) {
        var report = values; report["at"] = Date().timeIntervalSince1970
        guard let data = try? JSONSerialization.data(withJSONObject:report,options:.sortedKeys) else { return }
        let path = AppPaths.runtime.appendingPathComponent("passport-input-diagnostic.json")
        try? data.write(to:path,options:.atomic)
        try? FileManager.default.setAttributes([.posixPermissions:0o600],ofItemAtPath:path.path)
    }
    @objc private func testInsertion() {
        setupNote?.stringValue = "请在8秒内点选测试文稿的输入位置。将输入‘工牌输入测试’，不会发送。"
        DispatchQueue.main.asyncAfter(deadline:.now()+8) { [weak self] in
            guard let self else { return }
            guard let target = PassportInputTarget.capture(generation:self.generation) else {
                self.setupNote?.stringValue = "请先允许辅助功能，并点选一个输入框。"; return
            }
            Task { @MainActor in
                let ok = await target.insert("工牌输入测试",generation:{self.generation},diagnostic:self.inputDiagnostic)
                self.setupNote?.stringValue = ok ? "输入适配测试成功，没有发送。" : "未能确认输入，请检查文稿和辅助功能权限。"
            }
        }
    }
    @objc private func authorizeInput() {
        let options = [kAXTrustedCheckOptionPrompt.takeUnretainedValue() as String:true] as CFDictionary
        _ = AXIsProcessTrustedWithOptions(options)
        if let url = URL(string:"x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility") { NSWorkspace.shared.open(url) }
    }
    private func retain(_ text: String, note: String) {
        // Keep earlier retained drafts as well; no audio is written to disk.
        if retainedCopied { retained = ""; retainedCount = 0; retainedCopied = false }
        retainedCount += 1
        retained += (retained.isEmpty ? "" : "\n\n──── \(retainedCount) ────\n") + text
        if draftWindow == nil {
            let w = NSWindow(contentRect:NSRect(x:0,y:0,width:500,height:350),styleMask:[.titled,.closable,.resizable],backing:.buffered,defer:false)
            w.title = "工牌听写 · 已保留的文字"; w.isReleasedWhenClosed = false; w.center(); draftWindow = w
        }
        draftWindow?.title = "工牌听写 · 已保留的文字"
        let content = NSView(frame:NSRect(x:0,y:0,width:500,height:350))
        let info = NSTextField(wrappingLabelWithString:note); info.frame = NSRect(x:20,y:270,width:460,height:60); content.addSubview(info)
        let scroll = NSScrollView(frame:NSRect(x:20,y:65,width:460,height:195)); scroll.hasVerticalScroller = true
        let editor = NSTextView(frame:scroll.bounds); editor.string = retained; editor.isEditable = false; editor.font = .systemFont(ofSize:17)
        scroll.documentView = editor; content.addSubview(scroll)
        let copy = NSButton(title:"复制文字",target:self,action:#selector(copyRetained)); copy.frame = NSRect(x:370,y:18,width:110,height:32); content.addSubview(copy)
        draftWindow?.contentView = content
        setupNote?.stringValue = "有未输入的听写文字，可点‘查看保留的听写文字’。"
    }
    @objc private func showRetained() {
        guard !retained.isEmpty else { setupNote?.stringValue = "目前没有保留的听写文字。"; return }
        draftWindow?.makeKeyAndOrderFront(nil); NSApp.activate(ignoringOtherApps:true)
    }
    @objc private func copyRetained() {
        guard !retained.isEmpty else { return }
        NSPasteboard.general.prepareForNewContents(with:.currentHostOnly)
        if NSPasteboard.general.setString(retained,forType:.string) {
            retainedCopied = true; draftWindow?.title = "工牌听写 · 已复制"
        }
    }
}
