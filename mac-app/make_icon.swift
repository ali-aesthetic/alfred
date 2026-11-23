import AppKit
// "The pill is the logo": a dark squircle holding one horizontal glass capsule with a blue status dot and a short bar.
// usage:
//   swift make_icon.swift out.iconset            -> app icon (variant 1) as an iconset
//   swift make_icon.swift --report out-dir [N]   -> icon-1/2/3.png (1024) + icon-strip.png (legibility at 32 / 16 px)
//   swift make_icon.swift --png out.png px [N]   -> one PNG, variant N (default 1)

func c(_ hex: UInt32, _ a: CGFloat = 1) -> NSColor {
    NSColor(srgbRed: CGFloat((hex >> 16) & 255) / 255, green: CGFloat((hex >> 8) & 255) / 255, blue: CGFloat(hex & 255) / 255, alpha: a)
}

struct Look {
    var bgTop: NSColor, bgBottom: NSColor
    var rimTop: NSColor, rimBottom: NSColor
    var innerLight: NSColor?            // soft light from the top edge, inside the squircle
    var brushed = false
    var glassTop: NSColor, glassBottom: NSColor, well: NSColor
    var edgeBright: NSColor, edgeDim: NSColor
    var dotTop: NSColor, dotBottom: NSColor
    var bar: NSColor
}

func look(_ v: Int) -> Look {
    switch v {
    case 2: // deep navy glass
        return Look(bgTop: c(0x16306A), bgBottom: c(0x050B22), rimTop: c(0xBFD8FF, 0.30), rimBottom: c(0x000000, 0.35),
                    innerLight: c(0x8DB8FF, 0.26),
                    glassTop: c(0xFFFFFF, 0.20), glassBottom: c(0xFFFFFF, 0.05), well: c(0x020718, 0.55),
                    edgeBright: c(0xD6E6FF, 0.65), edgeDim: c(0x9CBFFF, 0.20),
                    dotTop: c(0x7CC0FF), dotBottom: c(0x2F86FF), bar: c(0xE4EEFF, 0.88))
    case 3: // silver aluminium
        return Look(bgTop: c(0xFAFAFB), bgBottom: c(0xBCC0C7), rimTop: c(0xFFFFFF, 0.95), rimBottom: c(0x000000, 0.16),
                    innerLight: nil, brushed: true,
                    glassTop: c(0x3A3C42), glassBottom: c(0x17181B), well: c(0x000000, 0.25),
                    edgeBright: c(0xFFFFFF, 0.55), edgeDim: c(0xFFFFFF, 0.14),
                    dotTop: c(0x58A6FF), dotBottom: c(0x0A7BFF), bar: c(0xFFFFFF, 0.90))
    default: // graphite
        return Look(bgTop: c(0x45474D), bgBottom: c(0x141518), rimTop: c(0xFFFFFF, 0.22), rimBottom: c(0x000000, 0.45),
                    innerLight: c(0xFFFFFF, 0.06),
                    glassTop: c(0xFFFFFF, 0.17), glassBottom: c(0xFFFFFF, 0.05), well: c(0x000000, 0.50),
                    edgeBright: c(0xFFFFFF, 0.50), edgeDim: c(0xFFFFFF, 0.14),
                    dotTop: c(0x5BA8FF), dotBottom: c(0x0A7BFF), bar: c(0xFFFFFF, 0.86))
    }
}

/// Fills the band between two outlines with a vertical gradient.
func ring(outer: NSBezierPath, inner: NSBezierPath, colors: [NSColor], locations: [CGFloat]) {
    NSGraphicsContext.saveGraphicsState()
    let band = NSBezierPath()
    band.append(outer); band.append(inner); band.windingRule = .evenOdd
    band.addClip()
    NSGradient(colors: colors, atLocations: locations, colorSpace: .sRGB)!.draw(in: outer.bounds, angle: -90)
    NSGraphicsContext.restoreGraphicsState()
}

