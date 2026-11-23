import SwiftUI
import Combine
import AppKit
import AVFoundation
import ApplicationServices
import CoreGraphics

/// First-run guide, one calm step at a time: check Mac → download → Claude sign-in → permissions (pictured) → how to address you → Telegram (optional).
struct OnboardingView: View {
    var onClose: () -> Void
    @ObservedObject private var bridge = Bridge.shared
    @ObservedObject private var setup = SetupManager.shared
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    enum Step: Int, CaseIterable { case welcome, download, claude, permissions, you, telegram, done
        var title: String {
            switch self {
            case .welcome: return "Welcome"; case .download: return "Download"; case .claude: return "Sign in"
            case .permissions: return "Permissions"; case .you: return "You"; case .telegram: return "Telegram"; case .done: return "Ready"
            }
        }
    }
    @State private var step: Step = .welcome
    @State private var mic = false
    @State private var ax = false
    @State private var screen = false
    @State private var input = false
    @State private var signedIn = ClaudeLogin.signedIn()
    @State private var guide: PermissionGuide.Kind = .accessibility
    private let timer = Timer.publish(every: 1, on: .main, in: .common).autoconnect()

    private var macOK: Bool { ProcessInfo.processInfo.isOperatingSystemAtLeast(OperatingSystemVersion(majorVersion: 14, minorVersion: 0, patchVersion: 0)) }
    private var appleSilicon: Bool {
        var s = 0; var size = MemoryLayout<Int>.size
        sysctlbyname("hw.optional.arm64", &s, &size, nil, 0); return s == 1
    }
    private var telegramLinked: Bool { FileManager.default.fileExists(atPath: Paths.data + "/telegram_bot_token") }   // existence only, never read

    var body: some View {
        ZStack {
            WVisualEffect(material: .underWindowBackground).ignoresSafeArea()
            VStack(alignment: .leading, spacing: 0) {
                progressDots.padding(.bottom, 18)
                ScrollView { content.frame(maxWidth: .infinity, alignment: .leading) }.scrollIndicators(.hidden)
                Spacer(minLength: 8)
                footer
            }
            .padding(.horizontal, 32).padding(.top, 34).padding(.bottom, 22)
        }
        .onAppear { refresh(); if setup.needed && !setup.running && step == .welcome { } }
        .onReceive(timer) { _ in refresh() }
    }

