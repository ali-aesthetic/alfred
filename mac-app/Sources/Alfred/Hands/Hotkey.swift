import AppKit
import ScreenCaptureKit
import ImageIO
import Combine

/// Hold right Option (or `settings["hotkey"]`) = push-to-talk + screenshot + "draw to point".
@MainActor
final class Hotkey {
    static let shared = Hotkey()

    private var monitors: [Any] = []
    private var mouseMonitors: [Any] = []
    private var pending: Timer?
    private var held = false          // key physically down
    private var active = false        // ptt_down sent
    private var capture: Task<CGImage?, Never>?
    private var selectionTask: Task<Hotkey.Selection?, Never>?
    private let holdDelay: TimeInterval = 0.18
    private var bag = Set<AnyCancellable>()
    private var lastKey: UInt16 = 61

    private init() {}

    func start() {
        guard monitors.isEmpty else { return }
        lastKey = keyCode
        // react to hotkey changes from Settings: drop any half-finished hold
        Bridge.shared.$settings.receive(on: RunLoop.main).sink { [weak self] _ in
            MainActor.assumeIsolated {
                guard let self, self.keyCode != self.lastKey else { return }
                self.lastKey = self.keyCode
                if self.active { self.released() } else { self.cancelPending() }
            }
        }.store(in: &bag)
        let flags: (NSEvent) -> Void = { [weak self] e in MainActor.assumeIsolated { self?.flags(e) } }
        let keys: (NSEvent) -> Void = { [weak self] _ in MainActor.assumeIsolated { self?.keyTyped() } }
        if let m = NSEvent.addGlobalMonitorForEvents(matching: .flagsChanged, handler: flags) { monitors.append(m) }
        if let m = NSEvent.addGlobalMonitorForEvents(matching: .keyDown, handler: keys) { monitors.append(m) }
        if let m = NSEvent.addLocalMonitorForEvents(matching: .flagsChanged, handler: { e in flags(e); return e }) { monitors.append(m) }
        if let m = NSEvent.addLocalMonitorForEvents(matching: .keyDown, handler: { e in keys(e); return e }) { monitors.append(m) }
    }

    // MARK: key config

    private var keyCode: UInt16 {
        let v = Bridge.shared.settings["hotkey"]
        if let n = v as? Int { return UInt16(n) }
        switch (v as? String)?.lowercased().replacingOccurrences(of: " ", with: "_") {
        case "left_option", "left_alt": return 58
        case "right_command": return 54
        case "right_control": return 62
        case "right_shift": return 60
        case "fn": return 63
        default: return 61
        }
    }
    private func mask(_ code: UInt16) -> NSEvent.ModifierFlags {
        switch code {
        case 58, 61: return .option
        case 54, 55: return .command
        case 59, 62: return .control
        case 56, 60: return .shift
        default: return .function
        }
    }

    // MARK: events

    private func flags(_ e: NSEvent) {
        let code = keyCode
        let m = mask(code)
        let all: NSEvent.ModifierFlags = [.option, .command, .control, .shift]
        if e.keyCode == code {
            let down = e.modifierFlags.contains(m)
            let others = e.modifierFlags.intersection(all).subtracting(m)
            if down && !held && others.isEmpty { pressed() }
            else if !down && held { released() }
        } else if held && !active {
            cancelPending()   // another modifier joined: it's a shortcut, not PTT
        }
    }

    private func keyTyped() { if held && !active { cancelPending() } }

    private func cancelPending() {
        pending?.invalidate(); pending = nil
        held = false
    }

    private func pressed() {
        held = true
        pending?.invalidate()
        pending = Timer.scheduledTimer(withTimeInterval: holdDelay, repeats: false) { [weak self] _ in
            MainActor.assumeIsolated { self?.activate() }
        }
    }

    private func activate() {
        pending = nil
        guard held, !active else { return }
        active = true
        PointerOverlay.shared.beginDrawing()
        installMouse()
        capture = Task { await Hotkey.grab() }
        startSelectionGrab()
        Bridge.shared.send("ptt_down")
    }

