import SwiftUI
import AppKit

// MARK: - Mic glyph (one look everywhere: pill, Home, sidebar)

/// On = plain mic. Muted = grey mic with a red slash. Never colour alone: the slash is the signal.
struct MicGlyph: View {
    var muted: Bool
    var size: CGFloat = 11
    var tint: Color? = nil
    var body: some View {
        ZStack {
            Image(systemName: "mic.fill")
                .font(.system(size: size, weight: .semibold))
                .foregroundStyle(muted ? Color.secondary : (tint ?? Color.primary))
            if muted {
                Capsule().fill(JTheme.danger).frame(width: size * 1.45, height: max(1.6, size * 0.17))
                    .rotationEffect(.degrees(45))
                    .shadow(color: .black.opacity(0.25), radius: 0, x: 0.5, y: 0.5)
            }
        }
        .frame(width: size * 1.4, height: size * 1.4)
        .accessibilityHidden(true)
    }
}

/// Short live bars (listening / speaking). Driven by time, no audio meter needed.
struct LiveBars: View {
    var color: Color
    var count = 5
    var maxHeight: CGFloat = 16
    var barWidth: CGFloat = 3
    var gap: CGFloat = 2.5
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    var body: some View {
        TimelineView(.animation(minimumInterval: 1 / 30, paused: reduceMotion)) { ctx in
            let t = reduceMotion ? 0 : ctx.date.timeIntervalSinceReferenceDate
            HStack(spacing: gap) {
                ForEach(0..<count, id: \.self) { i in
                    let a = reduceMotion ? 0.6 : abs(sin(t * 5 + Double(i) * 0.9))
                    Capsule().fill(color).frame(width: barWidth, height: maxHeight * (0.32 + 0.68 * a))
                }
            }.frame(height: maxHeight)
        }
    }
}

// MARK: - The mark: "the pill is the logo" (same drawing as make_icon.swift, variant 1)

struct JMark: View {
    var awake: Bool
    var mode: PillMode
    var size: CGFloat = 88
    @ObservedObject private var st = AppState.shared
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var sweepX: CGFloat = -0.6
    @State private var sweeping = false

    private var ch: CGFloat { size * 0.255 }
    private var dotColors: [Color] {
        if !awake { return [Color(white: 0.62), Color(white: 0.42)] }
        if mode == .listening { return [Color(red: 0.42, green: 0.90, blue: 0.55), Color(red: 0.16, green: 0.74, blue: 0.36)] }
        return [Color(red: 0.36, green: 0.66, blue: 1.0), Color(red: 0.04, green: 0.48, blue: 1.0)]
    }

    var body: some View {
        let r = size * 0.225
        ZStack {
            RoundedRectangle(cornerRadius: r, style: .continuous)
                .fill(LinearGradient(colors: [Color(red: 0.27, green: 0.28, blue: 0.30), Color(red: 0.08, green: 0.08, blue: 0.09)], startPoint: .top, endPoint: .bottom))
            RoundedRectangle(cornerRadius: r, style: .continuous)
                .strokeBorder(LinearGradient(stops: [.init(color: .white.opacity(0.22), location: 0), .init(color: .white.opacity(0), location: 0.3),
                                                     .init(color: .black.opacity(0), location: 0.75), .init(color: .black.opacity(0.45), location: 1)],
                                             startPoint: .top, endPoint: .bottom), lineWidth: 1.2)
            capsule
            sweep(r: r)
        }
        .frame(width: size, height: size)
        .shadow(color: .black.opacity(0.22), radius: 7, y: 4)
        .onChange(of: st.sweepTick) { _, _ in runSweep() }
        .accessibilityHidden(true)
    }

