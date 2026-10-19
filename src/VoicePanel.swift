import AppKit
import SwiftUI

enum VoiceTheme {
    static func color(_ light: UInt32, _ dark: UInt32) -> Color {
        Color(nsColor: NSColor(name: nil) { appearance in
            let value = appearance.bestMatch(from: [.aqua, .darkAqua]) == .darkAqua ? dark : light
            return NSColor(srgbRed: CGFloat((value >> 16) & 255) / 255, green: CGFloat((value >> 8) & 255) / 255, blue: CGFloat(value & 255) / 255, alpha: 1)
        })
    }
    static let background = color(0xfafaf8, 0x242624)
    static let paper = color(0xffffff, 0x2b2e2b)
    static let ink = color(0x242b26, 0xedf1eb)
    static let secondary = color(0x657066, 0xaeb9ad)
    static let line = color(0xe5e9e2, 0x3d443d)
    static let soft = color(0xf0f3ed, 0x343b33)
    static let green = color(0x2f6850, 0x9bc9a8)
    static let greenFill = color(0xe9f2e9, 0x33483a)
    static let amber = color(0x996329, 0xe7b87c)
    static let amberFill = color(0xfbf0df, 0x483b2b)
    static let primary = color(0x293d32, 0xdce8dc)
    static let primaryText = color(0xffffff, 0x24352a)
    static let resultAction = color(0xb0312c, 0xb63b33)
    static let switchOn = color(0x23805a, 0x37936c)
    static let switchOff = color(0x929a94, 0x657067)
    static func font(_ size: CGFloat, medium: Bool = false) -> Font {
        let name = medium ? "MiSans-Medium" : "MiSans-Regular"
        return NSFont(name: name, size: size) == nil ? .system(size: size, weight: medium ? .medium : .regular) : .custom(name, size: size)
    }
}

struct VoiceAlert: Identifiable {
    let id: String
    let title: String
    let detail: String
    let kind: String
    let nextAt: Double
    let count: Int
    let state: String
    let voiceEnabled: Bool
    let playLimit: Int
    let limitReached: Bool
    let recoveryPending: Bool
    init?(_ raw: [String: Any]) {
        guard let id = raw["id"] as? String else { return nil }
        self.id = id; title = raw["title"] as? String ?? "当前任务"
        detail = raw["detail"] as? String ?? ""; kind = raw["kind"] as? String ?? "result"
        nextAt = raw["nextAt"] as? Double ?? 0; count = raw["count"] as? Int ?? 0
        state = raw["state"] as? String ?? "pending"
        voiceEnabled = raw["voiceEnabled"] as? Bool ?? true
        playLimit = raw["playLimit"] as? Int ?? 0
        limitReached = raw["limitReached"] as? Bool ?? false
        recoveryPending = raw["recoveryPending"] as? Bool ?? false
    }
    var badge: String { ["approval":"等待审批", "question":"等待回答", "result":"已有结果", "blocked":"需要关注", "test":"播报测试"][kind] ?? "提醒" }
    var summary: String { ["approval":"有一项审批等待你处理", "question":"有个问题需要你回答", "result":"任务已有结果，可以查看了", "blocked":"这件事需要你关注", "test":"听到后点「已接手」停止"][kind] ?? "有一条新的提醒" }
    var isResult: Bool { kind == "result" }
    var ackTitle: String { isResult ? "知道了" : "已接手" }
}

struct VoiceOutput: Identifiable {
    let id: String
    let name: String
    let transport: String
    init?(_ raw: [String: Any]) {
        guard let name = raw["name"] as? String, let uid = raw["uid"] as? String else { return nil }
        self.name = name; id = uid; transport = raw["transport"] as? String ?? "other"
    }
    var caption: String { ["builtIn":"Mac 内置扬声器", "bluetooth":"蓝牙音频设备", "usb":"USB 音频设备", "airplay":"AirPlay 设备", "virtual":"虚拟音频设备"][transport] ?? "音频输出设备" }
    var symbol: String { transport == "bluetooth" ? "headphones" : transport == "airplay" ? "airplay.audio" : "speaker.wave.2" }
}

final class VoicePanelModel: ObservableObject {
    @Published var snapshot: [String: Any] = [:]
    @Published var now = Date().timeIntervalSince1970
    @Published var settingsOpen = false
    @Published var speechSettingsOpen = false
    @Published var pauseDurationOpen = false
    @Published var usageOpen = false
    @Published var rulesOpen = false
    @Published var quietHoursOpen = false
    @Published var panelArrowX: CGFloat = PanelChrome.width / 2
    @Published var devicePickerOpen = false
    @Published var connectionConfigured = false
    @Published var connectionMessage = "正在检查连接"
    @Published var startupEnabled = false
    @Published var serviceError: String?
    @Published var serviceRecovering = false
    @Published var recentTitle: String?
    @Published var listContentHeight: CGFloat = 160
    @Published var maximumListHeight: CGFloat = 380
    @Published var maximumSettingsHeight: CGFloat = 540
    var action: ([String: Any]) -> Void = { _ in }
    var changeStartup: (Bool) -> Void = { _ in }
    var hide: () -> Void = {}
    var retry: () -> Void = {}
    var connectCodex: () -> Void = {}

