import SwiftUI
import AppKit

// MARK: - Model

struct RStep: Identifiable {
    var id = UUID()
    var kind = "open_app"
    var f: [String: String] = [:]
    var on = true                          // dnd / silent: turn on or off
    var extra: [String: Any] = [:]         // unknown keys, kept so we never lose data

    /// kind, plain-language name, icon
    static let kinds: [(String, String, String)] = [
        ("open_app", "Open an app", "app.badge"), ("open_url", "Open a website", "link"),
        ("window", "Place a window", "rectangle.split.2x1"), ("music", "Play music", "music.note"),
        ("dnd", "Do Not Disturb", "moon.fill"), ("silent", "Alfred voice", "speaker.slash"),
        ("say", "Say something", "quote.bubble")]
    static func name(_ k: String) -> String { kinds.first { $0.0 == k }?.1 ?? k.replacingOccurrences(of: "_", with: " ").capitalized }
    static func icon(_ k: String) -> String { kinds.first { $0.0 == k }?.2 ?? "bolt" }

    /// key, label, placeholder
    static func fields(_ k: String) -> [(String, String, String)] {
        switch k {
        case "open_app": return [("app", "App", "Final Cut Pro")]
        case "open_url": return [("url", "Website", "https://…")]
        case "window": return [("app", "App", "Safari"), ("where", "Where", "left, right, right third…")]
        case "music": return [("query", "Play", "Lo-fi, a playlist… (optional)"), ("volume", "Volume %", "30")]
        case "dnd": return [("minutes", "For how long (minutes)", "120")]
        case "silent": return []
        default: return [("text", "Words", "Edit mode on.")]
        }
    }
    static let hasSwitch: Set<String> = ["dnd", "silent"]

    init(kind: String = "open_app", f: [String: String] = [:], on: Bool = true) { self.kind = kind; self.f = f; self.on = on }
    init(json: [String: Any]) {
        kind = json["do"] as? String ?? "open_app"
        let known = Set(Self.fields(kind).map { $0.0 })
        for (k, v) in json where k != "do" {
            if k == "on" { on = (v as? NSNumber)?.boolValue ?? true }
            else if known.contains(k) {
                if let n = v as? NSNumber, CFGetTypeID(n) != CFBooleanGetTypeID() { f[k] = n.doubleValue == n.doubleValue.rounded() ? "\(n.intValue)" : "\(n.doubleValue)" }
                else { f[k] = "\(v)" }
            } else { extra[k] = v }
        }
    }
    var json: [String: Any] {
        var o: [String: Any] = extra
        o["do"] = kind
        for (k, _, _) in Self.fields(kind) {
            guard let v = f[k]?.trimmingCharacters(in: .whitespaces), !v.isEmpty else { continue }
            if ["volume", "minutes"].contains(k), let d = Double(v) { o[k] = d == d.rounded() ? Int(d) as Any : d as Any } else { o[k] = v }
        }
        if Self.hasSwitch.contains(kind) { o["on"] = on }
        return o
    }

    /// One short plain phrase, e.g. “Do Not Disturb 2 h”.
    var summary: String {
        func v(_ k: String) -> String { f[k]?.trimmingCharacters(in: .whitespaces) ?? "" }
        switch kind {
        case "open_app": return v("app").isEmpty ? "Opens an app" : "Opens \(v("app"))"
        case "open_url":
            let u = v("url").replacingOccurrences(of: "https://", with: "").replacingOccurrences(of: "http://", with: "").replacingOccurrences(of: "www.", with: "")
            return u.isEmpty ? "Opens a website" : "Opens \(u.split(separator: "/").first.map(String.init) ?? u)"
        case "window": return v("app").isEmpty ? "Places a window" : "\(v("app")) → \(v("where").isEmpty ? "placed" : v("where"))"
        case "music":
            let vol = v("volume"), q = v("query")
            if vol == "0" { return "Mutes music" }
            if q.isEmpty { return vol.isEmpty ? "Plays music" : "Music at \(vol)%" }
            return vol.isEmpty ? "\(q) music" : "\(q) at \(vol)%"
        case "dnd":
            if !on { return "Turns off Do Not Disturb" }
            if let m = Int(v("minutes")), m > 0 { return "Do Not Disturb \(Self.duration(m))" }
            return "Do Not Disturb"
        case "silent": return on ? "Voice off, text only" : "Voice back on"
        case "say": return v("text").isEmpty ? "Says something" : "Says “\(v("text"))”"
        default: return Self.name(kind)
        }
    }
    static func duration(_ m: Int) -> String {
        if m < 60 { return "\(m) min" }
        let h = m / 60, r = m % 60
        return r == 0 ? "\(h) h" : "\(h) h \(r) m"
    }
}

struct Routine: Identifiable {
    var id: String
    var name: String
    var hotkey: String
    var steps: [RStep]
    var json: [String: Any] { ["id": id, "name": name, "hotkey": hotkey, "steps": steps.map { $0.json }] }

