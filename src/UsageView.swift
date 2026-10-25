import SwiftUI

struct UsageWindow: Identifiable {
    let id: String
    let remaining: Int
    let minutes: Double?
    let resetsAt: Double?

    init?(_ raw: [String: Any]) {
        guard let id = raw["id"] as? String, let remaining = raw["remainingPercent"] as? Int,
              (0...100).contains(remaining) else { return nil }
        self.id = id; self.remaining = remaining
        let duration = (raw["windowMinutes"] as? NSNumber)?.doubleValue
        minutes = duration.flatMap { $0.isFinite && $0 > 0 && $0 <= 10_000_000 ? $0 : nil }
        let reset = (raw["resetsAt"] as? NSNumber)?.doubleValue
        resetsAt = reset.flatMap { $0.isFinite && $0 > 0 && $0 <= 253_402_300_799 ? $0 : nil }
    }
    var title: String {
        guard let minutes else { return id == "secondary" ? "另一额度周期" : "当前额度周期" }
        if minutes == 10080 { return "每周额度" }
        if minutes == 1440 { return "每日额度" }
        if minutes.truncatingRemainder(dividingBy: 1440) == 0 { return "\(Int(minutes / 1440)) 天额度" }
        if minutes.truncatingRemainder(dividingBy: 60) == 0 { return "\(Int(minutes / 60)) 小时额度" }
        return "\(Int(minutes)) 分钟额度"
    }
    func resetNote(now:Double) -> String {
        guard let resetsAt else {return "自动同步周期"}
        let minutes=max(0,Int(ceil((resetsAt-now)/60)))
        if minutes==0 {return "等待周期更新"}
        if minutes>=1440 {return "\(minutes/1440)天\((minutes%1440)/60)小时后重置"}
        if minutes>=60 {return "\(minutes/60)小时\(minutes%60 == 0 ? "" : "\(minutes%60)分")后重置"}
        return "\(minutes)分钟后重置"
    }
}

struct CodexUsage {
    let state: String
    let message: String
    let remaining: Int?
    let windows: [UsageWindow]
    let fetchedAt: Double
    let lastAttemptAt: Double
    let refreshing: Bool
    let plan: String
    let now: Double
    let warningThreshold: Int

    init(_ raw: [String: Any], now: Double, warningThreshold: Int = 20) {
        self.now = now
        self.warningThreshold = warningThreshold
        fetchedAt = raw["fetchedAt"] as? Double ?? 0
        lastAttemptAt = raw["lastAttemptAt"] as? Double ?? 0
        refreshing = raw["refreshing"] as? Bool ?? false
        let parsed = (raw["windows"] as? [[String: Any]] ?? []).compactMap(UsageWindow.init)
        let incoming = raw["state"] as? String ?? "loading"
        let expired = !fetchedAt.isFinite || now - fetchedAt >= 180 || fetchedAt > now + 5 || parsed.contains { ($0.resetsAt ?? .infinity) <= now }
        let percent = raw["remainingPercent"] as? Int
        let valid = percent.map { (0...100).contains($0) } == true && !parsed.isEmpty
        state = incoming == "ready" && expired ? "stale" : incoming == "ready" && !valid ? "unavailable" : incoming
        remaining = state == "ready" ? percent : nil
        windows = state == "ready" ? parsed : []
        message = state == "stale" ? "用量数据已过期，等待重新同步。" : raw["message"] as? String ?? "正在读取 Codex 用量"
        plan = ["pro":"Pro", "plus":"Plus", "free":"Free", "team":"Team", "business":"Business", "enterprise":"Enterprise", "edu":"Edu"][raw["planType"] as? String ?? ""] ?? ""
    }
    var percentage: String { remaining.map { "\($0)%" } ?? "—" }
    var low: Bool { (remaining ?? 100) < warningThreshold }
    var canRefresh: Bool { !refreshing && now - lastAttemptAt >= 10 }
    var updateNote: String {
        if refreshing { return "正在同步…" }
        guard state == "ready" else {
            return ["loading":"正在读取用量", "signed_out":"等待登录 Codex", "api_key":"API Key 账号", "missing_cli":"未找到 Codex", "unsupported":"请更新 Codex", "stale":"数据已过期"][state] ?? "同步失败 · 自动重试"
        }
        let seconds = max(0, Int(now - fetchedAt))
        return seconds < 15 ? "刚刚更新 · 每分钟同步" : seconds < 60 ? "\(seconds) 秒前更新" : "\(seconds / 60) 分钟前更新"
    }
}

