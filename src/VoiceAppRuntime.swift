import AppKit
import SwiftUI

final class ReminderPanel: NSPanel {
    override var canBecomeKey: Bool { true }
    override var canBecomeMain: Bool { false }
}

final class PanelHostingView: NSHostingView<VoicePanelView> {
    var measuredHeight: ((CGFloat) -> Void)?
    override func layout() {
        super.layout()
        measuredHeight?(intrinsicContentSize.height)
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate, NSWindowDelegate {
    var statusItem: NSStatusItem!
    var window: ReminderPanel!
    var hosting: PanelHostingView!
    let model = VoicePanelModel()
    var process: Process?
    var input: Pipe?
    var buffer = Data()
    var knownIDs = Set<String>()
    var runtimeURL: URL?
    var clock: Timer?
    var lastStartupCheck = Date.distantPast
    var quitting = false

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.accessory)
        if NSRunningApplication.runningApplications(withBundleIdentifier: "local.rico.CodexVoice").count > 1 {
            NSApp.terminate(nil); return
        }
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        statusItem.button?.image = NSImage(systemSymbolName: "waveform", accessibilityDescription: "Codex 语音提醒")
        statusItem.button?.imagePosition = .imageLeading
        statusItem.button?.target = self
        statusItem.button?.action = #selector(toggleWindow)
        statusItem.button?.toolTip = "Codex 语音提醒 · 点此打开控制面板"
        model.action = { [weak self] in self?.send($0) }
        model.changeStartup = { [weak self] in self?.setStartup($0) }
        model.hide = { [weak self] in self?.hidePanel("manual-hide") }
        model.retry = { [weak self] in self?.startEngine() }
        model.connectCodex = { [weak self] in self?.installConnection() }
        model.maximumListHeight = max(140, min(380, (NSScreen.main?.visibleFrame.height ?? 900) - 300))
        buildWindow()
        startEngine()
        refreshClock()
        refreshConnection()
        if !CommandLine.arguments.contains("--background") { showWindow() }
        clock = Timer.scheduledTimer(withTimeInterval: 1, repeats: true) { [weak self] _ in self?.refreshClock() }
    }