    // MARK: header / footer
    private var progressDots: some View {
        HStack(spacing: 6) {
            ForEach(Step.allCases, id: \.rawValue) { s in
                Capsule().fill(s.rawValue <= step.rawValue ? WTheme.accent : Color.primary.opacity(0.12)).frame(height: 4)
            }
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("Step \(step.rawValue + 1) of \(Step.allCases.count): \(step.title)")
    }

    private var footer: some View {
        HStack {
            if step != .welcome && step != .done { Button("Back") { go(-1) }.disabled(step == .download && setup.running) }
            Spacer()
            switch step {
            case .welcome:
                Button("Continue") { go(1); if setup.needed { setup.start() } }.buttonStyle(.borderedProminent).controlSize(.large)
                    .disabled(!macOK || !appleSilicon).keyboardShortcut(.defaultAction)
            case .download:
                Button(setup.finished || !setup.needed ? "Continue" : "Continue when finished") { go(1) }
                    .buttonStyle(.borderedProminent).controlSize(.large).disabled(setup.needed && !setup.finished)
            case .claude:
                if signedIn { Button("Continue") { go(1) }.buttonStyle(.borderedProminent).controlSize(.large) } else { Button("Skip for now") { go(1) }.buttonStyle(.bordered).controlSize(.large) }
            case .permissions:
                Button(ax && mic ? "Continue" : "Continue anyway") { go(1) }.buttonStyle(.borderedProminent).controlSize(.large)
            case .you, .telegram:
                Button(step == .telegram && !telegramLinked ? "Skip" : "Continue") { go(1) }.buttonStyle(.borderedProminent).controlSize(.large)
            case .done:
                Button("Start using Alfred") { finish() }.buttonStyle(.borderedProminent).controlSize(.large).keyboardShortcut(.defaultAction)
            }
        }
    }

    private func go(_ d: Int) {
        let n = Step(rawValue: step.rawValue + d) ?? step
        if reduceMotion { step = n } else { withAnimation(.easeInOut(duration: 0.2)) { step = n } }
    }

    private func finish() {
        Bridge.shared.set("onboarded", true)
        (NSApp.delegate as? AppDelegate)?.brain.restart()
        onClose()
    }

    // MARK: steps
    @ViewBuilder private var content: some View {
        switch step {
        case .welcome: welcome
        case .download: download
        case .claude: claude
        case .permissions: permissions
        case .you: you
        case .telegram: telegram
        case .done: done
        }
    }

    private func title(_ t: String, _ sub: String) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(t).font(.system(size: 26, weight: .semibold))
            Text(sub).font(.callout).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
        }.padding(.bottom, 16)
    }

    private var welcome: some View {
        VStack(alignment: .leading, spacing: 0) {
            Image(systemName: "circle.circle").font(.system(size: 34, weight: .thin)).padding(.bottom, 6)
            title("At your service.", "Alfred is a voice assistant that lives on your Mac. Setup takes about ten minutes; most of it is one download.")
            check("macOS 14 or newer", macOK, macOK ? "You have \(ProcessInfo.processInfo.operatingSystemVersionString)" : "Please update macOS first")
            check("Apple Silicon Mac (M1 or newer)", appleSilicon, appleSilicon ? "Yes" : "Alfred's speech engine needs Apple Silicon")
            check("About 6 GB free disk space", freeGB >= 6, String(format: "%.0f GB free", freeGB))
            row("lock.shield", "Private by design", "Your voice is turned into text on this Mac. Alfred never sees your Claude login.")
        }
    }
    private var freeGB: Double {
        ((try? URL(fileURLWithPath: NSHomeDirectory()).resourceValues(forKeys: [.volumeAvailableCapacityForImportantUsageKey]).volumeAvailableCapacityForImportantUsage) ?? 0).map { Double($0) / 1e9 } ?? 0
    }

    private var download: some View {
        VStack(alignment: .leading, spacing: 12) {
            title("Getting Alfred ready", setup.needed ? "One-time download, about 1.5 GB. You can pause it, and it keeps going if you close this window." : "Everything is already installed.")
            if setup.needed || setup.finished { SetupProgressCard() }
            else { check("Alfred is installed", true, Paths.home) }
        }
    }

    private var claude: some View {
        VStack(alignment: .leading, spacing: 12) {
            title("Sign in to Claude", "Alfred thinks with your own Claude account. You sign in once on Anthropic's own web page; Alfred never sees your password.")
            check("Claude account", signedIn, signedIn ? "Signed in" : "Not signed in yet")
            if !signedIn {
                numbered(1, "Press the button. Terminal opens and installs Claude Code if needed.")
                numbered(2, "Your browser opens Anthropic's sign-in page. Approve it.")
                numbered(3, "Come back here. This page notices by itself.")
                Button { ClaudeLogin.openTerminal() } label: { Label("Open sign-in", systemImage: "person.badge.key") }.controlSize(.large)
                Text("No Claude plan yet? You can use an API key or a local model later in Settings → Brain. Computer control works best on Claude.")
                    .font(.caption).foregroundStyle(.secondary)
            }
        }
    }

    private var permissions: some View {
        VStack(alignment: .leading, spacing: 10) {
            title("Permissions", "macOS asks you to allow each one. Tap a row to see exactly where to click.")
            perm("Microphone", "mic", .microphone, mic, "to hear you") {
                if AVCaptureDevice.authorizationStatus(for: .audio) == .notDetermined { AVCaptureDevice.requestAccess(for: .audio) { _ in } } else { open("Privacy_Microphone") }
            }
            perm("Accessibility", "hand.point.up.left", .accessibility, ax, "to click and type for you") {
                _ = AXIsProcessTrustedWithOptions(["AXTrustedCheckOptionPrompt": true] as CFDictionary); open("Privacy_Accessibility")
            }
            perm("Screen Recording", "rectangle.dashed.badge.record", .screen, screen, "to see what you see (optional)") {
                _ = CGRequestScreenCaptureAccess(); open("Privacy_ScreenCapture")
            }
            perm("Input Monitoring", "keyboard", .input, input, "for the talk key, right ⌥ (optional)") {
                _ = CGRequestListenEventAccess(); open("Privacy_ListenEvent")
            }
            HStack(spacing: 10) {
                icon("gearshape.2")
                VStack(alignment: .leading, spacing: 1) { Text("Automation"); Text("macOS asks the first time Alfred controls another app. Press Allow then.").font(.caption).foregroundStyle(.secondary) }
            }.rowStyle()
            PermissionGuide(kind: guide).padding(.top, 6)
        }
    }

    private var you: some View {
        VStack(alignment: .leading, spacing: 12) {
            title("How should I address you?", "You can change this any time, or just say \"call me ma'am\".")
            TextField("Your name", text: SB.str("name", ""), prompt: Text("Your name (optional)")).textFieldStyle(.roundedBorder).frame(maxWidth: 320)
            Picker("Address you as", selection: SB.str("address", "sir")) {
                Text("Sir").tag("sir"); Text("Ma'am").tag("ma'am"); Text("My name").tag("name"); Text("Nothing").tag("none")
            }.pickerStyle(.segmented).labelsHidden().frame(maxWidth: 360)
            Text("Voice").font(.system(size: 11, weight: .semibold)).tracking(0.8).foregroundStyle(.secondary).padding(.top, 8)
            HStack(spacing: 10) {
                icon("speaker.wave.2")
                Picker("Voice", selection: Binding(get: { bridge.settings["voice"] as? String ?? "bm_lewis" }, set: { Bridge.shared.set("voice", $0); Bridge.shared.send("voice_preview", ["voice": $0]) })) {
                    Text("Lewis · British, calm").tag("bm_lewis"); Text("Isabella · British").tag("bf_isabella")
                    Text("George · British").tag("bm_george"); Text("Daniel · British").tag("bm_daniel"); Text("Emma · British").tag("bf_emma")
                }.labelsHidden().frame(maxWidth: 300)
            }.rowStyle()
            Text("Sir picks Lewis and Ma'am picks Isabella, until you choose a voice yourself. Voices run offline on your Mac. Samples play once Alfred has started.")
                .font(.caption).foregroundStyle(.secondary)
        }
    }

    private var telegram: some View {
        VStack(alignment: .leading, spacing: 12) {
            title("Telegram (optional)", "Get Alfred's answers on your phone too. Skip it if you are unsure; it is one tap in Help later.")
            HStack(spacing: 10) {
                icon("paperplane")
                VStack(alignment: .leading, spacing: 1) { Text("Telegram bot"); Text(telegramLinked ? "Already connected" : "Alfred walks you through it").font(.caption).foregroundStyle(.secondary) }
                Spacer()
                if telegramLinked { Label("Connected", systemImage: "checkmark.circle.fill").foregroundStyle(WTheme.done) }
                else { Button("Set up with Alfred") { Bridge.shared.ask("Help me connect Telegram") }.controlSize(.small) }
            }.rowStyle()
        }
    }

    private var done: some View {
        VStack(alignment: .leading, spacing: 10) {
            title("All set", "Say \"Alfred\" and ask for something, or hold right ⌥ and talk.")
            check("Alfred installed", !setup.needed, "")
            check("Claude account", signedIn, signedIn ? "" : "Not signed in: open Settings → Claude")
            check("Microphone", mic, ""); check("Accessibility", ax, ax ? "" : "Needed for clicking and typing")
            Text("The wake word \"Hey Alfred\" model is not trained yet, so Alfred listens for his name through speech recognition. See Help → Wake word.")
                .font(.caption).foregroundStyle(.secondary).padding(.top, 6)
        }
    }

    // MARK: pieces
    private func refresh() {
        mic = AVCaptureDevice.authorizationStatus(for: .audio) == .authorized
        ax = AXIsProcessTrusted(); screen = CGPreflightScreenCaptureAccess(); input = CGPreflightListenEventAccess()
        signedIn = ClaudeLogin.signedIn()
    }
    private func open(_ pane: String) {
        if let u = URL(string: "x-apple.systempreferences:com.apple.preference.security?\(pane)") { NSWorkspace.shared.open(u) }
    }
    private func icon(_ name: String) -> some View {
        Image(systemName: name).font(.system(size: 13)).frame(width: 26, height: 26)
            .background(RoundedRectangle(cornerRadius: 7, style: .continuous).fill(Color.primary.opacity(0.07)))
    }
    private func row(_ sym: String, _ t: String, _ s: String) -> some View {
        HStack(alignment: .top, spacing: 10) { icon(sym); VStack(alignment: .leading, spacing: 1) { Text(t); Text(s).font(.caption).foregroundStyle(.secondary) } }.padding(.top, 12)
    }
    private func check(_ t: String, _ ok: Bool, _ sub: String) -> some View {
        HStack(spacing: 10) {
            Image(systemName: ok ? "checkmark.circle.fill" : "circle").foregroundStyle(ok ? WTheme.done : .secondary).font(.system(size: 17))
            VStack(alignment: .leading, spacing: 0) { Text(t); if !sub.isEmpty { Text(sub).font(.caption).foregroundStyle(.secondary) } }
        }.padding(.vertical, 3)
        .accessibilityElement(children: .combine).accessibilityValue(ok ? "done" : "not done")
    }
    private func numbered(_ n: Int, _ t: String) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: 10) {
            Text("\(n)").font(.system(size: 12, weight: .bold, design: .rounded)).frame(width: 22, height: 22)
                .background(Circle().fill(WTheme.accent.opacity(0.18)))
            Text(t).fixedSize(horizontal: false, vertical: true)
        }
    }
    private func perm(_ title: String, _ sym: String, _ kind: PermissionGuide.Kind, _ ok: Bool, _ why: String, _ action: @escaping () -> Void) -> some View {
        HStack(spacing: 10) {
            icon(sym)
            VStack(alignment: .leading, spacing: 1) { Text(title); Text(why).font(.caption).foregroundStyle(.secondary) }
            Spacer()
            if ok { Label("Allowed", systemImage: "checkmark.circle.fill").font(.callout).foregroundStyle(WTheme.done) }
            else { Button("Allow…") { guide = kind; action() }.controlSize(.small) }
        }
        .rowStyle()
        .contentShape(Rectangle()).onTapGesture { guide = kind }
        .overlay(RoundedRectangle(cornerRadius: 10, style: .continuous).strokeBorder(guide == kind ? WTheme.accent.opacity(0.6) : .clear, lineWidth: 1.5))
    }
}

