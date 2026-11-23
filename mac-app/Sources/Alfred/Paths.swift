import Foundation

/// Where Alfred lives: the ALFRED_HOME setting (environment variable).
/// Default: ~/Library/Application Support/Alfred. Code, data/, models/, .venv/ and bin/ all sit inside it.
enum Paths {
    static let home: String = {
        if let e = ProcessInfo.processInfo.environment["ALFRED_HOME"], !e.isEmpty {
            return (e as NSString).expandingTildeInPath
        }
        return NSHomeDirectory() + "/Library/Application Support/Alfred"
    }()
    static var data: String { home + "/data" }
    static var uiDir: String { home + "/data/ui" }
    static var python: String { home + "/.venv/bin/python" }
    static var brainInstalled: Bool { FileManager.default.fileExists(atPath: home + "/alfred.py") && FileManager.default.fileExists(atPath: python) }
    /// Brain source shipped inside the app bundle (Contents/Resources/brain) — copied to `home` on first run.
    static var bundledBrain: String? {
        let p = Bundle.main.resourcePath.map { $0 + "/brain" }
        if let p, FileManager.default.fileExists(atPath: p + "/alfred.py") { return p }
        return nil
    }
}
