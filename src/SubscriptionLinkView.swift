import SwiftUI

enum SubscriptionWebsite {
    static let url = URL(string: "https://slashx.shop/")!
    static let domain = "slashx.shop"
}

struct SubscriptionServiceLink: View {
    var compact = false

    var body: some View {
        Link(destination: SubscriptionWebsite.url) {
            if compact {
                HStack(spacing: 7) {
                    Text("工具免费 · 第三方服务")
                        .font(VoiceTheme.font(10)).foregroundColor(VoiceTheme.secondary)
                    Spacer(minLength: 5)
                    Text("订阅与充值").font(VoiceTheme.font(11, medium: true)).foregroundColor(VoiceTheme.green)
                    Text(SubscriptionWebsite.domain).font(VoiceTheme.font(10)).foregroundColor(VoiceTheme.secondary)
                    Image(systemName: "arrow.up.right").font(.system(size: 10, weight: .medium)).foregroundColor(VoiceTheme.green)
                }.padding(.vertical, 3).contentShape(Rectangle())
            } else {
                VStack(alignment: .leading, spacing: 8) {
                    HStack(spacing: 8) {
                        Image(systemName: "creditcard").font(.system(size: 15)).foregroundColor(VoiceTheme.green)
                        Text("订阅与充值").font(VoiceTheme.font(13, medium: true)).foregroundColor(VoiceTheme.ink)
                        Spacer(minLength: 5)
                        Image(systemName: "arrow.up.right").font(.system(size: 12, weight: .medium)).foregroundColor(VoiceTheme.green)
                    }
                    Text("查看 ChatGPT / Codex 套餐与兑换说明")
                        .font(VoiceTheme.font(11)).foregroundColor(VoiceTheme.ink)
                    HStack(spacing: 5) {
                        Text("工具免费使用 · 可选第三方服务")
                        Spacer(minLength: 0)
                        Text(SubscriptionWebsite.domain)
                    }.font(VoiceTheme.font(10)).foregroundColor(VoiceTheme.secondary)
                }.padding(13).frame(maxWidth: .infinity, alignment: .leading)
                    .background(VoiceTheme.greenFill).clipShape(RoundedRectangle(cornerRadius: 10))
                    .contentShape(RoundedRectangle(cornerRadius: 10))
            }
        }
        .buttonStyle(.plain)
        .accessibilityLabel("订阅与充值，在浏览器中打开第三方网站 slashx.shop")
        .help("在默认浏览器打开 https://slashx.shop/；本工具免费使用。")
    }
}
