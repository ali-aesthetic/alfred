import AppKit
import Combine
import QuartzCore

/// Click-through layer on the screen that holds the target: arrow pointer, ring, tag, freehand strokes.
@MainActor
final class PointerOverlay {
    static let shared = PointerOverlay()

    private static let blue = NSColor(red: 0.04, green: 0.52, blue: 1, alpha: 1)
    private static let green = NSColor(red: 0.19, green: 0.82, blue: 0.35, alpha: 1)
    private static let ringR: CGFloat = 22

    private var panel: NSPanel!
    private var root: CALayer!
    private var bag = Set<AnyCancellable>()
    private var clickMonitors: [Any] = []
    private var keyMonitors: [Any] = []

    // pointer state
    private let pointer = CAShapeLayer()
    private var pointerPos: CGPoint?                 // layer coords of the arrow tip (bottom-left origin)
    private var pointerScreen: NSScreen?
    private var ring: CAShapeLayer?
    private var tick: CAShapeLayer?
    private var tag: NSVisualEffectView?
    private var ringCenter: CGPoint = .zero          // global top-left coords
    private var step = 1, of = 1
    private var waiting = false
    private var busy = false                         // flying / drawing ring
    private var queue: [[String: Any]] = []
    private var clearTimer: Timer?

    // drawing
    private var strokes: [[CGPoint]] = []
    private var strokeLayers: [CAShapeLayer] = []
    private var drawing = false

    private var primaryH: CGFloat { NSScreen.screens.first?.frame.height ?? 0 }
    private var reduceMotion: Bool { NSWorkspace.shared.accessibilityDisplayShouldReduceMotion }
    private var dark: Bool { panel.effectiveAppearance.bestMatch(from: [.darkAqua, .aqua]) == .darkAqua }

    /// Global top-left point (matches `alfred-ctl find` frames) to layer coords of the current panel.
    private func lp(_ p: CGPoint) -> CGPoint {
        let s = panel.frame
        return CGPoint(x: p.x - s.minX, y: (primaryH - p.y) - s.minY)
    }

    static func topLeft(_ p: NSPoint) -> CGPoint {
        let h = NSScreen.screens.first?.frame.height ?? 0
        return CGPoint(x: p.x, y: h - p.y)
    }

    private func screen(containing tl: CGPoint) -> NSScreen? {
        let a = CGPoint(x: tl.x, y: primaryH - tl.y)
        if let s = NSScreen.screens.first(where: { $0.frame.contains(a) }) { return s }
        return NSScreen.screens.min { d($0.frame, a) < d($1.frame, a) }
    }
    private func d(_ r: CGRect, _ p: CGPoint) -> CGFloat {
        hypot(max(r.minX - p.x, 0, p.x - r.maxX), max(r.minY - p.y, 0, p.y - r.maxY))
    }

    private init() {}

    func start() {
        guard panel == nil, let screen = NSScreen.screens.first else { return }
        panel = NSPanel(contentRect: screen.frame, styleMask: [.borderless, .nonactivatingPanel], backing: .buffered, defer: false)
        panel.level = .screenSaver
        panel.isOpaque = false
        panel.backgroundColor = .clear
        panel.hasShadow = false
        panel.ignoresMouseEvents = true
        panel.isReleasedWhenClosed = false
        panel.collectionBehavior = [.canJoinAllSpaces, .stationary, .fullScreenAuxiliary, .ignoresCycle]
        let v = NSView(frame: CGRect(origin: .zero, size: screen.frame.size))
        v.wantsLayer = true
        panel.contentView = v
        root = v.layer
        // SF-style arrow, tip at the layer origin
        let a = CGMutablePath()
        let pts: [CGPoint] = [(0, 0), (0, -17), (4.1, -13.4), (6.6, -19.4), (9.3, -18.2), (6.8, -12.4), (12, -12.4)].map { CGPoint(x: $0.0, y: $0.1) }
        a.move(to: pts[0]); pts.dropFirst().forEach { a.addLine(to: $0) }; a.closeSubpath()
        pointer.path = a
        pointer.fillColor = NSColor.black.cgColor
        pointer.strokeColor = NSColor.white.cgColor
        pointer.lineWidth = 1.5; pointer.lineJoin = .round
        pointer.shadowColor = NSColor.black.cgColor; pointer.shadowOpacity = 0.3; pointer.shadowRadius = 3; pointer.shadowOffset = CGSize(width: 0, height: -1)
        pointer.opacity = 0
        root.addSublayer(pointer)
        panel.orderFrontRegardless()

        NotificationCenter.default.addObserver(forName: NSApplication.didChangeScreenParametersNotification, object: nil, queue: .main) { [weak self] _ in
            MainActor.assumeIsolated { self?.clear() }
        }
        Bridge.shared.events.receive(on: RunLoop.main).sink { [weak self] e in
            guard let self, let t = e["type"] as? String else { return }
            if t == "point" { self.enqueue(e) } else if t == "point_clear" { self.clear() }
        }.store(in: &bag)
    }

