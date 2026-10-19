import SwiftUI

// Name the property wrapper explicitly: newer SDKs also export a State macro.
private typealias StoredState<Value> = SwiftUI.State<Value>

struct SpeechVoice: Identifiable {
    let id: String
    let name: String
    let language: String
    init?(_ raw: [String: Any]) {
        guard let id = raw["id"] as? String, let name = raw["name"] as? String else { return nil }
        self.id = id; self.name = name; language = raw["language"] as? String ?? ""
    }
}

private struct SpeechDraft: Hashable {
    var voice = "Tingting"
    var rate: Double = 185
    var address = "老板"
    var intervals = ["30", "60", "180"]

    init(_ raw: [String: Any] = [:]) {
        voice = raw["voice"] as? String ?? "Tingting"
        rate = Double(raw["rate"] as? Int ?? 185)
        address = raw["address"] as? String ?? "老板"
        intervals = (raw["intervals"] as? [Int] ?? [30, 60, 180]).map(String.init)
    }
    var error: String? {
        if address.trimmingCharacters(in: .whitespaces).unicodeScalars.count > 20 || address.unicodeScalars.contains(where: { $0.value < 32 || $0.value == 127 || $0 == "[" || $0 == "]" }) {
            return "称呼最多 20 个字，不能包含换行或方括号。"
        }
        if intervals.contains(where: { Int($0.trimmingCharacters(in: .whitespaces)).map { !(5...3600).contains($0) } ?? true }) {
            return "每档间隔请填写 5–3600 秒的整数。"
        }
        return nil
    }
    var settings: [String: Any] {
        ["voice": voice, "rate": Int(rate.rounded()), "address": address.trimmingCharacters(in: .whitespaces), "intervals": intervals.map { Int($0.trimmingCharacters(in: .whitespaces)) ?? 0 }]
    }
    func matches(_ raw: [String: Any]) -> Bool {
        let saved = SpeechDraft(raw)
        return voice == saved.voice && Int(rate.rounded()) == Int(saved.rate) && address.trimmingCharacters(in: .whitespaces) == saved.address && intervals.map { Int($0.trimmingCharacters(in: .whitespaces)) } == saved.intervals.map(Int.init)
    }
}

struct SpeechSettingsView: View {
    @ObservedObject var model: VoicePanelModel
    @StoredState private var draft: SpeechDraft
    @StoredState private var validationError: String?

