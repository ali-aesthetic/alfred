import Foundation
import Combine

/// First-run installer: copies the brain into ALFRED_HOME, builds a private Python, downloads the models.
/// Real numbers only: bytes and package counts come from the downloads themselves; steps that cannot be measured
/// say so (indeterminate) until they can. Pause (really suspends the work), Retry and Cancel are supported.
@MainActor
final class SetupManager: ObservableObject {
    static let shared = SetupManager()

    enum State: Equatable { case pending, running, done, failed(String) }
    struct Step: Identifiable {
        let id: String
        let title: String
        let weight: Double            // share of the overall bar
        var state: State = .pending
        var pct: Double? = nil        // nil = cannot be measured right now
        var detail: String = ""
    }

    @Published private(set) var steps: [Step] = [
        Step(id: "prepare", title: "Unpacking Alfred", weight: 2),
        Step(id: "python", title: "Setting up Python (private, your system is untouched)", weight: 28),
        Step(id: "models", title: "Downloading the ears and the voice", weight: 70),
    ]
    @Published private(set) var running = false
    @Published private(set) var paused = false
    @Published private(set) var finished = false
    @Published private(set) var errorText: String?
    @Published private(set) var currentLabel = ""

    var overall: Double {
        steps.reduce(0) { $0 + $1.weight * (($1.state == .done) ? 1 : ($1.pct ?? 0) / 100) } / steps.reduce(0) { $0 + $1.weight }
    }
    var needed: Bool { !Paths.brainInstalled || !modelsPresent }
    var modelsPresent: Bool {
        FileManager.default.fileExists(atPath: Paths.home + "/models/kokoro/voices-v1.0.bin")
    }

    private var task: Task<Void, Never>?
    private var proc: Process?
    private var download: URLSessionDownloadTask?
    private var cancelled = false

    // MARK: controls
    func start() {
        guard !running else { return }
        cancelled = false; errorText = nil; finished = false; paused = false; running = true
        task = Task { await self.runAll() }
    }
    func retry() { start() }
    func pause() {
        paused = true
        _ = proc?.suspend(); download?.suspend()
    }
    func resume() {
        paused = false
        _ = proc?.resume(); download?.resume()
    }
    func cancel() {
        cancelled = true
        if paused { resume() }
        proc?.terminate(); download?.cancel()
        task?.cancel()
        running = false
    }

    // MARK: steps
    private func set(_ id: String, _ body: (inout Step) -> Void) {
        if let i = steps.firstIndex(where: { $0.id == id }) { body(&steps[i]) }
    }

    private func runAll() async {
        for s in steps where s.state != .done {
            if cancelled { return }
            set(s.id) { $0.state = .running; $0.pct = nil; $0.detail = "" }
            currentLabel = s.title
            do {
                switch s.id {
                case "prepare": try prepare()
                case "python": try await python()
                default: try await models()
                }
                set(s.id) { $0.state = .done; $0.pct = 100; $0.detail = "" }
            } catch {
                if cancelled { return }
                let msg = (error as? SetupError)?.text ?? error.localizedDescription
                set(s.id) { $0.state = .failed(msg) }
                errorText = msg; running = false
                return
            }
        }
        running = false; finished = true; currentLabel = "All set"
    }

    struct SetupError: Error { let text: String }

    /// Alfred never deletes: anything in the way is moved into ALFRED_HOME/to delete.
    private func aside(_ path: String) {
        let fm = FileManager.default
        guard fm.fileExists(atPath: path) else { return }
        let td = Paths.home + "/to delete"
        try? fm.createDirectory(atPath: td, withIntermediateDirectories: true)
        try? fm.moveItem(atPath: path, toPath: td + "/" + (path as NSString).lastPathComponent + ".\(Int(Date().timeIntervalSince1970))")
    }

    private var env: [String: String] {
        var e = ProcessInfo.processInfo.environment
        let h = Paths.home
        e["ALFRED_HOME"] = h
        e["UV_PYTHON_INSTALL_DIR"] = h + "/python"; e["UV_CACHE_DIR"] = h + "/.uv-cache"; e["UV_LINK_MODE"] = "copy"
        e["HF_HOME"] = h + "/models"; e["PIP_CACHE_DIR"] = h + "/.pip-cache"
        e["PATH"] = h + "/bin:/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin:/usr/local/bin"
        e["PYTHONUNBUFFERED"] = "1"
        return e
    }

