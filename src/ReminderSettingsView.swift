import SwiftUI

private typealias ReminderDraftState<Value> = SwiftUI.State<Value>

private struct ReminderRuleDraft {
    var enabled = true
    var limited = false
    var count = "1"
    var useGlobal = true
    var intervals = ["30", "60", "180"]
    init(_ raw: [String: Any], global: [Int]) {
        enabled = raw["enabled"] as? Bool ?? true
        let cap = raw["max_plays"] as? Int ?? 0
        limited = cap > 0; count = String(max(1, cap))
        let custom = raw["intervals"] as? [Int]
        useGlobal = custom == nil
        intervals = (custom ?? global).map(String.init)
    }
    var patch: [String: Any]? {
        guard !limited || (Int(count).map { (1...99).contains($0) } == true) else { return nil }
        let values = intervals.compactMap(Int.init)
        guard useGlobal || (values.count == 3 && values.allSatisfy { (5...3600).contains($0) }) else { return nil }
        return ["enabled": enabled, "max_plays": limited ? Int(count)! : 0, "intervals": useGlobal ? NSNull() : values]
    }
    func matches(_ raw: [String: Any]) -> Bool {
        guard let patch else { return false }
        return patch["enabled"] as? Bool == (raw["enabled"] as? Bool ?? true)
            && patch["max_plays"] as? Int == (raw["max_plays"] as? Int ?? 0)
            && patch["intervals"] as? [Int] == raw["intervals"] as? [Int]
    }
}

private struct RuleEditor: View {
    @ObservedObject var model: VoicePanelModel
    let kind: String
    let title: String
    @ReminderDraftState private var draft: ReminderRuleDraft
    private var raw: [String: Any] { model.reminderRules[kind] as? [String: Any] ?? [:] }
    private var signature: String {
        (try? JSONSerialization.data(withJSONObject: raw, options: [.sortedKeys])).flatMap { String(data: $0, encoding: .utf8) } ?? ""
    }
    init(model: VoicePanelModel, kind: String, title: String) {
        self.model = model; self.kind = kind; self.title = title
        _draft = State(initialValue: ReminderRuleDraft(model.reminderRules[kind] as? [String: Any] ?? [:], global: model.speech["intervals"] as? [Int] ?? [30,60,180]))
    }
    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Text(title).font(VoiceTheme.font(13, medium: true))
                Spacer()
                Toggle(title + "语音", isOn: $draft.enabled).toggleStyle(PersistentSwitchStyle()).labelsHidden()
            }
            Text("关闭此类语音后，待办卡片仍会保留。")
                .font(VoiceTheme.font(10)).foregroundColor(VoiceTheme.secondary)
            HStack {
                Text("自动播报").font(VoiceTheme.font(12))
                Spacer()
                Picker("播报次数", selection: $draft.limited) {
                    Text("持续到接手").tag(false)
                    Text("限制次数").tag(true)
                }.labelsHidden().frame(width: 160).accessibilityLabel(title + "播报方式")
            }
            if draft.limited {
                HStack(spacing: 8) {
                    Text("最多").font(VoiceTheme.font(12))
                    TextField("1", text: $draft.count).textFieldStyle(.plain).multilineTextAlignment(.center)
                        .font(VoiceTheme.font(13)).padding(7).frame(width: 52).background(VoiceTheme.soft).clipShape(RoundedRectangle(cornerRadius: 6))
                        .accessibilityLabel(title + "最多播报次数")
                    Text("次 · 1 次表示只播一次").font(VoiceTheme.font(11)).foregroundColor(VoiceTheme.secondary)
                    Spacer(minLength: 0)
                }
            }
            Toggle("使用全局重复间隔", isOn: $draft.useGlobal).font(VoiceTheme.font(11)).toggleStyle(.checkbox)
                .accessibilityLabel(title + "使用全局重复间隔")
            if draft.useGlobal {
                Text(model.intervalSummary).font(VoiceTheme.font(10)).foregroundColor(VoiceTheme.secondary)
            } else {
                HStack(spacing: 9) {
                    ForEach(0..<3) { index in
                        VStack(alignment: .leading, spacing: 5) {
                            Text(["首次重复", "再次重复", "之后每次"][index]).font(VoiceTheme.font(10)).foregroundColor(VoiceTheme.secondary)
                            HStack(spacing: 3) {
                                TextField("秒", text: Binding(get: { draft.intervals[index] }, set: { draft.intervals[index] = $0 }))
                                    .textFieldStyle(.plain).font(VoiceTheme.font(12)).monospacedDigit()
                                    .accessibilityLabel(title + "第\(index + 1)档间隔秒数")
                                Text("秒").font(VoiceTheme.font(10)).foregroundColor(VoiceTheme.secondary)
                            }.padding(8).background(VoiceTheme.soft).clipShape(RoundedRectangle(cornerRadius: 6))
                        }.frame(maxWidth: .infinity)
                    }
                }
            }
            HStack {
                Text(draft.patch == nil ? "次数须为 1–99；间隔须为 5–3600 秒。" : draft.matches(raw) ? "已保存" : "修改后点击保存")
                    .font(VoiceTheme.font(10)).foregroundColor(draft.patch == nil ? VoiceTheme.amber : VoiceTheme.secondary)
                Spacer(minLength: 4)
                Button("保存") { if let patch = draft.patch { model.action(["action":"set_reminder_rules", "rules":[kind:patch]]) } }
                    .buttonStyle(.bordered).font(VoiceTheme.font(11))
                    .disabled(!model.connected || draft.patch == nil || draft.matches(raw))
                    .accessibilityLabel("保存" + title + "规则")
            }
        }.padding(14).background(VoiceTheme.paper).clipShape(RoundedRectangle(cornerRadius: 11))
            .overlay(RoundedRectangle(cornerRadius: 11).stroke(VoiceTheme.line, lineWidth: 1))
            .disabled(!model.connected)
            .onChange(of: signature) { _ in draft = ReminderRuleDraft(raw, global: model.speech["intervals"] as? [Int] ?? [30,60,180]) }
    }
}

