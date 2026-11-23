import SwiftUI
import Combine
import AppKit

struct ChatMsg: Identifiable {
    let id = UUID()
    let fromUser: Bool
    let text: String
}

/// Keeps the session's conversation. Created at launch (via WindowsHub.shared) so no events are missed.
@MainActor
final class ConsoleModel: ObservableObject {
    static let shared = ConsoleModel()
    @Published var messages: [ChatMsg] = []
    @Published var status = "Ready"
    @Published var busy = false
    @Published var live = ""            // partial words while listening
    private var lastPartial = ""
    private var bag = Set<AnyCancellable>()

    private init() {
        loadLog()
        Bridge.shared.events.receive(on: DispatchQueue.main).sink { [weak self] e in
            MainActor.assumeIsolated { self?.handle(e) }
        }.store(in: &bag)
    }

    private func handle(_ e: [String: Any]) {
        switch e["type"] as? String {
        case "state":
            let s = e["state"] as? String ?? ""
            switch s {
            case "listening": status = "Listening…"; busy = false; lastPartial = ""
            case "thinking":
                status = "Thinking…"; busy = true
                if !lastPartial.isEmpty { messages.append(ChatMsg(fromUser: true, text: lastPartial)); lastPartial = ""; live = "" }
            case "speaking": status = "Speaking…"; busy = true
            case "silent": status = "Silent"; busy = false
            case "asleep": status = "Asleep"; busy = false
            default: status = e["text"] as? String ?? "Ready"; busy = false; live = ""
            }
        case "partial": lastPartial = e["text"] as? String ?? ""; live = lastPartial
        case "step": status = e["text"] as? String ?? status; busy = true
        case "reply":
            if let t = e["text"] as? String, !t.isEmpty { messages.append(ChatMsg(fromUser: false, text: t)) }
            status = "Ready"; busy = false; live = ""
        default: break
        }
    }

    func send(_ text: String) {
        let t = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !t.isEmpty else { return }
        messages.append(ChatMsg(fromUser: true, text: t))
        status = "Thinking…"; busy = true
        Bridge.shared.ask(t)
    }
    /// Hides internal lines the brain adds to requests (screen path, system hints).
    static func clean(_ s: String) -> String {
        var t = s
        if let r = t.range(of: "\nScreen (only when asked") { t = String(t[..<r.lowerBound]) }
        return t.trimmingCharacters(in: .whitespacesAndNewlines)
    }
    func stop() { Bridge.shared.send("stop"); busy = false; status = "Stopped" }

    /// Last 30 request/reply/quick lines of log.jsonl (read-only, tail only).
    private func loadLog() {
        guard let h = FileHandle(forReadingAtPath: Bridge.root + "/data/log.jsonl") else { return }
        defer { try? h.close() }
        let size = (try? h.seekToEnd()) ?? 0
        try? h.seek(toOffset: size > 400_000 ? size - 400_000 : 0)
        let data = h.readDataToEndOfFile()
        let lines = String(decoding: data, as: UTF8.self).split(separator: "\n")
        var out: [ChatMsg] = []
        for l in lines {
            guard let o = try? JSONSerialization.jsonObject(with: Data(l.utf8)) as? [String: Any],
                  let ty = o["type"] as? String, ["request", "reply", "quick"].contains(ty) else { continue }
            let text = o["text"] as? String ?? ""
            switch ty {
            case "request": out.append(ChatMsg(fromUser: true, text: text))
            case "reply": out.append(ChatMsg(fromUser: false, text: text))
            default:
                out.append(ChatMsg(fromUser: true, text: text))
                if let r = o["reply"] as? String { out.append(ChatMsg(fromUser: false, text: r)) }
            }
        }
        messages = Array(out.suffix(30))
    }
}

struct ConsoleView: View {
    @ObservedObject private var m = ConsoleModel.shared
    @State private var input = ""
    @FocusState private var focused: Bool