    private func prepare() throws {
        let fm = FileManager.default
        let h = Paths.home
        for d in ["", "/data", "/data/ui", "/bin"] { try fm.createDirectory(atPath: h + d, withIntermediateDirectories: true) }
        if let src = Paths.bundledBrain {
            // copy brain files (never overwrite the user's config or data)
            for name in try fm.contentsOfDirectory(atPath: src) where name != "config.json" && name != "data" {
                let to = h + "/" + name
                if fm.fileExists(atPath: to) { aside(to) }
                try fm.copyItem(atPath: src + "/" + name, toPath: to)
            }
        } else if !fm.fileExists(atPath: h + "/alfred.py") {
            throw SetupError(text: "Alfred's brain files were not found inside the app. Please download Alfred again.")
        }
        if !fm.fileExists(atPath: h + "/config.json"), fm.fileExists(atPath: h + "/config.example.json") {
            try fm.copyItem(atPath: h + "/config.example.json", toPath: h + "/config.json")
        }
        if let items = try? fm.contentsOfDirectory(atPath: h + "/scripts") {
            for n in items {
                let to = h + "/bin/" + n
                if fm.fileExists(atPath: to) { aside(to) }   // our own copy of our own script
                try? fm.copyItem(atPath: h + "/scripts/" + n, toPath: to)
                chmod(to, 0o755)
            }
        }
        // alfred-ctl (computer control) ships next to the app's own binary
        if let ctl = Bundle.main.path(forResource: "alfred-ctl", ofType: nil) ?? Bundle.main.executablePath.map({ ($0 as NSString).deletingLastPathComponent + "/alfred-ctl" }),
           fm.fileExists(atPath: ctl) {
            aside(h + "/bin/alfred-ctl")
            try? fm.copyItem(atPath: ctl, toPath: h + "/bin/alfred-ctl")
        }
    }

    private func python() async throws {
        let h = Paths.home
        let fm = FileManager.default
        if !fm.fileExists(atPath: h + "/bin/uv") {
            set("python") { $0.detail = "Downloading the Python tool (uv)" }
            let url = URL(string: "https://github.com/astral-sh/uv/releases/latest/download/uv-aarch64-apple-darwin.tar.gz")!
            let tmp = try await downloadFile(url) { got, total in
                self.set("python") { s in
                    s.pct = total > 0 ? Double(got) / Double(total) * 8 : nil     // the download is the first 8% of this step
                    s.detail = total > 0 ? "Python tool: \(Self.mb(got)) of \(Self.mb(total))" : "Downloading the Python tool"
                }
            }
            let x = h + "/.uv-extract"
            aside(x); try fm.createDirectory(atPath: x, withIntermediateDirectories: true)
            _ = try await run("/usr/bin/tar", ["-xzf", tmp.path, "-C", x], lines: { _ in })
            let found = try fm.subpathsOfDirectory(atPath: x).first { $0.hasSuffix("/uv") && !$0.contains("uvx") }
            guard let f = found else { throw SetupError(text: "Could not unpack the Python tool.") }
            aside(h + "/bin/uv")
            try fm.moveItem(atPath: x + "/" + f, toPath: h + "/bin/uv")
            chmod(h + "/bin/uv", 0o755)
            aside(x)
        }
        set("python") { $0.pct = 8; $0.detail = "Creating the private Python environment" }
        if !fm.fileExists(atPath: h + "/.venv/bin/python") {
            _ = try await run(h + "/bin/uv", ["venv", "--python", "3.12", h + "/.venv"], lines: { l in self.set("python") { $0.detail = String(l.prefix(80)) } })
        }
        // count packages so the bar is real: uv prints one " + name==version" line per installed package
        let req = (try? String(contentsOfFile: h + "/requirements.txt", encoding: .utf8)) ?? ""
        let total = max(1, req.split(separator: "\n").filter { !$0.hasPrefix("#") && !$0.trimmingCharacters(in: .whitespaces).isEmpty }.count)
        var done = 0
        set("python") { $0.pct = nil; $0.detail = "Working out which packages to install…" }   // unmeasurable until uv starts installing
        _ = try await run(h + "/bin/uv", ["pip", "install", "--python", h + "/.venv/bin/python", "-r", h + "/requirements.txt"], lines: { l in
            if l.trimmingCharacters(in: .whitespaces).hasPrefix("+ ") {
                done += 1
                let name = l.trimmingCharacters(in: .whitespaces).dropFirst(2).split(separator: "=").first.map(String.init) ?? ""
                self.set("python") { s in s.pct = 10 + 90 * min(1, Double(done) / Double(total)); s.detail = "Package \(min(done, total)) of \(total): \(name)" }
            }
        })
    }

