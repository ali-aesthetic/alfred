import SwiftUI
import AppKit

/// Direction C+ tokens (light + dark). Shared by the pill, pop-out and all windows.
enum JTheme {
    private static func dyn(_ light: UInt32, _ dark: UInt32) -> NSColor {
        NSColor(name: nil) { ap in
            let isDark = ap.bestMatch(from: [.darkAqua, .aqua]) == .darkAqua
            return NSColor(hex: isDark ? dark : light)
        }
    }
    // NSColor
    static let nsLabel = dyn(0x1D1D1F, 0xF5F5F7)
    static let nsSecondary = dyn(0x6E6E73, 0x98989D)
    static let nsAccent = dyn(0x0A84FF, 0x0A84FF)
    static let nsDone = dyn(0x34C759, 0x30D158)
    static let nsBg = dyn(0xF5F5F7, 0x1C1C1E)
    static let nsDanger = dyn(0xFF3B30, 0xFF453A)
    // SwiftUI
    static let label = Color(nsLabel)
    static let secondary = Color(nsSecondary)
    static let accent = Color(nsAccent)
    static let done = Color(nsDone)
    static let bg = Color(nsBg)
    static let danger = Color(nsDanger)
    /// glass tint: white 55-60% (light) / black 45-55% (dark)
    static let glassTint = Color(NSColor(name: nil) { ap in
        ap.bestMatch(from: [.darkAqua, .aqua]) == .darkAqua ? NSColor.black.withAlphaComponent(0.30) : NSColor.white.withAlphaComponent(0.38)
    })
    static let rim = Color(NSColor(name: nil) { ap in
        ap.bestMatch(from: [.darkAqua, .aqua]) == .darkAqua ? NSColor.white.withAlphaComponent(0.12) : NSColor.white.withAlphaComponent(0.7)
    })
    static let rimOuter = Color(NSColor(name: nil) { ap in
        ap.bestMatch(from: [.darkAqua, .aqua]) == .darkAqua ? NSColor.black.withAlphaComponent(0.4) : NSColor.black.withAlphaComponent(0.08)
    })
    // radii
    static let pillRadius: CGFloat = 22
    static let windowRadius: CGFloat = 16
    static let controlRadius: CGFloat = 7
    // fonts (SF Pro)
    static func title(_ size: CGFloat = 22) -> Font { .system(size: size, weight: .semibold, design: .default) }
    static func text(_ size: CGFloat = 13, _ w: Font.Weight = .regular) -> Font { .system(size: size, weight: w) }
    static let body = Font.system(size: 13)
    static let caption = Font.system(size: 11, weight: .medium)
    // springs
    static let spring = Animation.spring(response: 0.42, dampingFraction: 0.78)
    static let springSnappy = Animation.spring(response: 0.28, dampingFraction: 0.82)
    static let springSoft = Animation.spring(response: 0.6, dampingFraction: 0.85)
}

extension NSColor {
    convenience init(hex: UInt32) {
        self.init(srgbRed: CGFloat((hex >> 16) & 255) / 255, green: CGFloat((hex >> 8) & 255) / 255,
                  blue: CGFloat(hex & 255) / 255, alpha: 1)
    }
}

/// Native blur behind the window (vibrancy).
struct VisualEffect: NSViewRepresentable {
    var material: NSVisualEffectView.Material = .hudWindow
    var blending: NSVisualEffectView.BlendingMode = .behindWindow
    func makeNSView(context: Context) -> NSVisualEffectView {
        let v = NSVisualEffectView()
        v.material = material; v.blendingMode = blending; v.state = .active
        return v
    }
    func updateNSView(_ v: NSVisualEffectView, context: Context) { v.material = material; v.blendingMode = blending }
}

/// Glass: blur + tint + 1px rim + soft shadow. Use as `.background(GlassBackground(radius: 16))`.
struct GlassBackground: View {
    var topLeading: CGFloat, topTrailing: CGFloat, bottomLeading: CGFloat, bottomTrailing: CGFloat
    var material: NSVisualEffectView.Material = .hudWindow
    var shadow = true

    init(radius: CGFloat = JTheme.windowRadius, material: NSVisualEffectView.Material = .hudWindow, shadow: Bool = true) {
        topLeading = radius; topTrailing = radius; bottomLeading = radius; bottomTrailing = radius
        self.material = material; self.shadow = shadow
    }
    init(top: CGFloat, bottom: CGFloat, material: NSVisualEffectView.Material = .hudWindow, shadow: Bool = true) {
        topLeading = top; topTrailing = top; bottomLeading = bottom; bottomTrailing = bottom
        self.material = material; self.shadow = shadow
    }
    private var shape: UnevenRoundedRectangle {
        UnevenRoundedRectangle(topLeadingRadius: topLeading, bottomLeadingRadius: bottomLeading,
                               bottomTrailingRadius: bottomTrailing, topTrailingRadius: topTrailing, style: .continuous)
    }
    var body: some View {
        ZStack {
            VisualEffect(material: material).clipShape(shape)
            shape.fill(JTheme.glassTint)
            shape.strokeBorder(JTheme.rim, lineWidth: 1)
        }
        .shadow(color: .black.opacity(shadow ? 0.18 : 0), radius: 14, y: 6)
    }
}

extension View {
    func glass(radius: CGFloat = JTheme.windowRadius) -> some View { background(GlassBackground(radius: radius)) }
}
