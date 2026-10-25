import AppKit
@main struct PassportClipboardTests {
    static func main() {
        let board = NSPasteboard.withUniqueName()
        defer { board.releaseGlobally() }
        let custom = NSPasteboard.PasteboardType("local.rico.passport-test")
        let one=NSPasteboardItem(); one.setString("原剪贴板",forType:.string); one.setData(Data([0,1,2,255]),forType:custom)
        let two=NSPasteboardItem(); two.setData(Data("<b>original</b>".utf8),forType:.html)
        board.writeObjects([one,two])
        let saved=PassportClipboardSnapshot.capture(board)!
        board.prepareForNewContents(with:.currentHostOnly); board.setString("临时听写文字",forType:.string)
        let temporary=board.changeCount
        precondition(saved.restore(board,ifChangeCount:temporary))
        precondition(board.pasteboardItems?.count == 2)
        precondition(board.pasteboardItems?[0].string(forType:.string) == "原剪贴板")
        precondition(board.pasteboardItems?[0].data(forType:custom) == Data([0,1,2,255]))
        precondition(board.pasteboardItems?[1].data(forType:.html) == Data("<b>original</b>".utf8))
        precondition(PassportClipboardSnapshot.capture(board,limit:1) == nil)
        board.prepareForNewContents(with:.currentHostOnly); board.setString("用户稍后复制的新内容",forType:.string)
        precondition(!saved.restore(board,ifChangeCount:temporary))
        precondition(board.string(forType:.string) == "用户稍后复制的新内容")
        precondition(PassportTextEdit.matches(expected:"文字",observed:"文字\n"))
        precondition(!PassportTextEdit.matches(expected:"文字",observed:"文字额外内容"))
        print("Private pasteboard formats, restore, size bound, newer-copy protection and read-back: PASS")
    }
}
