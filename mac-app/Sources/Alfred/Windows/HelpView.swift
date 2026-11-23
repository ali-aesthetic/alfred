import SwiftUI
import AppKit

/// Built-in instructions. Plain words, short sections, open one at a time.
struct HelpPane: View {
    @State private var open: String? = "start"
    @State private var guide: PermissionGuide.Kind = .accessibility

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 12) {
                VStack(alignment: .leading, spacing: 2) {
                    Text("Help").font(.title2.weight(.semibold))
                    Text("Everything you need, in short steps.").font(.callout).foregroundStyle(.secondary)
                }
                section("start", "Getting started", "play.circle") {
                    step(1, "Say \"Alfred\" and ask for something. Or hold right ⌥ (Option), talk, and let go.")
                    step(2, "He answers out loud and, if you ask, does it: opens apps, searches, writes, clicks.")
                    step(3, "Say \"that's all\" or \"thanks\" when you are done.")
                    Text("Try: \"Alfred, open Notes.\"  ·  \"What's on my calendar today?\"  ·  \"Set a timer for ten minutes.\"").font(.callout).foregroundStyle(.secondary)
                }
                section("address", "How Alfred addresses you", "person.crop.circle") {
                    Text("Settings → You has: Sir · Ma'am · My name · Nothing. Or say it:").font(.callout)
                    bullets(["\"Don't call me sir\"", "\"Call me ma'am\"", "\"Just use my name\"", "\"Stop addressing me\""])
                    Text("Alfred confirms once with \"Very good.\" The voice follows the choice (Sir → Lewis, Ma'am → Isabella) until you pick a voice yourself in Settings → Voice.").font(.callout).foregroundStyle(.secondary)
                }
                section("perms", "Permissions (with pictures)", "lock.shield") {
                    Picker("", selection: $guide) {
                        Text("Microphone").tag(PermissionGuide.Kind.microphone); Text("Accessibility").tag(PermissionGuide.Kind.accessibility)
                        Text("Screen").tag(PermissionGuide.Kind.screen); Text("Keys").tag(PermissionGuide.Kind.input)
                    }.pickerStyle(.segmented).labelsHidden()
                    PermissionGuide(kind: guide)
                    HStack {
                        Button("Open Privacy & Security") { NSWorkspace.shared.open(URL(string: "x-apple.systempreferences:com.apple.preference.security")!) }
                        Button("Show setup guide again") { WindowsHub.shared.showOnboarding() }
                    }.controlSize(.small)
                }
                section("brain", "Brains: which AI thinks for Alfred", "brain") {
                    ForEach(BrainCatalog.all) { b in
                        VStack(alignment: .leading, spacing: 2) {
                            HStack { Text(b.label).font(.callout.weight(.semibold)); Text(b.badge).font(.caption2.weight(.bold)).padding(.horizontal, 5).padding(.vertical, 1)
                                .background(Capsule().fill(b.ready ? WTheme.done.opacity(0.25) : WTheme.warn.opacity(0.25))) }
                            Text(b.note).font(.callout).foregroundStyle(.secondary)
                        }
                    }
                    Text("Computer control (clicking, typing, opening things) is strongest on Claude. Small local models are much weaker at it. Experimental brains are not verified end to end.").font(.callout)
                }
                section("wake", "Wake word", "waveform") {
                    Text("Until the \"Hey Alfred\" model is trained, Alfred listens for his name through speech recognition. Hold right ⌥ and talk, or type in the Console, any time.").font(.callout)
                    Text("To train your own free wake-word model, follow docs/TRAIN-HEY-ALFRED.md in the Alfred folder.").font(.callout).foregroundStyle(.secondary)
                }
                section("tg", "Telegram", "paperplane") {
                    Text("Ask Alfred: \"Help me connect Telegram.\" He walks you through making a bot with @BotFather. Your token stays on this Mac.").font(.callout)
                }
                section("trouble", "Troubleshooting", "wrench.and.screwdriver") {
                    bullets(["Alfred does not hear me: System Settings → Privacy & Security → Microphone → Alfred on.",
                             "He cannot click or type: Accessibility → Alfred on, then press Restart my brain in Settings.",
                             "\"Not ready\" or login errors: Settings → Claude → Sign in again.",
                             "Download stuck: Help → Show setup guide again → Retry.",
                             "macOS says the app is from an unidentified developer: System Settings → Privacy & Security → Open Anyway."])
                    HStack {
                        Button("Open Alfred's folder") { NSWorkspace.shared.open(URL(fileURLWithPath: Paths.home)) }
                        Button("Open the log") { NSWorkspace.shared.open(URL(fileURLWithPath: Paths.data + "/app-brain.log")) }
                    }.controlSize(.small)
                }
                section("privacy", "Privacy", "hand.raised") {
                    Text("Speech is turned into text on this Mac. The words you say are sent to the brain you chose (for Claude: to Anthropic through your own account). Memory and logs stay in Alfred's folder. Alfred never deletes files: he moves them to a \"to delete\" folder.").font(.callout)
                }
            }.padding(24).frame(maxWidth: 720, alignment: .leading)
        }
    }

    private func section<C: View>(_ id: String, _ title: String, _ icon: String, @ViewBuilder _ c: () -> C) -> some View {
        VStack(alignment: .leading, spacing: 0) {
            Button { open = (open == id) ? nil : id } label: {
                HStack { Image(systemName: icon).frame(width: 22); Text(title).font(.headline); Spacer(); Image(systemName: open == id ? "chevron.up" : "chevron.down").foregroundStyle(.secondary) }
                    .contentShape(Rectangle())
            }.buttonStyle(.plain).padding(12)
            if open == id { VStack(alignment: .leading, spacing: 8) { c() }.padding([.horizontal, .bottom], 14) }
        }
        .background(RoundedRectangle(cornerRadius: 12, style: .continuous).fill(Color.primary.opacity(0.05)))
        .accessibilityElement(children: .contain)
    }
    private func step(_ n: Int, _ t: String) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: 10) {
            Text("\(n)").font(.system(size: 12, weight: .bold, design: .rounded)).frame(width: 22, height: 22).background(Circle().fill(WTheme.accent.opacity(0.18)))
            Text(t).fixedSize(horizontal: false, vertical: true)
        }
    }
    private func bullets(_ items: [String]) -> some View {
        VStack(alignment: .leading, spacing: 4) { ForEach(items, id: \.self) { item in HStack(alignment: .firstTextBaseline) { Text("•"); Text(item).fixedSize(horizontal: false, vertical: true) }.font(.callout) } }
    }
}

/// The brains Alfred can use (mirrors brains/__init__.py). Honest labels: nothing untested is called "ready".
struct BrainCatalog: Identifiable {
    let id: String, label: String, note: String, ready: Bool
    var badge: String { ready ? "READY" : "EXPERIMENTAL" }
    static let all: [BrainCatalog] = [
        .init(id: "claude-subscription", label: "Claude (your subscription)", note: "Best at controlling your Mac. Uses your own Claude plan through the Claude Code tool.", ready: true),
        .init(id: "claude-api", label: "Claude (API key)", note: "Same strength, billed per use on your Anthropic API key. Key goes in the Keychain item \"alfred-anthropic\".", ready: true),
        .init(id: "openai-codex", label: "ChatGPT account (Codex CLI)", note: "Stub, not tested end to end. Chat only; no computer control yet.", ready: false),
        .init(id: "openai-compatible", label: "OpenAI-compatible API", note: "Chat only for now (tested against a mock server, not a real provider). Computer control is not connected.", ready: false),
        .init(id: "ollama", label: "Local model (Ollama)", note: "Private and free, runs on your Mac. Chat only for now; local models are weak at computer control.", ready: false),
    ]
}