struct UsageSummaryRow: View {
    @ObservedObject var model:VoicePanelModel
    var body:some View {
        VStack(spacing:12) {
            UsageOverviewCard(model:model,compact:true)
            SubscriptionServiceLink()
        }.padding(.horizontal,18).padding(.bottom,12)
    }
}

struct UsageRefreshButton: View {
    @ObservedObject var model: VoicePanelModel
    var compact = false
    var body: some View {
        Button { model.action(["action":"refresh_usage"]) } label: {
            HStack(spacing: 6) {
                Image(systemName: "arrow.clockwise").font(.system(size: 12))
                if !compact { Text(model.usage.refreshing ? "同步中…" : "刷新用量").font(VoiceTheme.font(12)) }
            }.foregroundColor(VoiceTheme.green).padding(compact ? 7 : 9).contentShape(Rectangle())
        }.buttonStyle(.plain).disabled(!model.connected || !model.usage.canRefresh)
            .opacity(!model.connected || !model.usage.canRefresh ? 0.45 : 1)
            .accessibilityLabel("刷新 Codex 用量").help("每分钟自动同步；手动刷新间隔至少 10 秒")
    }
}

private typealias UsageDraftState<Value> = SwiftUI.State<Value>

private struct UsageContentHeightKey: PreferenceKey {
    static var defaultValue: CGFloat = 0
    static func reduce(value: inout CGFloat, nextValue: () -> CGFloat) { value = nextValue() }
}

private struct UsageLowSettingsCard: View {
    @ObservedObject var model: VoicePanelModel
    @UsageDraftState private var threshold: String

    init(model: VoicePanelModel) {
        self.model = model
        _threshold = State(initialValue: String(model.usageLowThreshold))
    }
    private var value: Int? {
        guard let result = Int(threshold.trimmingCharacters(in: .whitespaces)), (1...99).contains(result) else { return nil }
        return result
    }
    private var canSave: Bool { model.connected && value != nil && value != model.usageLowThreshold }
    private func save() {
        if let value, canSave { model.action(["action":"set_usage_low_settings", "settings":["threshold":value]]) }
    }
    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Text("低额度语音提醒").font(VoiceTheme.font(12, medium: true))
                Spacer()
                Toggle("低额度语音提醒", isOn: Binding(get: { model.usageLowEnabled }, set: { model.action(["action":"set_usage_low_settings", "settings":["enabled":$0]]) }))
                    .toggleStyle(PersistentSwitchStyle()).labelsHidden().disabled(!model.connected)
            }
            HStack(spacing: 8) {
                Text("剩余低于").font(VoiceTheme.font(12))
                TextField("20", text: $threshold).textFieldStyle(.plain)
                    .font(VoiceTheme.font(14, medium: true)).monospacedDigit().multilineTextAlignment(.center)
                    .padding(.vertical, 6).frame(width: 48).background(VoiceTheme.paper).clipShape(RoundedRectangle(cornerRadius: 6))
                    .overlay(RoundedRectangle(cornerRadius: 6).stroke(value == nil ? VoiceTheme.amber : VoiceTheme.line, lineWidth: 1))
                    .accessibilityLabel("低额度提醒阈值，百分比").onSubmit(save).disabled(!model.connected)
                Text("% 时提醒").font(VoiceTheme.font(12))
                Spacer(minLength: 0)
                Button("保存", action: save).buttonStyle(.plain).font(VoiceTheme.font(11, medium: true))
                    .padding(.horizontal, 11).padding(.vertical, 7).foregroundColor(VoiceTheme.primaryText)
                    .background(VoiceTheme.primary).clipShape(RoundedRectangle(cornerRadius: 6))
                    .disabled(!canSave).opacity(canSave ? 1 : 0.4)
                    .accessibilityLabel("保存低额度提醒阈值")
            }
            Text(value == nil ? "请输入 1–99 之间的整数。" : value == model.usageLowThreshold ? "阈值已保存 · 同一周期、同一阈值只提醒一次。" : "点“保存”后生效，并检查最新用量。")
                .font(VoiceTheme.font(10)).foregroundColor(value == nil ? VoiceTheme.amber : VoiceTheme.secondary)
                .fixedSize(horizontal: false, vertical: true)
            Button { model.action(["action":model.usageLowPreviewing ? "stop_usage_low_preview" : "preview_usage_low"]) } label: {
                Label(model.usageLowPreviewing ? "停止试听" : "试听低额度提醒", systemImage: model.usageLowPreviewing ? "stop.fill" : "speaker.wave.2")
                    .font(VoiceTheme.font(11)).foregroundColor(VoiceTheme.green).padding(.vertical, 4).contentShape(Rectangle())
            }.buttonStyle(.plain)
                .disabled(!model.connected || (!model.usageLowPreviewing && (!model.canPlay || model.speaking || value != model.usageLowThreshold)))
                .help("使用已保存的阈值，只试听一次，不改变真实用量")
            if !model.usageLowError.isEmpty {
                Text(model.usageLowError).font(VoiceTheme.font(10)).foregroundColor(VoiceTheme.amber).fixedSize(horizontal: false, vertical: true)
            }
        }.padding(13).background(VoiceTheme.soft).clipShape(RoundedRectangle(cornerRadius: 10)).padding(.top, 14)
            .onChange(of: model.usageLowThreshold) { threshold = String($0) }
    }
}