    /// The name people see: raw ids like "edit" become “Edit mode”.
    var title: String {
        get {
            let n = name.trimmingCharacters(in: .whitespaces)
            if !n.isEmpty && n != id { return n }
            switch id {
            case "edit": return "Edit mode"
            case "class": return "Class mode"
            case "wind_down": return "Wind down"
            default:
                let s = id.replacingOccurrences(of: "_", with: " ")
                return n.isEmpty && s.isEmpty ? "New routine" : (n.isEmpty ? s : n).prefix(1).uppercased() + (n.isEmpty ? s : n).dropFirst()
            }
        }
        set { name = newValue }
    }
    var icon: String {
        switch id {
        case "edit": return "film"
        case "class": return "graduationcap"
        case "wind_down": return "moon"
        default:
            switch steps.first?.kind {
            case "music": return "music.note"
            case "open_app": return "macwindow"
            case "open_url": return "safari"
            case "dnd": return "moon"
            case "say": return "bubble.left"
            default: return "bolt"
            }
        }
    }
    var tint: Color {
        switch id {
        case "edit": return .purple
        case "class": return .orange
        case "wind_down": return .indigo
        default: return [Color.teal, .pink, .green, .blue, .red][abs(id.hashValue) % 5]
        }
    }
    var summary: String {
        steps.isEmpty ? "No steps yet. Tap Edit to add some." : steps.filter { $0.kind != "say" || steps.count == 1 }.map(\.summary).joined(separator: " · ")
    }
}

@MainActor
final class RoutinesModel: ObservableObject {
    @Published var items: [Routine] = []
    init() { load() }
    func load() {
        let b = Bridge.shared
        if let arr = b.readJSON(b.routinesPath) as? [[String: Any]] {
            items = arr.map { Routine(id: $0["id"] as? String ?? UUID().uuidString, name: $0["name"] as? String ?? "",
                                      hotkey: $0["hotkey"] as? String ?? "", steps: (($0["steps"] as? [[String: Any]]) ?? []).map(RStep.init(json:))) }
        } else {
            items = Self.defaults; save()
        }
    }
    func save() {
        let b = Bridge.shared
        try? FileManager.default.createDirectory(atPath: Bridge.uiDir, withIntermediateDirectories: true)
        b.writeJSON(items.map { $0.json }, to: b.routinesPath)
    }
    static let defaults: [Routine] = [
        Routine(id: "edit", name: "Edit mode", hotkey: "⌥E", steps: [
            RStep(kind: "open_app", f: ["app": "Final Cut Pro"]),
            RStep(kind: "music", f: ["query": "Lo-fi", "volume": "30"]),
            RStep(kind: "dnd", f: ["minutes": "120"])]),
        Routine(id: "class", name: "Class mode", hotkey: "", steps: [
            RStep(kind: "dnd", f: ["minutes": "240"]),
            RStep(kind: "say", f: ["text": "Class mode on."])]),
        Routine(id: "wind_down", name: "Wind down", hotkey: "", steps: [
            RStep(kind: "music", f: ["query": "Calm evening", "volume": "20"]),
            RStep(kind: "say", f: ["text": "Time to wind down."])])
    ]
}

// MARK: - Pane

struct RoutinesPane: View {
    @StateObject private var m = RoutinesModel()
    @State private var editingID: String?
    @State private var ran: String?

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                VStack(alignment: .leading, spacing: 2) {
                    Text("Routines").font(.title2.weight(.semibold))
                    Text("One tap sets up your Mac for what you're doing.").font(.callout).foregroundStyle(.secondary)
                }.padding(.bottom, 2)

                ForEach(m.items) { r in card(r) }