    var body: some View {
        ZStack {
            WVisualEffect(material: .hudWindow).ignoresSafeArea()
            VStack(spacing: 0) {
                ScrollViewReader { proxy in
                    ScrollView {
                        LazyVStack(spacing: 10) {
                            ForEach(m.messages) { msg in Bubble(msg: msg).id(msg.id) }
                            if !m.live.isEmpty { Bubble(msg: ChatMsg(fromUser: true, text: m.live)).opacity(0.6) }
                        }.padding(14)
                    }
                    .onChange(of: m.messages.count) { _, _ in
                        if let last = m.messages.last { withAnimation { proxy.scrollTo(last.id, anchor: .bottom) } }
                    }
                    .onAppear { if let last = m.messages.last { proxy.scrollTo(last.id, anchor: .bottom) } }
                }
                Divider().opacity(0.4)
                HStack(spacing: 6) {
                    if m.busy { ProgressView().controlSize(.small) } else { Circle().fill(WTheme.done).frame(width: 7, height: 7) }
                    Text(m.status).font(.caption).foregroundStyle(.secondary).lineLimit(1)
                    Spacer()
                    if m.busy {
                        Button { m.stop() } label: { Label("Stop", systemImage: "stop.circle.fill").font(.caption) }.buttonStyle(.borderless)
                    }
                }.padding(.horizontal, 14).padding(.vertical, 6)
                HStack(spacing: 8) {
                    TextField("Ask Alfred…", text: $input)
                        .textFieldStyle(.plain).focused($focused)
                        .onSubmit { m.send(input); input = "" }
                        .padding(.horizontal, 12).padding(.vertical, 8)
                        .background(.background.opacity(0.5), in: RoundedRectangle(cornerRadius: 10))
                        .overlay(RoundedRectangle(cornerRadius: 10).stroke(.white.opacity(0.12)))
                    Button { m.send(input); input = "" } label: { Image(systemName: "arrow.up.circle.fill").font(.title2).foregroundStyle(WTheme.accent) }
                        .buttonStyle(.plain).disabled(input.trimmingCharacters(in: .whitespaces).isEmpty)
                }.padding([.horizontal, .bottom], 12)
            }
        }
        .onAppear { focused = true }
    }
}

struct Bubble: View {
    let msg: ChatMsg
    var body: some View {
        HStack {
            if msg.fromUser { Spacer(minLength: 50) }
            MarkdownView(text: ConsoleModel.clean(msg.text), color: msg.fromUser ? .white : .primary)
                .padding(.horizontal, 12).padding(.vertical, 8)
                .background(msg.fromUser ? AnyShapeStyle(WTheme.accent) : AnyShapeStyle(.regularMaterial), in: RoundedRectangle(cornerRadius: 14))
                .textSelection(.enabled)
            if !msg.fromUser { Spacer(minLength: 50) }
        }
    }
}

/// Minimal Markdown: inline styles + paragraphs + bullet lists + pipe tables.
struct MarkdownView: View {
    let text: String
    var color: Color = .primary
    private enum Block { case para(String), table([[String]]) }

    private var blocks: [Block] {
        var out: [Block] = [], para: [String] = [], rows: [[String]] = []
        func flushP() { if !para.isEmpty { out.append(.para(para.joined(separator: "\n"))); para = [] } }
        func flushT() { if !rows.isEmpty { out.append(.table(rows)); rows = [] } }
        for line in text.components(separatedBy: "\n") {
            let t = line.trimmingCharacters(in: .whitespaces)
            if t.hasPrefix("|") {
                flushP()
                let cells = t.split(separator: "|", omittingEmptySubsequences: false).dropFirst().dropLast().map { $0.trimmingCharacters(in: .whitespaces) }
                if cells.allSatisfy({ $0.allSatisfy { "-: ".contains($0) } && !$0.isEmpty }) { continue }
                rows.append(Array(cells))
            } else { flushT(); para.append(t.hasPrefix("- ") || t.hasPrefix("* ") ? "• " + t.dropFirst(2) : line) }
        }
        flushP(); flushT()
        return out
    }
    private func inline(_ s: String) -> Text {
        let a = try? AttributedString(markdown: s, options: .init(interpretedSyntax: .inlineOnlyPreservingWhitespace))
        return Text(a ?? AttributedString(s))
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            ForEach(Array(blocks.enumerated()), id: \.offset) { _, b in
                switch b {
                case .para(let s): inline(s).foregroundStyle(color).frame(maxWidth: .infinity, alignment: .leading)
                case .table(let rows):
                    Grid(alignment: .leading, horizontalSpacing: 12, verticalSpacing: 4) {
                        ForEach(Array(rows.enumerated()), id: \.offset) { i, r in
                            GridRow { ForEach(Array(r.enumerated()), id: \.offset) { _, c in
                                inline(c).font(.callout.weight(i == 0 ? .semibold : .regular)).foregroundStyle(color)
                            } }
                            if i == 0 { Divider() }
                        }
                    }
                }
            }
        }
    }
}