    private func released() {
        held = false
        if pending != nil { pending?.invalidate(); pending = nil; return }
        guard active else { return }
        active = false
        removeMouse()
        let strokes = PointerOverlay.shared.endDrawing()
        let task = capture; capture = nil
        let selTask = selectionTask; selectionTask = nil
        Bridge.shared.emitLocal(["type": "selection_clear"])
        Task { @MainActor in
            async let sel = selTask?.value
            if let img = await task?.value {
                Hotkey.save(img, strokes: strokes, to: Bridge.shared.screenPath)
            }
            var fields: [String: Any] = [:]
            if let s = await sel, !s.text.isEmpty {
                fields["selection"] = s.text
                fields["selection_app"] = s.app
            }
            Bridge.shared.send("ptt_up", fields)
        }
    }

    // MARK: selected text

    struct Selection { var text: String; var app: String }

    /// Reads the front app's selected text while the key is held (AX first, ⌘C fallback) and tells the pill.
    private func startSelectionGrab() {
        let front = NSWorkspace.shared.frontmostApplication
        let me = ProcessInfo.processInfo.processIdentifier
        guard let front, front.processIdentifier != me else { selectionTask = nil; return }
        let pid = front.processIdentifier
        let name = front.localizedName ?? "the front app"
        let bundle = front.bundleIdentifier ?? ""
        selectionTask = Task.detached(priority: .userInitiated) {
            guard let text = Hotkey.readSelection(pid: pid, bundle: bundle), !text.isEmpty else { return nil }
            let capped = text.count > 8000 ? String(text.prefix(8000)) : text
            let words = capped.split(whereSeparator: { $0.isWhitespace || $0.isNewline }).count
            await MainActor.run { Bridge.shared.emitLocal(["type": "selection", "words": words]) }
            return Selection(text: capped, app: name)
        }
    }

    /// Editors where ⌘C with no selection copies the whole line: never use the clipboard fallback there.
    nonisolated private static let lineCopyApps: Set<String> = ["com.microsoft.VSCode", "com.todesktop.230313mzl4w4u92", "com.sublimetext.4",
                                                    "com.sublimetext.3", "dev.zed.Zed", "com.apple.dt.Xcode"]

    /// nil = unreadable, "" = nothing selected.
    nonisolated static func readSelection(pid: pid_t, bundle: String) -> String? {
        if let ax = axSelectedText(pid: pid) { return ax }
        if lineCopyApps.contains(bundle) || bundle.hasPrefix("com.jetbrains.") { return nil }
        return copySelection()
    }

    nonisolated static func axSelectedText(pid: pid_t) -> String? {
        guard AXIsProcessTrusted() else { return nil }
        func selected(_ el: AXUIElement) -> String? {
            var v: CFTypeRef?
            guard AXUIElementCopyAttributeValue(el, kAXSelectedTextAttribute as CFString, &v) == .success else { return nil }
            return v as? String
        }
        func focused(_ root: AXUIElement) -> AXUIElement? {
            var f: CFTypeRef?
            guard AXUIElementCopyAttributeValue(root, kAXFocusedUIElementAttribute as CFString, &f) == .success,
                  let f, CFGetTypeID(f) == AXUIElementGetTypeID() else { return nil }
            return (f as! AXUIElement)
        }
        let sys = AXUIElementCreateSystemWide()
        AXUIElementSetMessagingTimeout(sys, 0.3)
        if let el = focused(sys) {
            var p: pid_t = 0
            AXUIElementGetPid(el, &p)
            if p == pid, let t = selected(el) { return t }
        }
        let app = AXUIElementCreateApplication(pid)
        AXUIElementSetMessagingTimeout(app, 0.3)
        if let el = focused(app), let t = selected(el) { return t }
        return nil
    }

    /// Save clipboard, press ⌘C, read, restore. Returns "" when nothing was copied (nothing selected).
    nonisolated static func copySelection() -> String? {
        let pb = NSPasteboard.general
        let saved: [[(NSPasteboard.PasteboardType, Data)]] = (pb.pasteboardItems ?? []).map { item in
            item.types.compactMap { t in item.data(forType: t).map { (t, $0) } }
        }
        let before = pb.changeCount
        let src = CGEventSource(stateID: .privateState)   // ignores the physically held Option key
        for down in [true, false] {
            let e = CGEvent(keyboardEventSource: src, virtualKey: 8, keyDown: down)   // "c"
            e?.flags = .maskCommand
            e?.post(tap: .cghidEventTap)
        }
        var waited = 0
        while pb.changeCount == before && waited < 60 { Thread.sleep(forTimeInterval: 0.01); waited += 1 }
        guard pb.changeCount != before else { return "" }
        let text = pb.string(forType: .string) ?? ""
        pb.clearContents()
        let items = saved.map { entry -> NSPasteboardItem in
            let it = NSPasteboardItem()
            for (t, d) in entry { it.setData(d, forType: t) }
            return it
        }
        if !items.isEmpty { pb.writeObjects(items) }
        return text
    }

