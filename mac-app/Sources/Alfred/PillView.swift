import SwiftUI

private struct SizeKey: PreferenceKey {
    static var defaultValue: CGSize = .zero
    static func reduce(value: inout CGSize, nextValue: () -> CGSize) { value = nextValue() }
}

struct PillView: View {
    @ObservedObject var model: PillModel
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var shake: CGFloat = 0

    private var signature: String {
        "\(model.mode.rawValue)|\(model.micOff)|\(model.text)|\(model.partial.isEmpty)|\(model.selectionWords ?? -1)|\(model.steps.suffix(3).map { $0.text + ($0.done ? "1" : "0") })|\(model.toast ?? "")|\(model.chip?.id ?? "")|\(model.flash == nil ? 0 : 1)"
    }

    var body: some View {
        VStack(spacing: 6) {
            pill
                .modifier(ShakeEffect(t: shake))
                .offset(x: model.shrugX + model.lean, y: model.nod)
            if model.mode == .listening, let n = model.selectionWords {
                HStack(spacing: 6) {
                    Image(systemName: "text.cursor").font(.system(size: 9)).foregroundStyle(JTheme.secondary)
                    Text("Selection: \(n) \(n == 1 ? "word" : "words")").lineLimit(1)
                }
                .font(.system(size: 11, weight: .medium)).foregroundStyle(JTheme.label)
                .padding(.horizontal, 10).padding(.vertical, 5)
                .background(GlassBackground(radius: 12, shadow: false))
                .transition(.opacity.combined(with: .scale(scale: 0.9, anchor: .top)))
                .accessibilityLabel("Selected text, \(n) words")
            }
            if let c = model.chip {
                Button(action: model.forgetChip) {
                    HStack(spacing: 6) {
                        Image(systemName: "bookmark.fill").font(.system(size: 9)).foregroundStyle(JTheme.accent)
                        Text("Noted · \(c.text)").lineLimit(1)
                        Image(systemName: "arrow.uturn.backward").font(.system(size: 9)).foregroundStyle(JTheme.secondary)
                    }
                    .font(.system(size: 11, weight: .medium)).foregroundStyle(JTheme.label)
                    .padding(.horizontal, 10).padding(.vertical, 5)
                    .background(GlassBackground(radius: 12, shadow: false))
                }
                .buttonStyle(.plain)
                .help("Tap to forget this")
                .transition(.scale(scale: 0.8, anchor: .top).combined(with: .opacity))
            }
        }
        .fixedSize()
        .background(GeometryReader { g in Color.clear.preference(key: SizeKey.self, value: g.size) })
        .onPreferenceChange(SizeKey.self) { s in DispatchQueue.main.async { model.contentSize = s } }
        .animation(reduceMotion ? .easeOut(duration: 0.15) : JTheme.spring, value: signature)
        .onChange(of: model.flash) { _, f in
            if f == .error && !reduceMotion { withAnimation(.linear(duration: 0.45)) { shake = floor(shake) + 1 } }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
    }

    // MARK: pill

    /// On notched Macs the idle pill would sit entirely inside the notch; let it hang out below it.
    private var notch: CGFloat { max(0, (NSScreen.main?.safeAreaInsets.top ?? 0)) }
    private var showToast: Bool { model.mode == .idle && model.toast != nil }

    @ViewBuilder private var pill: some View {
        let bottom: CGFloat = (model.mode == .idle && !showToast) ? 12 : (model.mode == .asleep ? 9 : JTheme.pillRadius)
        let shape = UnevenRoundedRectangle(bottomLeadingRadius: bottom, bottomTrailingRadius: bottom, style: .continuous)
        content
            .background(
                ZStack {
                    GlassBackground(top: 0, bottom: bottom)
                    if model.mode == .silent || (model.mode == .idle && model.micOff && !showToast) {
                        shape.fill(Color.gray.opacity(model.mode == .silent ? 0.22 : 0.14))
                    }
                }
            )
            .overlay(sweepOverlay(shape))
            .overlay { rim(bottom: bottom) }
    }

    /// The edge of the pill is the state: green breathing = listening, blue lap = thinking, faster + steady = doing,
    /// one green flash = done, red + shake = error.
    @ViewBuilder private func rim(bottom: CGFloat) -> some View {
        let shape = UnevenRoundedRectangle(bottomLeadingRadius: bottom, bottomTrailingRadius: bottom, style: .continuous)
        ZStack {
            switch model.phase {
            case .listening where !showToast: RimBreath(bottom: bottom).transition(.opacity)
            case .thinking: RimArc(bottom: bottom, color: JTheme.accent, period: 2.4).transition(.opacity)
            case .doing: RimArc(bottom: bottom, color: JTheme.accent, period: 1.2, base: 0.35).transition(.opacity)
            case .error: shape.strokeBorder(JTheme.danger.opacity(0.75), lineWidth: 1.5).transition(.opacity)
            default: EmptyView()
            }
            if let f = model.flash {
                let c = f == .done ? JTheme.done : JTheme.danger
                shape.strokeBorder(c, lineWidth: 1.8).shadow(color: c.opacity(0.55), radius: 7).transition(.opacity)
            }
        }
        .allowsHitTesting(false)
    }

    private func sweepOverlay(_ shape: UnevenRoundedRectangle) -> some View {
        GeometryReader { g in
            LinearGradient(colors: [.clear, .white.opacity(0.38), .clear], startPoint: .leading, endPoint: .trailing)
                .frame(width: g.size.width * 0.4)
                .offset(x: g.size.width * model.sweepX - g.size.width * 0.2)
                .opacity(model.sweepOn ? 1 : 0)
        }
        .clipShape(shape)
        .allowsHitTesting(false)
    }

    private var contentKey: String { showToast ? "toast" : "\(model.phase)" }

    /// Content swaps with a short cross-fade while the pill itself resizes smoothly around it.
    private var content: some View {
        ZStack {
            rawContent
                .id(contentKey)
                .transition(.asymmetric(insertion: .opacity.combined(with: .scale(scale: 0.96)), removal: .opacity))
        }
    }

    @ViewBuilder private var rawContent: some View {
        if showToast {
            Text(model.toast ?? "").font(JTheme.text(12, .medium)).foregroundStyle(JTheme.label)
                .padding(.horizontal, 16).padding(.top, 6).padding(.bottom, 9)
        } else {
            switch model.mode {
            case .idle:
                Button(action: model.toggleMic) {
                    HStack(spacing: 5) {
                        MicGlyph(muted: model.micOff, size: 10, tint: JTheme.label)
                        if model.micOff {
                            Text("Muted").font(JTheme.text(11, .medium)).foregroundStyle(JTheme.secondary)
                        }
                    }
                    .padding(.horizontal, model.micOff ? 15 : 14).padding(.top, 3 + notch).padding(.bottom, 7)
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .help(model.micOff ? "Microphone is off. Click to turn on" : "Microphone is on. Click to mute")
                .accessibilityLabel(model.micOff ? "Microphone off. Turn on" : "Microphone on. Mute")
            case .asleep:
                Image(systemName: "moon.fill").font(.system(size: 9)).foregroundStyle(JTheme.secondary)
                    .frame(width: 44, height: 18)
            case .listening:
                HStack(spacing: 8) {
                    MicGlyph(muted: false, size: 11, tint: JTheme.done)
                    LiveBars(color: JTheme.done, count: 4, maxHeight: 13, barWidth: 2.5, gap: 2)
                    // fixed width + one line: new words only move the end of the line, the pill never resizes
                    Text(model.partial.isEmpty ? "Listening…" : model.partial)
                        .font(JTheme.text(13, .medium))
                        .foregroundStyle(model.partial.isEmpty ? JTheme.secondary : JTheme.label)
                        .lineLimit(1).truncationMode(.head)
                        .frame(width: 300, alignment: .leading)
                        .animation(.easeOut(duration: 0.12), value: model.partial)
                }.padding(.horizontal, 18).padding(.top, 8).padding(.bottom, 12)
            case .thinking:
                HStack(alignment: .top, spacing: 10) {
                    if model.micOff { MicGlyph(muted: true, size: 9).padding(.top, 1) }
                    VStack(alignment: .leading, spacing: 4) {
                        if model.steps.isEmpty { stepRow(StepLine(text: "Working…", done: false)) }
                        ForEach(model.steps.suffix(3)) { stepRow($0).transition(.asymmetric(insertion: .move(edge: .bottom).combined(with: .opacity), removal: .opacity)) }
                    }
                    stopButton
                }.padding(.leading, 18).padding(.trailing, 12).padding(.top, 9).padding(.bottom, 13)
            case .speaking:
                HStack(spacing: 11) {
                    if model.micOff { MicGlyph(muted: true, size: 9) }
                    doneOrBars
                    Text(model.text).font(JTheme.text(13, .medium)).foregroundStyle(JTheme.label)
                        .lineLimit(3).frame(maxWidth: 330, alignment: .leading)
                    stopButton
                }.padding(.leading, 18).padding(.trailing, 12).padding(.top, 8).padding(.bottom, 12)
            case .silent:
                HStack(spacing: 8) {
                    if model.flash == .done {
                        Image(systemName: "checkmark.circle.fill").font(.system(size: 12)).foregroundStyle(JTheme.done)
                            .transition(.scale(scale: 0.4).combined(with: .opacity))
                    } else {
                        Image(systemName: "speaker.slash.fill").font(.system(size: 10)).foregroundStyle(JTheme.secondary)
                    }
                    Text(model.text).font(JTheme.text(13)).foregroundStyle(JTheme.secondary)
                        .lineLimit(3).frame(maxWidth: 340, alignment: .leading)
                }.padding(.horizontal, 18).padding(.top, 8).padding(.bottom, 12)
            case .error:
                HStack(spacing: 9) {
                    Image(systemName: "exclamationmark.circle.fill").font(.system(size: 13)).foregroundStyle(JTheme.danger)
                    Text(model.text).font(JTheme.text(13, .medium)).foregroundStyle(JTheme.label)
                        .lineLimit(2).frame(maxWidth: 320, alignment: .leading)
                }.padding(.horizontal, 18).padding(.top, 8).padding(.bottom, 12)
            }
        }
    }

    /// Voice bars while talking; a green check pops in for the first second after a task finished.
    @ViewBuilder private var doneOrBars: some View {
        if model.flash == .done {
            Image(systemName: "checkmark.circle.fill").font(.system(size: 14)).foregroundStyle(JTheme.done)
                .transition(.scale(scale: 0.4).combined(with: .opacity))
        } else {
            LiveBars(color: JTheme.accent).transition(.opacity)
        }
    }

    private func stepRow(_ s: StepLine) -> some View {
        HStack(spacing: 7) {
            if s.done {
                Image(systemName: "checkmark").font(.system(size: 9, weight: .bold)).foregroundStyle(JTheme.done)
                    .frame(width: 12, height: 12)
            } else {
                ProgressView().controlSize(.mini).scaleEffect(0.7).frame(width: 12, height: 12)
            }
            Text(s.text).font(JTheme.text(12.5, .medium))
                .foregroundStyle(s.done ? JTheme.secondary : JTheme.label).lineLimit(1)
                .frame(maxWidth: 320, alignment: .leading)
        }
    }

    private var stopButton: some View {
        Button(action: model.stop) {
            Image(systemName: "xmark").font(.system(size: 8, weight: .bold)).foregroundStyle(JTheme.secondary)
                .frame(width: 18, height: 18).background(Circle().fill(Color.gray.opacity(0.2)))
        }.buttonStyle(.plain).help("Stop")
    }
}

// MARK: - Light rim (look 2B): the pill keeps its shape, its edge tells the state

/// Rotating arc of light along the pill's edge. `period` seconds per lap.
struct RimArc: View {
    let bottom: CGFloat
    var color: Color
    var period: Double
    var base: Double = 0
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    var body: some View {
        let shape = UnevenRoundedRectangle(bottomLeadingRadius: bottom, bottomTrailingRadius: bottom, style: .continuous)
        ZStack {
            if base > 0 { shape.strokeBorder(color.opacity(base), lineWidth: 1.2) }
            if reduceMotion {
                shape.strokeBorder(color.opacity(0.75), lineWidth: 1.5)
            } else {
                TimelineView(.animation) { tl in
                    let a = (tl.date.timeIntervalSinceReferenceDate / period).truncatingRemainder(dividingBy: 1) * 360
                    shape.strokeBorder(
                        AngularGradient(gradient: Gradient(stops: [.init(color: .clear, location: 0), .init(color: .clear, location: 0.5),
                                                                   .init(color: color, location: 1)]),
                                        center: .center, angle: .degrees(a)),
                        lineWidth: 1.8)
                }
            }
        }
    }
}

/// Green edge that breathes while the mic is live. Never fades below 60%: "listening" must stay obvious.
struct RimBreath: View {
    let bottom: CGFloat
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    var body: some View {
        let shape = UnevenRoundedRectangle(bottomLeadingRadius: bottom, bottomTrailingRadius: bottom, style: .continuous)
        TimelineView(.animation(minimumInterval: 1 / 30, paused: reduceMotion)) { tl in
            let o = reduceMotion ? 1 : 0.8 + 0.2 * sin(tl.date.timeIntervalSinceReferenceDate * 3.2)
            shape.strokeBorder(JTheme.done.opacity(o), lineWidth: 1.5)
                .shadow(color: JTheme.done.opacity(0.25 * o), radius: 5)
        }
    }
}

/// Decaying side-to-side shake. Animate `t` from n to n+1 for one shake.
struct ShakeEffect: GeometryEffect {
    var t: CGFloat
    var animatableData: CGFloat { get { t } set { t = newValue } }
    func effectValue(size: CGSize) -> ProjectionTransform {
        let f = t - floor(t)
        return ProjectionTransform(CGAffineTransform(translationX: 5 * sin(f * .pi * 6) * (1 - f), y: 0))
    }
}
