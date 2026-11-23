import SwiftUI
import Combine

enum PillMode: String { case idle, listening, thinking, speaking, silent, asleep, error }

/// What the pill is showing right now. `doing` = thinking with at least one step running.
enum PillPhase { case asleep, idle, listening, thinking, doing, speaking, silent, error }
/// A short rim flash after something finished (`done`) or failed (`error`).
enum PillFlash { case done, error }

struct StepLine: Identifiable, Equatable { let id = UUID(); var text: String; var done: Bool }
struct NotedChip: Equatable { var text: String; var id: String }

/// All pill state, driven by Bridge events.
@MainActor
final class PillModel: ObservableObject {
    @Published var mode: PillMode = .asleep
    @Published var text = ""
    @Published var partial = ""
    @Published var steps: [StepLine] = []
    @Published var toast: String?
    @Published var chip: NotedChip?
    /// Words in the text that was selected when the hotkey went down (chip "Selection: 34 words" while listening).
    @Published var selectionWords: Int?
    @Published var nod: CGFloat = 0
    @Published var shrugX: CGFloat = 0
    @Published var lean: CGFloat = 0
    /// Light sweep across the pill: position (-0.4...1.4 of its width) and visibility.
    @Published var sweepX: CGFloat = -0.4
    @Published var sweepOn = false
    /// Mic muted (settings.json `mic_off`).
    @Published var micOff = false
    @Published var contentSize = CGSize(width: 44, height: 10)
    /// One-second rim flash: green after a finished task, red after an error.
    @Published var flash: PillFlash?
    private var flashTask: Task<Void, Never>?

    var phase: PillPhase {
        switch mode {
        case .asleep: return .asleep
        case .idle: return .idle
        case .listening: return .listening
        case .thinking: return steps.isEmpty ? .thinking : .doing
        case .speaking: return .speaking
        case .silent: return .silent
        case .error: return .error
        }
    }

    func flashNow(_ k: PillFlash, for seconds: Double = 1.1) {
        flashTask?.cancel()
        flash = k
        flashTask = Task { [weak self] in
            try? await Task.sleep(nanoseconds: UInt64(seconds * 1_000_000_000))
            if !Task.isCancelled { withAnimation(.easeOut(duration: 0.45)) { self?.flash = nil } }
        }
    }

    private var bag = Set<AnyCancellable>()
    private var replyActive = false
    private var collapseTask: Task<Void, Never>?
    private var toastTask: Task<Void, Never>?
    private var chipTask: Task<Void, Never>?
    private var brainAwake = false

    var interactive: Bool { mode == .idle || mode == .thinking || mode == .speaking || chip != nil }

    init() {
        micOff = (Bridge.shared.settings["mic_off"] as? Bool) == true
        Bridge.shared.$settings.receive(on: RunLoop.main).sink { [weak self] s in
            self?.micOff = (s["mic_off"] as? Bool) == true
        }.store(in: &bag)
        Bridge.shared.events.receive(on: RunLoop.main).sink { [weak self] e in
            MainActor.assumeIsolated { self?.handle(e) }
        }.store(in: &bag)
        if ProcessInfo.processInfo.environment["ALFRED_PILL_DEMO"] != nil { runDemo() }   // preview hook for screenshots
    }

    /// Plays every state in a loop (silent: no voice involved).
    private func runDemo() {
        Task { @MainActor in
            @MainActor func ev(_ o: [String: Any]) { handle(o) }
            try? await Task.sleep(nanoseconds: 3_000_000_000)
            while true {
                ev(["type": "state", "state": "listening"]);                         try? await Task.sleep(nanoseconds: 4_000_000_000)
                ev(["type": "state", "state": "thinking"]);                          try? await Task.sleep(nanoseconds: 4_000_000_000)
                ev(["type": "step", "text": "Opening Music", "done": false]);        try? await Task.sleep(nanoseconds: 4_000_000_000)
                ev(["type": "step", "text": "Opening Music", "done": true]);
                ev(["type": "reply", "text": "Done. Music is open.", "long": false]); try? await Task.sleep(nanoseconds: 0_600_000_000)
                try? await Task.sleep(nanoseconds: 4_000_000_000)
                ev(["type": "state", "state": "error", "text": "Couldn't reach Music"]); try? await Task.sleep(nanoseconds: 5_000_000_000)
            }
        }
    }

    /// Called by AppDelegate when the brain process appears/disappears.
    func setAwake(_ awake: Bool) {
        brainAwake = awake
        if !awake { reset(); mode = .asleep }
        else if mode == .asleep { mode = .idle }
    }

    private func reset() {
        collapseTask?.cancel(); replyActive = false
        text = ""; partial = ""; steps = []; selectionWords = nil
    }