func render(_ px: Int, variant: Int) -> NSBitmapImageRep {
    let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: px, pixelsHigh: px, bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false, colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
    NSGraphicsContext.saveGraphicsState()
    let gc = NSGraphicsContext(bitmapImageRep: rep)!
    NSGraphicsContext.current = gc
    gc.imageInterpolation = .high
    let L = look(variant)
    let s = CGFloat(px)
    let small = px <= 48

    // squircle (macOS icon grid: 824/1024)
    let side = s * 0.805
    let q = NSRect(x: (s - side) / 2, y: (s - side) / 2, width: side, height: side)
    let sq = NSBezierPath(roundedRect: q, xRadius: side * 0.225, yRadius: side * 0.225)

    // soft drop shadow
    if px >= 64 {
        NSGraphicsContext.saveGraphicsState()
        let sh = NSShadow(); sh.shadowColor = NSColor.black.withAlphaComponent(0.38)
        sh.shadowOffset = NSSize(width: 0, height: -s * 0.012); sh.shadowBlurRadius = s * 0.022; sh.set()
        NSColor.black.setFill(); sq.fill()
        NSGraphicsContext.restoreGraphicsState()
    }
    // body
    NSGradient(starting: L.bgTop, ending: L.bgBottom)!.draw(in: sq, angle: -90)
    NSGraphicsContext.saveGraphicsState()
    sq.addClip()
    if let light = L.innerLight {
        NSGradient(colors: [light, light.withAlphaComponent(0)])!.draw(fromCenter: NSPoint(x: q.midX, y: q.maxY + side * 0.05), radius: 0,
                                                                       toCenter: NSPoint(x: q.midX, y: q.maxY + side * 0.05), radius: side * 0.75, options: [])
    }
    if L.brushed && px >= 256 {
        var y = q.minY
        var seed: UInt64 = 7
        while y < q.maxY {
            seed = seed &* 6364136223846793005 &+ 1442695040888963407
            let a = CGFloat((seed >> 33) % 100) / 100
            NSColor(white: a > 0.5 ? 1 : 0, alpha: 0.025 + 0.03 * a).setFill()
            NSRect(x: q.minX, y: y, width: side, height: max(1, s * 0.0012)).fill()
            y += s * 0.0035
        }
    }
    NSGraphicsContext.restoreGraphicsState()
    // rim: bright at the top edge fading out, dark at the bottom edge (one smooth ring, no seam)
    let rimW = max(1, s * 0.006)
    ring(outer: sq, inner: NSBezierPath(roundedRect: q.insetBy(dx: rimW, dy: rimW), xRadius: side * 0.225 - rimW, yRadius: side * 0.225 - rimW),
         colors: [L.rimTop, L.rimTop.withAlphaComponent(0), L.rimBottom.withAlphaComponent(0), L.rimBottom], locations: [0, 0.3, 0.75, 1])

    // capsule (a little bigger at tiny sizes so it survives 16 px)
    let cw = side * (small ? 0.74 : 0.62)
    let ch = side * (small ? 0.34 : 0.255)
    let cap = NSRect(x: q.midX - cw / 2, y: q.midY - ch / 2, width: cw, height: ch)
    let capPath = NSBezierPath(roundedRect: cap, xRadius: ch / 2, yRadius: ch / 2)
    // depth well, glass body
    L.well.setFill(); capPath.fill()
    NSGradient(starting: L.glassTop, ending: L.glassBottom)!.draw(in: capPath, angle: -90)
    // gloss: soft light fading down from the top inside edge
    if !small {
        NSGraphicsContext.saveGraphicsState()
        capPath.addClip()
        NSGradient(colors: [NSColor.white.withAlphaComponent(variant == 3 ? 0.10 : 0.13), NSColor.white.withAlphaComponent(0)])!
            .draw(in: NSRect(x: cap.minX, y: cap.midY - ch * 0.05, width: cw, height: ch * 0.55), angle: -90)
        NSGraphicsContext.restoreGraphicsState()
    }
    // edge: bright on top, dim below, one smooth ring
    let ew = max(small ? 0.8 : 1, ch * 0.035)
    ring(outer: capPath, inner: NSBezierPath(roundedRect: cap.insetBy(dx: ew, dy: ew), xRadius: ch / 2 - ew, yRadius: ch / 2 - ew),
         colors: [L.edgeBright, L.edgeDim, L.edgeDim], locations: [0, 0.55, 1])

    // status dot (flat, no halo) + short bar, centred as a pair
    let dd = ch * (small ? 0.46 : 0.42)
    let gap = ch * 0.24
    let bw = ch * (small ? 1.05 : 1.30)
    let bh = max(ch * 0.15, s * 0.0045)
    let pair = dd + gap + bw
    let x0 = cap.midX - pair / 2
    let dot = NSBezierPath(ovalIn: NSRect(x: x0, y: cap.midY - dd / 2, width: dd, height: dd))
    NSGradient(starting: L.dotTop, ending: L.dotBottom)!.draw(in: dot, angle: -90)
    L.bar.setFill()
    NSBezierPath(roundedRect: NSRect(x: x0 + dd + gap, y: cap.midY - bh / 2, width: bw, height: bh), xRadius: bh / 2, yRadius: bh / 2).fill()

    NSGraphicsContext.restoreGraphicsState()
    return rep
}