    // MARK: point

    private func enqueue(_ e: [String: Any]) {
        if busy { queue.append(e) } else { handlePoint(e) }
    }

    private func handlePoint(_ e: [String: Any]) {
        guard panel != nil,
              let x = (e["x"] as? NSNumber)?.doubleValue, let y = (e["y"] as? NSNumber)?.doubleValue else { return }
        let label = (e["label"] as? String) ?? ""
        let hint = e["hint"] as? String
        step = (e["step"] as? NSNumber)?.intValue ?? 1
        of = max((e["of"] as? NSNumber)?.intValue ?? step, step)
        clearTimer?.invalidate()
        removeRing(animated: false)
        busy = true; waiting = false

        // move the panel to the screen holding the target
        let g = CGPoint(x: x, y: y)
        guard let scr = screen(containing: g) else { busy = false; return }
        let sameScreen = pointerScreen == scr && pointerPos != nil
        if panel.frame != scr.frame { panel.setFrame(scr.frame, display: true) }
        panel.orderFrontRegardless()
        ringCenter = g
        let target = lp(g)
        let start = sameScreen ? pointerPos! : CGPoint(x: panel.frame.width / 2, y: panel.frame.height - 18)  // launch from the pill
        pointerScreen = scr
        pointerPos = target
        pointer.removeAllAnimations()
        pointer.position = target

        if reduceMotion {
            let f = CABasicAnimation(keyPath: "opacity"); f.fromValue = 0; f.toValue = 1; f.duration = 0.15
            pointer.add(f, forKey: "f"); pointer.opacity = 1
            landed(label: label, hint: hint, animated: false)
            return
        }

        // curved path sampled through a damped spring (0.45 s, slight overshoot)
        let dx = target.x - start.x, dy = target.y - start.y
        let dist = max(hypot(dx, dy), 1)
        let bend = min(140, dist * 0.28)
        let ctl = CGPoint(x: (start.x + target.x) / 2 - dy / dist * bend, y: (start.y + target.y) / 2 + dx / dist * bend)
        let n = 36
        var vals: [NSValue] = [], times: [NSNumber] = []
        for i in 0...n {
            let t = CGFloat(i) / CGFloat(n)
            let s = i == n ? 1 : 1 - exp(-7.5 * t) * cos(9 * t)
            let u = 1 - s
            let p = CGPoint(x: u*u*start.x + 2*u*s*ctl.x + s*s*target.x, y: u*u*start.y + 2*u*s*ctl.y + s*s*target.y)
            vals.append(NSValue(point: p)); times.append(NSNumber(value: Double(t)))
        }
        pointer.opacity = 1
        let fly = CAKeyframeAnimation(keyPath: "position")
        fly.values = vals; fly.keyTimes = times; fly.duration = 0.45; fly.calculationMode = .linear
        pointer.add(fly, forKey: "fly")
        let appear = CABasicAnimation(keyPath: "opacity"); appear.fromValue = 0; appear.toValue = 1; appear.duration = 0.12
        pointer.add(appear, forKey: "appear")

        // dotted fading trail
        for i in 1...10 {
            let t = CGFloat(i) / 11, u = 1 - t
            let p = CGPoint(x: u*u*start.x + 2*u*t*ctl.x + t*t*target.x, y: u*u*start.y + 2*u*t*ctl.y + t*t*target.y)
            let dot = CALayer()
            dot.bounds = CGRect(x: 0, y: 0, width: 4, height: 4); dot.cornerRadius = 2
            dot.position = p
            dot.backgroundColor = PointerOverlay.blue.cgColor
            dot.opacity = 0
            root.addSublayer(dot)
            let a = CAKeyframeAnimation(keyPath: "opacity")
            a.values = [0, 0.7, 0]; a.keyTimes = [0, 0.2, 1]
            a.duration = 0.6; a.beginTime = CACurrentMediaTime() + 0.45 * Double(t) * 0.85
            a.fillMode = .backwards; a.isRemovedOnCompletion = true
            dot.add(a, forKey: "trail")
            DispatchQueue.main.asyncAfter(deadline: .now() + 1.3) { dot.removeFromSuperlayer() }
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.45) { [weak self] in
            MainActor.assumeIsolated { self?.landed(label: label, hint: hint, animated: true) }
        }
    }

