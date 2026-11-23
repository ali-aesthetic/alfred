import Foundation

/// Starts / watches the Python brain (alfred.py), mirroring alfred.command's restart loop.
@MainActor
final class BrainManager: ObservableObject {
    enum Mode { case stopped, external, ours, restarting }

    @Published private(set) var awake = false
    @Published private(set) var mode: Mode = .stopped

    private let root = Paths.home
    private var stopFile: String { root + "/data/STOP" }
    private var logPath: String { root + "/data/app-brain.log" }

    private var proc: Process?
    private var wantRunning = false        // false = user/exit-42/STOP asked us to stay stopped
    private var quitting = false
    private var pollTimer: Timer?
    private var restartWork: DispatchWorkItem?

    // MARK: lifecycle

    func begin() {
        renameStop()
        if externalPIDs().isEmpty { wantRunning = true; startOwn() } else { takeOver() }
        refresh()
        pollTimer = Timer.scheduledTimer(withTimeInterval: 2, repeats: true) { [weak self] _ in
            MainActor.assumeIsolated { self?.refresh() }
        }
    }

    /// User-initiated start (menu), like Start Alfred.command.
    func userStart() {
        renameStop()
        guard !awake else { return }
        wantRunning = true
        startOwn()
        refresh()
    }

    func restart() {
        renameStop()
        if let p = proc, p.isRunning {
            wantRunning = true
            restartWork?.cancel()
            // stop, then terminationHandler restarts it (crash path) after 3 s; do it faster:
            p.terminationHandler = nil
            Task { @MainActor [weak self] in
                await Self.terminate(p)
                self?.proc = nil; self?.startOwn(); self?.refresh()
            }
        } else if !externalPIDs().isEmpty {
            takeOver()
        } else {
            wantRunning = true
            startOwn(); refresh()
        }
    }

    /// Quit: stop the brain only if this app started it. SIGTERM, then wait.
    func shutdown() {
        quitting = true
        wantRunning = false
        pollTimer?.invalidate()
        restartWork?.cancel()
        if let p = proc, p.isRunning {
            p.terminationHandler = nil
            let pid = p.processIdentifier
            kill(pid, SIGTERM)
            let deadline = Date().addingTimeInterval(8)
            while p.isRunning && Date() < deadline { Thread.sleep(forTimeInterval: 0.1) }
            if p.isRunning { kill(pid, SIGKILL) }
        }
    }

    /// Take over a brain started from Terminal: STOP file + SIGTERM, wait up to 8 s, then start our own.
    private func takeOver() {
        wantRunning = true
        mode = .restarting
        let fm = FileManager.default
        fm.createFile(atPath: stopFile, contents: nil)
        let pids = externalPIDs()
        for pid in pids { kill(pid, SIGTERM) }
        Task { @MainActor [weak self] in
            guard let self else { return }
            let deadline = Date().addingTimeInterval(8)
            while !self.externalPIDs().isEmpty && Date() < deadline { try? await Task.sleep(nanoseconds: 200_000_000) }
            for pid in self.externalPIDs() { kill(pid, SIGKILL) }
            try? fm.removeItem(atPath: self.stopFile + ".old")
            try? fm.moveItem(atPath: self.stopFile, toPath: self.stopFile + ".old")
            guard !self.quitting else { return }
            self.startOwn(); self.refresh()
        }
    }

    // MARK: internals

    private func renameStop() {
        let fm = FileManager.default
        if fm.fileExists(atPath: stopFile) {
            try? fm.removeItem(atPath: stopFile + ".old")   // same as `mv -f` (replaces the old marker)
            try? fm.moveItem(atPath: stopFile, toPath: stopFile + ".old")
        }
    }

    private func shq(_ s: String) -> String { "'" + s.replacingOccurrences(of: "'", with: "'\\''") + "'" }

    private func startOwn() {
        guard !quitting, proc == nil || proc?.isRunning == false else { return }
        guard externalPIDs().isEmpty else { mode = .external; return }
        let fm = FileManager.default
        if !fm.fileExists(atPath: logPath) { fm.createFile(atPath: logPath, contents: nil) }
        guard let log = FileHandle(forWritingAtPath: logPath) else { return }
        log.seekToEndOfFile()

        let p = Process()
        p.executableURL = URL(fileURLWithPath: "/bin/bash")
        p.arguments = ["-c",
            "export ALFRED_HOME=\(shq(root)); source \"$ALFRED_HOME/env.sh\"; export HF_HUB_OFFLINE=1; cd \"$J\" || exit 1; exec \"$J/.venv/bin/python\" \"$J/alfred.py\""]
        var env = ProcessInfo.processInfo.environment
        env["ALFRED_APP"] = "1"
        p.environment = env
        p.standardOutput = log
        p.standardError = log
        p.standardInput = FileHandle.nullDevice
        p.terminationHandler = { [weak self] done in
            let code = done.terminationStatus
            Task { @MainActor in self?.brainExited(code: code) }
        }
        do {
            try p.run()
            proc = p
            mode = .ours
        } catch {
            mode = .stopped
        }
    }

    private func brainExited(code: Int32) {
        proc = nil
        guard !quitting else { return }
        if code == 42 || FileManager.default.fileExists(atPath: stopFile) {
            wantRunning = false; mode = .stopped; refresh(); return
        }
        guard wantRunning else { mode = .stopped; refresh(); return }
        mode = .restarting
        let w = DispatchWorkItem { [weak self] in
            MainActor.assumeIsolated {
                guard let self, !self.quitting, self.wantRunning else { return }
                if FileManager.default.fileExists(atPath: self.stopFile) { self.wantRunning = false; self.mode = .stopped; return }
                self.startOwn(); self.refresh()
            }
        }
        restartWork = w
        DispatchQueue.main.asyncAfter(deadline: .now() + 3, execute: w)
        refresh()
    }

    private func refresh() {
        let running = (proc?.isRunning ?? false) || !externalPIDs().isEmpty
        if running && mode == .stopped { mode = .external }
        if !running && mode == .external { mode = .stopped }
        if awake != running { awake = running }
    }

    nonisolated static func terminate(_ p: Process) async {
        let pid = p.processIdentifier
        kill(pid, SIGTERM)
        let deadline = Date().addingTimeInterval(8)
        while p.isRunning && Date() < deadline { try? await Task.sleep(nanoseconds: 100_000_000) }
        if p.isRunning { kill(pid, SIGKILL) }
    }

    /// PIDs of any alfred.py from this folder (same test as Start Alfred.command).
    private func externalPIDs() -> [Int32] {
        let t = Process()
        t.executableURL = URL(fileURLWithPath: "/usr/bin/pgrep")
        t.arguments = ["-f", "[J]arvis/alfred.py"]
        let out = Pipe()
        t.standardOutput = out
        t.standardError = FileHandle.nullDevice
        do { try t.run() } catch { return [] }
        let data = out.fileHandleForReading.readDataToEndOfFile()
        t.waitUntilExit()
        let ownPID = proc?.processIdentifier ?? -1
        return (String(data: data, encoding: .utf8) ?? "")
            .split(separator: "\n").compactMap { Int32($0) }
            .filter { $0 != ownPID }
    }
}
