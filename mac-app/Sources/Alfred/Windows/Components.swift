import SwiftUI
import AppKit

// MARK: - Shared building blocks for the Alfred windows

/// A little keyboard key, e.g. ⌥ E.
struct Keycap: View {
    let text: String
    var body: some View {
        Text(text)
            .font(.system(size: 12, weight: .semibold, design: .rounded))
            .foregroundStyle(.primary.opacity(0.8))
            .frame(minWidth: 22, minHeight: 22)
            .padding(.horizontal, 3)
            .background(
                RoundedRectangle(cornerRadius: 6, style: .continuous)
                    .fill(Color.primary.opacity(0.07))
            )
            .overlay(
                RoundedRectangle(cornerRadius: 6, style: .continuous)
                    .strokeBorder(Color.primary.opacity(0.14), lineWidth: 1)
            )
            .shadow(color: .black.opacity(0.12), radius: 0, y: 1)
    }
}

struct Keycaps: View {
    let combo: String
    var body: some View {
        HStack(spacing: 4) {
            ForEach(Array(combo.enumerated()), id: \.offset) { _, c in
                if c != " " { Keycap(text: String(c).uppercased()) }
            }
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("Shortcut \(combo)")
    }
}

/// Soft card surface that reads in light and dark.
struct JCard: ViewModifier {
    var radius: CGFloat = 16
    var padding: CGFloat = 16
    func body(content: Content) -> some View {
        content
            .padding(padding)
            .background(
                RoundedRectangle(cornerRadius: radius, style: .continuous)
                    .fill(Color.primary.opacity(0.045))
            )
            .overlay(
                RoundedRectangle(cornerRadius: radius, style: .continuous)
                    .strokeBorder(Color.primary.opacity(0.09), lineWidth: 1)
            )
    }
}
extension View {
    func jCard(radius: CGFloat = 16, padding: CGFloat = 16) -> some View { modifier(JCard(radius: radius, padding: padding)) }
}

/// Wraps its children onto centred rows.
struct FlowLayout: Layout {
    var spacing: CGFloat = 8
    private func rows(_ subviews: Subviews, width: CGFloat) -> [[Int]] {
        var out: [[Int]] = [[]]
        var x: CGFloat = 0
        for (i, s) in subviews.enumerated() {
            let w = s.sizeThatFits(.unspecified).width
            if x > 0 && x + w > width { out.append([]); x = 0 }
            out[out.count - 1].append(i); x += w + spacing
        }
        return out
    }
    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        let w = proposal.width ?? 600
        let rs = rows(subviews, width: w)
        var h: CGFloat = 0
        for r in rs { h += (r.map { subviews[$0].sizeThatFits(.unspecified).height }.max() ?? 0) }
        h += spacing * CGFloat(max(0, rs.count - 1))
        return CGSize(width: w, height: h)
    }
    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        var y = bounds.minY
        for r in rows(subviews, width: bounds.width) {
            let sizes = r.map { subviews[$0].sizeThatFits(.unspecified) }
            let total = sizes.reduce(0) { $0 + $1.width } + spacing * CGFloat(max(0, r.count - 1))
            var x = bounds.minX + (bounds.width - total) / 2
            let rh = sizes.map(\.height).max() ?? 0
            for (k, i) in r.enumerated() {
                subviews[i].place(at: CGPoint(x: x, y: y), proposal: .unspecified)
                x += sizes[k].width + spacing
            }
            y += rh + spacing
        }
    }
}

/// Capsule suggestion chip.
struct ChipStyle: ButtonStyle {
    @State private var hover = false
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.system(size: 13, weight: .medium))
            .padding(.horizontal, 14).padding(.vertical, 8)
            .background(Capsule().fill(Color.primary.opacity(hover ? 0.12 : 0.07)))
            .overlay(Capsule().strokeBorder(Color.primary.opacity(0.1), lineWidth: 1))
            .scaleEffect(configuration.isPressed ? 0.97 : 1)
            .onHover { hover = $0 }
            .animation(.easeOut(duration: 0.12), value: hover)
    }
}
