import AppKit
import Darwin

extension AppDelegate {
    func startEngine() {
        guard !quitting else { return }
        guard process?.isRunning != true else { return }
        do { try AppPaths.prepare() }
        catch { model.serviceError = error.localizedDescription; return }
        runtimeURL = AppPaths.runtime
        model.serviceError = "正在启动提醒服务…"
        model.serviceRecovering = true
        let engine = EngineProcess(executable: AppPaths.python,
                                   script: AppPaths.resources.appendingPathComponent("voice_engine.py"),
                                   environment: AppPaths.environment,
                                   stateDirectory: AppPaths.runtime, codexDirectory: AppPaths.codexHome)
        let p = engine.process, inputPipe = engine.input, outputPipe = engine.output, errorPipe = engine.errors
        outputPipe.fileHandleForReading.readabilityHandler = { [weak self, weak p] handle in
            let chunk = handle.availableData
            if chunk.isEmpty { return }
            DispatchQueue.main.async { if let self, let p, self.process === p { self.receive(chunk) } }
        }
        errorPipe.fileHandleForReading.readabilityHandler = { handle in _ = handle.availableData }
        p.terminationHandler = { [weak self] stopped in
            DispatchQueue.main.async {
                guard let self, self.process === stopped, !self.quitting else { return }
                self.cleanupEngineGroup(stopped)
                if !self.stoppingForRecovery { self.scheduleRecovery("提醒服务意外停止") }
            }
        }
        do {
            try p.run(); process = p; input = inputPipe; engineMessages = EngineMessages()
            engineStartedAt = Date(); lastSnapshotAt = .distantPast; healthySince = nil; engineGroup = nil
        } catch { scheduleRecovery("提醒服务启动失败") }
    }

    func cleanupEngineGroup(_ stopped: Process) {
        if let group = engineGroup, group > 0, group == stopped.processIdentifier { _ = Darwin.kill(-group, SIGTERM) }
        engineGroup = nil
    }

    func scheduleRecovery(_ reason: String) {
        guard !quitting else { return }
        restartWork?.cancel()
        healthySince = nil
        guard let delay = restartPolicy.nextDelay(at: Date()) else {
            stoppingForRecovery = process?.isRunning == true
            if let old = process, old.isRunning {
                send(["action":"quit"])
                old.terminate()
                DispatchQueue.main.asyncAfter(deadline: .now() + 4) { [weak self] in
                    if old.isRunning {
                        if self?.engineGroup == old.processIdentifier { _ = Darwin.kill(-old.processIdentifier, SIGKILL) }
                        else { _ = Darwin.kill(old.processIdentifier, SIGKILL) }
                    }
                }
            }
            model.serviceRecovering = false
            model.serviceError = "连续恢复失败，请点击「重新连接」再试。"
            updateStatusItem(); recordPanelState("service-recovery-limit")
            return
        }
        model.serviceRecovering = true
        model.serviceError = reason + "，正在自动恢复…"
        let old = process
        let wasRunning = old?.isRunning == true
        stoppingForRecovery = true
        if wasRunning, let old {
            send(["action":"quit"])
            try? input?.fileHandleForWriting.close()
            DispatchQueue.main.asyncAfter(deadline: .now() + 1) {
                if old.isRunning { old.terminate() }
            }
            DispatchQueue.main.asyncAfter(deadline: .now() + 4) { [weak self] in
                if old.isRunning {
                    if self?.engineGroup == old.processIdentifier { _ = Darwin.kill(-old.processIdentifier, SIGKILL) }
                    else { _ = Darwin.kill(old.processIdentifier, SIGKILL) }
                }
            }
        }
        let work = DispatchWorkItem { [weak self] in
            guard let self, !self.quitting else { return }
            self.restartWork = nil
            self.stoppingForRecovery = false
            if self.process?.isRunning == true { self.scheduleRecovery("提醒服务尚未停止"); return }
            self.startEngine()
        }
        restartWork = work
        DispatchQueue.main.asyncAfter(deadline: .now() + max(delay, wasRunning ? 5 : 0), execute: work)
        updateStatusItem(); recordPanelState("service-recovering")
    }

    func manualReconnect() {
        guard !quitting else { return }
        restartPolicy.reset(); restartWork?.cancel(); restartWork = nil
        if process?.isRunning == true { scheduleRecovery("正在重新连接") }
        else { stoppingForRecovery = false; startEngine() }
    }

}
