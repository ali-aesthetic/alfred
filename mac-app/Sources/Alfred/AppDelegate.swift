import AppKit
import Combine

@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate {
    let model = PillModel()
    let brain = BrainManager()
    var panel: PillPanel!
    var menu: MenuController!
    var bag = Set<AnyCancellable>()

    func applicationDidFinishLaunching(_ n: Notification) {
        let firstLaunch = !FileManager.default.fileExists(atPath: Bridge.shared.settingsPath) || SetupManager.shared.needed
        Bridge.shared.start()
        panel = PillPanel(model: model)
        panel.orderFrontRegardless()
        menu = MenuController(brain: brain, model: model)

        brain.$awake.receive(on: RunLoop.main).sink { [weak self] awake in
            self?.model.setAwake(awake)
            AppState.shared.awake = awake
            self?.menu.updateIcon()
        }.store(in: &bag)
        model.$mode.receive(on: RunLoop.main).sink { [weak self] m in
            AppState.shared.mode = m
            self?.menu.updateIcon()
        }.store(in: &bag)
        model.$micOff.receive(on: RunLoop.main).sink { [weak self] _ in self?.menu.updateIcon() }.store(in: &bag)
        if Bridge.shared.settings["holo_mode"] == nil { Bridge.shared.set("holo_mode", "off") }
        installMainMenu()

        if Paths.brainInstalled { brain.begin() }   // otherwise the first-run guide installs it, then starts the brain
        Hotkey.shared.start()
        PointerOverlay.shared.start()
        WindowsHub.shared.showMain(.home, quiet: true)
        if firstLaunch { WindowsHub.shared.showOnboarding() }
    }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        WindowsHub.shared.showMain(); return true
    }
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { false }

    @objc func openMain() { WindowsHub.shared.showMain(.home) }
    @objc func openSettings() { WindowsHub.shared.showSettings() }
    @objc func openHelp() { WindowsHub.shared.showMain(.help) }
    @objc func openSetupGuide() { WindowsHub.shared.showOnboarding() }
    @objc func openConsole() { WindowsHub.shared.showConsole() }
    @objc func newRequest() { WindowsHub.shared.showMain(.home); AppState.shared.draft = "" }

    private func installMainMenu() {
        let main = NSMenu()
        func top(_ title: String) -> NSMenu {
            let it = NSMenuItem(); main.addItem(it)
            let m = NSMenu(title: title); it.submenu = m; return m
        }
        func add(_ m: NSMenu, _ t: String, _ sel: Selector?, _ key: String = "", _ mods: NSEvent.ModifierFlags = .command, target: AnyObject? = nil) {
            let i = NSMenuItem(title: t, action: sel, keyEquivalent: key)
            i.keyEquivalentModifierMask = mods; i.target = target; m.addItem(i)
        }
        let app = top("Alfred")
        add(app, "About Alfred", #selector(NSApplication.orderFrontStandardAboutPanel(_:)), target: NSApp)
        app.addItem(.separator())
        add(app, "Settings…", #selector(openSettings), ",", target: self)
        app.addItem(.separator())
        let services = NSMenu(title: "Services")
        let si = NSMenuItem(title: "Services", action: nil, keyEquivalent: ""); si.submenu = services; app.addItem(si)
        NSApp.servicesMenu = services
        app.addItem(.separator())
        add(app, "Hide Alfred", #selector(NSApplication.hide(_:)), "h", target: NSApp)
        add(app, "Hide Others", #selector(NSApplication.hideOtherApplications(_:)), "h", [.command, .option], target: NSApp)
        add(app, "Show All", #selector(NSApplication.unhideAllApplications(_:)), target: NSApp)
        app.addItem(.separator())
        add(app, "Quit Alfred", #selector(NSApplication.terminate(_:)), "q", target: NSApp)

        let file = top("File")
        add(file, "New Request", #selector(newRequest), "n", target: self)
        add(file, "Open Console", #selector(openConsole), "0", target: self)
        file.addItem(.separator())
        add(file, "Close Window", #selector(NSWindow.performClose(_:)), "w")

        let edit = top("Edit")
        add(edit, "Undo", Selector(("undo:")), "z")
        add(edit, "Redo", Selector(("redo:")), "z", [.command, .shift])
        edit.addItem(.separator())
        add(edit, "Cut", #selector(NSText.cut(_:)), "x")
        add(edit, "Copy", #selector(NSText.copy(_:)), "c")
        add(edit, "Paste", #selector(NSText.paste(_:)), "v")
        add(edit, "Select All", #selector(NSText.selectAll(_:)), "a")

        let win = top("Window")
        add(win, "Minimize", #selector(NSWindow.performMiniaturize(_:)), "m")
        add(win, "Zoom", #selector(NSWindow.performZoom(_:)))
        win.addItem(.separator())
        add(win, "Alfred", #selector(openMain), "1", target: self)
        NSApp.windowsMenu = win

        let help = top("Help")
        add(help, "Alfred Help", #selector(openHelp), "?", target: self)
        add(help, "Setup Guide…", #selector(openSetupGuide), target: self)
        NSApp.helpMenu = help
        NSApp.mainMenu = main
    }

    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        brain.shutdown()
        return .terminateNow
    }
}