    private func handle(_ e: [String: Any]) {
        guard let type = e["type"] as? String else { return }
        switch type {
        case "state":
            let s = PillMode(rawValue: (e["state"] as? String) ?? "") ?? .idle
            let t = (e["text"] as? String) ?? ""
            if s == .error {
                collapseTask?.cancel(); selectionWords = nil
                steps = []; partial = ""
                text = t.isEmpty ? "Something went wrong" : t
                mode = .error; replyActive = true
                flashNow(.error, for: 1.4)
                collapse(after: 4)
                return
            }
            if s == .idle {
                if replyActive { return }
                reset(); mode = .idle
            } else {
                if s != .silent && s != .speaking { collapseTask?.cancel(); replyActive = false }
                if s == .listening { partial = ""; steps = []; text = "" } else { selectionWords = nil }
                if s == .thinking && mode != .thinking { steps = [] }
                mode = s
                if !t.isEmpty { text = t }
            }
        case "partial":
            if mode == .thinking { return }   // late live words after the key went up: stay on "thinking"
            collapseTask?.cancel(); replyActive = false
            partial = PillModel.tail((e["text"] as? String) ?? "", words: 8)
            mode = .listening
        case "selection":
            let n = (e["words"] as? Int) ?? 0
            selectionWords = n > 0 ? n : nil
        case "selection_clear":
            selectionWords = nil
        case "step":
            let t = (e["text"] as? String) ?? ""
            let done = (e["done"] as? Bool) ?? false
            if let i = steps.lastIndex(where: { $0.text == t }) { steps[i].done = done }
            else { steps.append(StepLine(text: t, done: done)) }
            if mode == .idle || mode == .listening { mode = .thinking }
        case "reply":
            let wasThinking = mode == .thinking
            let t = (e["text"] as? String) ?? ""
            if (e["long"] as? Bool) == true {
                PopOut.shared.show(t)
                text = "Opened below"
            } else { text = t }
            mode = (Bridge.shared.settings["silent"] as? Bool) == true ? .silent : .speaking
            replyActive = true
            let words = Double(t.split(separator: " ").count)
            collapse(after: max(3, words / 3.5))
            if wasThinking { lightSweep(); flashNow(.done) }   // task finished: one soft light pass over the pill and the Home mark
        case "toast":
            toast = (e["text"] as? String)
            toastTask?.cancel()
            toastTask = Task { [weak self] in
                try? await Task.sleep(nanoseconds: 2_800_000_000)
                if !Task.isCancelled { withAnimation(JTheme.spring) { self?.toast = nil } }
            }
        case "noted":
            chip = NotedChip(text: (e["text"] as? String) ?? "", id: "\(e["id"] ?? "")")
            chipTask?.cancel()
            chipTask = Task { [weak self] in
                try? await Task.sleep(nanoseconds: 7_000_000_000)
                if !Task.isCancelled { withAnimation(JTheme.spring) { self?.chip = nil } }
            }
        case "mood":
            if let m = e["move"] as? String { move(m) }
        default: break
        }
    }

    /// Last `words` words, so the live line stays short and only its end moves.
    static func tail(_ s: String, words n: Int) -> String {
        let w = s.split(whereSeparator: { $0.isWhitespace })
        return w.count <= n ? w.joined(separator: " ") : "…" + w.suffix(n).joined(separator: " ")
    }

    private func collapse(after s: Double) {
        collapseTask?.cancel()
        collapseTask = Task { [weak self] in
            try? await Task.sleep(nanoseconds: UInt64(s * 1_000_000_000))
            guard !Task.isCancelled, let self else { return }
            self.replyActive = false
            self.text = ""; self.steps = []
            self.mode = self.brainAwake ? .idle : .asleep
        }
    }

    func forgetChip() {
        if let c = chip { Bridge.shared.send("memory_forget", ["id": c.id]) }
        chipTask?.cancel()
        withAnimation(JTheme.spring) { chip = nil }
    }

    func stop() { Bridge.shared.send("stop") }

    func toggleMic() { Bridge.shared.set("mic_off", !micOff) }

    /// One soft light pass (600 ms). Reduce Motion: nothing.
    func lightSweep(duration: Double = 0.6) {
        guard !NSWorkspace.shared.accessibilityDisplayShouldReduceMotion else { return }
        AppState.shared.sweepTick &+= 1
        Task { @MainActor in
            sweepX = -0.4; sweepOn = true
            try? await Task.sleep(nanoseconds: 30_000_000)
            withAnimation(.easeInOut(duration: duration)) { sweepX = 1.4 }
            try? await Task.sleep(nanoseconds: UInt64((duration + 0.08) * 1_000_000_000))
            sweepOn = false; sweepX = -0.4
        }
    }

    // micro-moves
    func move(_ m: String) {
        Task { @MainActor in
            switch m {
            case "nod":
                withAnimation(.easeOut(duration: 0.12)) { nod = 3 }
                try? await Task.sleep(nanoseconds: 140_000_000)
                withAnimation(JTheme.spring) { nod = 0 }
            case "glint":
                lightSweep(duration: 0.8)
            case "shrug":
                for _ in 0..<2 {
                    withAnimation(.easeInOut(duration: 0.09)) { shrugX = -4 }
                    try? await Task.sleep(nanoseconds: 100_000_000)
                    withAnimation(.easeInOut(duration: 0.09)) { shrugX = 4 }
                    try? await Task.sleep(nanoseconds: 100_000_000)
                }
                withAnimation(JTheme.spring) { shrugX = 0 }
            case "lean":
                lean = 0 // continuous lean is driven by the panel's cursor poll
            default: break
            }
        }
    }
}