    var alerts: [VoiceAlert] {
        let items = (snapshot["alerts"] as? [[String: Any]] ?? []).compactMap(VoiceAlert.init)
        return items.filter { !$0.isResult } + items.filter { $0.isResult }
    }
    var enabled: Bool { snapshot["enabled"] as? Bool ?? true }
    var connected: Bool { snapshot["at"] != nil && serviceError == nil }
    var mutedUntil: Double { snapshot["mutedUntil"] as? Double ?? 0 }
    var muted: Bool { mutedUntil > now }
    var pauseMinutes: Int { (snapshot["pause"] as? [String: Any])?["minutes"] as? Int ?? 15 }
    var pauseError: String { (snapshot["pause"] as? [String: Any])?["error"] as? String ?? "" }
    var audio: [String: Any] { snapshot["audio"] as? [String: Any] ?? [:] }
    var device: String { audio["device"] as? String ?? "播报设备" }
    var audioAvailable: Bool { audio["available"] as? Bool ?? false }
    var audioReady: Bool { audio["ready"] as? Bool ?? false }
    var speaking: Bool { snapshot["speakingId"] is String }
    var eventsAvailable: Bool { (snapshot["monitor"] as? [String: Any])?["state"] as? String == "connected" }
    var usage: CodexUsage {
        CodexUsage(serviceError == nil ? snapshot["usage"] as? [String: Any] ?? [:] : ["state":"error", "message":"提醒服务已断开，请重新连接后刷新用量。"], now: now, warningThreshold: usageLowThreshold)
    }
    var usageAnnouncement: [String: Any] { snapshot["usageAnnouncement"] as? [String: Any] ?? [:] }
    var usageResetEnabled: Bool { usageAnnouncement["enabled"] as? Bool ?? true }
    var usageResetPreviewing: Bool { usageAnnouncement["previewing"] as? Bool ?? false }
    var usageResetError: String { usageAnnouncement["error"] as? String ?? "" }
    var usageLowAnnouncement: [String: Any] { snapshot["usageLowAnnouncement"] as? [String: Any] ?? [:] }
    var usageLowEnabled: Bool { usageLowAnnouncement["enabled"] as? Bool ?? true }
    var usageLowThreshold: Int { usageLowAnnouncement["threshold"] as? Int ?? 20 }
    var usageLowPreviewing: Bool { usageLowAnnouncement["previewing"] as? Bool ?? false }
    var usageLowError: String { usageLowAnnouncement["error"] as? String ?? "" }
    var followSystem: Bool { audio["followSystem"] as? Bool ?? false }
    var outputs: [VoiceOutput] { (audio["devices"] as? [[String: Any]] ?? []).compactMap(VoiceOutput.init) }
    var defaultName: String { audio["defaultName"] as? String ?? "" }
    var displayDevice: String { followSystem ? "跟随系统输出" : device }
    var speech: [String: Any] { snapshot["speech"] as? [String: Any] ?? [:] }
    var voices: [SpeechVoice] { (speech["voices"] as? [[String: Any]] ?? []).compactMap(SpeechVoice.init) }
    var speechReady: Bool { speech["ready"] as? Bool ?? true }
    var previewing: Bool { speech["previewing"] as? Bool ?? false }
    var voiceName: String {
        let selected = speech["voice"] as? String ?? "Tingting"
        return voices.first(where: { $0.id == selected })?.name ?? selected
    }
    var intervalSummary: String {
        let values = speech["intervals"] as? [Int] ?? [30, 60, 180]
        return values.enumerated().map { index, value in
            let duration = value % 60 == 0 ? "\(value / 60) 分钟" : "\(value) 秒"
            return (index == 2 ? "每 " : "") + duration
        }.joined(separator: " → ")
    }
    func isSelected(_ output: VoiceOutput) -> Bool {
        if followSystem { return false }
        let uid = audio["selectedUID"] as? String ?? ""
        return uid.isEmpty ? output.name == audio["selectedDevice"] as? String : output.id == uid
    }
    func openDevicePicker() { action(["action":"refresh_audio"]); devicePickerOpen = true }
    func chooseDevice(_ output: VoiceOutput?) {
        let uid = output?.id ?? ""
        action(["action":"set_audio_device", "device":output?.name ?? "", "uid":uid.hasPrefix("name:") ? "" : uid])
        devicePickerOpen = false
    }
    var quiet: [String: Any] { snapshot["quietHours"] as? [String: Any] ?? [:] }
    var quietActive: Bool { quiet["active"] as? Bool ?? false }
    var allowQuietApproval: Bool { quiet["allow_approval"] as? Bool ?? false }
    var quietSummary: String { quiet["enabled"] as? Bool == true ? "\(quiet["start"] as? String ?? "23:00")–\(quiet["end"] as? String ?? "09:00") · 按所选日期" : "未开启 · 按本机时间执行" }
    var reminderRules: [String: Any] { snapshot["reminderRules"] as? [String: Any] ?? [:] }
    var rulesError: String { snapshot["rulesError"] as? String ?? "" }
    var canPlay: Bool { connected && enabled && audioReady && speechReady && !muted && !quietActive }
    func canPlay(_ alert: VoiceAlert) -> Bool { connected && enabled && audioReady && speechReady && !muted && (!quietActive || (alert.kind == "approval" && allowQuietApproval)) }
    var audioNote: String {
        if !audioAvailable { return "未连接 · 待处理事项已保留" }
        if !audioReady { return audio["error"] as? String ?? "扬声器暂时无法播报" }
        if followSystem { return speaking ? "正在播报 · 接手后停止" : "当前：" + device }
        return speaking ? "正在播报 · 接手后停止" : "已连接 · 声音从此设备播放"
    }
    var heading: (title: String, subtitle: String, icon: String, tone: Int) {
        if let error = serviceError { return (serviceRecovering ? "正在恢复提醒服务" : "提醒服务需要检查", error, "exclamationmark", 1) }
        if !connected { return ("正在连接", "准备好后，有事我会喊你", "waveform", 0) }
        if !enabled { return ("提醒已关闭", "重新开启后，只接收新的提醒", "bell.slash", 0) }
        if !audioAvailable { return ("扬声器未连接", "待处理事项会保留，连接后继续播报", "speaker.slash", 1) }
        if !audioReady { return ("扬声器暂时无法播报", audioNote, "speaker.slash", 1) }
        if let error = speech["error"] as? String, !error.isEmpty { return ("播报声音需要检查", error, "waveform", 1) }
        if muted { return ("提醒已暂停", "\(max(1, Int(ceil((mutedUntil - now) / 60)))) 分钟后恢复，待处理事项会保留", "pause", 0) }
        if quietActive { return ("定时免打扰", allowQuietApproval ? "保留待办卡片，仅审批提醒可出声" : "待办会保留，时段结束后恢复播报", "moon", 0) }
        if !alerts.isEmpty { return ("\(alerts.count) 件事需要你", "重要的事，听到后再来处理", "bell.badge", 1) }
        if !eventsAvailable { return ("等待 Codex 连接", "未读到本机任务事件，请先打开 Codex", "link", 0) }
        if !connectionConfigured { return ("完成提醒已就绪", "连接 Codex，以增加审批与提问提醒", "checkmark", 2) }
        return ("一切就绪", "有结果、等确认时，我会喊你", "checkmark", 2)
    }
    func meta(_ alert: VoiceAlert) -> String {
        if !connected { return "服务连接中 · 待处理事项已保留" }
        if alert.recoveryPending { return "等待核验任务状态 · 暂不自动播报" }
        if quietActive && !(alert.kind == "approval" && allowQuietApproval) { return "定时免打扰 · 卡片已保留" }
        if alert.state == "snoozed" {
            let seconds = max(0, Int(ceil(alert.nextAt - now)))
            let delay = seconds >= 60 ? "\(Int(ceil(Double(seconds) / 60))) 分钟" : "\(seconds) 秒"
            return "已安排稍后 · \(delay)后再提醒"
        }
        if !alert.voiceEnabled { return "此类语音已关闭 · 可手动重播" }
        if alert.limitReached { return "已播报 \(alert.count) 次 · 本条已达到次数上限" }
        if !audioReady { return "音箱暂不可用 · 恢复后继续提醒" }
        if !speechReady { return "音色暂不可用 · 请在设置中调整" }
        if muted { return "已暂停 · 恢复后继续提醒" }
        let seconds = max(0, Int(ceil(alert.nextAt - now)))
        let delay = seconds >= 60 ? "\(Int(ceil(Double(seconds) / 60))) 分钟" : "\(seconds) 秒"
        if snapshot["speakingId"] as? String == alert.id { return "正在播报 · 接手后停止" }
        if alert.count == 0 { return seconds > 0 ? "\(delay)后提醒" : "等待播报" }
        return "已提醒 \(alert.count) 次 · " + (seconds > 0 ? "\(delay)后再次提醒" : "等待播报")
    }
    func pauseOrResume() { action(["action": muted ? "unmute" : "mute"]) }
    func setPause(minutes: Int, start: Bool) { action(["action": start ? "pause" : "set_pause_duration", "minutes": minutes]) }
}