    private func landed(label: String, hint: String?, animated: Bool) {
        guard let pos = pointerPos else { busy = false; return }
        let r = PointerOverlay.ringR
        func makeRing() -> CAShapeLayer {
            let l = CAShapeLayer()
            let p = CGMutablePath()
            p.addArc(center: .zero, radius: r, startAngle: .pi / 2, endAngle: .pi / 2 - 2 * .pi, clockwise: true)
            l.path = p; l.position = pos; l.fillColor = nil
            l.strokeColor = PointerOverlay.blue.cgColor
            l.lineWidth = 2; l.lineCap = .round
            return l
        }
        let ring = makeRing()
        root.insertSublayer(ring, below: pointer)
        self.ring = ring
        if animated {
            let d = CABasicAnimation(keyPath: "strokeEnd"); d.fromValue = 0; d.toValue = 1; d.duration = 0.3
            d.timingFunction = CAMediaTimingFunction(name: .easeOut)
            ring.add(d, forKey: "draw")
            // one pulse: a faint copy swells out and fades
            let echo = makeRing()
            echo.lineWidth = 1.5
            root.insertSublayer(echo, below: ring)
            let g = CAAnimationGroup(); g.duration = 0.55; g.beginTime = CACurrentMediaTime() + 0.3; g.fillMode = .backwards
            let sc = CABasicAnimation(keyPath: "transform.scale"); sc.fromValue = 1; sc.toValue = 1.7
            let op = CABasicAnimation(keyPath: "opacity"); op.fromValue = 0.55; op.toValue = 0
            g.animations = [sc, op]; g.isRemovedOnCompletion = false; g.fillMode = .both
            echo.opacity = 0
            echo.add(g, forKey: "pulse")
            DispatchQueue.main.asyncAfter(deadline: .now() + 1.0) { echo.removeFromSuperlayer() }
        }
        showTag(label: label, hint: hint, at: pos, animated: animated)
        waiting = true
        installMonitors()
        scheduleClear(step >= of ? 25 : 90)   // safety: nobody clicked
        let delay = animated ? 0.3 : 0
        DispatchQueue.main.asyncAfter(deadline: .now() + delay) { [weak self] in
            MainActor.assumeIsolated {
                guard let self else { return }
                self.busy = false
                if !self.queue.isEmpty { self.handlePoint(self.queue.removeFirst()) }
            }
        }
    }