/// Determinate progress with real numbers (HIG: show a determinate bar whenever progress can be measured).
/// Shows: percent, the current step's name, size and time left, Pause/Resume, Retry. No fake animation; Reduce Motion respected.
struct SetupProgressCard: View {
    @ObservedObject private var s = SetupManager.shared
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    private var current: SetupManager.Step? { s.steps.first { $0.state == .running } ?? s.steps.first { if case .failed = $0.state { return true } else { return false } } }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(alignment: .firstTextBaseline) {
                Text(s.finished ? "Done" : (s.paused ? "Paused" : (current?.title ?? "Ready to start"))).font(.headline)
                Spacer()
                Text("\(Int((s.overall * 100).rounded()))%").font(.system(.title3, design: .rounded).monospacedDigit().weight(.semibold))
                    .accessibilityLabel("\(Int((s.overall * 100).rounded())) percent")
            }
            ProgressView(value: s.overall).progressViewStyle(.linear).tint(s.errorText == nil ? WTheme.accent : WTheme.warn)
                .animation(reduceMotion ? nil : .linear(duration: 0.2), value: s.overall)
            if let c = current {
                if c.pct == nil && c.state == .running && !s.paused {
                    // honest: this phase cannot be measured yet; say so instead of faking a percentage
                    HStack(spacing: 6) { ProgressView().controlSize(.small); Text(c.detail.isEmpty ? "Working…" : c.detail) }.font(.callout).foregroundStyle(.secondary)
                } else { Text(c.detail.isEmpty ? " " : c.detail).font(.callout).foregroundStyle(.secondary).lineLimit(2) }
            }
            if let e = s.errorText { Label(e, systemImage: "exclamationmark.triangle.fill").font(.callout).foregroundStyle(WTheme.warn).fixedSize(horizontal: false, vertical: true) }
            HStack {
                if s.running { Button(s.paused ? "Resume" : "Pause") { s.paused ? s.resume() : s.pause() }.controlSize(.small) }
                if s.errorText != nil { Button("Retry") { s.retry() }.controlSize(.small).keyboardShortcut("r") }
                if !s.running && !s.finished && s.errorText == nil { Button("Start download") { s.start() }.controlSize(.small) }
                Spacer()
            }
            Divider()
            ForEach(s.steps) { st in
                HStack(spacing: 8) {
                    switch st.state {
                    case .done: Image(systemName: "checkmark.circle.fill").foregroundStyle(WTheme.done)
                    case .running: Image(systemName: "arrow.right.circle.fill").foregroundStyle(WTheme.accent)
                    case .failed: Image(systemName: "xmark.circle.fill").foregroundStyle(WTheme.warn)
                    case .pending: Image(systemName: "circle").foregroundStyle(.secondary)
                    }
                    Text(st.title).font(.callout).foregroundStyle(st.state == .pending ? .secondary : .primary)
                }
            }
        }
        .padding(14)
        .background(RoundedRectangle(cornerRadius: 12, style: .continuous).fill(Color.primary.opacity(0.05)))
        .overlay(RoundedRectangle(cornerRadius: 12, style: .continuous).strokeBorder(Color.primary.opacity(0.08), lineWidth: 1))
    }
}