func png(_ rep: NSBitmapImageRep) -> Data { rep.representation(using: .png, properties: [:])! }
func write(_ rep: NSBitmapImageRep, _ path: String) { try! png(rep).write(to: URL(fileURLWithPath: path)) }

// MARK: strip

func strip(to path: String) {
    let cellW = 372, rowH = 168, pad = 24
    let W = cellW * 3 + pad, H = rowH * 2 + pad
    let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: W, pixelsHigh: H, bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false, colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
    NSGraphicsContext.saveGraphicsState()
    let gc = NSGraphicsContext(bitmapImageRep: rep)!
    NSGraphicsContext.current = gc
    let bgs: [NSColor] = [c(0xECECEE), c(0x1E1E20)]
    for (r, bg) in bgs.enumerated() {
        bg.setFill()
        NSRect(x: 0, y: CGFloat(H - (r + 1) * rowH - (r == 0 ? 0 : 0)) - (r == 0 ? CGFloat(pad) / 2 : CGFloat(pad) / 2), width: CGFloat(W), height: CGFloat(rowH)).fill()
    }
    func draw(_ rep: NSBitmapImageRep, at p: NSPoint, size: CGFloat, crisp: Bool = false) {
        gc.imageInterpolation = crisp ? .none : .high
        rep.draw(in: NSRect(x: p.x, y: p.y, width: size, height: size))
    }
    for r in 0..<2 {
        let rowY = CGFloat(H) - CGFloat(r + 1) * CGFloat(rowH) - CGFloat(pad) / 2
        let ink = r == 0 ? NSColor(white: 0.25, alpha: 1) : NSColor(white: 0.8, alpha: 1)
        for v in 1...3 {
            let x = CGFloat(pad / 2 + (v - 1) * cellW)
            let base = rowY + (CGFloat(rowH) - 128) / 2
            draw(render(1024, variant: v), at: NSPoint(x: x, y: base), size: 128)
            draw(render(32, variant: v), at: NSPoint(x: x + 148, y: base + 48), size: 32, crisp: true)
            draw(render(16, variant: v), at: NSPoint(x: x + 196, y: base + 56), size: 16, crisp: true)
            draw(render(16, variant: v), at: NSPoint(x: x + 232, y: base + 32), size: 64, crisp: true)   // 16 px at 4x, to inspect
            let label = "\(v)" as NSString
            label.draw(at: NSPoint(x: x + 4, y: base - 20), withAttributes: [.font: NSFont.systemFont(ofSize: 12, weight: .semibold), .foregroundColor: ink])
        }
        let cap = "128  |  32 px  16 px  |  16 px x4" as NSString
        cap.draw(at: NSPoint(x: CGFloat(pad / 2) + 4, y: rowY + CGFloat(rowH) - 18), withAttributes: [.font: NSFont.systemFont(ofSize: 10), .foregroundColor: ink.withAlphaComponent(0.6)])
    }
    NSGraphicsContext.restoreGraphicsState()
    write(rep, path)
}

// MARK: main

let args = CommandLine.arguments
if args.count >= 3 && args[1] == "--report" {
    let dir = args[2]
    try? FileManager.default.createDirectory(atPath: dir, withIntermediateDirectories: true)
    for v in 1...3 { write(render(1024, variant: v), "\(dir)/icon-\(v).png") }
    strip(to: "\(dir)/icon-strip.png")
} else if args.count >= 4 && args[1] == "--png" {
    write(render(Int(args[3]) ?? 1024, variant: args.count > 4 ? Int(args[4]) ?? 1 : 1), args[2])
} else {
    let out = args[1]
    try? FileManager.default.createDirectory(atPath: out, withIntermediateDirectories: true)
    for (n, px) in [("16x16", 16), ("16x16@2x", 32), ("32x32", 32), ("32x32@2x", 64), ("128x128", 128), ("128x128@2x", 256),
                    ("256x256", 256), ("256x256@2x", 512), ("512x512", 512), ("512x512@2x", 1024)] {
        write(render(px, variant: 1), "\(out)/icon_\(n).png")
    }
}
