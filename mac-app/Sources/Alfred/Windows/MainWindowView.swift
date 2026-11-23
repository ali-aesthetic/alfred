import SwiftUI
import AppKit
import AVFoundation

enum MainSection: String, CaseIterable, Identifiable {
    case home = "Home", console = "Console", routines = "Routines", memory = "Memory", settings = "Settings", help = "Help"
    var id: String { rawValue }
    var icon: String {
        switch self {
        case .home: return "house"
        case .console: return "text.bubble"
        case .routines: return "bolt.circle"
        case .memory: return "brain.head.profile"
        case .settings: return "gearshape"
        case .help: return "questionmark.circle"
        }
    }
}

/// Shared state for the main window and menu-bar icon.
@MainActor
final class AppState: ObservableObject {
    static let shared = AppState()
    @Published var section: MainSection = MainSection(rawValue: UserDefaults.standard.string(forKey: "alfred.section") ?? "") ?? .home {
        didSet { UserDefaults.standard.set(section.rawValue, forKey: "alfred.section") }
    }
    @Published var awake = false
    @Published var mode: PillMode = .asleep
    @Published var draft = ""
    /// Bumped when a task finishes: Home's mark plays its one light sweep.
    @Published var sweepTick = 0
    var label: String { !awake ? "Asleep" : (mode == .listening ? "Listening" : "Awake") }
}

struct MainWindowView: View {
    @ObservedObject private var st = AppState.shared
    @ObservedObject private var bridge = Bridge.shared
    var body: some View {
        NavigationSplitView {
            List(MainSection.allCases, selection: Binding(get: { st.section }, set: { st.section = $0 ?? .home })) { s in
                Label(s.rawValue, systemImage: s.icon).tag(s)
            }
            .listStyle(.sidebar)
            .navigationSplitViewColumnWidth(min: 160, ideal: 176, max: 220)
            .toolbar(removing: .sidebarToggle)
            .safeAreaInset(edge: .bottom) {
                HStack(spacing: 7) {
                    Circle().fill(st.awake ? WTheme.done : Color.secondary).frame(width: 7, height: 7)
                    Text(st.label).font(.caption).foregroundStyle(.secondary)
                    Spacer()
                    MicGlyph(muted: (bridge.settings["mic_off"] as? Bool) == true, size: 10)
                        .help((bridge.settings["mic_off"] as? Bool) == true ? "Microphone off" : "Microphone on")
                }
                .padding(.horizontal, 16).padding(.vertical, 12)
            }
        } detail: {
            Group {
                switch st.section {
                case .home: HomePane()
                case .console: ConsoleView()
                case .routines: RoutinesPane()
                case .memory: MemoryPane()
                case .settings: SettingsPage()
                case .help: HelpPane()
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .navigationTitle(st.section == .home ? "Alfred" : st.section.rawValue)
            .toolbar(removing: .sidebarToggle)
        }
    }
}

struct HomePane: View {
    @ObservedObject private var st = AppState.shared
    @ObservedObject private var chat = ConsoleModel.shared
    @ObservedObject private var bridge = Bridge.shared
    @FocusState private var focused: Bool
    @State private var perms = PermStatus()
    @State private var routines: [Routine] = []
    private let timer = Timer.publish(every: 2, on: .main, in: .common).autoconnect()

    private var hour: Int { Calendar.current.component(.hour, from: Date()) }
    private var greeting: String {
        let name = (bridge.settings["name"] as? String)?.trimmingCharacters(in: .whitespaces) ?? ""
        let g: String
        switch hour {
        case 5..<12: g = "Good morning"
        case 12..<17: g = "Good afternoon"
        case 17..<22: g = "Good evening"
        default: return name.isEmpty ? "Still up?" : "Still up, \(name)?"
        }
        return name.isEmpty ? g : "\(g), \(name)"
    }
    private var micOff: Bool { (bridge.settings["mic_off"] as? Bool) == true }
    /// One quiet status line, only when something is going on (no filler text).
    private var subtitle: String {
        if !st.awake { return "Asleep. Press the talk key to wake me." }
        switch st.mode {
        case .listening: return "Listening"
        case .thinking: return "On it…"
        case .speaking: return "Talking…"
        default: return ""
        }
    }

    var body: some View {
        ScrollView {
            VStack(spacing: 12) {
                if !perms.allOK { permsBanner }
                VStack(spacing: 8) {
                    JMark(awake: st.awake, mode: st.mode, size: 56)
                    Text(greeting).font(.system(size: 24, weight: .semibold, design: .rounded))
                    Text(subtitle).font(.callout).foregroundStyle(.secondary).frame(height: 14)
                }
                micToggle
                askField
                TodayCard()
                chips
                recent
            }
            .padding(.horizontal, 28).padding(.vertical, 18).frame(maxWidth: 620).frame(maxWidth: .infinity)
        }
        .onAppear { focused = true; perms.refresh(); loadRoutines() }
        .onReceive(timer) { _ in perms.refresh() }
    }

    /// Big, labelled, one click. On = green + switch right; Off = grey mic with red slash + switch left.
    private var micToggle: some View {
        let off = micOff
        return Button { Bridge.shared.set("mic_off", !off) } label: {
            HStack(spacing: 12) {
                ZStack {
                    Circle().fill(off ? Color.primary.opacity(0.07) : WTheme.done.opacity(0.18))
                    MicGlyph(muted: off, size: 15, tint: WTheme.done)
                }.frame(width: 34, height: 34)
                (Text("Microphone: ").foregroundStyle(.secondary) + Text(off ? "Off" : "On").fontWeight(.semibold).foregroundStyle(off ? Color.primary : WTheme.done))
                    .font(.system(size: 16))
                Spacer(minLength: 8)
                ZStack(alignment: off ? .leading : .trailing) {
                    Capsule().fill(off ? Color.primary.opacity(0.18) : WTheme.done).frame(width: 40, height: 24)
                    Circle().fill(.white).frame(width: 20, height: 20).shadow(color: .black.opacity(0.25), radius: 1.5, y: 1).padding(2)
                }
            }
            .padding(.leading, 10).padding(.trailing, 14).padding(.vertical, 8)
            .frame(width: 300)
            .background(Capsule().fill(off ? Color.primary.opacity(0.04) : WTheme.done.opacity(0.08)))
            .overlay(Capsule().strokeBorder(off ? Color.primary.opacity(0.14) : WTheme.done.opacity(0.7), lineWidth: off ? 1 : 1.5))
            .contentShape(Capsule())
            .animation(.easeOut(duration: 0.18), value: off)
        }
        .buttonStyle(.plain)
        .accessibilityLabel("Microphone")
        .accessibilityValue(off ? "Off" : "On")
        .accessibilityHint("Turns the microphone \(off ? "on" : "off")")
    }

    private var askField: some View {
        HStack(spacing: 10) {
            Image(systemName: "text.cursor").font(.body).foregroundStyle(.secondary)
            TextField("Ask Alfred anything…", text: $st.draft)
                .textFieldStyle(.plain).font(.system(size: 17)).focused($focused)
                .onSubmit(send)
            Button(action: send) {
                Image(systemName: "arrow.up.circle.fill").font(.system(size: 28)).foregroundStyle(canSend ? WTheme.accent : Color.secondary.opacity(0.4))
            }
            .buttonStyle(.plain).disabled(!canSend).accessibilityLabel("Send")
        }
        .padding(.horizontal, 16).padding(.vertical, 11)
        .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 18, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 18, style: .continuous).strokeBorder(focused ? WTheme.accent.opacity(0.55) : Color.primary.opacity(0.12), lineWidth: focused ? 1.5 : 1))
        .shadow(color: .black.opacity(0.08), radius: 12, y: 4)
    }
    private var canSend: Bool { !st.draft.trimmingCharacters(in: .whitespaces).isEmpty }

