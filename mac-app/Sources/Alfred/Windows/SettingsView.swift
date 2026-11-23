import SwiftUI
import Combine
import AppKit
import AVFoundation
import ServiceManagement

/// Kept for `SettingsNav` (older callers). Settings is now one flat page.
enum SettingsPane: String, CaseIterable, Identifiable {
    case personality = "Personality", schedule = "Schedule", routines = "Routines", memory = "Memory", abilities = "Abilities", general = "General"
    var id: String { rawValue }
}

/// Standalone settings (same page the main window shows).
struct SettingsView: View {
    var body: some View { SettingsPage().frame(minWidth: 520, minHeight: 480) }
}

// MARK: - bindings to Bridge settings

@MainActor
struct SB {
    static var bridge: Bridge { Bridge.shared }
    static func str(_ k: String, _ d: String) -> Binding<String> {
        Binding(get: { bridge.settings[k] as? String ?? d }, set: { bridge.set(k, $0) })
    }
    static func bool(_ k: String, _ d: Bool) -> Binding<Bool> {
        Binding(get: { (bridge.settings[k] as? NSNumber)?.boolValue ?? d }, set: { bridge.set(k, $0) })
    }
    static func dbl(_ k: String, _ d: Double) -> Binding<Double> {
        Binding(get: { (bridge.settings[k] as? NSNumber)?.doubleValue ?? d }, set: { bridge.set(k, $0) })
    }
    /// 0...100 whole number, stored as Int.
    static func pct(_ k: String, _ d: Int) -> Binding<Double> {
        Binding(get: { Double((bridge.settings[k] as? NSNumber)?.intValue ?? d) },
                set: { bridge.set(k, Int(($0 / 5).rounded()) * 5) })
    }
}

// MARK: - One flat settings page

struct SettingsPage: View {
    @ObservedObject private var bridge = Bridge.shared
    @State private var login = SMAppService.mainApp.status == .enabled
    @State private var classFrom = 0
    @State private var classTo = 3
    @State private var classStart = 10
    @State private var classEnd = 14
    static let days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

    var body: some View {
        Form {
            youSection
            personalitySection
            voiceSection
            brainSection
            quietSection
            abilitiesSection
            generalSection
        }
        .formStyle(.grouped)
        .onAppear(perform: loadClassHours)
    }