private struct PanelButtonStyle: ButtonStyle {
    @Environment(\.isEnabled) private var enabled
    enum Kind { case primary, secondary, quiet, icon }
    var kind: Kind = .secondary
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(VoiceTheme.font(12))
            .foregroundColor(kind == .primary ? VoiceTheme.primaryText : kind == .quiet ? VoiceTheme.secondary : VoiceTheme.ink)
            .padding(.horizontal, kind == .icon ? 8 : kind == .quiet ? 7 : 12)
            .padding(.vertical, 7)
            .background(kind == .primary ? VoiceTheme.primary : kind == .secondary ? VoiceTheme.paper : Color.clear)
            .clipShape(RoundedRectangle(cornerRadius: 7))
            .overlay(RoundedRectangle(cornerRadius: 7).stroke(kind == .secondary ? VoiceTheme.line : Color.clear, lineWidth: 1))
            .opacity(!enabled ? 0.4 : configuration.isPressed ? 0.72 : 1)
    }
}

private struct IconAction: View {
    let symbol: String
    let label: String
    var disabled = false
    let action: () -> Void
    var body: some View {
        Button(action: action) { Image(systemName: symbol).font(.system(size: 14, weight: .regular)).frame(width: 16, height: 16) }
            .buttonStyle(PanelButtonStyle(kind: .icon))
            .accessibilityLabel(label).help(label).disabled(disabled).opacity(disabled ? 0.4 : 1)
    }
}