    private var capsule: some View {
        let cw = size * 0.62
        return ZStack {
            Capsule().fill(Color.black.opacity(0.5))
            Capsule().fill(LinearGradient(colors: [.white.opacity(0.17), .white.opacity(0.05)], startPoint: .top, endPoint: .bottom))
            Capsule().strokeBorder(LinearGradient(colors: [.white.opacity(0.5), .white.opacity(0.14), .white.opacity(0.14)], startPoint: .top, endPoint: .bottom), lineWidth: max(1, ch * 0.04))
            HStack(spacing: ch * 0.24) {
                TimelineView(.animation(minimumInterval: 1 / 20, paused: reduceMotion || mode != .thinking)) { tl in
                    let p = (reduceMotion || mode != .thinking) ? 1 : 0.65 + 0.35 * (0.5 + 0.5 * sin(tl.date.timeIntervalSinceReferenceDate * 4))
                    Circle().fill(LinearGradient(colors: dotColors, startPoint: .top, endPoint: .bottom))
                        .frame(width: ch * 0.42, height: ch * 0.42).opacity(p)
                }
                if mode == .speaking || mode == .listening {
                    LiveBars(color: .white.opacity(0.86), count: 5, maxHeight: ch * 0.42, barWidth: max(1.5, ch * 0.075), gap: ch * 0.1)
                        .frame(width: ch * 1.3)
                } else {
                    Capsule().fill(Color.white.opacity(awake ? 0.86 : 0.45)).frame(width: ch * 1.3, height: max(2, ch * 0.15))
                }
            }
        }
        .frame(width: cw, height: ch)
    }

    private func sweep(r: CGFloat) -> some View {
        LinearGradient(colors: [.clear, .white.opacity(0.34), .clear], startPoint: .leading, endPoint: .trailing)
            .frame(width: size * 0.45)
            .offset(x: sweepX * size)
            .opacity(sweeping ? 1 : 0)
            .frame(width: size, height: size)
            .clipShape(RoundedRectangle(cornerRadius: r, style: .continuous))
            .allowsHitTesting(false)
    }

    /// One soft pass, 600 ms. Reduce Motion: nothing.
    private func runSweep() {
        guard !reduceMotion else { return }
        sweepX = -0.6; sweeping = true
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.03) {
            withAnimation(.easeInOut(duration: 0.6)) { sweepX = 0.6 }
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.68) { sweeping = false; sweepX = -0.6 }
    }
}

// MARK: - Menu-bar glyph (template unless it needs a colour)

enum MenuMark {
    /// Muted: mic.slash. Otherwise the pill mark: outline capsule + dot + bar.
    /// Listening: same mark with a green dot (not a template, so the colour survives).
    static func image(awake: Bool, mode: PillMode, micOff: Bool) -> NSImage? {
        if micOff {
            let img = NSImage(systemSymbolName: "mic.slash", accessibilityDescription: "Alfred, microphone off")
            img?.isTemplate = true
            return img
        }
        let listening = awake && mode == .listening
        let thinking = awake && mode == .thinking
        let alpha: CGFloat = awake ? 1 : 0.42
        let img = NSImage(size: NSSize(width: 24, height: 14), flipped: false) { _ in
            let ink: NSColor = listening ? .labelColor : .black
            ink.withAlphaComponent(alpha).setStroke()
            let cap = NSRect(x: 1.5, y: 1.5, width: 21, height: 11)
            let p = NSBezierPath(roundedRect: cap.insetBy(dx: 0.65, dy: 0.65), xRadius: 4.85, yRadius: 4.85)
            p.lineWidth = 1.3; p.stroke()
            (listening ? NSColor.systemGreen : ink.withAlphaComponent(alpha)).setFill()
            NSBezierPath(ovalIn: NSRect(x: 5.2, y: 5, width: 4, height: 4)).fill()
            ink.withAlphaComponent(alpha).setFill()
            if thinking {
                for i in 0..<3 { NSBezierPath(ovalIn: NSRect(x: 11.6 + CGFloat(i) * 3.1, y: 6, width: 2, height: 2)).fill() }
            } else {
                NSBezierPath(roundedRect: NSRect(x: 11.6, y: 6.1, width: 6.6, height: 1.8), xRadius: 0.9, yRadius: 0.9).fill()
            }
            return true
        }
        img.isTemplate = !listening
        img.accessibilityDescription = listening ? "Alfred, listening" : "Alfred"
        return img
    }
}
