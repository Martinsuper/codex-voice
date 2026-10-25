import SwiftUI

struct UsageRing: View {
    let remaining:Int?
    var size:CGFloat = 152
    var threshold=20
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    private var tint:Color { (remaining ?? 100)<threshold ? VoiceTheme.warningTint:VoiceTheme.accent }
    var body: some View {
        ZStack {
            Circle().stroke(VoiceTheme.soft,lineWidth:size>100 ? 10:5)
            if let remaining,remaining>0 {
                Circle().trim(from:0,to:CGFloat(min(100,max(0,remaining)))/100)
                    .stroke(tint,style:StrokeStyle(lineWidth:size>100 ? 10:5,lineCap:.round))
                    .rotationEffect(.degrees(-90))
            }
            VStack(spacing:size>100 ? 2:0) {
                HStack(alignment:.firstTextBaseline,spacing:1) {
                    Text(remaining.map(String.init) ?? "—")
                        .font(.system(size:size>100 ? 51:21,weight:.semibold,design:.rounded)).tracking(size>100 ? -2:-0.7).monospacedDigit()
                    if remaining != nil {Text("%").font(.system(size:size>100 ? 20:9,weight:.medium,design:.rounded)).foregroundColor(VoiceTheme.secondary)}
                }.foregroundColor(remaining == nil ? VoiceTheme.secondary:VoiceTheme.ink)
                if size>100 {Text(remaining == nil ? "等待同步":"剩余可用").font(VoiceTheme.font(10)).foregroundColor(VoiceTheme.secondary)}
            }
        }.frame(width:size,height:size)
            .padding(size>100 ? 5:3)
            .animation(reduceMotion ? nil:.easeInOut(duration:0.35),value:remaining)
            .accessibilityElement(children:.ignore).accessibilityLabel("剩余额度")
            .accessibilityValue(remaining.map {"\($0)%"} ?? "暂未获取")
    }
}

private struct UsageWindowMetric: View {
    let window:UsageWindow
    let now:Double
    let threshold:Int
    var body:some View {
        VStack(alignment:.leading,spacing:5) {
            HStack(alignment:.firstTextBaseline,spacing:4) {
                Text(window.title).font(VoiceTheme.font(10)).foregroundColor(VoiceTheme.secondary)
                Spacer(minLength:1)
                Text("\(window.remaining)%").font(.system(size:15,weight:.semibold,design:.rounded)).monospacedDigit().foregroundColor(VoiceTheme.ink)
            }
            GeometryReader {g in
                ZStack(alignment:.leading) {
                    Capsule().fill(VoiceTheme.soft)
                    Capsule().fill(window.remaining<threshold ? VoiceTheme.warningTint:VoiceTheme.accent)
                        .frame(width:g.size.width*CGFloat(window.remaining)/100)
                }
            }.frame(height:4).accessibilityHidden(true)
            Text(window.resetNote(now:now)).font(VoiceTheme.font(9)).foregroundColor(VoiceTheme.secondary).lineLimit(2)
        }.accessibilityElement(children:.combine)
    }
}

struct UsageOverviewCard: View {
    @ObservedObject var model:VoicePanelModel
    var compact=false
    private var usage:CodexUsage {model.usage}
    var body:some View {
        VStack(spacing:12) {
            if compact {
                HStack(spacing:13) {
                    Button {model.usageOpen=true} label: {
                        HStack(spacing:13) {
                            UsageRing(remaining:usage.remaining,size:58,threshold:model.usageLowThreshold).accessibilityHidden(true)
                            VStack(alignment:.leading,spacing:5) {
                                Text("Codex 剩余用量").font(VoiceTheme.font(12,medium:true))
                                Text(usage.updateNote).font(VoiceTheme.font(10)).foregroundColor(VoiceTheme.secondary)
                            }
                            Spacer(minLength:1)
                            Image(systemName:"chevron.right").font(.system(size:10,weight:.medium)).foregroundColor(VoiceTheme.secondary)
                        }.contentShape(Rectangle())
                    }.buttonStyle(.plain).accessibilityLabel("Codex 剩余用量 \(usage.percentage)，查看详情")
                    UsageRefreshButton(model:model,compact:true)
                }
            } else {
                HStack {
                    Button {model.usageOpen=true} label: {
                        HStack(spacing:6) {
                            Text("Codex 剩余用量").font(VoiceTheme.font(12,medium:true))
                            Image(systemName:"chevron.right").font(.system(size:9,weight:.semibold)).foregroundColor(VoiceTheme.secondary)
                        }.contentShape(Rectangle())
                    }.buttonStyle(.plain).accessibilityLabel("查看 Codex 用量详情")
                    Spacer(minLength:4)
                    UsageRefreshButton(model:model,compact:true)
                }
                Button {model.usageOpen=true} label: {
                    HStack(spacing:22) {
                        UsageRing(remaining:usage.remaining,threshold:model.usageLowThreshold).accessibilityHidden(true)
                        VStack(alignment:.leading,spacing:18) {
                            if !usage.windows.isEmpty {
                                ForEach(usage.windows.prefix(2)) {w in UsageWindowMetric(window:w,now:model.now,threshold:model.usageLowThreshold)}
                                if usage.windows.count>1 {Text("以剩余最少的周期为准").font(VoiceTheme.font(9)).foregroundColor(VoiceTheme.secondary)}
                            } else {
                                Text(usage.state=="loading" ? "正在同步":"暂未获取用量").font(VoiceTheme.font(14,medium:true))
                                Text(usage.message).font(VoiceTheme.font(11)).foregroundColor(VoiceTheme.secondary).fixedSize(horizontal:false,vertical:true)
                            }
                        }.frame(maxWidth:.infinity,alignment:.leading)
                    }.padding(.vertical,3).contentShape(Rectangle())
                }.buttonStyle(.plain).accessibilityLabel("Codex 剩余用量 \(usage.percentage)，查看详情")
                HStack(spacing:5) {
                    Image(systemName:usage.low ? "exclamationmark.circle":"clock").font(.system(size:9))
                    Text(usage.low ? "额度偏低 · \(usage.updateNote)":usage.updateNote).font(VoiceTheme.font(10))
                    Spacer(minLength:2)
                    if !usage.plan.isEmpty {Text(usage.plan).font(VoiceTheme.font(9,medium:true)).foregroundColor(VoiceTheme.secondary).padding(.horizontal,7).padding(.vertical,3).background(VoiceTheme.soft).clipShape(Capsule())}
                }.foregroundColor(usage.low ? VoiceTheme.amber:VoiceTheme.secondary)
            }
        }.padding(compact ? 13:16).frame(maxWidth:.infinity)
            .background(VoiceTheme.paper).clipShape(RoundedRectangle(cornerRadius:18,style:.continuous))
            .overlay(RoundedRectangle(cornerRadius:18,style:.continuous).stroke(VoiceTheme.line,lineWidth:0.6))
    }
}