private struct AcknowledgeButtonStyle: ButtonStyle {
    var isResult: Bool
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(VoiceTheme.font(15, medium: true))
            .foregroundColor(isResult ? .white : VoiceTheme.primaryText)
            .frame(width: 100, height: 64)
            .background(isResult ? VoiceTheme.resultAction : VoiceTheme.primary)
            .clipShape(RoundedRectangle(cornerRadius: 10))
            .contentShape(RoundedRectangle(cornerRadius: 10))
            .opacity(configuration.isPressed ? 0.72 : 1)
    }
}

private struct ListHeightKey: PreferenceKey {
    static var defaultValue: CGFloat = 0
    static func reduce(value: inout CGFloat, nextValue: () -> CGFloat) { value = nextValue() }
}

private typealias PauseDraftState<Value> = SwiftUI.State<Value>

private struct PauseDurationView: View {
    @ObservedObject var model: VoicePanelModel
    @PauseDraftState private var minutes: String

    init(model: VoicePanelModel) {
        self.model = model
        _minutes = State(initialValue: String(model.pauseMinutes))
    }
    private var value: Int? {
        guard let value = Int(minutes.trimmingCharacters(in: .whitespaces)), (1...1440).contains(value) else { return nil }
        return value
    }
    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            HStack {
                Text("暂停时长").font(VoiceTheme.font(17, medium: true))
                Spacer()
                IconAction(symbol: "xmark", label: "返回提醒") { model.pauseDurationOpen = false }
            }
            Text("暂停期间保留事项，到时自动恢复提醒。")
                .font(VoiceTheme.font(12)).foregroundColor(VoiceTheme.secondary)
            HStack(alignment: .firstTextBaseline, spacing: 10) {
                TextField("15", text: $minutes).textFieldStyle(.plain)
                    .font(VoiceTheme.font(25, medium: true)).monospacedDigit()
                    .accessibilityLabel("自定义暂停分钟数")
                    .onSubmit { save(start: model.enabled) }
                Text("分钟").font(VoiceTheme.font(13)).foregroundColor(VoiceTheme.secondary)
            }.padding(14).background(VoiceTheme.soft).clipShape(RoundedRectangle(cornerRadius: 9))
                .disabled(!model.connected)
            HStack(spacing: 7) {
                ForEach([5, 15, 30, 60], id: \.self) { duration in
                    Button("\(duration) 分钟") { minutes = String(duration) }
                        .buttonStyle(PanelButtonStyle()).frame(maxWidth: .infinity)
                }
            }.disabled(!model.connected)
            Text(value == nil ? "请输入 1–1440 之间的整数分钟。" : "时长会保存，下次可直接使用。")
                .font(VoiceTheme.font(11)).foregroundColor(value == nil ? VoiceTheme.amber : VoiceTheme.secondary)
            if !model.pauseError.isEmpty {
                Text(model.pauseError).font(VoiceTheme.font(11)).foregroundColor(VoiceTheme.amber)
            }
            if model.muted {
                Text("仅保存不会改变当前暂停；再次暂停会从现在重新计时。")
                    .font(VoiceTheme.font(11)).foregroundColor(VoiceTheme.secondary).fixedSize(horizontal: false, vertical: true)
            }
            HStack(spacing: 9) {
                Spacer()
                Button("仅保存") { save(start: false) }.buttonStyle(PanelButtonStyle())
                    .disabled(value == nil || !model.connected)
                Button("保存并暂停") { save(start: true) }.buttonStyle(PanelButtonStyle(kind: .primary))
                    .disabled(value == nil || !model.connected || !model.enabled)
            }.padding(.top, 2)
        }.padding(20)
    }
    private func save(start: Bool) {
        guard let value, model.connected, !start || model.enabled else { return }
        model.setPause(minutes: value, start: start)
        model.pauseDurationOpen = false
    }
}

