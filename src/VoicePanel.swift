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
    init?(_ raw: [String: Any]) {
        guard let id = raw["id"] as? String else { return nil }
        self.id = id; title = raw["title"] as? String ?? "当前任务"
        detail = raw["detail"] as? String ?? ""; kind = raw["kind"] as? String ?? "result"
        nextAt = raw["nextAt"] as? Double ?? 0; count = raw["count"] as? Int ?? 0
        state = raw["state"] as? String ?? "pending"
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
    @Published var devicePickerOpen = false
    @Published var connectionConfigured = false
    @Published var connectionMessage = "正在检查连接"
    @Published var startupEnabled = false
    @Published var serviceError: String?
    @Published var recentTitle: String?
    @Published var listContentHeight: CGFloat = 160
    var maximumListHeight: CGFloat = 380
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
    var audio: [String: Any] { snapshot["audio"] as? [String: Any] ?? [:] }
    var device: String { audio["device"] as? String ?? "播报设备" }
    var audioAvailable: Bool { audio["available"] as? Bool ?? false }
    var audioReady: Bool { audio["ready"] as? Bool ?? false }
    var speaking: Bool { snapshot["speakingId"] is String }
    var eventsAvailable: Bool { (snapshot["monitor"] as? [String: Any])?["state"] as? String == "connected" }
    var followSystem: Bool { audio["followSystem"] as? Bool ?? false }
    var outputs: [VoiceOutput] { (audio["devices"] as? [[String: Any]] ?? []).compactMap(VoiceOutput.init) }
    var defaultName: String { audio["defaultName"] as? String ?? "" }
    var displayDevice: String { followSystem ? "跟随系统输出" : device }
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
    var canPlay: Bool { connected && enabled && audioReady && !muted }
    var audioNote: String {
        if !audioAvailable { return "未连接 · 待处理事项已保留" }
        if !audioReady { return audio["error"] as? String ?? "扬声器暂时无法播报" }
        if followSystem { return speaking ? "正在播报 · 接手后停止" : "当前：" + device }
        return speaking ? "正在播报 · 接手后停止" : "已连接 · 声音从此设备播放"
    }
    var heading: (title: String, subtitle: String, icon: String, tone: Int) {
        if let error = serviceError { return ("提醒服务已停止", error, "exclamationmark", 1) }
        if !connected { return ("正在连接", "准备好后，有事我会喊你", "waveform", 0) }
        if !enabled { return ("提醒已关闭", "重新开启后，只接收新的提醒", "bell.slash", 0) }
        if !audioAvailable { return ("扬声器未连接", "待处理事项会保留，连接后继续播报", "speaker.slash", 1) }
        if !audioReady { return ("扬声器暂时无法播报", audioNote, "speaker.slash", 1) }
        if muted { return ("提醒已暂停", "\(max(1, Int(ceil((mutedUntil - now) / 60)))) 分钟后恢复，待处理事项会保留", "pause", 0) }
        if !alerts.isEmpty { return ("\(alerts.count) 件事需要你", "重要的事，听到后再来处理", "bell.badge", 1) }
        if !eventsAvailable { return ("等待 Codex 连接", "未读到本机任务事件，请先打开 Codex", "link", 0) }
        if !connectionConfigured { return ("完成提醒已就绪", "连接 Codex，以增加审批与提问提醒", "checkmark", 2) }
        return ("一切就绪", "有结果、等确认时，我会喊你", "checkmark", 2)
    }
    func meta(_ alert: VoiceAlert) -> String {
        if !connected { return "服务连接中 · 待处理事项已保留" }
        if !audioReady { return "音箱暂不可用 · 恢复后继续提醒" }
        if muted { return "已暂停 · 恢复后继续提醒" }
        let seconds = max(0, Int(ceil(alert.nextAt - now)))
        let delay = seconds >= 60 ? "\(Int(ceil(Double(seconds) / 60))) 分钟" : "\(seconds) 秒"
        if alert.state == "snoozed" { return "已安排稍后 · \(delay)后再提醒" }
        if snapshot["speakingId"] as? String == alert.id { return "正在播报 · 接手后停止" }
        if alert.count == 0 { return seconds > 0 ? "\(delay)后提醒" : "等待播报" }
        return "已提醒 \(alert.count) 次 · " + (seconds > 0 ? "\(delay)后再次提醒" : "等待播报")
    }
    func pauseOrResume() { action(["action": muted ? "unmute" : "mute", "seconds": 900]) }
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

private struct ListHeightKey: PreferenceKey {
    static var defaultValue: CGFloat = 0
    static func reduce(value: inout CGFloat, nextValue: () -> CGFloat) { value = nextValue() }
}

struct VoicePanelView: View {
    @ObservedObject var model: VoicePanelModel
    var body: some View {
        Group {
            if model.devicePickerOpen { devicePicker }
            else if model.settingsOpen { settings }
            else { main }
        }
        .frame(width: 410)
        .fixedSize(horizontal: true, vertical: true)
        .font(VoiceTheme.font(13)).foregroundColor(VoiceTheme.ink)
        .background(VoiceTheme.background)
        .clipShape(RoundedRectangle(cornerRadius: 18))
        .overlay(RoundedRectangle(cornerRadius: 18).stroke(VoiceTheme.line, lineWidth: 1))
        .onExitCommand {
            if model.devicePickerOpen { model.devicePickerOpen = false }
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
            deviceRow
            HStack(spacing: 8) {
                Button(action: model.pauseOrResume) { Label(model.muted ? "恢复提醒" : "暂停 15 分钟", systemImage: model.muted ? "play" : "pause") }
                    .buttonStyle(PanelButtonStyle(kind: .quiet)).disabled(!model.enabled || !model.connected)
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
            .toggleStyle(.switch).tint(VoiceTheme.green).labelsHidden().controlSize(.small).disabled(!model.connected)
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
                settingRow("需要你时，重复提醒", "30 秒 → 1 分钟 → 每 3 分钟") {
                    Image(systemName: "repeat").font(.system(size: 16)).foregroundColor(VoiceTheme.secondary)
                }
            }.background(VoiceTheme.paper).clipShape(RoundedRectangle(cornerRadius: 11)).overlay(RoundedRectangle(cornerRadius: 11).stroke(VoiceTheme.line, lineWidth: 1))
            Text("启动与运行").font(VoiceTheme.font(11)).foregroundColor(VoiceTheme.secondary).padding(.top, 20).padding(.bottom, 8)
            VStack(spacing: 0) {
                settingRow("登录后自动启动", "后台安静运行，需要时再出现") {
                    Toggle("登录后自动启动", isOn: Binding(get: { model.startupEnabled }, set: model.changeStartup)).toggleStyle(.switch).tint(VoiceTheme.green).labelsHidden().controlSize(.small)
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
            HStack {
                Circle().fill(model.connected ? VoiceTheme.green : VoiceTheme.amber).frame(width: 5, height: 5)
                Text(model.connected ? "提醒服务运行正常" : "提醒服务未连接").font(VoiceTheme.font(11)).foregroundColor(VoiceTheme.secondary)
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
            Text(alert.summary).font(VoiceTheme.font(15, medium: true)).fixedSize(horizontal: false, vertical: true)
                .help(alert.detail.isEmpty ? alert.summary : alert.detail)
            Text(model.meta(alert)).font(VoiceTheme.font(11)).monospacedDigit().foregroundColor(VoiceTheme.secondary).padding(.top, 5)
            HStack(spacing: 7) {
                Button(alert.ackTitle) { model.action(["action":"ack", "id":alert.id]) }
                    .buttonStyle(PanelButtonStyle(kind: alert.isResult ? .secondary : .primary))
                    .accessibilityIdentifier("ack-" + alert.id)
                    .help(alert.kind == "approval" ? "停止这条提醒，审批仍在原聊天处理" : "停止这条提醒")
                Menu {
                    ForEach([5,15,30], id: \.self) { minutes in Button("\(minutes) 分钟") { model.action(["action":"snooze", "id":alert.id, "seconds":minutes * 60]) } }
                } label: { Text("稍后").font(VoiceTheme.font(12)).foregroundColor(VoiceTheme.secondary).padding(.horizontal, 7).padding(.vertical, 6) }
                    .menuStyle(.borderlessButton).menuIndicator(.hidden).fixedSize().help("选择稍后提醒的时间")
                IconAction(symbol: "speaker.wave.2", label: "再次播报「\(alert.title)」", disabled: !model.canPlay) { model.action(["action":"replay", "id":alert.id]) }
                Spacer(minLength: 0)
            }.padding(.top, 13)
        }.padding(15).frame(maxWidth: .infinity, alignment: .leading)
            .background(VoiceTheme.paper).clipShape(RoundedRectangle(cornerRadius: 12))
            .overlay(RoundedRectangle(cornerRadius: 12).stroke(VoiceTheme.line, lineWidth: 1))
            .accessibilityElement(children: .contain)
    }
}
