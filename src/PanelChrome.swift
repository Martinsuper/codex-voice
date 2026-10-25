import AppKit
import SwiftUI

enum PanelChrome {
    static let width: CGFloat = 420
    static let arrowHeight: CGFloat = 10
    static let arrowHalfWidth: CGFloat = 10
    static let menuGap: CGFloat = 1

    static func placement(size: CGSize, anchor: CGRect, visible: CGRect) -> (origin: CGPoint, arrowX: CGFloat) {
        let maximumX = max(visible.minX, visible.maxX - size.width)
        var x = min(max(anchor.midX - size.width / 2, visible.minX + 12), max(visible.minX, maximumX - 12))
        // Relax the screen margin near an edge so the arrow can still point at the icon.
        let minimumTipInset = arrowHalfWidth + 4
        let lower = max(visible.minX, anchor.midX - size.width + minimumTipInset)
        let upper = min(maximumX, anchor.midX - minimumTipInset)
        x = lower <= upper ? min(max(x, lower), upper) : min(max(anchor.midX - size.width / 2, visible.minX), maximumX)
        let top = min(anchor.minY, visible.maxY) - menuGap
        let y = max(visible.minY + 12, top - size.height)
        return (CGPoint(x: x, y: y), min(max(anchor.midX - x, 2), size.width - 2))
    }
}

struct PanelBubbleShape: Shape {
    var arrowX: CGFloat
    var animatableData: CGFloat {
        get { arrowX }
        set { arrowX = newValue }
    }
    func path(in rect: CGRect) -> Path {
        let top = rect.minY + PanelChrome.arrowHeight
        let tip = min(max(rect.minX + arrowX, rect.minX + 2), rect.maxX - 2)
        let half = min(PanelChrome.arrowHalfWidth, tip - rect.minX - 1, rect.maxX - tip - 1)
        let leftRadius = min(18, max(1, tip - half - rect.minX - 1))
        let rightRadius = min(18, max(1, rect.maxX - tip - half - 1))
        let bottomRadius: CGFloat = 18
        var path = Path()
        path.move(to: CGPoint(x: rect.minX + leftRadius, y: top))
        path.addLine(to: CGPoint(x: tip - half, y: top))
        path.addLine(to: CGPoint(x: tip, y: rect.minY))
        path.addLine(to: CGPoint(x: tip + half, y: top))
        path.addLine(to: CGPoint(x: rect.maxX - rightRadius, y: top))
        path.addQuadCurve(to: CGPoint(x: rect.maxX, y: top + rightRadius), control: CGPoint(x: rect.maxX, y: top))
        path.addLine(to: CGPoint(x: rect.maxX, y: rect.maxY - bottomRadius))
        path.addQuadCurve(to: CGPoint(x: rect.maxX - bottomRadius, y: rect.maxY), control: CGPoint(x: rect.maxX, y: rect.maxY))
        path.addLine(to: CGPoint(x: rect.minX + bottomRadius, y: rect.maxY))
        path.addQuadCurve(to: CGPoint(x: rect.minX, y: rect.maxY - bottomRadius), control: CGPoint(x: rect.minX, y: rect.maxY))
        path.addLine(to: CGPoint(x: rect.minX, y: top + leftRadius))
        path.addQuadCurve(to: CGPoint(x: rect.minX + leftRadius, y: top), control: CGPoint(x: rect.minX, y: top))
        path.closeSubpath()
        return path
    }
}

struct PersistentSwitchStyle: ToggleStyle {
    func makeBody(configuration: Configuration) -> some View {
        Button { configuration.isOn.toggle() } label: {
            ZStack(alignment: .leading) {
                Capsule().fill(configuration.isOn ? VoiceTheme.switchOn : VoiceTheme.switchOff)
                Circle().fill(Color.white).frame(width: 18, height: 18)
                    .shadow(color: .black.opacity(0.12), radius: 1, y: 1)
                    .offset(x: configuration.isOn ? 23 : 3)
            }.frame(width: 44, height: 24).contentShape(Capsule())
        }
        .buttonStyle(.plain)
        .accessibilityRepresentation {
            Toggle(isOn: configuration.$isOn) { configuration.label }.toggleStyle(.switch)
        }
    }
}
