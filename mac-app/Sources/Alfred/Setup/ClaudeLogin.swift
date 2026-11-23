import Foundation
import AppKit

/// Claude sign-in happens in Anthropic's own browser page, started by the `claude` tool. Alfred never sees your login.
enum ClaudeLogin {
    /// True when Claude Code has an account on this Mac (checks only that an account exists).
    static func signedIn() -> Bool {
        let p = NSHomeDirectory() + "/.claude.json"
        guard let d = FileManager.default.contents(atPath: p),
              let j = try? JSONSerialization.jsonObject(with: d) as? [String: Any] else { return false }
        return j["oauthAccount"] != nil || j["userID"] != nil
    }
    static var claudeInstalled: Bool {
        ["/.local/bin/claude", "/opt/homebrew/bin/claude", "/usr/local/bin/claude"].contains { FileManager.default.isExecutableFile(atPath: ($0.hasPrefix("/.") ? NSHomeDirectory() : "") + $0) }
    }
    /// Opens Terminal with a tiny script: installs Claude Code if missing and starts the sign-in.
    static func openTerminal() {
        let path = Paths.home + "/sign-in-to-claude.command"
        let script = "#!/bin/bash\nexport ALFRED_HOME=\(shq(Paths.home))\nif [ -f \"$ALFRED_HOME/ensure_claude.sh\" ]; then bash \"$ALFRED_HOME/ensure_claude.sh\"; else (command -v claude >/dev/null || curl -fsSL https://claude.ai/install.sh | bash); export PATH=\"$HOME/.local/bin:$PATH\"; claude; fi\necho; read -n 1 -s -r -p \"Done. Press any key to close this window.\"\n"
        try? FileManager.default.createDirectory(atPath: Paths.home, withIntermediateDirectories: true)
        try? script.write(toFile: path, atomically: true, encoding: .utf8)
        chmod(path, 0o755)
        NSWorkspace.shared.open(URL(fileURLWithPath: path))
    }
    private static func shq(_ s: String) -> String { "'" + s.replacingOccurrences(of: "'", with: "'\\''") + "'" }
}