    private var subPct: [String: Double] = [:]
    private func models() async throws {
        let h = Paths.home
        let weights: [String: Double] = ["wake": 5, "voice": 20, "ears": 75]
        subPct = [:]
        var failed: String?
        set("models") { $0.detail = "Starting the download"; $0.pct = 0 }
        _ = try await run(h + "/.venv/bin/python", ["-u", h + "/setup_models.py", "--json"], lines: { l in
            guard let d = l.data(using: .utf8), let o = try? JSONSerialization.jsonObject(with: d) as? [String: Any], let step = o["step"] as? String else { return }
            let state = o["state"] as? String ?? "running"
            if state == "error" { failed = (o["note"] as? String) ?? "download failed"; return }
            guard let w = weights[step] else { return }
            let pct = (o["pct"] as? Double) ?? (state == "done" ? 100 : 0)
            self.subPct[step] = state == "done" ? 100 : pct
            let overall = weights.reduce(0) { $0 + $1.value * (self.subPct[$1.key] ?? 0) / 100 }
            var detail = (o["label"] as? String) ?? step
            if let done = o["done"] as? Double, let total = o["total"] as? Double, total > 0, state == "running" {
                detail += ": \(Self.mb(Int64(done))) of \(Self.mb(Int64(total)))"
                if let eta = o["eta"] as? Double, eta > 1 { detail += " · about \(Self.eta(eta)) left" }
            }
            _ = w
            self.set("models") { $0.pct = overall; $0.detail = detail }
        })
        if let f = failed { throw SetupError(text: "A download failed: \(f). Check your internet connection, then press Retry.") }
    }

    // MARK: process + download helpers
    private func run(_ exe: String, _ args: [String], lines: @escaping (String) -> Void) async throws -> Int32 {
        let p = Process()
        p.executableURL = URL(fileURLWithPath: exe); p.arguments = args
        p.environment = env; p.currentDirectoryURL = URL(fileURLWithPath: Paths.home)
        let out = Pipe(); p.standardOutput = out; p.standardError = out
        var buf = Data()
        out.fileHandleForReading.readabilityHandler = { h in
            let d = h.availableData
            if d.isEmpty { return }
            buf.append(d)
            while let nl = buf.firstIndex(of: 0x0A) {
                let line = String(decoding: buf[buf.startIndex..<nl], as: UTF8.self)
                buf.removeSubrange(buf.startIndex...nl)
                DispatchQueue.main.async { MainActor.assumeIsolated { lines(line) } }
            }
        }
        proc = p
        let code: Int32 = try await withCheckedThrowingContinuation { cont in
            p.terminationHandler = { cont.resume(returning: $0.terminationStatus) }
            do { try p.run() } catch { cont.resume(throwing: error) }
        }
        out.fileHandleForReading.readabilityHandler = nil
        proc = nil
        if code != 0 && !cancelled { throw SetupError(text: "A setup step failed (code \(code)). Press Retry; if it keeps failing, open Help → Troubleshooting.") }
        return code
    }

    private func downloadFile(_ url: URL, progress: @escaping @MainActor (Int64, Int64) -> Void) async throws -> URL {
        let d = Downloader(progress: progress)
        let session = URLSession(configuration: .default, delegate: d, delegateQueue: nil)
        let t = session.downloadTask(with: url)
        download = t
        defer { download = nil; session.finishTasksAndInvalidate() }
        return try await withCheckedThrowingContinuation { cont in d.cont = cont; t.resume() }
    }

    static func mb(_ b: Int64) -> String { b >= 1_000_000_000 ? String(format: "%.1f GB", Double(b) / 1e9) : String(format: "%.0f MB", Double(b) / 1e6) }
    static func eta(_ s: Double) -> String { s < 90 ? "\(Int(s)) seconds" : "\(Int((s / 60).rounded())) minutes" }
}

private final class Downloader: NSObject, URLSessionDownloadDelegate {
    var cont: CheckedContinuation<URL, Error>?
    let progress: @MainActor (Int64, Int64) -> Void
    init(progress: @escaping @MainActor (Int64, Int64) -> Void) { self.progress = progress }
    func urlSession(_ s: URLSession, downloadTask t: URLSessionDownloadTask, didWriteData: Int64, totalBytesWritten w: Int64, totalBytesExpectedToWrite e: Int64) {
        Task { @MainActor in progress(w, e) }
    }
    func urlSession(_ s: URLSession, downloadTask t: URLSessionDownloadTask, didFinishDownloadingTo loc: URL) {
        let keep = FileManager.default.temporaryDirectory.appendingPathComponent("alfred-" + UUID().uuidString + ".tgz")
        try? FileManager.default.moveItem(at: loc, to: keep)
        cont?.resume(returning: keep); cont = nil
    }
    func urlSession(_ s: URLSession, task: URLSessionTask, didCompleteWithError e: Error?) {
        if let e { cont?.resume(throwing: e); cont = nil }
    }
}