    private func send() {
        let t = st.draft.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !t.isEmpty else { return }
        chat.send(t); st.draft = ""
    }

    private func loadRoutines() {
        let b = Bridge.shared
        guard let arr = b.readJSON(b.routinesPath) as? [[String: Any]] else { routines = RoutinesModel.defaults; return }
        routines = arr.map { Routine(id: $0["id"] as? String ?? "", name: $0["name"] as? String ?? "", hotkey: "", steps: (($0["steps"] as? [[String: Any]]) ?? []).map(RStep.init(json:))) }
    }

    private struct Chip: Identifiable { let id = UUID(); let text: String; let icon: String; let action: () -> Void }

    private var suggestions: [Chip] {
        var out: [Chip] = []
        func routine(_ id: String) -> Chip? {
            guard let r = routines.first(where: { $0.id == id }) else { return nil }
            return Chip(text: r.title, icon: r.icon) { Bridge.shared.send("routine", ["name": r.id]) }
        }
        func ask(_ t: String, _ icon: String) -> Chip { Chip(text: t, icon: icon) { chat.send(t) } }
        switch hour {
        case 5..<12:
            out = [ask("What's on today?", "calendar"), routine("class"), routine("edit")].compactMap { $0 }
        case 12..<18:
            out = [routine("edit"), routine("class"), ask("What should I focus on?", "scope")].compactMap { $0 }
        default:
            out = [routine("wind_down"), routine("edit"), ask("Remind me tomorrow", "bell")].compactMap { $0 }
        }
        for r in routines where out.count < 3 && !out.contains(where: { $0.text == r.title }) {
            out.append(Chip(text: r.title, icon: r.icon) { Bridge.shared.send("routine", ["name": r.id]) })
        }
        return Array(out.prefix(3))
    }

    private var chips: some View {
        FlowLayout(spacing: 8) {
            ForEach(suggestions) { c in
                Button(action: c.action) { Label(c.text, systemImage: c.icon).lineLimit(1).fixedSize() }
                    .buttonStyle(ChipStyle())
            }
        }
    }