struct ReminderRulesView: View {
    @ObservedObject var model: VoicePanelModel
    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack {
                Text("按类型设置提醒").font(VoiceTheme.font(17, medium: true))
                Spacer()
                Button { model.rulesOpen = false } label: { Image(systemName: "xmark").frame(width: 28, height: 28) }
                    .buttonStyle(.plain).accessibilityLabel("返回提醒设置")
            }.padding(.horizontal, 20).padding(.top, 18).padding(.bottom, 14)
            ScrollView {
                VStack(spacing: 12) {
                    RuleEditor(model: model, kind: "result", title: "任务完成")
                    RuleEditor(model: model, kind: "approval", title: "等待审批")
                    RuleEditor(model: model, kind: "question", title: "需要回答")
                    RuleEditor(model: model, kind: "blocked", title: "异常关注")
                    VStack(alignment: .leading, spacing: 9) {
                        Text("额度提醒保持单次播报，可在用量详情独立开关及设置阈值。")
                            .font(VoiceTheme.font(11)).foregroundColor(VoiceTheme.secondary)
                        Button("打开用量提醒设置") { model.rulesOpen = false; model.usageOpen = true }
                            .buttonStyle(.plain).font(VoiceTheme.font(12)).foregroundColor(VoiceTheme.green)
                    }.frame(maxWidth: .infinity, alignment: .leading).padding(13)
                    if !model.rulesError.isEmpty { Text(model.rulesError).font(VoiceTheme.font(11)).foregroundColor(VoiceTheme.amber) }
                }.padding(.horizontal, 20).padding(.vertical, 2)
            }.frame(height: model.maximumSettingsHeight)
            Text("达到次数后保留卡片；手动重播仍可使用。")
                .font(VoiceTheme.font(11)).foregroundColor(VoiceTheme.secondary).padding(20)
        }
    }
}

private struct QuietDraft {
    var enabled = false
    var start = "23:00"
    var end = "09:00"
    var days = [0,1,2,3,4,5,6]
    var approval = false
    init(_ raw: [String: Any]) {
        enabled = raw["enabled"] as? Bool ?? false
        start = raw["start"] as? String ?? "23:00"; end = raw["end"] as? String ?? "09:00"
        days = raw["days"] as? [Int] ?? [0,1,2,3,4,5,6]
        approval = raw["allow_approval"] as? Bool ?? false
    }
    var valid: Bool {
        let pattern = "^(?:[01][0-9]|2[0-3]):[0-5][0-9]$"
        return start.range(of: pattern, options: .regularExpression) != nil && end.range(of: pattern, options: .regularExpression) != nil && start != end && !days.isEmpty
    }
    var patch: [String: Any] { ["enabled":enabled,"start":start,"end":end,"days":days.sorted(),"allow_approval":approval] }
    func matches(_ raw: [String: Any]) -> Bool {
        let saved = QuietDraft(raw)
        return enabled == saved.enabled && start == saved.start && end == saved.end && days.sorted() == saved.days.sorted() && approval == saved.approval
    }
}