    func buildWindow() {
        window = ReminderPanel(contentRect: NSRect(x: 0, y: 0, width: 410, height: 430), styleMask: [.borderless, .nonactivatingPanel], backing: .buffered, defer: false)
        window.title = "Codex 语音提醒"
        window.isReleasedWhenClosed = false
        window.hidesOnDeactivate = false
        window.level = .floating
        window.isOpaque = false
        window.backgroundColor = .clear
        window.hasShadow = true
        window.isMovableByWindowBackground = true
        window.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary]
        window.delegate = self
        hosting = PanelHostingView(rootView: VoicePanelView(model: model))
        hosting.sizingOptions = [.intrinsicContentSize]
        hosting.measuredHeight = { [weak self] height in DispatchQueue.main.async { self?.resizePanel(height) } }
        window.contentView = hosting
        window.center()
    }

    func resizePanel(_ proposed: CGFloat) {
        guard let window, proposed.isFinite, proposed > 100 else { return }
        let screen = window.screen ?? NSScreen.main
        let visible = screen?.visibleFrame ?? NSRect(x: 0, y: 0, width: 1440, height: 900)
        let height = min(ceil(proposed), visible.height - 24)
        guard abs(window.frame.height - height) > 0.5 else { return }
        var frame = window.frame
        frame.origin.y = max(visible.minY + 12, frame.maxY - height)
        frame.size = NSSize(width: 410, height: height)
        window.setFrame(frame, display: true)
        window.invalidateShadow()
        recordPanelState("content-resized")
    }

    func positionPanel() {
        guard let button = statusItem.button, let barWindow = button.window else { window.center(); return }
        let anchor = barWindow.convertToScreen(button.convert(button.bounds, to: nil))
        let screen = barWindow.screen ?? NSScreen.main
        let visible = screen?.visibleFrame ?? NSRect(x: 0, y: 0, width: 1440, height: 900)
        let x = min(max(anchor.midX - window.frame.width / 2, visible.minX + 12), visible.maxX - window.frame.width - 12)
        let y = max(visible.minY + 12, min(anchor.minY - window.frame.height - 8, visible.maxY - window.frame.height - 8))
        window.setFrameOrigin(NSPoint(x: x, y: y))
    }

    func startEngine() {
        guard process?.isRunning != true else { return }
        do { try AppPaths.prepare() }
        catch { model.serviceError = error.localizedDescription; return }
        runtimeURL = AppPaths.runtime
        model.serviceError = nil
        let p = Process()
        p.executableURL = AppPaths.python
        p.environment = AppPaths.environment
        p.arguments = ["-s", AppPaths.resources.appendingPathComponent("voice_engine.py").path, "--state-dir", AppPaths.runtime.path, "--codex-dir", AppPaths.codexHome.path]
        let inputPipe = Pipe(), outputPipe = Pipe(), errorPipe = Pipe()
        p.standardInput = inputPipe; p.standardOutput = outputPipe; p.standardError = errorPipe
        outputPipe.fileHandleForReading.readabilityHandler = { [weak self] handle in
            let chunk = handle.availableData
            if chunk.isEmpty { return }
            DispatchQueue.main.async { self?.receive(chunk) }
        }
        errorPipe.fileHandleForReading.readabilityHandler = { handle in _ = handle.availableData }
        p.terminationHandler = { [weak self] stopped in
            DispatchQueue.main.async {
                guard let self, self.process === stopped, !self.quitting else { return }
                self.model.serviceError = "点击「重新连接」恢复提醒。"
                self.statusItem.button?.title = " !"
                if !self.window.isVisible { self.positionPanel() }
                self.window.orderFrontRegardless()
                self.recordPanelState("service-stopped")
            }
        }
        do { try p.run(); process = p; input = inputPipe; buffer = Data() }
        catch { model.serviceError = "启动失败：\(error.localizedDescription)" }
    }

    func send(_ event: [String: Any]) {
        guard let input, let data = try? JSONSerialization.data(withJSONObject: event) else { return }
        do { try input.fileHandleForWriting.write(contentsOf: data + Data([10])) }
        catch { model.serviceError = "服务连接已断开，请重新连接。" }
        // A sound test started from Settings should show its acknowledgement.
        if event["action"] as? String == "test" { model.settingsOpen = false }
    }

    func receive(_ data: Data) {
        buffer.append(data)
        while let index = buffer.firstIndex(of: 10) {
            let line = buffer[..<index]
            buffer.removeSubrange(...index)
            guard let value = try? JSONSerialization.jsonObject(with: line) as? [String: Any] else { continue }
            if let error = value["error"] as? String { model.serviceError = error; continue }
            let alerts = (value["alerts"] as? [[String: Any]] ?? []).compactMap(VoiceAlert.init)
            let ids = Set(alerts.map(\.id))
            let changed = ids != knownIDs
            let finishedAll = !knownIDs.isEmpty && ids.isEmpty
            let hasNew = !ids.subtracting(knownIDs).isEmpty
            if let removed = model.alerts.first(where: { !ids.contains($0.id) }) { model.recentTitle = removed.title }
            knownIDs = ids
            if changed { model.listContentHeight = CGFloat(alerts.count) * 148 + CGFloat(max(0, alerts.count - 1)) * 9 + 14 }
            model.snapshot = value
            model.serviceError = nil
            statusItem.button?.title = alerts.isEmpty ? "" : " \(alerts.count)"
            if hasNew {
                if !model.devicePickerOpen { model.settingsOpen = false }
                if !window.isVisible { positionPanel() }
                window.orderFrontRegardless()
            }
            refreshClock()
            if finishedAll { model.settingsOpen = false; model.devicePickerOpen = false; window.orderOut(nil) }
            if changed { recordPanelState(finishedAll ? "all-handled" : hasNew ? "new-reminder" : "pending-updated") }
        }
    }

    func refreshClock() {
        model.now = Date().timeIntervalSince1970
        statusItem.button?.image = NSImage(systemSymbolName: model.enabled ? "waveform" : "bell.slash", accessibilityDescription: model.enabled ? "语音提醒已开启" : "语音提醒已关闭")
        if Date().timeIntervalSince(lastStartupCheck) > 30 {
            model.startupEnabled = LoginStartup.status()["enabled"] as? Bool ?? false
            lastStartupCheck = Date()
        }
    }

    func setStartup(_ enabled: Bool) {
        do {
            try LoginStartup.setEnabled(enabled)
            lastStartupCheck = .distantPast
            refreshClock()
        } catch {
            let alert = NSAlert(); alert.messageText = "未能更新登录自启"; alert.informativeText = error.localizedDescription
            alert.addButton(withTitle: "知道了"); alert.runModal()
        }
    }

    func refreshConnection() {
        let status = CodexConnection.run("--status")
        model.connectionConfigured = status["configured"] as? Bool ?? false
        model.connectionMessage = status["error"] as? String ?? (model.connectionConfigured ? "观察器已安装；信任状态请在 Codex 中检查" : "连接后增加审批与提问提醒")
    }
    func installConnection() {
        let alert = NSAlert()
        alert.messageText = "连接 Codex 提醒"
        alert.informativeText = "将注册5个本地观察器，用于观察提问、权限请求、工具结束、你的回复和中断。它们只传递提醒元数据，不联网、不替你作审批决定。\n\n安装后仍需你在 Codex 的 /hooks 中审阅并信任这些观察器。现有配置会备份，其他观察器与审批设置保留。"
        alert.addButton(withTitle: "安装连接"); alert.addButton(withTitle: "取消")
        guard alert.runModal() == .alertFirstButtonReturn else { return }
        let result = CodexConnection.run("--install")
        refreshConnection()
        model.connectionMessage = result["error"] as? String ?? result["message"] as? String ?? "请在 Codex 中检查连接。"
    }

    func recordPanelState(_ reason: String) {
        guard let runtimeURL else { return }
        let state: [String: Any] = ["at": Date().timeIntervalSince1970, "pid": ProcessInfo.processInfo.processIdentifier, "visible": window.isVisible, "pending": knownIDs.count, "reason": reason, "settingsOpen": model.settingsOpen, "width": window.frame.width, "height": window.frame.height]
        guard let data = try? JSONSerialization.data(withJSONObject: state, options: [.sortedKeys]) else { return }
        try? data.write(to: runtimeURL.appendingPathComponent("panel-state.json"), options: .atomic)
    }
    func hidePanel(_ reason: String) { window.orderOut(nil); recordPanelState(reason) }
    @objc func toggleWindow() { window.isVisible ? hidePanel("manual-hide") : showWindow() }
    func showWindow() {
        resizePanel(hosting.fittingSize.height)
        positionPanel()
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        recordPanelState("manual-open")
    }
    func windowShouldClose(_ sender: NSWindow) -> Bool { hidePanel("manual-hide"); return false }
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { false }
    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool { showWindow(); return true }
    func applicationWillTerminate(_ notification: Notification) {
        quitting = true
        clock?.invalidate()
        send(["action":"quit"])
        try? input?.fileHandleForWriting.close()
    }
}