    init(model: VoicePanelModel) {
        self.model = model
        _draft = State(initialValue: SpeechDraft(model.speech))
    }
    private var error: String? {
        if let validationError { return validationError }
        for key in ["settingsError", "previewError", "error"] {
            if let value = model.speech[key] as? String, !value.isEmpty { return value }
        }
        return nil
    }
    private var saved: Bool { draft.matches(model.speech) && validationError == nil && (model.speech["settingsError"] as? String ?? "").isEmpty }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack {
                VStack(alignment: .leading, spacing: 5) {
                    Text("声音与规则").font(VoiceTheme.font(17, medium: true))
                    Text("用习惯的声音，在合适的时候喊你")
                        .font(VoiceTheme.font(11)).foregroundColor(VoiceTheme.secondary)
                }
                Spacer()
                Button { model.speechSettingsOpen = false } label: {
                    Image(systemName: "xmark").font(.system(size: 13)).frame(width: 28, height: 28)
                }.buttonStyle(.plain).accessibilityLabel("返回提醒设置").help("返回提醒设置")
            }.padding(.horizontal, 20).padding(.top, 18).padding(.bottom, 16)

            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    soundCard
                    intervalCard
                    if let error {
                        Label(error, systemImage: "exclamationmark.circle")
                            .font(VoiceTheme.font(11)).foregroundColor(VoiceTheme.amber)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }.padding(.horizontal, 20).padding(.vertical, 2).fixedSize(horizontal: false, vertical: true)
            }.frame(height: model.maximumSettingsHeight)

            HStack(spacing: 10) {
                VStack(alignment: .leading, spacing: 5) {
                    Text(!model.connected ? "服务连接后可保存" : saved ? "已自动保存" : error == nil ? "正在保存…" : "更改尚未保存")
                        .font(VoiceTheme.font(11)).foregroundColor(VoiceTheme.secondary)
                    Button("恢复默认") { draft = SpeechDraft(); submit() }
                        .buttonStyle(.plain).font(VoiceTheme.font(11)).foregroundColor(VoiceTheme.green)
                        .disabled(!model.connected)
                }
                Spacer()
                Button(action: preview) {
                    Label(model.previewing ? "停止试听" : "试听声音", systemImage: model.previewing ? "stop.fill" : "speaker.wave.2")
                        .font(VoiceTheme.font(12, medium: true)).padding(.horizontal, 14).padding(.vertical, 9)
                        .foregroundColor(VoiceTheme.primaryText).background(VoiceTheme.primary).clipShape(RoundedRectangle(cornerRadius: 8))
                }.buttonStyle(.plain)
                    .disabled(!model.connected || (!model.previewing && (!model.canPlay || (model.speaking && !model.previewing) || draft.error != nil)))
                    .help("只播放一次，使用当前选择的扬声器")
            }.padding(20)
        }
        .task(id: draft) {
            guard !draft.matches(model.speech) else { validationError = nil; return }
            do { try await Task.sleep(nanoseconds: 400_000_000) }
            catch { return }
            submit()
        }
        .onDisappear {
            submit()
            model.action(["action":"stop_preview"])
        }
    }

    private var soundCard: some View {
        VStack(alignment: .leading, spacing: 16) {
            HStack {
                Text("播报音色").font(VoiceTheme.font(12, medium: true))
                Spacer()
                Button("刷新音色") { model.action(["action":"refresh_voices"]) }
                    .buttonStyle(.plain).font(VoiceTheme.font(11)).foregroundColor(VoiceTheme.green)
            }
            Picker("播报音色", selection: $draft.voice) {
                if !model.voices.contains(where: { $0.id == draft.voice }) {
                    Text(draft.voice + " · 暂不可用").tag(draft.voice)
                }
                Section("中文音色") {
                    ForEach(model.voices.filter { $0.language.hasPrefix("zh_") }) { voice in Text(voice.name).tag(voice.id) }
                }
                Section("其他语言") {
                    ForEach(model.voices.filter { !$0.language.hasPrefix("zh_") }) { voice in Text(voice.name).tag(voice.id) }
                }
            }.labelsHidden().pickerStyle(.menu).frame(maxWidth: .infinity).accessibilityLabel("播报音色")
            Text("使用本机系统音色；添加更多音色后，可刷新列表。")
                .font(VoiceTheme.font(10)).foregroundColor(VoiceTheme.secondary).fixedSize(horizontal: false, vertical: true)
            VoiceTheme.line.frame(height: 1)
            VStack(spacing: 8) {
                HStack {
                    Text("语速").font(VoiceTheme.font(12, medium: true))
                    Spacer()
                    Text("\(Int(draft.rate.rounded()))").font(VoiceTheme.font(12)).monospacedDigit().foregroundColor(VoiceTheme.secondary)
                }
                Slider(value: $draft.rate, in: 100...300, step: 5).tint(VoiceTheme.green).accessibilityLabel("播报语速")
                HStack { Text("慢 · 100"); Spacer(); Text("默认 185"); Spacer(); Text("快 · 300") }
                    .font(VoiceTheme.font(10)).foregroundColor(VoiceTheme.secondary)
            }
            VoiceTheme.line.frame(height: 1)
            VStack(alignment: .leading, spacing: 8) {
                Text("怎么称呼你").font(VoiceTheme.font(12, medium: true))
                TextField("留空则不加称呼", text: $draft.address).textFieldStyle(.plain)
                    .font(VoiceTheme.font(13)).padding(10).background(VoiceTheme.soft).clipShape(RoundedRectangle(cornerRadius: 7))
                    .accessibilityLabel("播报称呼").onSubmit { submit() }
                Text("例如：老板、Rico；最多 20 个字。")
                    .font(VoiceTheme.font(10)).foregroundColor(VoiceTheme.secondary)
            }
        }.padding(14).background(VoiceTheme.paper).clipShape(RoundedRectangle(cornerRadius: 11))
            .overlay(RoundedRectangle(cornerRadius: 11).stroke(VoiceTheme.line, lineWidth: 1)).disabled(!model.connected)
    }

    private var intervalCard: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Text("重复间隔").font(VoiceTheme.font(12, medium: true))
                Spacer()
                Text("单位：秒").font(VoiceTheme.font(10)).foregroundColor(VoiceTheme.secondary)
            }
            HStack(spacing: 10) {
                ForEach(0..<3) { index in
                    VStack(alignment: .leading, spacing: 7) {
                        Text(["第一次重复", "第二次重复", "之后每次"][index])
                            .font(VoiceTheme.font(10)).foregroundColor(VoiceTheme.secondary)
                        TextField("秒", text: $draft.intervals[index]).textFieldStyle(.plain)
                            .font(VoiceTheme.font(14)).monospacedDigit().multilineTextAlignment(.center)
                            .padding(.vertical, 10).frame(maxWidth: .infinity).background(VoiceTheme.soft).clipShape(RoundedRectangle(cornerRadius: 7))
                            .accessibilityLabel(["第一次重复间隔，秒", "第二次重复间隔，秒", "之后每次间隔，秒"][index])
                            .onSubmit { submit() }
                    }.frame(maxWidth: .infinity)
                }
            }
            Text("首次立即播报；之后依次等待这三档间隔，最后一档持续重复，直到接手。每档 5–3600 秒。")
                .font(VoiceTheme.font(10)).foregroundColor(VoiceTheme.secondary).fixedSize(horizontal: false, vertical: true)
            Text("修改会用于当前提醒；已选“稍后”的时间保留。")
                .font(VoiceTheme.font(10)).foregroundColor(VoiceTheme.secondary).fixedSize(horizontal: false, vertical: true)
        }.padding(14).background(VoiceTheme.paper).clipShape(RoundedRectangle(cornerRadius: 11))
            .overlay(RoundedRectangle(cornerRadius: 11).stroke(VoiceTheme.line, lineWidth: 1)).disabled(!model.connected)
    }

    private func submit() {
        validationError = draft.error
        if validationError == nil && model.connected && !draft.matches(model.speech) {
            model.action(["action":"set_speech_settings", "settings":draft.settings])
        }
    }
    private func preview() {
        if model.previewing { model.action(["action":"stop_preview"]); return }
        submit()
        if validationError == nil { model.action(["action":"preview"]) }
    }
}