struct QuietHoursView: View {
    @ObservedObject var model: VoicePanelModel
    @ReminderDraftState private var draft: QuietDraft
    init(model: VoicePanelModel) { self.model = model; _draft = State(initialValue: QuietDraft(model.quiet)) }
    private var signature: String { "\(model.quiet["enabled"] ?? false)|\(model.quiet["start"] ?? "")|\(model.quiet["end"] ?? "")|\(model.quiet["days"] ?? [])|\(model.quiet["allow_approval"] ?? false)" }
    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack {
                Text("定时免打扰").font(VoiceTheme.font(17, medium: true))
                Spacer()
                Button { model.quietHoursOpen = false } label: { Image(systemName: "xmark").frame(width: 28, height: 28) }
                    .buttonStyle(.plain).accessibilityLabel("返回提醒设置")
            }.padding(.bottom, 8)
            Text(model.quietActive ? "当前处于免打扰时段" : model.quiet["enabled"] as? Bool == true ? "当前处于可播报时段" : "当前未开启，保存后生效")
                .font(VoiceTheme.font(11)).foregroundColor(VoiceTheme.secondary).padding(.bottom, 17)
            ScrollView {
                VStack(alignment: .leading, spacing: 18) {
                    HStack {
                        Text("启用定时免打扰").font(VoiceTheme.font(13, medium: true))
                        Spacer()
                        Toggle("启用定时免打扰", isOn: $draft.enabled).toggleStyle(PersistentSwitchStyle()).labelsHidden()
                    }
                    HStack(spacing: 10) {
                        VStack(alignment: .leading, spacing: 6) {
                            Text("开始").font(VoiceTheme.font(11)).foregroundColor(VoiceTheme.secondary)
                            TextField("23:00", text: $draft.start).textFieldStyle(.plain).monospacedDigit().padding(10).background(VoiceTheme.soft).clipShape(RoundedRectangle(cornerRadius: 7)).accessibilityLabel("免打扰开始时间")
                        }
                        Text("至").foregroundColor(VoiceTheme.secondary)
                        VStack(alignment: .leading, spacing: 6) {
                            Text("结束").font(VoiceTheme.font(11)).foregroundColor(VoiceTheme.secondary)
                            TextField("09:00", text: $draft.end).textFieldStyle(.plain).monospacedDigit().padding(10).background(VoiceTheme.soft).clipShape(RoundedRectangle(cornerRadius: 7)).accessibilityLabel("免打扰结束时间")
                        }
                    }
                    VStack(alignment: .leading, spacing: 8) {
                        Text("开始日期").font(VoiceTheme.font(12, medium: true))
                        HStack(spacing: 5) {
                            ForEach(0..<7) { day in
                                Button(["一","二","三","四","五","六","日"][day]) {
                                    if draft.days.contains(day) { draft.days.removeAll { $0 == day } } else { draft.days.append(day) }
                                }.buttonStyle(.plain).font(VoiceTheme.font(12))
                                    .frame(maxWidth: .infinity).frame(height: 31)
                                    .foregroundColor(draft.days.contains(day) ? VoiceTheme.green : VoiceTheme.secondary)
                                    .background(draft.days.contains(day) ? VoiceTheme.greenFill : VoiceTheme.soft).clipShape(RoundedRectangle(cornerRadius: 6))
                                    .accessibilityLabel("星期" + ["一","二","三","四","五","六","日"][day]).accessibilityValue(draft.days.contains(day) ? "已选择" : "未选择")
                            }
                        }
                        Text("跨午夜时延续到次日，例如周一 23:00 至周二 09:00。")
                            .font(VoiceTheme.font(10)).foregroundColor(VoiceTheme.secondary).fixedSize(horizontal: false, vertical: true)
                    }
                    Toggle("允许审批提醒出声", isOn: $draft.approval).font(VoiceTheme.font(12)).toggleStyle(.checkbox)
                    Text("时段内保留待办卡片；结束后只播报仍未处理的事项。手动暂停和提醒总开关始终优先。")
                        .font(VoiceTheme.font(11)).foregroundColor(VoiceTheme.secondary).fixedSize(horizontal: false, vertical: true)
                }.padding(14).background(VoiceTheme.paper).clipShape(RoundedRectangle(cornerRadius: 11)).disabled(!model.connected)
            }.frame(height: min(365, model.maximumSettingsHeight))
            if !draft.valid { Text("请填写不同的有效时间，并至少选择一天。") .font(VoiceTheme.font(11)).foregroundColor(VoiceTheme.amber).padding(.top, 9) }
            if let error = model.quiet["error"] as? String, !error.isEmpty { Text(error).font(VoiceTheme.font(11)).foregroundColor(VoiceTheme.amber).padding(.top, 9) }
            HStack {
                Text(draft.matches(model.quiet) ? "已保存 · 使用本机时间" : "有修改，保存后生效").font(VoiceTheme.font(11)).foregroundColor(VoiceTheme.secondary)
                Spacer()
                Button("保存") { model.action(["action":"set_quiet_hours", "settings":draft.patch]) }
                    .buttonStyle(.borderedProminent).tint(VoiceTheme.primary).font(VoiceTheme.font(12))
                    .disabled(!model.connected || !draft.valid || draft.matches(model.quiet)).accessibilityLabel("保存定时免打扰设置")
            }.padding(.top, 18)
        }.padding(20)
            .onChange(of: signature) { _ in draft = QuietDraft(model.quiet) }
    }
}