    // MARK: recent ("Today")

    private static func plain(_ s: String) -> String {
        var t = ConsoleModel.clean(s).replacingOccurrences(of: "\n", with: " ")
        for c in ["**", "__", "`", "#", "*"] { t = t.replacingOccurrences(of: c, with: "") }
        return t.trimmingCharacters(in: .whitespacesAndNewlines)
    }
    private static func internalText(_ s: String) -> Bool {
        let t = s.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        if t.isEmpty { return true }
        if t.hasPrefix("[") || t.hasPrefix("{") || t.hasPrefix("<") || t.hasPrefix("(") { return true }
        return ["alfred-ctl", "/users/", "data/ui", "tool_use", "system-reminder", "no_reply", "traceback", "```", "http://localhost"].contains { t.contains($0) }
    }
    private struct Entry: Identifiable { let id: UUID; let ask: String; let answer: String? }
    private var entries: [Entry] {
        var out: [Entry] = []
        let ms = chat.messages
        for (i, m) in ms.enumerated() where m.fromUser {
            let q = Self.plain(m.text)
            if Self.internalText(q) || q.count < 2 { continue }
            var a: String?
            if let r = ms[(i + 1)...].first(where: { !$0.fromUser }), !(ms[(i + 1)...].prefix(while: { !$0.fromUser }).isEmpty), !Self.internalText(ConsoleModel.clean(r.text)) {
                let p = Self.plain(r.text)
                a = String(p.split(whereSeparator: { ".!?".contains($0) }).first ?? Substring(p))
            }
            out.append(Entry(id: m.id, ask: q, answer: a))
        }
        return Array(out.suffix(4).reversed())
    }

    private var recent: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Recent asks").font(.headline).foregroundStyle(.secondary)
            let items = entries
            if items.isEmpty {
                Text("Nothing yet. Ask me something, or hold the talk key.").font(.callout).foregroundStyle(.secondary)
                    .frame(maxWidth: .infinity, alignment: .leading).jCard(radius: 14, padding: 14)
            } else {
                VStack(spacing: 0) {
                    ForEach(Array(items.enumerated()), id: \.element.id) { i, e in
                        HStack(alignment: .top, spacing: 12) {
                            Image(systemName: "arrow.turn.down.right").font(.caption).foregroundStyle(.tertiary).padding(.top, 4)
                            VStack(alignment: .leading, spacing: 2) {
                                Text(e.ask).font(.callout.weight(.medium)).lineLimit(1)
                                if let a = e.answer { Text(a).font(.callout).foregroundStyle(.secondary).lineLimit(1) }
                            }
                            Spacer(minLength: 0)
                        }
                        .padding(.vertical, 9).padding(.horizontal, 14)
                        if i < items.count - 1 { Divider().padding(.leading, 40) }
                    }
                }
                .background(RoundedRectangle(cornerRadius: 14, style: .continuous).fill(Color.primary.opacity(0.045)))
                .overlay(RoundedRectangle(cornerRadius: 14, style: .continuous).strokeBorder(Color.primary.opacity(0.09), lineWidth: 1))
            }
        }.frame(maxWidth: .infinity, alignment: .leading)
    }

    private var permsBanner: some View {
        VStack(alignment: .leading, spacing: 8) {
            Label("A few permissions are missing", systemImage: "exclamationmark.triangle.fill")
                .font(.callout.weight(.semibold)).foregroundStyle(.orange)
            HStack(spacing: 8) {
                if !perms.ax { permBtn("Accessibility", "Privacy_Accessibility") { _ = AXIsProcessTrustedWithOptions(["AXTrustedCheckOptionPrompt": true] as CFDictionary) } }
                if !perms.screen { permBtn("Screen Recording", "Privacy_ScreenCapture") { _ = CGRequestScreenCaptureAccess() } }
                if !perms.input { permBtn("Input Monitoring", "Privacy_ListenEvent") { _ = CGRequestListenEventAccess() } }
            }
        }
        .padding(12).frame(maxWidth: .infinity, alignment: .leading)
        .background(Color.orange.opacity(0.12), in: RoundedRectangle(cornerRadius: 12, style: .continuous))
    }

    private func permBtn(_ title: String, _ pane: String, _ req: @escaping () -> Void) -> some View {
        Button("Open \(title)…") {
            req()
            if let u = URL(string: "x-apple.systempreferences:com.apple.preference.security?\(pane)") { NSWorkspace.shared.open(u) }
        }.controlSize(.small)
    }
}

struct PermStatus {
    var ax = true, screen = true, input = true
    var allOK: Bool { ax && screen && input }
    mutating func refresh() {
        ax = AXIsProcessTrusted()
        screen = CGPreflightScreenCaptureAccess()
        input = CGPreflightListenEventAccess()
    }
}
