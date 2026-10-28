import AppKit
import ApplicationServices

struct PassportClipboardSnapshot {
    let items: [NSPasteboardItem]
    static func capture(_ board: NSPasteboard, limit: Int = 32*1024*1024) -> Self? {
        let initial = board.changeCount
        var saved: [NSPasteboardItem] = []; var bytes = 0
        for item in board.pasteboardItems ?? [] {
            let copy = NSPasteboardItem()
            for type in item.types {
                guard let data = item.data(forType:type) else { return nil }
                bytes += data.count
                guard bytes <= limit, copy.setData(data,forType:type) else { return nil }
            }
            saved.append(copy)
        }
        guard board.changeCount == initial else { return nil }
        return Self(items:saved)
    }
    @discardableResult func restore(_ board: NSPasteboard, ifChangeCount expected: Int) -> Bool {
        guard board.changeCount == expected else { return false }
        board.prepareForNewContents(with:.currentHostOnly)
        return items.isEmpty || board.writeObjects(items)
    }
}

struct PassportInputTarget {
    let element: AXUIElement
    let pid: pid_t
    let value: String
    let range: NSRange
    let generation: Int
    let appName: String
    static func attribute(_ element: AXUIElement, _ name: String) -> CFTypeRef? {
        var result: CFTypeRef?
        return AXUIElementCopyAttributeValue(element, name as CFString, &result) == .success ? result : nil
    }
    static func capture(generation: Int) -> Self? {
        guard AXIsProcessTrusted(),
              let front = NSWorkspace.shared.frontmostApplication,
              front.processIdentifier != ProcessInfo.processInfo.processIdentifier,
              let focused = attribute(AXUIElementCreateSystemWide(), kAXFocusedUIElementAttribute),
              CFGetTypeID(focused) == AXUIElementGetTypeID() else { return nil }
        let element = focused as! AXUIElement
        var pid: pid_t = 0
        guard AXUIElementGetPid(element, &pid) == .success, pid == front.processIdentifier,
              attribute(element, kAXEnabledAttribute) as? Bool != false,
              attribute(element, kAXSubroleAttribute) as? String != kAXSecureTextFieldSubrole,
              let role = attribute(element, kAXRoleAttribute) as? String,
              [kAXTextFieldRole, kAXTextAreaRole, kAXComboBoxRole].contains(role),
              let value = attribute(element, kAXValueAttribute) as? String,
              let selection = attribute(element, kAXSelectedTextRangeAttribute),
              CFGetTypeID(selection) == AXValueGetTypeID() else { return nil }
        var range = CFRange()
        guard AXValueGetValue(selection as! AXValue, .cfRange, &range), range.location >= 0, range.length >= 0,
              range.location <= (value as NSString).length,
              range.length <= (value as NSString).length-range.location else { return nil }
        return Self(element: element, pid: pid, value: value,
                    range: NSRange(location: range.location, length: range.length), generation: generation,
                    appName: front.localizedName ?? "电脑")
    }
    func unchanged(generation: Int) -> Bool {
        guard self.generation == generation, let current = Self.capture(generation: generation),
              current.pid == pid, CFEqual(current.element, element),
              current.value == value, current.range == range else { return false }
        return true
    }
    /// 回车发送只需要确认焦点还在同一个可输入的界面上：前台应用不变、
    /// 系统能读到焦点元素时要求仍是同一个元素。不比较字段内容和选区，
    /// 因为粘贴后应用可能自行改写文本（自动格式化、终端提示行、IME 等），
    /// 严格比较会误判“输入框已变化”，导致听写后按回车无法提交。
    func sameField(generation: Int) -> Bool {
        guard self.generation == generation else { return false }
        guard let front = NSWorkspace.shared.frontmostApplication else { return false }
        guard front.processIdentifier == pid,
              let current = Self.capture(generation: generation) else { return false }
        // Electron 等应用在插入文字后可能重建焦点元素：新旧元素不可比较时，
        // 只要归属同一个前台应用就接受，避免误拦应该发出的回车。
        return CFEqual(current.element, element) || current.pid == pid
    }
    // One normal Paste command, no Return. Preserve all pasteboard formats;
    // do not overwrite a newer user copy while restoring the previous contents.
    @MainActor func insert(_ text: String, generation: @escaping () -> Int,
                          diagnostic: ([String:Any])->Void = { _ in }) async -> Bool {
        var report:[String:Any] = ["app":appName,"beforeLength":value.utf16.count,
                                  "accessibility":AXIsProcessTrusted(),"postEvents":CGPreflightPostEventAccess(),
                                  "originalOnlyParagraphMarker":!value.isEmpty && value.unicodeScalars.allSatisfy { CharacterSet.newlines.contains($0) },
                                  "selectionLocation":range.location,"selectionLength":range.length]
        func finish(_ stage:String,_ ok:Bool) -> Bool {
            report["stage"] = stage; report["inserted"] = ok; diagnostic(report); return ok
        }
        guard unchanged(generation:generation()), CGPreflightPostEventAccess(),
              let expected = PassportTextEdit.inserting(text,in:value,range:range) else { return finish("targetChangedOrPermission",false) }
        let board = NSPasteboard.general
        guard let previous = PassportClipboardSnapshot.capture(board),
              unchanged(generation:generation()) else { return finish("clipboardUnavailable",false) }
        board.prepareForNewContents(with:.currentHostOnly)
        guard board.setString(text,forType:.string) else {
            _ = previous.restore(board,ifChangeCount:board.changeCount)
            return finish("clipboardWrite",false)
        }
        let written = board.changeCount
        defer { _ = previous.restore(board,ifChangeCount:written) }
        guard unchanged(generation:generation()), board.changeCount == written,
              let source = CGEventSource(stateID:.privateState),
              let down = CGEvent(keyboardEventSource:source,virtualKey:9,keyDown:true),
              let up = CGEvent(keyboardEventSource:source,virtualKey:9,keyDown:false) else { return finish("targetChangedBeforePaste",false) }
        // kVK_ANSI_V with Command, delivered through the normal HID event path.
        // Direct CGEventPostToPid / AXSelectedText is ignored by some Electron fields.
        down.flags = .maskCommand; up.flags = .maskCommand
        down.post(tap:.cghidEventTap); up.post(tap:.cghidEventTap)
        report["expectedLength"] = expected.utf16.count
        for _ in 0..<20 {
            try? await Task.sleep(nanoseconds:50_000_000)
            let observed = Self.attribute(element,kAXValueAttribute) as? String
            report["afterLength"] = observed?.utf16.count ?? -1
            if let observed, PassportTextEdit.confirmsInsertion(original:value,expected:expected,inserted:text,observed:observed) {
                report["verification"] = PassportTextEdit.matches(expected:expected,observed:observed,original:value) ? "draftAndText" : "exactFinalText"
                return finish("verifiedPaste",true)
            }
            if Task.isCancelled { return finish("cancelledAfterPaste",false) }
        }
        // GPU 终端（Ghostty 等）不会把粘贴后的完整内容暴露给 AX value：字段值
        // 对粘贴验证“看起来没变”。要求 AX 确认会放弃这些目标并阻塞后续的
        // 回车发送，因此对已知终端应用，粘贴事件已按正常 HID 路径送达，
        // 直接接受本次插入。
        let terminalApps = ["Ghostty","iTerm2","Terminal","Alacritty","kitty","WezTerm","Warp"]
        if terminalApps.contains(appName) {
            report["terminal"] = appName
            return finish("terminalPasteAccepted",true)
        }
        return finish("pasteNotConfirmed",false)
    }
}