    // You
    private var youSection: some View {
        Section {
            TextField("Your name", text: SB.str("name", ""), prompt: Text("What should I call you?"))
            Picker("Address you as", selection: SB.str("address", "sir")) {
                Text("Sir").tag("sir"); Text("Ma'am").tag("ma'am"); Text("My name").tag("name"); Text("Nothing").tag("none")
            }
        } header: { Text("You") } footer: {
            Text("Say \"call me ma'am\" or \"don't call me sir\" any time. The voice follows (Sir: Lewis, Ma'am: Isabella) until you pick one yourself.").frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    // Personality
    private var personalitySection: some View {
        let humor = SB.pct("humor", 75), honesty = SB.pct("honesty", 90)
        return Section {
            PercentSlider(title: "Humor", icon: "theatermasks", value: humor, low: "Serious", high: "Joker")
            PercentSlider(title: "Honesty", icon: "scalemass", value: honesty, low: "Gentle", high: "Blunt")
            Picker("Talk length", selection: SB.str("length", "normal")) {
                Text("Short").tag("short"); Text("Normal").tag("normal"); Text("Detailed").tag("detailed")
            }.pickerStyle(.segmented)
            ExampleBubble(text: Self.example(humor: Int(humor.wrappedValue), honesty: Int(honesty.wrappedValue)))
            Toggle("One joke a day", isOn: SB.bool("joke_a_day", false))
        } header: { Text("Personality") } footer: {
            Text("Drag the sliders and watch how I'd answer.").frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    /// Deadpan one-liner for “Rate my 3 a.m. edit.” at the chosen humor / honesty.
    static func example(humor: Int, honesty: Int) -> String {
        let h = humor < 34 ? 0 : (humor < 67 ? 1 : 2)
        let t = honesty < 34 ? 0 : (honesty < 67 ? 1 : 2)
        let grid: [[String]] = [
            // rows: humor low / mid / high — columns: honesty low / mid / high
            ["Looks great.", "Solid work. The ending could be tighter.", "The middle drags. Cut 20 seconds."],
            ["A triumph. I would watch it twice.", "Good bones. The ending wanders, like a cat.", "Strong start, weak ending. Cut the last 20 seconds."],
            ["Oscar material. I have notified the Academy. They have not replied.", "Nice. The ending drags. My circuits yawned, politely.", "The ending is rough. I have filed a formal complaint with myself."]
        ]
        return grid[h][t]
    }

    // Voice
    private var voiceSection: some View {
        VoicePicker()
    }

    // Brain
    private var brainSection: some View {
        Section {
            Picker("Brain", selection: SB.str("brain", "claude-subscription")) {
                ForEach(BrainCatalog.all) { Text($0.label + ($0.ready ? "" : " (experimental)")).tag($0.id) }
            }
            LabeledContent("Restart to apply") { Button("Restart my brain") { Bridge.shared.send("restart") }.controlSize(.small) }
        } header: { Text("Brain") } footer: {
            Text("Computer control is strongest on Claude and weaker on small local models. Experimental brains chat only and are not verified end to end.").frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    // Quiet hours
    private var quietSection: some View {
        let on = SB.bool("quiet_class", true)
        return Section {
            Toggle("Stay quiet during class", isOn: on)
            if on.wrappedValue {
                Picker("Days", selection: $classFrom) { ForEach(0..<7, id: \.self) { Text(Self.days[$0]).tag($0) } }
                    .onChange(of: classFrom) { _, _ in saveClassHours() }
                Picker("Until", selection: $classTo) { ForEach(0..<7, id: \.self) { Text(Self.days[$0]).tag($0) } }
                    .onChange(of: classTo) { _, _ in saveClassHours() }
                Picker("From", selection: $classStart) { ForEach(0..<24, id: \.self) { Text(String(format: "%02d:00", $0)).tag($0) } }
                    .onChange(of: classStart) { _, _ in saveClassHours() }
                Picker("To", selection: $classEnd) { ForEach(0..<24, id: \.self) { Text(String(format: "%02d:00", $0)).tag($0) } }
                    .onChange(of: classEnd) { _, _ in saveClassHours() }
            }
        } header: { Text("Quiet hours") } footer: {
            Text("No voice while you're in lectures. I'll reply in text only.").frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    private func loadClassHours() {
        let s = SB.str("class_hours", "Mon-Thu 10:00-14:00").wrappedValue
        let parts = s.split(separator: " ")
        guard parts.count >= 2 else { return }
        let d = parts[0].split(separator: "-").map(String.init)
        if let f = Self.days.firstIndex(of: d.first ?? "") { classFrom = f }
        if let t = Self.days.firstIndex(of: d.last ?? "") { classTo = t }
        let h = parts[1].split(separator: "-").map { Int($0.split(separator: ":").first ?? "") ?? 0 }
        if h.count == 2 { classStart = h[0]; classEnd = h[1] }
    }
    private func saveClassHours() {
        let d = classFrom == classTo ? Self.days[classFrom] : "\(Self.days[classFrom])-\(Self.days[classTo])"
        let v = "\(d) \(String(format: "%02d:00", classStart))-\(String(format: "%02d:00", classEnd))"
        if SB.str("class_hours", "").wrappedValue != v { Bridge.shared.set("class_hours", v) }
    }

    // Abilities
    private var abilitiesSection: some View {
        Section {
            Toggle(isOn: SB.bool("computer_control", true)) { Label("Use my Mac for me", systemImage: "cursorarrow.click.2") }
            Toggle(isOn: SB.bool("camera", false)) { Label("Look at me (camera)", systemImage: "camera") }
            Toggle(isOn: Binding(get: { !SB.bool("mic_off", false).wrappedValue }, set: { Bridge.shared.set("mic_off", !$0) })) { Label("Listen (microphone)", systemImage: "mic") }
            Toggle(isOn: SB.bool("silent", false)) { Label("Text only, no voice", systemImage: "speaker.slash") }
            Toggle(isOn: SB.bool("stay_awake", false)) { Label("Stay awake while I'm away", systemImage: "cup.and.saucer") }
            Toggle(isOn: Binding(get: { SB.str("holo_mode", "off").wrappedValue != "off" },
                                 set: { Bridge.shared.set("holo_mode", $0 ? "auto" : "off") })) { Label("Holograms (experimental)", systemImage: "cube.transparent") }
        } header: { Text("What I can do") } footer: {
            Text("I only look at your screen while you hold the talk key. Stay awake keeps the Mac online for Telegram (plugged in, lid open).").frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    // General
    private var generalSection: some View {
        Section {
            Picker("Hold to talk", selection: SB.str("hotkey", "right_option")) {
                Text("Right ⌥").tag("right_option"); Text("Left ⌥").tag("left_option"); Text("Right ⌘").tag("right_command"); Text("Fn").tag("fn")
            }
            Toggle("Open at login", isOn: Binding(get: { login }, set: { v in
                do { if v { try SMAppService.mainApp.register() } else { try SMAppService.mainApp.unregister() } } catch {}
                login = SMAppService.mainApp.status == .enabled
            }))
            let signed = SB.bool("claude_signed_in", true).wrappedValue
            LabeledContent("Claude account") {
                if signed {
                    Label("Signed in", systemImage: "checkmark.circle.fill").foregroundStyle(WTheme.done)
                } else {
                    Button("Sign in…") { ClaudeLogin.openTerminal() }
                }
            }
            LabeledContent("Feeling stuck?") {
                Button("Restart my brain") { Bridge.shared.send("restart") }
            }
        } header: { Text("General") }
    }
}

// MARK: - Controls

struct PercentSlider: View {
    let title: String, icon: String
    @Binding var value: Double
    let low: String, high: String
    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack {
                Label(title, systemImage: icon)
                Spacer()
                Text("\(Int(value))%").monospacedDigit().foregroundStyle(.secondary)
            }
            HStack(spacing: 8) {
                Text(low).font(.caption).foregroundStyle(.secondary).frame(width: 52, alignment: .leading)
                Slider(value: $value, in: 0...100, step: 5).accessibilityLabel(title)
                Text(high).font(.caption).foregroundStyle(.secondary).frame(width: 52, alignment: .trailing)
            }
        }
        .padding(.vertical, 2)
    }
}

struct ExampleBubble: View {
    let text: String
    var body: some View {
        HStack(alignment: .top, spacing: 10) {
            Image(systemName: "circle.circle").foregroundStyle(WTheme.accent).padding(.top, 1)
            VStack(alignment: .leading, spacing: 2) {
                Text("Ask: “Rate my 3 a.m. edit.”").font(.caption).foregroundStyle(.secondary)
                Text(text).font(.callout).fixedSize(horizontal: false, vertical: true)
                    .contentTransition(.opacity)
            }
            Spacer(minLength: 0)
        }
        .padding(12)
        .background(Color.primary.opacity(0.05), in: RoundedRectangle(cornerRadius: 12, style: .continuous))
        .animation(.easeOut(duration: 0.15), value: text)
    }
}

struct VoicePicker: View {
    @ObservedObject private var bridge = Bridge.shared
    struct V: Identifiable { let id: String; let label: String }

    private static let fallback: [V] = [
        V(id: "Daniel", label: "Daniel · English (UK)"), V(id: "Samantha", label: "Samantha · English (US)"),
        V(id: "Karen", label: "Karen · English (Australia)"), V(id: "Moira", label: "Moira · English (Ireland)"),
        V(id: "Milena", label: "Milena · Russian"), V(id: "Yuri", label: "Yuri · Russian")]

    var voices: [V] {
        var out: [V] = []
        if let arr = bridge.settings["voices"] as? [[String: Any]] {
            for d in arr {
                guard let id = d["id"] as? String else { continue }
                let name = d["name"] as? String ?? id
                let lang = (d["lang"] as? String).flatMap { Locale.current.localizedString(forIdentifier: $0.replacingOccurrences(of: "_", with: "-")) }
                out.append(V(id: id, label: lang.map { "\(name) · \($0)" } ?? name))
            }
        }
        if out.isEmpty { out = Self.fallback }
        let cur = bridge.settings["voice"] as? String ?? "bm_lewis"
        if !out.contains(where: { $0.id == cur }) { out.insert(V(id: cur, label: cur), at: 0) }
        return out
    }

    var body: some View {
        let sel = Binding<String>(get: { bridge.settings["voice"] as? String ?? "bm_lewis" }, set: { id in
            Bridge.shared.set("voice", id)
            Bridge.shared.send("voice_preview", ["voice": id])
        })
        Section {
            Picker("Voice", selection: sel) { ForEach(voices) { Text($0.label).tag($0.id) } }
            LabeledContent("Hear it") {
                Button { Bridge.shared.send("voice_preview", ["voice": sel.wrappedValue]) } label: { Label("Play sample", systemImage: "speaker.wave.2") }
            }
        } header: { Text("Voice") } footer: {
            Text("Picking a voice plays a short sample.").frame(maxWidth: .infinity, alignment: .leading)
        }
    }
}

// MARK: - Memory

struct MemItem: Identifiable { var id: String; var type: String; var date: String; var fact: String }

struct MemoryPane: View {
    @State private var items: [MemItem] = []
    @State private var editing: String?
    @State private var draft = ""
    let timer = Timer.publish(every: 3, on: .main, in: .common).autoconnect()

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                HStack(alignment: .firstTextBaseline) {
                    VStack(alignment: .leading, spacing: 2) {
                        Text("What I know about you").font(.title2.weight(.semibold))
                        Text("Things I picked up along the way. Edit or forget any of them.").font(.callout).foregroundStyle(.secondary)
                    }
                    Spacer()
                    Button { Bridge.shared.send("learn_now") } label: { Label("Learn now", systemImage: "arrow.triangle.2.circlepath") }
                        .keyboardShortcut("l", modifiers: .command)
                }
                if items.isEmpty {
                    VStack(spacing: 8) {
                        Image(systemName: "brain.head.profile").font(.system(size: 34, weight: .light)).foregroundStyle(.secondary)
                        Text("Nothing yet").font(.headline)
                        Text("I'll note things as we go.").font(.callout).foregroundStyle(.secondary)
                    }.frame(maxWidth: .infinity).padding(.vertical, 50)
                }
                ForEach(items) { it in
                    VStack(alignment: .leading, spacing: 8) {
                        HStack(spacing: 8) {
                            Text(it.type.capitalized).font(.caption.weight(.semibold)).padding(.horizontal, 8).padding(.vertical, 3)
                                .background(WTheme.accent.opacity(0.15), in: Capsule()).foregroundStyle(WTheme.accent)
                            Text(it.date).font(.caption).foregroundStyle(.secondary)
                            Spacer()
                            Button("Edit") { editing = it.id; draft = it.fact }.buttonStyle(.borderless)
                            Button("Forget") { forget(it) }.buttonStyle(.borderless).foregroundStyle(JTheme.danger)
                        }
                        if editing == it.id {
                            HStack {
                                TextField("Fact", text: $draft).textFieldStyle(.roundedBorder).onSubmit { commit(it) }
                                Button("Save") { commit(it) }.buttonStyle(.borderedProminent)
                            }
                        } else {
                            Text(it.fact).font(.body)
                        }
                    }.jCard(radius: 14, padding: 14)
                }
            }
            .padding(24).frame(maxWidth: 680).frame(maxWidth: .infinity)
        }
        .onAppear(perform: load)
        .onReceive(timer) { _ in if editing == nil { load() } }
    }

    private func load() {
        let b = Bridge.shared
        let arr = (b.readJSON(b.memoryPath) as? [[String: Any]]) ?? []
        items = arr.map { MemItem(id: "\($0["id"] ?? UUID().uuidString)", type: $0["type"] as? String ?? "fact", date: $0["date"] as? String ?? "", fact: $0["fact"] as? String ?? "") }
    }
    private func forget(_ it: MemItem) {
        Bridge.shared.send("memory_forget", ["id": it.id])
        items.removeAll { $0.id == it.id }
    }
    private func commit(_ it: MemItem) {
        if let i = items.firstIndex(where: { $0.id == it.id }) { items[i].fact = draft }
        let b = Bridge.shared
        var arr = (b.readJSON(b.memoryPath) as? [[String: Any]]) ?? []
        if let i = arr.firstIndex(where: { "\($0["id"] ?? "")" == it.id }) { arr[i]["fact"] = draft; b.writeJSON(arr, to: b.memoryPath) }
        editing = nil
    }
}