/// A drawn picture of the System Settings pane for each permission: where to click, with the Alfred toggle highlighted.
struct PermissionGuide: View {
    enum Kind { case microphone, accessibility, screen, input
        var pane: String {
            switch self { case .microphone: return "Microphone"; case .accessibility: return "Accessibility"
            case .screen: return "Screen & System Audio Recording"; case .input: return "Input Monitoring" }
        }
        var tip: String {
            switch self {
            case .microphone: return "Press Allow in the pop-up. If you missed it, switch Alfred on here."
            case .accessibility: return "Switch Alfred on. macOS may ask for your Mac password or Touch ID."
            case .screen: return "Switch Alfred on, then press Quit & Reopen if macOS offers it."
            case .input: return "Switch Alfred on. This only lets the talk key (right ⌥) work in any app."
            }
        }
    }
    let kind: Kind

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("What you will see: System Settings → Privacy & Security → \(kind.pane)").font(.caption).foregroundStyle(.secondary)
            HStack(spacing: 0) {
                VStack(alignment: .leading, spacing: 5) {
                    ForEach(["Privacy & Security"], id: \.self) { Text($0).font(.caption2.weight(.semibold)).padding(.horizontal, 6).padding(.vertical, 3).background(RoundedRectangle(cornerRadius: 5).fill(WTheme.accent.opacity(0.9))).foregroundStyle(.white) }
                    ForEach(["Wi-Fi", "Notifications", "Battery"], id: \.self) { Text($0).font(.caption2).foregroundStyle(.secondary).padding(.horizontal, 6) }
                }.frame(width: 120, alignment: .leading).padding(8)
                Divider()
                VStack(alignment: .leading, spacing: 6) {
                    Text(kind.pane).font(.caption.weight(.semibold))
                    toggleRow("Terminal", on: false)
                    toggleRow("Alfred", on: true, highlight: true)
                    toggleRow("Chrome", on: false)
                }.padding(10).frame(maxWidth: .infinity, alignment: .leading)
            }
            .background(RoundedRectangle(cornerRadius: 10, style: .continuous).fill(Color.primary.opacity(0.04)))
            .overlay(RoundedRectangle(cornerRadius: 10, style: .continuous).strokeBorder(Color.primary.opacity(0.1)))
            Label(kind.tip, systemImage: "hand.tap").font(.callout)
        }
        .accessibilityElement(children: .combine)
    }

    private func toggleRow(_ name: String, on: Bool, highlight: Bool = false) -> some View {
        HStack {
            Text(name).font(.caption)
            Spacer()
            Capsule().fill(on ? WTheme.done : Color.primary.opacity(0.2)).frame(width: 28, height: 16)
                .overlay(Circle().fill(.white).frame(width: 12, height: 12).offset(x: on ? 6 : -6))
        }
        .padding(.horizontal, 6).padding(.vertical, 3)
        .background(RoundedRectangle(cornerRadius: 6).fill(highlight ? WTheme.accent.opacity(0.15) : .clear))
        .overlay(RoundedRectangle(cornerRadius: 6).strokeBorder(highlight ? WTheme.accent : .clear, lineWidth: 1.5))
    }
}

extension View {
    func rowStyle() -> some View {
        padding(.horizontal, 10).padding(.vertical, 6)
            .background(RoundedRectangle(cornerRadius: 10, style: .continuous).fill(Color.primary.opacity(0.05)))
            .overlay(RoundedRectangle(cornerRadius: 10, style: .continuous).strokeBorder(Color.primary.opacity(0.08), lineWidth: 1))
    }
}
