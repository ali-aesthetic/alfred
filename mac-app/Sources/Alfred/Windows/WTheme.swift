import SwiftUI
import AppKit

/// Small local theme for the windows (independent of Theme.swift).
enum WTheme {
    static let accent = Color(red: 0.04, green: 0.52, blue: 1.0)      // #0A84FF
    static let done = Color(red: 0.19, green: 0.82, blue: 0.35)       // #30D158
    static let warn = Color.orange
}

/// Native vibrancy behind SwiftUI content.
struct WVisualEffect: NSViewRepresentable {
    var material: NSVisualEffectView.Material = .hudWindow
    var blending: NSVisualEffectView.BlendingMode = .behindWindow
    func makeNSView(context: Context) -> NSVisualEffectView {
        let v = NSVisualEffectView()
        v.material = material; v.blendingMode = blending; v.state = .active
        return v
    }
    func updateNSView(_ v: NSVisualEffectView, context: Context) {
        v.material = material; v.blendingMode = blending
    }
}