                Button(action: addRoutine) {
                    Label("New routine", systemImage: "plus")
                        .frame(maxWidth: .infinity).padding(.vertical, 14)
                }
                .buttonStyle(.plain).foregroundStyle(.secondary)
                .background(RoundedRectangle(cornerRadius: 16, style: .continuous).strokeBorder(Color.primary.opacity(0.18), style: StrokeStyle(lineWidth: 1, dash: [5, 4])))
            }
            .padding(24).frame(maxWidth: 680).frame(maxWidth: .infinity)
        }
        .onChange(of: m.items.map { $0.json as NSDictionary }) { _, _ in m.save() }
        .sheet(item: Binding(get: { editingID.map { IDBox(id: $0) } }, set: { editingID = $0?.id })) { box in
            if let i = m.items.firstIndex(where: { $0.id == box.id }) {
                RoutineEditor(routine: $m.items[i]) { editingID = nil }
            }
        }
    }

    private struct IDBox: Identifiable { let id: String }

    private func addRoutine() {
        let r = Routine(id: "r\(Int(Date().timeIntervalSince1970))", name: "New routine", hotkey: "", steps: [RStep()])
        m.items.append(r); editingID = r.id
    }

    private func card(_ r: Routine) -> some View {
        HStack(spacing: 14) {
            Image(systemName: r.icon)
                .font(.system(size: 20, weight: .medium)).foregroundStyle(.white)
                .frame(width: 46, height: 46)
                .background(r.tint.gradient, in: RoundedRectangle(cornerRadius: 12, style: .continuous))
            VStack(alignment: .leading, spacing: 4) {
                HStack(spacing: 10) {
                    Text(r.title).font(.headline)
                    if !r.hotkey.isEmpty { Keycaps(combo: r.hotkey) }
                }
                Text(r.summary).font(.callout).foregroundStyle(.secondary).lineLimit(2)
                    .fixedSize(horizontal: false, vertical: true)
            }
            Spacer(minLength: 8)
            Button("Edit") { editingID = r.id }.buttonStyle(.borderless).foregroundStyle(.secondary)
            Button {
                Bridge.shared.send("routine", ["name": r.id])
                ran = r.id
                DispatchQueue.main.asyncAfter(deadline: .now() + 1.6) { if ran == r.id { ran = nil } }
            } label: {
                Label(ran == r.id ? "Started" : "Run", systemImage: ran == r.id ? "checkmark" : "play.fill")
                    .frame(minWidth: 66)
            }
            .buttonStyle(.borderedProminent).controlSize(.large).tint(ran == r.id ? WTheme.done : WTheme.accent)
            .help("Run \(r.title) now")
        }
        .jCard()
        .contextMenu { Button("Edit…") { editingID = r.id } }
    }
}

// MARK: - Editor sheet

struct RoutineEditor: View {
    @Binding var routine: Routine
    var onDone: () -> Void

    var body: some View {
        VStack(spacing: 0) {
            Form {
                Section {
                    TextField("Name", text: Binding(get: { routine.title }, set: { routine.title = $0 }))
                    LabeledContent("Shortcut") {
                        TextField("", text: $routine.hotkey, prompt: Text("e.g. ⌥E")).multilineTextAlignment(.trailing).frame(width: 120)
                    }
                } footer: { Text("Press the shortcut anywhere to run this routine.") }

                Section {
                    ForEach($routine.steps) { $s in StepRow(step: $s) { routine.steps.removeAll { $0.id == s.id } } }
                    Menu {
                        ForEach(RStep.kinds, id: \.0) { k in
                            Button { routine.steps.append(RStep(kind: k.0)) } label: { Label(k.1, systemImage: k.2) }
                        }
                    } label: { Label("Add a step", systemImage: "plus") }
                    .menuStyle(.borderlessButton).fixedSize()
                } header: { Text("What happens, in order") }
            }
            .formStyle(.grouped)
            Divider()
            HStack {
                Button("Run now") { Bridge.shared.send("routine", ["name": routine.id]) }
                Spacer()
                Button("Done", action: onDone).keyboardShortcut(.defaultAction).buttonStyle(.borderedProminent)
            }.padding(14)
        }
        .frame(width: 480, height: 580)
    }
}

private struct StepRow: View {
    @Binding var step: RStep
    var remove: () -> Void
    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            Image(systemName: RStep.icon(step.kind)).font(.system(size: 13, weight: .medium)).foregroundStyle(.secondary)
                .frame(width: 28, height: 28).background(Color.primary.opacity(0.07), in: RoundedRectangle(cornerRadius: 8, style: .continuous))
            VStack(alignment: .leading, spacing: 8) {
                Picker("", selection: Binding(get: { step.kind }, set: { k in step.kind = k; step.f = [:]; step.extra = [:]; step.on = true })) {
                    ForEach(RStep.kinds, id: \.0) { Text($0.1).tag($0.0) }
                }.labelsHidden().fixedSize()
                if RStep.hasSwitch.contains(step.kind) {
                    Picker("", selection: $step.on) {
                        Text(step.kind == "dnd" ? "Turn on" : "Voice off").tag(true)
                        Text(step.kind == "dnd" ? "Turn off" : "Voice on").tag(false)
                    }.pickerStyle(.segmented).labelsHidden().frame(maxWidth: 220)
                }
                if !(step.kind == "dnd" && !step.on) {
                    ForEach(RStep.fields(step.kind), id: \.0) { key, label, ph in
                        HStack(spacing: 8) {
                            Text(label).font(.callout).foregroundStyle(.secondary).frame(width: 130, alignment: .leading)
                            TextField("", text: Binding(get: { step.f[key] ?? "" }, set: { step.f[key] = $0 }), prompt: Text(ph))
                                .textFieldStyle(.roundedBorder)
                        }
                    }
                }
            }
            Spacer(minLength: 0)
            Button(action: remove) { Image(systemName: "trash") }
                .buttonStyle(.borderless).foregroundStyle(.secondary).help("Remove this step")
                .accessibilityLabel("Remove step")
        }
        .padding(.vertical, 4)
    }
}