struct VoicePanelView: View {
    @ObservedObject var model: VoicePanelModel
    var body: some View {
        Group {
            if model.devicePickerOpen { devicePicker }
            else if model.pauseDurationOpen { PauseDurationView(model: model) }
            else if model.usageOpen { UsageDetailView(model: model) }
            else if model.rulesOpen { ReminderRulesView(model: model) }
            else if model.quietHoursOpen { QuietHoursView(model: model) }
            else if model.speechSettingsOpen { SpeechSettingsView(model: model) }
            else if model.settingsOpen { settings }
            else { main }
        }
        .frame(width: PanelChrome.width)
        .padding(.top, PanelChrome.arrowHeight)
        .fixedSize(horizontal: true, vertical: true)
        .font(VoiceTheme.font(13)).foregroundColor(VoiceTheme.ink)
        .background(VoiceTheme.background)
        .clipShape(PanelBubbleShape(arrowX: model.panelArrowX))
        .overlay(PanelBubbleShape(arrowX: model.panelArrowX).stroke(VoiceTheme.line, lineWidth: 1))
        .onExitCommand {
            if model.devicePickerOpen { model.devicePickerOpen = false }
            else if model.pauseDurationOpen { model.pauseDurationOpen = false }
            else if model.usageOpen { model.usageOpen = false }
            else if model.rulesOpen { model.rulesOpen = false }
            else if model.quietHoursOpen { model.quietHoursOpen = false }
            else if model.speechSettingsOpen { model.speechSettingsOpen = false }
            else if model.settingsOpen { model.settingsOpen = false }
            else { model.hide() }
        }
    }
    private var main: some View {
        VStack(spacing: 0) {
            HStack(spacing: 9) {
                Image(systemName: "waveform").font(.system(size: 15)).foregroundColor(VoiceTheme.green)
                    .frame(width: 29, height: 29).background(VoiceTheme.soft).clipShape(RoundedRectangle(cornerRadius: 9))
                Text("Codex 语音提醒").font(VoiceTheme.font(13, medium: true))
                Spacer(minLength: 8)
                enableToggle
                IconAction(symbol: "ellipsis", label: "更多设置") { model.settingsOpen = true }
            }.padding(.horizontal, 20).padding(.top, 17).padding(.bottom, 14)
            HStack(spacing: 12) {
                VStack(alignment: .leading, spacing: 5) {
                    Text("当前状态").font(VoiceTheme.font(11)).foregroundColor(VoiceTheme.secondary)
                    Text(model.heading.title).font(VoiceTheme.font(22, medium: true)).fixedSize(horizontal: false, vertical: true)
                    Text(model.heading.subtitle).font(VoiceTheme.font(12)).foregroundColor(VoiceTheme.secondary).fixedSize(horizontal: false, vertical: true)
                }
                Spacer(minLength: 4)
                Image(systemName: model.heading.icon).font(.system(size: 17, weight: .medium))
                    .foregroundColor(model.heading.tone == 1 ? VoiceTheme.amber : model.heading.tone == 2 ? VoiceTheme.green : VoiceTheme.secondary)
                    .frame(width: 38, height: 38)
                    .background(model.heading.tone == 1 ? VoiceTheme.amberFill : model.heading.tone == 2 ? VoiceTheme.greenFill : VoiceTheme.soft)
                    .clipShape(Circle())
            }.padding(.horizontal, 21).padding(.top, 9).padding(.bottom, 19)
            if model.serviceError != nil {
                HStack { Text("待处理事项保留在原聊天中").font(VoiceTheme.font(12)); Spacer(); Button("重新连接", action: model.retry).buttonStyle(PanelButtonStyle()) }
                    .padding(12).background(VoiceTheme.amberFill).clipShape(RoundedRectangle(cornerRadius: 9)).padding(.horizontal, 14).padding(.bottom, 12)
            }
            if model.alerts.isEmpty { emptyState }
            else { ReminderList(model: model) }
            if model.alerts.isEmpty, let title = model.recentTitle {
                HStack { Text("最近处理"); Spacer(); Text(title + " · 已停止提醒").lineLimit(1).truncationMode(.middle) }
                    .font(VoiceTheme.font(11)).foregroundColor(VoiceTheme.secondary).padding(.horizontal, 20).padding(.vertical, 12)
                    .overlay(alignment: .top) { VoiceTheme.line.frame(height: 1) }
            }
            UsageSummaryRow(model: model)
            deviceRow
            HStack(spacing: 8) {
                HStack(spacing: 0) {
                    Button(action: model.pauseOrResume) { Label(model.muted ? "恢复提醒" : "暂停 \(model.pauseMinutes) 分钟", systemImage: model.muted ? "play" : "pause") }
                        .buttonStyle(PanelButtonStyle(kind: .quiet)).disabled(!model.enabled || !model.connected)
                    Menu {
                        Text("默认时长：\(model.pauseMinutes) 分钟")
                        Divider()
                        ForEach([5, 15, 30, 60, 120], id: \.self) { minutes in
                            Button(model.enabled ? "暂停 \(minutes) 分钟" : "设为 \(minutes) 分钟") {
                                model.setPause(minutes: minutes, start: model.enabled)
                            }
                        }
                        Divider()
                        Button("自定义时长…") { model.pauseDurationOpen = true }
                    } label: {
                        Image(systemName: "chevron.down").font(.system(size: 9, weight: .medium))
                            .foregroundColor(VoiceTheme.secondary).frame(width: 22, height: 28).contentShape(Rectangle())
                    }.menuStyle(.borderlessButton).menuIndicator(.hidden).fixedSize().disabled(!model.connected)
                        .accessibilityLabel("设置暂停时长，默认 \(model.pauseMinutes) 分钟").help("选择常用时长或自定义")
                }
                Spacer(minLength: 5)
                if model.alerts.count > 1 {
                    Button("全部已接手") { model.action(["action":"ack_all"]) }.buttonStyle(PanelButtonStyle(kind: .quiet))
                        .help("停止当前所有提醒；审批仍在原聊天处理")
                } else if model.alerts.isEmpty {
                    Button("收起面板", action: model.hide).buttonStyle(PanelButtonStyle(kind: .quiet))
                } else {
                    Text("只在需要你时出声").font(VoiceTheme.font(11)).foregroundColor(VoiceTheme.secondary)
                }
            }.padding(.horizontal, 16).padding(.vertical, 10).background(VoiceTheme.soft)
        }
    }
    private var enableToggle: some View {
        Toggle("启用语音提醒", isOn: Binding(get: { model.enabled }, set: { model.action(["action":"set_enabled", "enabled":$0]) }))
            .toggleStyle(PersistentSwitchStyle()).labelsHidden().disabled(!model.connected)
            .help("关闭立即停喊，重新开启只接收新事项")
    }
    private var emptyState: some View {
        VStack(spacing: 10) {
            HStack(alignment: .center, spacing: 4) {
                ForEach(0..<7) { index in RoundedRectangle(cornerRadius: 2).fill(VoiceTheme.green.opacity([0.3,0.45,0.65,0.8,0.65,0.45,0.3][index])).frame(width: 3, height: [6,13,21,28,21,13,6][index]) }
            }.frame(height: 28).padding(.bottom, 5).accessibilityHidden(true)
            Text(model.enabled ? "现在没有等待处理的事" : "需要时，随时再开启").font(VoiceTheme.font(14, medium: true))
            Text(!model.enabled ? "提醒已暂停接收，随时可以重新开启。" : !model.eventsAvailable ? "打开本机 Codex 后，再检查提醒连接。" : "你可以继续忙自己的工作。")
                .font(VoiceTheme.font(12)).foregroundColor(VoiceTheme.secondary)
            if model.enabled {
                HStack(spacing: 7) {
                    if !model.connectionConfigured { Button("连接 Codex", action: model.connectCodex).buttonStyle(PanelButtonStyle()) }
                    Button("试听一下") { model.action(["action":"test"]) }.buttonStyle(PanelButtonStyle(kind: .quiet)).disabled(!model.canPlay)
                        .help("创建一条测试提醒，点「已接手」停止重复播报")
                }
            } else {
                Button("开启提醒") { model.action(["action":"set_enabled", "enabled":true]) }.buttonStyle(PanelButtonStyle(kind: .quiet)).disabled(!model.connected)
            }
        }.frame(maxWidth: .infinity).padding(.horizontal, 15).padding(.top, 21).padding(.bottom, 27)
    }
    private var deviceRow: some View {
        HStack(spacing: 9) {
            Image(systemName: model.audioReady ? "speaker.wave.2" : "speaker.slash").font(.system(size: 16)).foregroundColor(model.audioReady ? VoiceTheme.green : VoiceTheme.amber).frame(width: 18)
            VStack(alignment: .leading, spacing: 2) {
                Button(action: model.openDevicePicker) {
                    HStack(spacing: 5) {
                        Text(model.displayDevice).font(VoiceTheme.font(12, medium: true)).lineLimit(1)
                        Image(systemName: "chevron.up.chevron.down").font(.system(size: 9)).foregroundColor(VoiceTheme.secondary)
                    }
                }.buttonStyle(.plain).accessibilityLabel("选择播报设备，当前：\(model.displayDevice)").help("选择用于语音提醒的扬声器")
                Text(model.audioNote).font(VoiceTheme.font(11)).foregroundColor(VoiceTheme.secondary).lineLimit(2)
            }
            Spacer(minLength: 5)
            IconAction(symbol: "slider.horizontal.3", label: "播报设置") { model.settingsOpen = true }
        }.padding(.horizontal, 20).padding(.vertical, 12).overlay(alignment: .top) { VoiceTheme.line.frame(height: 1) }
    }
    private func settingRow<Content: View>(_ title: String, _ caption: String, @ViewBuilder control: () -> Content) -> some View {
        HStack(spacing: 12) {
            VStack(alignment: .leading, spacing: 3) {
                Text(title).font(VoiceTheme.font(13, medium: true))
                Text(caption).font(VoiceTheme.font(11)).foregroundColor(VoiceTheme.secondary).fixedSize(horizontal: false, vertical: true)
            }
            Spacer(minLength: 5)
            control()
        }.padding(13)
    }
    private var settings: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack {
                Text("提醒设置").font(VoiceTheme.font(17, medium: true))
                Spacer()
                IconAction(symbol: "xmark", label: "返回提醒") { model.settingsOpen = false }
            }.padding(.bottom, 18)
            ScrollView {
                VStack(alignment: .leading, spacing: 0) {
            Text("声音").font(VoiceTheme.font(11)).foregroundColor(VoiceTheme.secondary).padding(.bottom, 8)
            VStack(spacing: 0) {
                settingRow(model.displayDevice, model.audioNote) {
                    HStack(spacing: 7) {
                        Button("切换", action: model.openDevicePicker).buttonStyle(PanelButtonStyle())
                        Button("试听") { model.action(["action":"test"]) }.buttonStyle(PanelButtonStyle()).disabled(!model.canPlay)
                            .help("创建一条测试提醒，点「已接手」停止")
                    }
                }
                VoiceTheme.line.frame(height: 1)
                settingRow("声音与规则", model.voiceName + "\n" + model.intervalSummary) {
                    Button("调整") { model.speechSettingsOpen = true }.buttonStyle(PanelButtonStyle()).disabled(!model.connected)
                }
            }.background(VoiceTheme.paper).clipShape(RoundedRectangle(cornerRadius: 11)).overlay(RoundedRectangle(cornerRadius: 11).stroke(VoiceTheme.line, lineWidth: 1))
            VStack(spacing: 0) {
                settingRow("按类型设置提醒", "分别设置完成、审批、提问和异常的播报") {
                    Button("设置") { model.rulesOpen = true }.buttonStyle(PanelButtonStyle()).disabled(!model.connected)
                }
                VoiceTheme.line.frame(height: 1)
                settingRow("定时免打扰", model.quietSummary) {
                    Button("设置") { model.quietHoursOpen = true }.buttonStyle(PanelButtonStyle()).disabled(!model.connected)
                }
            }.background(VoiceTheme.paper).clipShape(RoundedRectangle(cornerRadius: 11)).overlay(RoundedRectangle(cornerRadius: 11).stroke(VoiceTheme.line, lineWidth: 1)).padding(.top, 12)
            Text("启动与运行").font(VoiceTheme.font(11)).foregroundColor(VoiceTheme.secondary).padding(.top, 20).padding(.bottom, 8)
            VStack(spacing: 0) {
                settingRow("登录后自动启动", "后台安静运行，需要时再出现") {
                    Toggle("登录后自动启动", isOn: Binding(get: { model.startupEnabled }, set: model.changeStartup)).toggleStyle(PersistentSwitchStyle()).labelsHidden()
                }
                VoiceTheme.line.frame(height: 1)
                settingRow("启用语音提醒", "关闭后不积压旧提醒") { enableToggle }
            }.background(VoiceTheme.paper).clipShape(RoundedRectangle(cornerRadius: 11)).overlay(RoundedRectangle(cornerRadius: 11).stroke(VoiceTheme.line, lineWidth: 1))
            Text("全部接手后自动收起；有新提醒时再出现。")
                .font(VoiceTheme.font(11)).foregroundColor(VoiceTheme.secondary).padding(.top, 16)
            VStack(alignment: .leading, spacing: 8) {
                HStack {
                    Text("Codex 连接").font(VoiceTheme.font(13, medium: true))
                    Spacer()
                    Button(model.connectionConfigured ? "重新安装连接" : "连接 Codex", action: model.connectCodex).buttonStyle(PanelButtonStyle())
                }
                Text(model.connectionMessage).font(VoiceTheme.font(11)).foregroundColor(VoiceTheme.secondary).fixedSize(horizontal: false, vertical: true)
            }.padding(13).background(VoiceTheme.paper).clipShape(RoundedRectangle(cornerRadius: 11)).overlay(RoundedRectangle(cornerRadius: 11).stroke(VoiceTheme.line, lineWidth: 1)).padding(.top, 16)
                }.padding(.bottom, 2)
            }.frame(height: model.maximumSettingsHeight)
            HStack {
                Circle().fill(model.connected ? VoiceTheme.green : VoiceTheme.amber).frame(width: 5, height: 5)
                Text(model.connected ? "服务正常 · 自动恢复已开启" : model.serviceRecovering ? "服务正在自动恢复" : "提醒服务未连接").font(VoiceTheme.font(11)).foregroundColor(VoiceTheme.secondary)
                Spacer()
                Button("退出应用") { NSApp.terminate(nil) }.buttonStyle(PanelButtonStyle(kind: .quiet))
            }.padding(.top, 18)
        }.padding(.horizontal, 20).padding(.top, 16).padding(.bottom, 19)
    }
    private var devicePicker: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack {
                Text("播报设备").font(VoiceTheme.font(17, medium: true))
                Spacer()
                IconAction(symbol: "xmark", label: "返回") { model.devicePickerOpen = false }
            }.padding(.bottom, 6)
            Text("选择用于语音提醒的扬声器")
                .font(VoiceTheme.font(12)).foregroundColor(VoiceTheme.secondary).padding(.bottom, 18)
            VStack(spacing: 5) {
                outputRow("跟随系统输出", caption: model.defaultName.isEmpty ? "使用 macOS 当前的输出设备" : "当前：" + model.defaultName, symbol: "speaker.wave.2", selected: model.followSystem) { model.chooseDevice(nil) }
                VoiceTheme.line.frame(height: 1).padding(.vertical, 5)
                if model.outputs.count > 5 { ScrollView { outputChoices }.frame(height: 320) }
                else { outputChoices }
                if !model.audioAvailable && !model.followSystem {
                    HStack {
                        Image(systemName: "speaker.slash").frame(width: 22)
                        Text(model.device + " · 未连接").font(VoiceTheme.font(12))
                        Spacer()
                        Image(systemName: "checkmark")
                    }.foregroundColor(VoiceTheme.secondary).padding(12)
                }
            }.padding(6).background(VoiceTheme.paper).clipShape(RoundedRectangle(cornerRadius: 11))
                .overlay(RoundedRectangle(cornerRadius: 11).stroke(VoiceTheme.line, lineWidth: 1))
            Text("未出现的蓝牙或 AirPlay 设备，请先在 macOS 中连接。")
                .font(VoiceTheme.font(11)).foregroundColor(VoiceTheme.secondary).fixedSize(horizontal: false, vertical: true).padding(.top, 14)
            HStack {
                Text("选择会自动保存").font(VoiceTheme.font(11)).foregroundColor(VoiceTheme.secondary)
                Spacer()
                Button { model.action(["action":"refresh_audio"]) } label: { Label("刷新设备", systemImage: "arrow.clockwise") }
                    .buttonStyle(PanelButtonStyle(kind: .quiet))
            }.padding(.top, 12)
        }.padding(.horizontal, 20).padding(.top, 16).padding(.bottom, 19)
    }
    private var outputChoices: some View {
        VStack(spacing: 5) {
            ForEach(model.outputs) { output in
                outputRow(output.name, caption: output.caption, symbol: output.symbol, selected: model.isSelected(output)) { model.chooseDevice(output) }
            }
        }
    }
    private func outputRow(_ title: String, caption: String, symbol: String, selected: Bool, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            HStack(spacing: 12) {
                Image(systemName: symbol).font(.system(size: 17)).frame(width: 23)
                VStack(alignment: .leading, spacing: 3) {
                    Text(title).font(VoiceTheme.font(13, medium: true)).fixedSize(horizontal: false, vertical: true)
                    Text(caption).font(VoiceTheme.font(11)).foregroundColor(VoiceTheme.secondary)
                }
                Spacer(minLength: 4)
                if selected { Image(systemName: "checkmark").font(.system(size: 13, weight: .medium)).accessibilityHidden(true) }
            }.foregroundColor(selected ? VoiceTheme.green : VoiceTheme.ink).padding(12).frame(maxWidth: .infinity, alignment: .leading)
                .background(selected ? VoiceTheme.greenFill : Color.clear).clipShape(RoundedRectangle(cornerRadius: 8))
        }.buttonStyle(.plain).accessibilityLabel(title).accessibilityValue(selected ? "已选择" : "未选择")
    }
}

