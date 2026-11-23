import AppKit
import SwiftUI

/// Borderless, non-activating panel hanging from the top edge of the main screen.
/// Click-through everywhere except over the pill when it has something to click.
final class PillPanel: NSPanel {
    static let canvas = CGSize(width: 480, height: 150)
    let model: PillModel
    private var timer: Timer?

    init(model: PillModel) {
        self.model = model
        super.init(contentRect: NSRect(origin: .zero, size: PillPanel.canvas),
                   styleMask: [.borderless, .nonactivatingPanel],
                   backing: .buffered, defer: false)
        isOpaque = false
        backgroundColor = .clear
        hasShadow = false
        collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .stationary, .ignoresCycle]
        isFloatingPanel = true
        level = NSWindow.Level(rawValue: NSWindow.Level.statusBar.rawValue + 1)   // after isFloatingPanel
        hidesOnDeactivate = false
        becomesKeyOnlyIfNeeded = true
        ignoresMouseEvents = true
        isMovable = false

        let host = NSHostingView(rootView: PillView(model: model))
        host.sizingOptions = []
        host.frame = NSRect(origin: .zero, size: PillPanel.canvas)
        host.autoresizingMask = [.width, .height]
        contentView = host

        reposition()
        NotificationCenter.default.addObserver(forName: NSApplication.didChangeScreenParametersNotification,
                                               object: nil, queue: .main) { [weak self] _ in self?.reposition() }
        timer = Timer.scheduledTimer(withTimeInterval: 0.05, repeats: true) { [weak self] _ in
            MainActor.assumeIsolated { self?.tick() }
        }
    }

    override func constrainFrameRect(_ frameRect: NSRect, to screen: NSScreen?) -> NSRect { frameRect }
    override var canBecomeKey: Bool { false }
    override var canBecomeMain: Bool { false }

    func reposition() {
        guard let screen = NSScreen.main ?? NSScreen.screens.first else { return }
        let f = screen.frame
        setFrame(NSRect(x: f.midX - PillPanel.canvas.width / 2, y: f.maxY - PillPanel.canvas.height,
                        width: PillPanel.canvas.width, height: PillPanel.canvas.height), display: true)
    }

    @MainActor private func tick() {
        guard isVisible else { return }
        let m = NSEvent.mouseLocation
        let f = frame
        let s = model.contentSize
        let rect = NSRect(x: f.midX - s.width / 2 - 4, y: f.maxY - s.height - 4, width: s.width + 8, height: s.height + 8)
        let want = !(model.interactive && rect.contains(m))
        if ignoresMouseEvents != want { ignoresMouseEvents = want }
        // lean: drift toward the cursor while listening
        var target: CGFloat = 0
        if model.mode == .listening { target = max(-8, min(8, (m.x - f.midX) / 60)) }
        if abs(model.lean - target) > 0.2 { model.lean += (target - model.lean) * 0.25 } else if model.lean != target { model.lean = target }
    }

    func toggle() { isVisible ? orderOut(nil) : orderFrontRegardless() }
}