    private func showTag(label: String, hint: String?, at pos: CGPoint, animated: Bool) {
        tag?.removeFromSuperview()
        let v = NSVisualEffectView()
        v.material = .popover; v.blendingMode = .behindWindow; v.state = .active
        v.wantsLayer = true
        v.layer?.cornerRadius = 8; v.layer?.masksToBounds = true
        v.layer?.borderWidth = 0.5
        v.layer?.borderColor = (dark ? NSColor(white: 1, alpha: 0.16) : NSColor(white: 0, alpha: 0.14)).cgColor

        func field(_ s: String, size: CGFloat, weight: NSFont.Weight, color: NSColor) -> NSTextField {
            let f = NSTextField(labelWithString: s)
            f.font = .systemFont(ofSize: size, weight: weight); f.textColor = color
            f.lineBreakMode = .byTruncatingTail; f.maximumNumberOfLines = 2
            f.preferredMaxLayoutWidth = 220
            return f
        }
        let words = label.split(separator: " ").prefix(6).joined(separator: " ")
        let title = field(words, size: 12.5, weight: .semibold, color: .labelColor)
        title.setContentCompressionResistancePriority(.defaultLow, for: .horizontal)
        var head: [NSView] = [title]
        if of > 1 {
            let c = field("\(step) of \(of)", size: 10.5, weight: .medium, color: .tertiaryLabelColor)
            c.setContentHuggingPriority(.required, for: .horizontal)
            head.append(c)
        }
        let top = NSStackView(views: head)
        top.orientation = .horizontal; top.alignment = .firstBaseline; top.spacing = 10
        var rows: [NSView] = [top]
        if let hint, !hint.isEmpty { rows.append(field(hint, size: 11, weight: .regular, color: .secondaryLabelColor)) }
        let stack = NSStackView(views: rows)
        stack.orientation = .vertical; stack.alignment = .leading; stack.spacing = 2
        stack.edgeInsets = NSEdgeInsets(top: 7, left: 10, bottom: 8, right: 10)
        stack.translatesAutoresizingMaskIntoConstraints = true
        let size = stack.fittingSize
        let w = min(max(size.width, 70), 270), h = size.height
        stack.frame = CGRect(x: 0, y: 0, width: w, height: h)
        v.frame = CGRect(x: 0, y: 0, width: w, height: h)
        v.addSubview(stack)

        // placement (layer coords): first side that fits on this screen and keeps clear of the ring
        let W = panel.frame.width, H = panel.frame.height, m: CGFloat = 12
        let gap = PointerOverlay.ringR + 12
        let keepOut = CGRect(x: pos.x - gap + 4, y: pos.y - gap + 4, width: 2 * gap - 8, height: 2 * gap - 8)
        let cands: [CGPoint] = [
            CGPoint(x: pos.x + gap, y: pos.y - h / 2),          // right
            CGPoint(x: pos.x - gap - w, y: pos.y - h / 2),      // left
            CGPoint(x: pos.x - w / 2, y: pos.y - gap - h),      // below
            CGPoint(x: pos.x - w / 2, y: pos.y + gap),          // above
        ]
        let screenR = CGRect(x: m, y: m, width: W - 2 * m, height: H - 2 * m)
        var o = cands.first { screenR.contains(CGRect(origin: $0, size: CGSize(width: w, height: h))) } ?? cands[0]
        if !screenR.contains(CGRect(origin: o, size: CGSize(width: w, height: h))) {
            // nothing fits cleanly: clamp, then push away from the ring vertically
            o.x = min(max(o.x, m), W - w - m); o.y = min(max(o.y, m), H - h - m)
            if CGRect(origin: o, size: CGSize(width: w, height: h)).intersects(keepOut) {
                o.y = pos.y > H / 2 ? pos.y - gap - h : pos.y + gap
                o.y = min(max(o.y, m), H - h - m)
            }
        }
        v.frame.origin = o
        panel.contentView?.addSubview(v)
        tag = v
        if animated {
            v.alphaValue = 0
            NSAnimationContext.runAnimationGroup { c in c.duration = 0.18; v.animator().alphaValue = 1 }
        }
    }

    // MARK: click + Esc

    private func installMonitors() {
        guard clickMonitors.isEmpty else { return }
        let h: (NSEvent) -> Void = { [weak self] _ in MainActor.assumeIsolated { self?.clicked() } }
        if let m = NSEvent.addGlobalMonitorForEvents(matching: .leftMouseDown, handler: h) { clickMonitors.append(m) }
        if let m = NSEvent.addLocalMonitorForEvents(matching: .leftMouseDown, handler: { e in h(e); return e }) { clickMonitors.append(m) }
        let k: (NSEvent) -> Void = { [weak self] e in if e.keyCode == 53 { MainActor.assumeIsolated { self?.clear() } } }
        if let m = NSEvent.addGlobalMonitorForEvents(matching: .keyDown, handler: k) { keyMonitors.append(m) }
        if let m = NSEvent.addLocalMonitorForEvents(matching: .keyDown, handler: { e in k(e); return e }) { keyMonitors.append(m) }
    }

    private func clicked() {
        guard waiting, !drawing, let ring else { return }
        let p = PointerOverlay.topLeft(NSEvent.mouseLocation)
        guard hypot(p.x - ringCenter.x, p.y - ringCenter.y) <= PointerOverlay.ringR + 10 else { return }
        waiting = false
        ring.strokeColor = PointerOverlay.green.cgColor
        let t = CAShapeLayer()
        let tp = CGMutablePath()
        tp.move(to: CGPoint(x: -7, y: 0)); tp.addLine(to: CGPoint(x: -2.5, y: -5.5)); tp.addLine(to: CGPoint(x: 8, y: 6.5))
        t.path = tp; t.fillColor = nil; t.strokeColor = PointerOverlay.green.cgColor
        t.lineWidth = 3; t.lineCap = .round; t.lineJoin = .round
        t.position = ring.position
        root.addSublayer(t); tick = t
        if !reduceMotion {
            let d = CABasicAnimation(keyPath: "strokeEnd"); d.fromValue = 0; d.toValue = 1; d.duration = 0.2
            t.add(d, forKey: "d")
        }
        Bridge.shared.send("point_done", ["step": step])
        scheduleClear(step >= of ? 3 : 60)
    }