private struct ReminderList: View {
    @ObservedObject var model: VoicePanelModel
    var body: some View {
        ScrollView(.vertical, showsIndicators: model.listContentHeight > model.maximumListHeight) {
            VStack(spacing: 9) {
                ForEach(model.alerts) { alert in ReminderCard(alert: alert, model: model) }
            }.padding(.horizontal, 13).padding(.bottom, 14)
                .background(GeometryReader { geometry in Color.clear.preference(key: ListHeightKey.self, value: geometry.size.height) })
        }
        .frame(height: min(model.listContentHeight, model.maximumListHeight))
        .onPreferenceChange(ListHeightKey.self) { if $0 > 1 && abs(model.listContentHeight - $0) > 0.5 { model.listContentHeight = $0 } }
    }
}

private struct ReminderCard: View {
    let alert: VoiceAlert
    @ObservedObject var model: VoicePanelModel
    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack(spacing: 8) {
                Text(alert.title).font(VoiceTheme.font(12, medium: true)).lineLimit(1).truncationMode(.middle).help(alert.title)
                Spacer(minLength: 4)
                HStack(spacing: 5) {
                    Circle().fill(alert.isResult ? VoiceTheme.green : VoiceTheme.amber).frame(width: 5, height: 5)
                    Text(alert.badge).font(VoiceTheme.font(11)).foregroundColor(alert.isResult ? VoiceTheme.green : VoiceTheme.amber)
                }.fixedSize()
            }.padding(.bottom, 9)
            HStack(alignment: .center, spacing: 14) {
                VStack(alignment: .leading, spacing: 0) {
                    Text(alert.summary).font(VoiceTheme.font(15, medium: true)).fixedSize(horizontal: false, vertical: true)
                        .help(alert.detail.isEmpty ? alert.summary : alert.detail)
                    Text(model.meta(alert)).font(VoiceTheme.font(11)).monospacedDigit().foregroundColor(VoiceTheme.secondary).padding(.top, 5)
                    HStack(spacing: 7) {
                        Menu {
                            ForEach([5,15,30], id: \.self) { minutes in Button("\(minutes) 分钟") { model.action(["action":"snooze", "id":alert.id, "seconds":minutes * 60]) } }
                        } label: { Text("稍后").font(VoiceTheme.font(12)).foregroundColor(VoiceTheme.secondary).padding(.horizontal, 7).padding(.vertical, 6) }
                            .menuStyle(.borderlessButton).menuIndicator(.hidden).fixedSize().help("选择稍后提醒的时间")
                        IconAction(symbol: "speaker.wave.2", label: "再次播报「\(alert.title)」", disabled: !model.canPlay(alert)) { model.action(["action":"replay", "id":alert.id]) }
                        Spacer(minLength: 0)
                    }.padding(.top, 11)
                }.frame(maxWidth: .infinity, alignment: .leading)
                Button(alert.ackTitle) { model.action(["action":"ack", "id":alert.id]) }
                    .buttonStyle(AcknowledgeButtonStyle(isResult: alert.isResult))
                    .accessibilityIdentifier("ack-" + alert.id)
                    .help(alert.kind == "approval" ? "停止这条提醒，审批仍在原聊天处理" : "停止这条提醒")
            }
        }.padding(15).frame(maxWidth: .infinity, alignment: .leading)
            .background(VoiceTheme.paper).clipShape(RoundedRectangle(cornerRadius: 12))
            .overlay(RoundedRectangle(cornerRadius: 12).stroke(VoiceTheme.line, lineWidth: 1))
            .accessibilityElement(children: .contain)
    }
}
