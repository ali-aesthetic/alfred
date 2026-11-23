import SwiftUI
import AppKit

/// Owns the four app windows (Settings, Console, Memory, Onboarding). One window each, reused.
@MainActor
final class WindowsHub: NSObject, NSWindowDelegate {
    static let shared = WindowsHub()
    private var windows: [String: NSWindow] = [:]

    private override init() {
        super.init()
        _ = ConsoleModel.shared      // start collecting events from launch
    }

    /// `quiet`: used at launch. Orders the window in without activating the app or stealing focus.
    func showMain(_ s: MainSection? = nil, quiet: Bool = false) {
        if let e = ProcessInfo.processInfo.environment["ALFRED_SECTION"], let o = MainSection(rawValue: e) { AppState.shared.section = o }   // preview hook
        else if let s { AppState.shared.section = s }
        if ProcessInfo.processInfo.environment["ALFRED_ONBOARDING"] != nil { showOnboarding() }   // preview hook
        show("main", "Alfred", CGSize(width: 900, height: 640), min: CGSize(width: 720, height: 480), quiet: quiet) { MainWindowView() }
    }
    func showSettings() { showMain(.settings) }
    func showMemory() { showMain(.memory) }
    func showConsole() { showMain(.console) }
    func showOnboarding() {
        show("onboarding", "Welcome to Alfred", CGSize(width: 600, height: 700), min: nil, glass: true) { OnboardingView(onClose: { [weak self] in self?.windows["onboarding"]?.close() }) }
    }

    func windowWillClose(_ n: Notification) {
        guard let w = n.object as? NSWindow, w === windows["main"] else { return }
        let key = "tipShown"
        if UserDefaults.standard.bool(forKey: key) { return }
        UserDefaults.standard.set(true, forKey: key)
        DispatchQueue.main.async {
            let a = NSAlert()
            a.messageText = "Alfred is still in the menu bar ◎"
            a.informativeText = "Quit with ⌘Q."
            a.addButton(withTitle: "OK")
            a.runModal()
        }
    }

    private func show<V: View>(_ id: String, _ title: String, _ size: CGSize, min: CGSize?, glass: Bool = false, quiet: Bool = false, @ViewBuilder content: () -> V) {
        if let w = windows[id] {
            if quiet { w.orderFrontRegardless() } else { w.makeKeyAndOrderFront(nil); NSApp.activate(ignoringOtherApps: true) }
            return
        }
        let hc = NSHostingController(rootView: content())
        hc.sizingOptions = []
        var mask: NSWindow.StyleMask = [.titled, .closable, .miniaturizable, .fullSizeContentView]
        if min != nil { mask.insert(.resizable) }
        let w = NSWindow(contentRect: NSRect(origin: .zero, size: size), styleMask: mask, backing: .buffered, defer: false)
        w.contentViewController = hc
        w.setContentSize(size)
        w.title = title
        if id != "main" { w.titlebarAppearsTransparent = true }
        if id == "onboarding" { w.titleVisibility = .hidden }
        if let min { w.contentMinSize = min }
        if glass { w.isOpaque = false; w.backgroundColor = .clear }
        w.isReleasedWhenClosed = false
        w.delegate = self
        w.center()
        w.setFrameAutosaveName("Alfred.\(id)\(id == "onboarding" ? "2" : "")")   // restores saved frame if present
        windows[id] = w
        if quiet { w.orderFrontRegardless() } else { w.makeKeyAndOrderFront(nil); NSApp.activate(ignoringOtherApps: true) }
    }
}

/// Lets showMemory() jump to a pane in an already-open Settings window.
@MainActor
final class SettingsNav: ObservableObject {
    static let shared = SettingsNav()
    @Published var pane: SettingsPane = .personality
    func go(_ p: SettingsPane) { pane = p }
}
