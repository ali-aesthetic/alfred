import SwiftUI
import AppKit

/// Glass panel dropping under the pill for long / table replies. Esc or click-away closes.
@MainActor
final class PopOut {
    static let shared = PopOut()
    private var panel: PopPanel?
    private var monitor: Any?

    func show(_ markdown: String) {
        close()
        guard let screen = NSScreen.main ?? NSScreen.screens.first else { return }
        let lines = markdown.split(separator: "\n", omittingEmptySubsequences: false)
        let est = lines.reduce(0) { $0 + max(1, Int(ceil(Double($1.count) / 64))) }
        let h = min(460, CGFloat(est) * 21 + 56)
        let w: CGFloat = 540
        let f = screen.frame
        let p = PopPanel(contentRect: NSRect(x: f.midX - w / 2, y: f.maxY - 56 - h, width: w, height: h))
        p.onClose = { [weak self] in self?.close() }
        let host = NSHostingView(rootView: PopOutView(markdown: markdown) { [weak self] in self?.close() })
        host.frame = NSRect(x: 0, y: 0, width: w, height: h)
        p.contentView = host
        p.alphaValue = 0
        p.orderFrontRegardless(); p.makeKey()
        NSAnimationContext.runAnimationGroup { c in c.duration = 0.2; p.animator().alphaValue = 1 }
        panel = p
        monitor = NSEvent.addGlobalMonitorForEvents(matching: [.leftMouseDown, .rightMouseDown]) { [weak self] _ in
            MainActor.assumeIsolated {
                guard let p = self?.panel else { return }
                if !p.frame.contains(NSEvent.mouseLocation) { self?.close() }
            }
        }
    }

    func close() {
        if let m = monitor { NSEvent.removeMonitor(m); monitor = nil }
        guard let p = panel else { return }
        panel = nil
        NSAnimationContext.runAnimationGroup({ c in c.duration = 0.15; p.animator().alphaValue = 0 },
                                             completionHandler: { p.orderOut(nil) })
    }
}

final class PopPanel: NSPanel {
    var onClose: (() -> Void)?
    init(contentRect: NSRect) {
        super.init(contentRect: contentRect, styleMask: [.borderless, .nonactivatingPanel], backing: .buffered, defer: false)
        isOpaque = false; backgroundColor = .clear; hasShadow = false
        isFloatingPanel = true
        level = NSWindow.Level(rawValue: NSWindow.Level.statusBar.rawValue + 1)
        collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary]
        hidesOnDeactivate = false
    }
    override var canBecomeKey: Bool { true }
    override func constrainFrameRect(_ r: NSRect, to s: NSScreen?) -> NSRect { r }
    override func cancelOperation(_ sender: Any?) { onClose?() }
    override func keyDown(with e: NSEvent) { if e.keyCode == 53 { onClose?() } else { super.keyDown(with: e) } }
    override func resignKey() { super.resignKey(); onClose?() }
}

private enum MDBlock: Identifiable {
    case heading(String, Int), para(String), bullet(String), table([[String]]), rule
    var id: UUID { UUID() }
}

private func parseMarkdown(_ s: String) -> [MDBlock] {
    var out: [MDBlock] = []
    var table: [[String]] = []
    func flush() { if !table.isEmpty { out.append(.table(table)); table = [] } }
    for raw in s.components(separatedBy: "\n") {
        let l = raw.trimmingCharacters(in: .whitespaces)
        if l.hasPrefix("|") {
            let cells = l.split(separator: "|", omittingEmptySubsequences: false).dropFirst().dropLast()
                .map { $0.trimmingCharacters(in: .whitespaces) }
            if cells.allSatisfy({ $0.allSatisfy { "-: ".contains($0) } && !$0.isEmpty }) { continue }
            table.append(cells); continue
        }
        flush()
        if l.isEmpty { continue }
        if l.hasPrefix("### ") { out.append(.heading(String(l.dropFirst(4)), 3)) }
        else if l.hasPrefix("## ") { out.append(.heading(String(l.dropFirst(3)), 2)) }
        else if l.hasPrefix("# ") { out.append(.heading(String(l.dropFirst(2)), 1)) }
        else if l.hasPrefix("- ") || l.hasPrefix("* ") { out.append(.bullet(String(l.dropFirst(2)))) }
        else if l == "---" { out.append(.rule) }
        else { out.append(.para(l)) }
    }
    flush()
    return out
}

private func md(_ s: String) -> AttributedString {
    (try? AttributedString(markdown: s, options: .init(interpretedSyntax: .inlineOnlyPreservingWhitespace))) ?? AttributedString(s)
}

struct PopOutView: View {
    let markdown: String
    var close: () -> Void
    var body: some View {
        let blocks = parseMarkdown(markdown)
        ScrollView {
            VStack(alignment: .leading, spacing: 9) {
                ForEach(Array(blocks.enumerated()), id: \.offset) { _, b in
                    switch b {
                    case .heading(let t, let lvl): Text(md(t)).font(JTheme.title(lvl == 1 ? 20 : lvl == 2 ? 16 : 14))
                    case .para(let t): Text(md(t)).font(JTheme.text(13.5)).fixedSize(horizontal: false, vertical: true)
                    case .bullet(let t):
                        HStack(alignment: .firstTextBaseline, spacing: 7) {
                            Text("•").foregroundStyle(JTheme.accent)
                            Text(md(t)).font(JTheme.text(13.5)).fixedSize(horizontal: false, vertical: true)
                        }
                    case .rule: Divider()
                    case .table(let rows): tableView(rows)
                    }
                }
            }
            .foregroundStyle(JTheme.label)
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.horizontal, 20).padding(.vertical, 16)
        }
        .background(GlassBackground(radius: JTheme.windowRadius, material: .popover))
        .overlay(alignment: .topTrailing) {
            Button(action: close) {
                Image(systemName: "xmark").font(.system(size: 9, weight: .bold)).foregroundStyle(JTheme.secondary)
                    .frame(width: 20, height: 20).background(Circle().fill(Color.gray.opacity(0.18)))
            }.buttonStyle(.plain).padding(10)
        }
    }

    private func tableView(_ rows: [[String]]) -> some View {
        Grid(alignment: .leading, horizontalSpacing: 18, verticalSpacing: 6) {
            ForEach(Array(rows.enumerated()), id: \.offset) { i, r in
                GridRow {
                    ForEach(Array(r.enumerated()), id: \.offset) { _, c in
                        Text(md(c)).font(JTheme.text(13, i == 0 ? .semibold : .regular))
                            .foregroundStyle(i == 0 ? JTheme.secondary : JTheme.label)
                    }
                }
                if i == 0 { Divider().gridCellUnsizedAxes(.horizontal) }
            }
        }
        .padding(10)
        .background(RoundedRectangle(cornerRadius: JTheme.controlRadius).fill(Color.gray.opacity(0.1)))
    }
}