struct UsageDetailView: View {
    @ObservedObject var model: VoicePanelModel
    @UsageDraftState private var contentHeight: CGFloat = 440
    private var usage: CodexUsage { model.usage }
    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack {
                Text("Codex 用量").font(VoiceTheme.font(17, medium: true))
                Spacer()
                Button { model.usageOpen = false } label: {
                    Image(systemName: "xmark").font(.system(size: 13)).frame(width: 28, height: 28)
                }.buttonStyle(.plain).accessibilityLabel("返回提醒")
            }.padding(.bottom, 20)
            ScrollView {
                VStack(alignment: .leading, spacing: 0) {
            HStack(spacing:22) {
                UsageRing(remaining:usage.remaining,size:132,threshold:model.usageLowThreshold)
                VStack(alignment:.leading,spacing:7) {
                    Text("可用额度").font(VoiceTheme.font(18,medium:true))
                    Text(usage.windows.count>1 ? "按剩余较少的周期显示" : "当前额度周期").font(VoiceTheme.font(11)).foregroundColor(VoiceTheme.secondary)
                    if !usage.plan.isEmpty {Text(usage.plan).font(VoiceTheme.font(11,medium:true)).foregroundColor(VoiceTheme.accent).padding(.horizontal,9).padding(.vertical,4).background(VoiceTheme.greenFill).clipShape(Capsule())}
                }
                Spacer(minLength:0)
            }.padding(.bottom,8)
            Text(usage.updateNote).font(VoiceTheme.font(11)).foregroundColor(VoiceTheme.secondary).padding(.top, 5).padding(.bottom, 17)
            SubscriptionServiceLink().padding(.bottom, 16)
            if !usage.windows.isEmpty {
                VStack(spacing: 14) {
                    ForEach(usage.windows) { window in
                        VStack(alignment: .leading, spacing: 8) {
                            HStack {
                                Text(window.title).font(VoiceTheme.font(12, medium: true))
                                Spacer()
                                Text("剩余 \(window.remaining)%").font(VoiceTheme.font(12)).monospacedDigit()
                            }
                            GeometryReader { geometry in
                                ZStack(alignment: .leading) {
                                    Capsule().fill(VoiceTheme.soft)
                                    Capsule().fill(window.remaining < model.usageLowThreshold ? VoiceTheme.amber : VoiceTheme.green)
                                        .frame(width: geometry.size.width * CGFloat(window.remaining) / 100)
                                }
                            }.frame(height: 5)
                                .accessibilityElement(children: .ignore)
                                .accessibilityLabel(window.title).accessibilityValue("剩余 \(window.remaining)%")
                            if let reset = window.resetsAt {
                                Text("重置时间：" + Date(timeIntervalSince1970: reset).formatted(date: .abbreviated, time: .shortened))
                                    .font(VoiceTheme.font(10)).foregroundColor(VoiceTheme.secondary)
                            }
                        }
                    }
                }.padding(14).background(VoiceTheme.paper).clipShape(RoundedRectangle(cornerRadius: 14))
                    .overlay(RoundedRectangle(cornerRadius: 14).stroke(VoiceTheme.line, lineWidth: 1))
            } else {
                Label(usage.message, systemImage: usage.state == "loading" ? "clock" : "exclamationmark.circle")
                    .font(VoiceTheme.font(12)).foregroundColor(VoiceTheme.secondary).fixedSize(horizontal: false, vertical: true)
                    .padding(14).frame(maxWidth: .infinity, alignment: .leading).background(VoiceTheme.soft).clipShape(RoundedRectangle(cornerRadius: 14))
            }
            Text("读取本机 Codex 当前登录账号，每分钟自动同步。多个周期时，菜单栏显示剩余最少的一项。")
                .font(VoiceTheme.font(11)).foregroundColor(VoiceTheme.secondary).fixedSize(horizontal: false, vertical: true).padding(.top, 15)
            VStack(alignment: .leading, spacing: 7) {
                HStack {
                    Text("额度重置时播报").font(VoiceTheme.font(12, medium: true))
                    Spacer()
                    Toggle("额度重置时播报", isOn: Binding(get: { model.usageResetEnabled }, set: { model.action(["action":"set_usage_reset_enabled", "enabled":$0]) }))
                        .toggleStyle(PersistentSwitchStyle()).labelsHidden().disabled(!model.connected)
                }
                Text("确认回满且额度周期更新后，只播报一次。沿用声音设置，遵守提醒总开关和暂停。")
                    .font(VoiceTheme.font(10)).foregroundColor(VoiceTheme.secondary).fixedSize(horizontal: false, vertical: true)
                if !model.usageResetError.isEmpty {
                    Text(model.usageResetError).font(VoiceTheme.font(10)).foregroundColor(VoiceTheme.amber).fixedSize(horizontal: false, vertical: true)
                }
            }.padding(.top, 14).padding(.bottom, 3)
                .overlay(alignment: .top) { VoiceTheme.line.frame(height: 1).padding(.top, 3) }
                UsageLowSettingsCard(model: model)
                }.fixedSize(horizontal: false, vertical: true)
                    .background(GeometryReader { geometry in Color.clear.preference(key: UsageContentHeightKey.self, value: geometry.size.height) })
            }.frame(height: min(contentHeight, model.maximumSettingsHeight))
                .onPreferenceChange(UsageContentHeightKey.self) { if $0 > 1 && abs(contentHeight - $0) > 0.5 { contentHeight = $0 } }
            HStack {
                Button { model.action(["action":model.usageResetPreviewing ? "stop_usage_preview" : "preview_usage_reset"]) } label: {
                    Label(model.usageResetPreviewing ? "停止试听" : "试听重置提醒", systemImage: model.usageResetPreviewing ? "stop.fill" : "speaker.wave.2")
                        .font(VoiceTheme.font(11)).foregroundColor(VoiceTheme.green).padding(.vertical, 9).contentShape(Rectangle())
                }.buttonStyle(.plain)
                    .disabled(!model.connected || (!model.usageResetPreviewing && (!model.canPlay || model.speaking)))
                    .help("只试听一次，不改变真实额度，不创建待处理事项")
                Spacer()
                UsageRefreshButton(model: model)
            }.padding(.top, 16)
        }.padding(.horizontal, 20).padding(.top, 16).padding(.bottom, 16)
            .onDisappear {
                model.action(["action":"stop_usage_preview"])
                model.action(["action":"stop_usage_low_preview"])
            }
    }
}