    private func scheduleClear(_ s: TimeInterval) {
        clearTimer?.invalidate()
        clearTimer = Timer.scheduledTimer(withTimeInterval: s, repeats: false) { [weak self] _ in
            MainActor.assumeIsolated { self?.clear() }
        }
    }

    private func removeRing(animated: Bool) {
        let items: [CALayer?] = [ring, tick]
        for l in items.compactMap({ $0 }) {
            if animated {
                let a = CABasicAnimation(keyPath: "opacity"); a.toValue = 0; a.duration = 0.3
                a.fillMode = .forwards; a.isRemovedOnCompletion = false
                l.add(a, forKey: "out")
                DispatchQueue.main.asyncAfter(deadline: .now() + 0.35) { l.removeFromSuperlayer() }
            } else { l.removeFromSuperlayer() }
        }
        ring = nil; tick = nil
        if let t = tag {
            if animated {
                NSAnimationContext.runAnimationGroup({ c in c.duration = 0.3; t.animator().alphaValue = 0 }, completionHandler: { t.removeFromSuperview() })
            } else { t.removeFromSuperview() }
            tag = nil
        }
    }

    func clear() {
        clearTimer?.invalidate()
        waiting = false; busy = false; queue = []
        removeRing(animated: true)
        let a = CABasicAnimation(keyPath: "opacity"); a.toValue = 0; a.duration = 0.3
        a.fillMode = .forwards; a.isRemovedOnCompletion = false
        pointer.add(a, forKey: "out")
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.35) { [weak self] in
            MainActor.assumeIsolated { if self?.pointerPos == nil { self?.pointer.removeAllAnimations(); self?.pointer.opacity = 0 } }
        }
        pointerPos = nil; pointerScreen = nil
        (clickMonitors + keyMonitors).forEach { NSEvent.removeMonitor($0) }; clickMonitors = []; keyMonitors = []
        clearStrokes(animated: true)
    }

    // MARK: freehand drawing (driven by Hotkey)

    func beginDrawing() {
        guard panel != nil else { return }
        clearStrokes(animated: false)
        drawing = true
        panel.orderFrontRegardless()
    }

    func strokeBegin(_ p: CGPoint) {
        guard drawing else { return }
        strokes.append([p])
        let l = CAShapeLayer()
        l.fillColor = nil; l.strokeColor = PointerOverlay.blue.cgColor
        l.lineWidth = 4; l.lineCap = .round; l.lineJoin = .round
        l.shadowColor = PointerOverlay.blue.cgColor; l.shadowOpacity = 0.5; l.shadowRadius = 4; l.shadowOffset = .zero
        root.addSublayer(l); strokeLayers.append(l)
        redraw()
    }
    func strokeAdd(_ p: CGPoint) {
        guard drawing, !strokes.isEmpty else { return }
        strokes[strokes.count - 1].append(p)
        redraw()
    }
    func strokeEnd() {}

    private func redraw() {
        guard let l = strokeLayers.last, let pts = strokes.last else { return }
        let path = CGMutablePath()
        path.move(to: lp(pts[0]))
        if pts.count == 1 { path.addLine(to: lp(CGPoint(x: pts[0].x + 0.1, y: pts[0].y))) }
        for p in pts.dropFirst() { path.addLine(to: lp(p)) }
        l.path = path
    }

    /// Stop drawing; strokes turn green at 50% and fade after 4 s. Returns the strokes (top-left points).
    func endDrawing() -> [[CGPoint]] {
        drawing = false
        let result = strokes
        for l in strokeLayers {
            l.strokeColor = PointerOverlay.green.withAlphaComponent(0.5).cgColor
            l.shadowColor = PointerOverlay.green.cgColor
        }
        if !strokeLayers.isEmpty {
            DispatchQueue.main.asyncAfter(deadline: .now() + 4) { [weak self] in
                MainActor.assumeIsolated { if self?.drawing == false { self?.clearStrokes(animated: true) } }
            }
        }
        return result
    }

    private func clearStrokes(animated: Bool) {
        let ls = strokeLayers
        strokes = []; strokeLayers = []
        for l in ls {
            if animated {
                let a = CABasicAnimation(keyPath: "opacity"); a.toValue = 0; a.duration = 0.4
                a.fillMode = .forwards; a.isRemovedOnCompletion = false
                l.add(a, forKey: "o")
                DispatchQueue.main.asyncAfter(deadline: .now() + 0.45) { l.removeFromSuperlayer() }
            } else { l.removeFromSuperlayer() }
        }
    }
}
