import Foundation
import Combine

/// App ↔ brain talk over JSON lines in data/ui/ (see mac-app/CONTRACT.md).
/// Public API is shared by all parts of the app: add, don't rename.
@MainActor
final class Bridge: ObservableObject {
    static let shared = Bridge()

    static let root = Paths.home
    static let uiDir = root + "/data/ui"
    var eventsPath: String { Bridge.uiDir + "/events.jsonl" }
    var commandsPath: String { Bridge.uiDir + "/commands.jsonl" }
    var settingsPath: String { Bridge.uiDir + "/settings.json" }
    var memoryPath: String { Bridge.uiDir + "/memory.json" }
    var routinesPath: String { Bridge.uiDir + "/routines.json" }
    var screenPath: String { Bridge.uiDir + "/screen.png" }

    /// Every event from the brain, in order. Subscribe with `.sink`.
    let events = PassthroughSubject<[String: Any], Never>()
    /// Last known settings (from settings.json or a `settings` event).
    @Published var settings: [String: Any] = [:]

    private var offset: UInt64 = 0
    private var timer: Timer?
    private var buffer = Data()

    private init() {
        try? FileManager.default.createDirectory(atPath: Bridge.uiDir, withIntermediateDirectories: true)
        if !FileManager.default.fileExists(atPath: eventsPath) { FileManager.default.createFile(atPath: eventsPath, contents: nil) }
        if !FileManager.default.fileExists(atPath: commandsPath) { FileManager.default.createFile(atPath: commandsPath, contents: nil) }
        offset = (try? FileManager.default.attributesOfItem(atPath: eventsPath)[.size] as? UInt64) ?? 0
        settings = readJSON(settingsPath) as? [String: Any] ?? [:]
    }

    /// Start tailing events.jsonl (call once at launch).
    func start() {
        guard timer == nil else { return }
        timer = Timer.scheduledTimer(withTimeInterval: 0.05, repeats: true) { [weak self] _ in
            MainActor.assumeIsolated { self?.poll() }
        }
    }

    private func poll() {
        guard let h = FileHandle(forReadingAtPath: eventsPath) else { return }
        defer { try? h.close() }
        let size = (try? h.seekToEnd()) ?? 0
        if size < offset { offset = 0 }            // file was rotated
        guard size > offset else { return }
        try? h.seek(toOffset: offset)
        let data = h.readDataToEndOfFile()
        offset += UInt64(data.count)
        buffer.append(data)
        while let nl = buffer.firstIndex(of: 0x0A) {
            let line = buffer[buffer.startIndex..<nl]
            buffer.removeSubrange(buffer.startIndex...nl)
            guard let obj = try? JSONSerialization.jsonObject(with: Data(line)) as? [String: Any] else { continue }
            if (obj["type"] as? String) == "settings", let d = obj["data"] as? [String: Any] { settings = d }
            events.send(obj)
        }
    }

    // MARK: app → brain

    func send(_ cmd: String, _ fields: [String: Any] = [:]) {
        var obj = fields
        obj["cmd"] = cmd
        obj["t"] = Date().timeIntervalSince1970
        guard let d = try? JSONSerialization.data(withJSONObject: obj),
              let h = FileHandle(forWritingAtPath: commandsPath) else { return }
        h.seekToEndOfFile()
        h.write(d); h.write(Data([0x0A]))
        try? h.close()
    }

    func ask(_ text: String, screen: String? = nil) {
        var f: [String: Any] = ["text": text]
        if let screen { f["screen"] = screen }
        send("ask", f)
    }

    /// Change one setting: saves settings.json and tells the brain.
    func set(_ key: String, _ value: Any) {
        settings[key] = value
        if let d = try? JSONSerialization.data(withJSONObject: settings, options: [.prettyPrinted, .sortedKeys]) {
            try? d.write(to: URL(fileURLWithPath: settingsPath), options: .atomic)
        }
        send("set", ["key": key, "value": value])
    }

    /// Emit an event locally (for previews/tests; also lets UI parts talk to each other).
    func emitLocal(_ obj: [String: Any]) { events.send(obj) }

    // MARK: shared files

    func readJSON(_ path: String) -> Any? {
        guard let d = FileManager.default.contents(atPath: path) else { return nil }
        return try? JSONSerialization.jsonObject(with: d)
    }

    func writeJSON(_ obj: Any, to path: String) {
        if let d = try? JSONSerialization.data(withJSONObject: obj, options: [.prettyPrinted, .sortedKeys]) {
            try? d.write(to: URL(fileURLWithPath: path), options: .atomic)
        }
    }
}
