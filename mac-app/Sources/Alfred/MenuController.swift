import AppKit
import ServiceManagement

/// The one menu-bar menu.
@MainActor
final class MenuController: NSObject, NSMenuDelegate {
    let item = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
    private let brain: BrainManager
    private let model: PillModel
    private let menu = NSMenu()
    private let status = NSMenuItem()
    private let mic = NSMenuItem(), silent = NSMenuItem(), camera = NSMenuItem(), login = NSMenuItem()
    private var holo: [String: NSMenuItem] = [:]
    private let routinesItem = NSMenuItem(title: "Routines", action: nil, keyEquivalent: "")
    private let holoItem = NSMenuItem(title: "Hologram", action: nil, keyEquivalent: "")

    init(brain: BrainManager, model: PillModel) {
        self.brain = brain; self.model = model
        super.init()
        menu.delegate = self
        menu.autoenablesItems = false
        build()
        item.menu = menu
        updateIcon()
    }

    func updateIcon() {
        item.button?.image = MenuMark.image(awake: brain.awake, mode: model.mode, micOff: model.micOff)
        item.button?.toolTip = model.micOff ? "Alfred: microphone off" : "Alfred"
    }

    private func add(_ title: String, _ symbol: String, _ sel: Selector?, key: String = "",
                     mods: NSEvent.ModifierFlags = .command, to m: NSMenu? = nil) -> NSMenuItem {
        let i = NSMenuItem(title: title, action: sel, keyEquivalent: key)
        i.target = self
        i.keyEquivalentModifierMask = mods
        if !symbol.isEmpty { i.image = NSImage(systemSymbolName: symbol, accessibilityDescription: nil) }
        (m ?? menu).addItem(i)
        return i
    }

    private func build() {
        _ = add("Open Alfred", "macwindow", #selector(openMain))
        menu.addItem(.separator())
        status.isEnabled = false
        menu.addItem(status)
        menu.addItem(.separator())
        _ = mic.self; copy(mic, add("Mic", "mic", #selector(toggleMic)))
        copy(silent, add("Silent mode", "speaker.slash", #selector(toggleSilent)))
        copy(camera, add("Camera: look at me", "camera", #selector(toggleCamera)))
        menu.addItem(.separator())
        _ = add("Learn now", "brain", #selector(learnNow), key: "l")
        _ = add("What I learned…", "list.bullet.rectangle", #selector(showMemory))
        routinesItem.image = NSImage(systemSymbolName: "bolt", accessibilityDescription: nil)
        routinesItem.submenu = NSMenu()
        menu.addItem(routinesItem)
        menu.addItem(.separator())
        _ = add("Open Console…", "terminal", #selector(showConsole))
        _ = add("Settings…", "gearshape", #selector(showSettings), key: ",")
        _ = add("Restart brain", "arrow.clockwise", #selector(restartBrain))
        copy(login, add("Start at login", "power", #selector(toggleLogin)))
        menu.addItem(.separator())
        _ = add("Quit Alfred", "xmark.circle", #selector(quit), key: "q")
    }

    private func copy(_ dst: NSMenuItem, _ src: NSMenuItem) {
        // `mic`, `silent`... were pre-created; swap the freshly added item for the stored one.
        if let idx = menu.items.firstIndex(of: src) { menu.removeItem(at: idx); dst.title = src.title; dst.image = src.image
            dst.action = src.action; dst.target = self; menu.insertItem(dst, at: idx) }
    }

    func menuWillOpen(_ menu: NSMenu) {
        let s = Bridge.shared.settings
        if !brain.awake { status.title = "Brain asleep"; status.image = NSImage(systemSymbolName: "moon", accessibilityDescription: nil) }
        else if model.mode == .listening { status.title = "Listening"; status.image = NSImage(systemSymbolName: "waveform", accessibilityDescription: nil) }
        else { status.title = "Awake"; status.image = NSImage(systemSymbolName: "circle.circle", accessibilityDescription: nil) }
        let micOff = (s["mic_off"] as? Bool) == true
        mic.title = micOff ? "Mic: off" : "Mic: on"
        mic.image = NSImage(systemSymbolName: micOff ? "mic.slash" : "mic", accessibilityDescription: nil)
        silent.state = (s["silent"] as? Bool) == true ? .on : .off
        camera.state = (s["camera"] as? Bool) == true ? .on : .off
        login.state = SMAppService.mainApp.status == .enabled ? .on : .off
        rebuildRoutines()
        updateIcon()
    }

    private func rebuildRoutines() {
        let m = routinesItem.submenu ?? NSMenu(); m.removeAllItems()
        var list: [(String, String)] = []
        if let arr = Bridge.shared.readJSON(Bridge.shared.routinesPath) as? [[String: Any]] {
            for r in arr { if let id = r["id"] as? String { list.append((id, (r["name"] as? String) ?? id)) } }
        }
        if list.isEmpty { list = [("edit", "Edit mode"), ("class", "Class mode"), ("wind_down", "Wind down")] }
        for (id, name) in list {
            let i = NSMenuItem(title: name, action: #selector(runRoutine(_:)), keyEquivalent: id == "edit" ? "e" : "")
            if id == "edit" { i.keyEquivalentModifierMask = .option }
            i.target = self; i.representedObject = id
            m.addItem(i)
        }
    }

    // MARK: actions
    private func flip(_ key: String) { Bridge.shared.set(key, !((Bridge.shared.settings[key] as? Bool) ?? false)) }
    @objc func toggleMic() { flip("mic_off") }
    @objc func toggleSilent() { flip("silent") }
    @objc func toggleCamera() { flip("camera") }
    @objc func setHolo(_ i: NSMenuItem) { Bridge.shared.set("holo_mode", i.representedObject as? String ?? "auto") }
    @objc func learnNow() { Bridge.shared.send("learn_now") }
    @objc func openMain() { WindowsHub.shared.showMain(.home) }
    @objc func showMemory() { WindowsHub.shared.showMemory() }
    @objc func runRoutine(_ i: NSMenuItem) { Bridge.shared.send("routine", ["name": i.representedObject as? String ?? ""]) }
    @objc func showConsole() { WindowsHub.shared.showConsole() }
    @objc func showSettings() { WindowsHub.shared.showSettings() }
    @objc func restartBrain() { brain.restart() }
    @objc func quit() { NSApp.terminate(nil) }
    @objc func toggleLogin() {
        do {
            if SMAppService.mainApp.status == .enabled { try SMAppService.mainApp.unregister() }
            else { try SMAppService.mainApp.register() }
        } catch { NSSound.beep() }
    }
}