    // MARK: drawing via mouse

    private func installMouse() {
        let h: (NSEvent) -> Void = { [weak self] e in MainActor.assumeIsolated { self?.mouse(e) } }
        let mask: NSEvent.EventTypeMask = [.leftMouseDown, .leftMouseDragged, .leftMouseUp]
        if let m = NSEvent.addGlobalMonitorForEvents(matching: mask, handler: h) { mouseMonitors.append(m) }
        if let m = NSEvent.addLocalMonitorForEvents(matching: mask, handler: { e in h(e); return e }) { mouseMonitors.append(m) }
    }
    private func removeMouse() { mouseMonitors.forEach { NSEvent.removeMonitor($0) }; mouseMonitors = [] }

    private func mouse(_ e: NSEvent) {
        let p = PointerOverlay.topLeft(NSEvent.mouseLocation)
        switch e.type {
        case .leftMouseDown: PointerOverlay.shared.strokeBegin(p)
        case .leftMouseDragged: PointerOverlay.shared.strokeAdd(p)
        default: PointerOverlay.shared.strokeEnd()
        }
    }

    // MARK: screenshot

    nonisolated static func grab() async -> CGImage? {
        let did = CGMainDisplayID()
        if let content = try? await SCShareableContent.excludingDesktopWindows(false, onScreenWindowsOnly: true),
           let d = content.displays.first(where: { $0.displayID == did }) ?? content.displays.first {
            let me = content.windows.filter { $0.owningApplication?.processID == ProcessInfo.processInfo.processIdentifier }
            let filter = SCContentFilter(display: d, excludingWindows: me)
            let cfg = SCStreamConfiguration()
            let scale = Int(filter.pointPixelScale)
            cfg.width = d.width * max(scale, 1)
            cfg.height = d.height * max(scale, 1)
            cfg.showsCursor = false
            if let img = try? await SCScreenshotManager.captureImage(contentFilter: filter, configuration: cfg) { return img }
        }
        // fallback: screencapture CLI
        let tmp = NSTemporaryDirectory() + "alfred-grab.png"
        let p = Process(); p.executableURL = URL(fileURLWithPath: "/usr/sbin/screencapture"); p.arguments = ["-x", tmp]
        try? p.run(); p.waitUntilExit()
        guard let src = CGImageSourceCreateWithURL(URL(fileURLWithPath: tmp) as CFURL, nil) else { return nil }
        return CGImageSourceCreateImageAtIndex(src, 0, nil)
    }

    /// Save PNG, compositing freehand strokes (points in screen points, top-left origin).
    static func save(_ img: CGImage, strokes: [[CGPoint]], to path: String) {
        var out = img
        let screenW = NSScreen.screens.first?.frame.width ?? CGFloat(img.width)
        if !strokes.isEmpty, let ctx = CGContext(data: nil, width: img.width, height: img.height, bitsPerComponent: 8, bytesPerRow: 0,
                                                 space: CGColorSpace(name: CGColorSpace.sRGB)!,
                                                 bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue) {
            ctx.draw(img, in: CGRect(x: 0, y: 0, width: img.width, height: img.height))
            let s = CGFloat(img.width) / screenW
            ctx.setStrokeColor(NSColor(red: 0.04, green: 0.52, blue: 1, alpha: 1).cgColor)
            ctx.setLineWidth(4 * s); ctx.setLineCap(.round); ctx.setLineJoin(.round)
            for st in strokes where st.count > 1 {
                ctx.beginPath()
                ctx.move(to: CGPoint(x: st[0].x * s, y: CGFloat(img.height) - st[0].y * s))
                for p in st.dropFirst() { ctx.addLine(to: CGPoint(x: p.x * s, y: CGFloat(img.height) - p.y * s)) }
                ctx.strokePath()
            }
            if let c = ctx.makeImage() { out = c }
        }
        let rep = NSBitmapImageRep(cgImage: out)
        if let d = rep.representation(using: .png, properties: [:]) {
            try? d.write(to: URL(fileURLWithPath: path), options: .atomic)
        }
    }
}
