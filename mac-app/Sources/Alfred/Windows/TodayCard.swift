import SwiftUI
import Combine

// MARK: - Data (brain → app via data/ui/today.json, see CONTRACT.md "Today card")

struct TodayEvent: Identifiable, Equatable {
    let id = UUID()
    var title: String
    var start: Date
    var end: Date?
    var allDay: Bool
}

struct TodayItem: Identifiable, Equatable {
    var id: String
    var kind: String          // done · approval · away
    var text: String
    var when: Date?
    var whenText: String?
}

@MainActor
final class TodayModel: ObservableObject {
    static let shared = TodayModel()
    @Published var events: [TodayEvent] = []
    @Published var done: [TodayItem] = []
    @Published var waiting: [TodayItem] = []
    /// False until the brain has written today.json at least once.
    @Published var hasFeed = false

    private var localDone: [TodayItem] = []
    private var localDay = Calendar.current.startOfDay(for: Date())
    private var bag = Set<AnyCancellable>()
    private var timer: Timer?

    private var path: String { Bridge.uiDir + "/today.json" }

    private init() {
        load()
        // Fallback for "what Alfred did": steps finished while the app is open.
        Bridge.shared.events.receive(on: RunLoop.main).sink { [weak self] e in
            MainActor.assumeIsolated { self?.onEvent(e) }
        }.store(in: &bag)
        timer = Timer.scheduledTimer(withTimeInterval: 20, repeats: true) { [weak self] _ in
            MainActor.assumeIsolated { self?.load() }
        }
    }

    private func onEvent(_ e: [String: Any]) {
        guard (e["type"] as? String) == "step", (e["done"] as? Bool) == true,
              let text = e["text"] as? String, !text.isEmpty else { return }
        let day = Calendar.current.startOfDay(for: Date())
        if day != localDay { localDay = day; localDone = [] }
        let t = Date(timeIntervalSince1970: (e["t"] as? Double) ?? Date().timeIntervalSince1970)
        if localDone.contains(where: { $0.text == text }) { return }
        localDone.append(TodayItem(id: UUID().uuidString, kind: "done", text: text, when: t, whenText: nil))
        if !hasFeedDone { done = Array(localDone.reversed()) }
    }

    private var hasFeedDone = false

    private func loadDemo() {
        let n = Date()
        hasFeed = true
        events = [TodayEvent(title: "Lecture: Databases", start: n.addingTimeInterval(4800), end: n.addingTimeInterval(8400), allDay: false),
                  TodayEvent(title: "Call with Dad", start: n.addingTimeInterval(14400), end: nil, allDay: false),
                  TodayEvent(title: "Gym", start: n.addingTimeInterval(21600), end: nil, allDay: false),
                  TodayEvent(title: "Standup", start: n.addingTimeInterval(-7200), end: n.addingTimeInterval(-6000), allDay: false)].sorted { $0.start < $1.start }
        done = [TodayItem(id: "1", kind: "done", text: "Opened your edit project", when: n.addingTimeInterval(-1200), whenText: nil),
                TodayItem(id: "2", kind: "done", text: "Morning briefing sent", when: n.addingTimeInterval(-9000), whenText: nil)]
        waiting = [TodayItem(id: "a", kind: "approval", text: "Send reel to Telegram", when: nil, whenText: nil),
                   TodayItem(id: "b", kind: "away", text: "Disk space check", when: nil, whenText: "Mon 10:00")]
    }

    func load() {
        if ProcessInfo.processInfo.environment["ALFRED_TODAY_DEMO"] != nil { loadDemo(); return }   // preview hook for screenshots
        let b = Bridge.shared
        var feedWaiting = false
        hasFeedDone = false
        if let o = b.readJSON(path) as? [String: Any] {
            hasFeed = true
            events = ((o["events"] as? [[String: Any]]) ?? []).compactMap { d in
                guard let t = d["title"] as? String, let s = d["start"] as? Double else { return nil }
                return TodayEvent(title: t, start: Date(timeIntervalSince1970: s),
                                  end: (d["end"] as? Double).map { Date(timeIntervalSince1970: $0) },
                                  allDay: (d["all_day"] as? Bool) ?? false)
            }.sorted { $0.start < $1.start }
            if let arr = o["done"] as? [[String: Any]] {
                hasFeedDone = true
                done = arr.compactMap { d in
                    guard let t = d["text"] as? String else { return nil }
                    return TodayItem(id: "\(d["id"] ?? UUID().uuidString)", kind: "done", text: t,
                                     when: (d["t"] as? Double).map { Date(timeIntervalSince1970: $0) }, whenText: nil)
                }
            }
            if let arr = o["waiting"] as? [[String: Any]] {
                feedWaiting = true
                waiting = arr.compactMap { d in
                    guard let t = d["text"] as? String else { return nil }
                    let w = d["when"]
                    return TodayItem(id: "\(d["id"] ?? UUID().uuidString)", kind: (d["kind"] as? String) ?? "away", text: t,
                                     when: (w as? Double).map { Date(timeIntervalSince1970: $0) }, whenText: w as? String)
                }
            }
        }
        if !hasFeedDone { done = Array(localDone.reversed()) }
        if !feedWaiting {
            // Fallback: the brain's own scheduled (away) tasks.
            let arr = (b.readJSON(Bridge.root + "/data/schedule.json") as? [[String: Any]]) ?? []
            waiting = arr.filter { ($0["enabled"] as? Bool) ?? true }.prefix(5).map {
                TodayItem(id: "\($0["id"] ?? UUID().uuidString)", kind: "away", text: ($0["task"] as? String) ?? "Scheduled task",
                          when: nil, whenText: $0["when"] as? String)
            }
        }
    }
}

// MARK: - View (look 1B: day strip + two tiles)

struct TodayCard: View {
    @ObservedObject private var m = TodayModel.shared
    @State private var open: String?
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    private var needsOK: Int { m.waiting.filter { $0.kind == "approval" }.count }
    private var nextEvent: TodayEvent? { m.events.first { !$0.allDay && ($0.end ?? $0.start) > Date() } }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("Today").font(.headline).foregroundStyle(.secondary)
            VStack(alignment: .leading, spacing: 6) {
                DayStrip(events: m.events.filter { !$0.allDay }, next: nextEvent?.id)
                nextLine
            }
            .frame(maxWidth: .infinity, alignment: .leading).jCard(radius: 14, padding: 14)
            HStack(spacing: 10) {
                tile(id: "done", title: "Did today", count: m.done.count, tint: WTheme.done,
                     sub: m.done.first?.text ?? "Nothing yet")
                tile(id: "wait", title: "Waiting on", count: m.waiting.count, tint: needsOK > 0 ? WTheme.warn : WTheme.accent,
                     sub: needsOK > 0 ? "\(needsOK) \(needsOK == 1 ? "needs" : "need") your OK" : (m.waiting.isEmpty ? "All clear" : "Away tasks"))
            }
            if let o = open { list(o).transition(.opacity.combined(with: .move(edge: .top))) }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .onAppear { m.load() }
    }

    @ViewBuilder private var nextLine: some View {
        if let n = nextEvent {
            (Text("Next: ").foregroundStyle(.secondary) + Text(n.title).fontWeight(.semibold) + Text("  \(Self.until(n.start))").foregroundStyle(.secondary))
                .font(.callout).lineLimit(1)
        } else {
            Text(m.hasFeed ? "Nothing else on your calendar today." : "No calendar yet. Ask me: “What's on today?”")
                .font(.callout).foregroundStyle(.secondary)
        }
    }

    static func until(_ d: Date) -> String {
        let mins = Int(d.timeIntervalSinceNow / 60)
        if mins <= 0 { return "now" }
        if mins < 60 { return "in \(mins) min" }
        let h = mins / 60, r = mins % 60
        return r == 0 ? "in \(h) h" : "in \(h) h \(r) min"
    }

    private func tile(id: String, title: String, count: Int, tint: Color, sub: String) -> some View {
        let on = open == id
        return Button {
            withAnimation(reduceMotion ? nil : .easeOut(duration: 0.2)) { open = on ? nil : id }
        } label: {
            VStack(alignment: .leading, spacing: 3) {
                HStack {
                    Text(title.uppercased()).font(.system(size: 10.5, weight: .semibold)).tracking(0.7).foregroundStyle(.secondary)
                    Spacer()
                    Image(systemName: "chevron.down").font(.system(size: 9, weight: .bold)).foregroundStyle(.tertiary)
                        .rotationEffect(.degrees(on ? 180 : 0))
                }
                Text("\(count)").font(.system(size: 28, weight: .semibold, design: .rounded)).foregroundStyle(count == 0 ? Color.secondary : tint)
                Text(sub).font(.caption).foregroundStyle(.secondary).lineLimit(1)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .jCard(radius: 14, padding: 12)
            .overlay(RoundedRectangle(cornerRadius: 14, style: .continuous).strokeBorder(on ? tint.opacity(0.6) : .clear, lineWidth: 1.2))
            .contentShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
        }
        .buttonStyle(.plain)
        .accessibilityLabel("\(title): \(count)")
        .accessibilityHint(on ? "Hides the list" : "Shows the list")
    }

    @ViewBuilder private func list(_ id: String) -> some View {
        let items = id == "done" ? Array(m.done.prefix(8)) : m.waiting
        VStack(spacing: 0) {
            if items.isEmpty {
                Text(id == "done" ? "Nothing yet today." : "Nothing is waiting on you.")
                    .font(.callout).foregroundStyle(.secondary).frame(maxWidth: .infinity, alignment: .leading).padding(12)
            }
            ForEach(Array(items.enumerated()), id: \.element.id) { i, it in
                HStack(spacing: 10) {
                    Circle().fill(it.kind == "approval" ? WTheme.warn : (it.kind == "done" ? WTheme.done : WTheme.accent)).frame(width: 7, height: 7)
                    Text(it.text).font(.callout).lineLimit(1)
                    Spacer(minLength: 8)
                    if it.kind == "approval" {
                        Button("Approve") { Bridge.shared.send("approval", ["id": it.id, "ok": true]) }.controlSize(.small)
                        Button("Skip") { Bridge.shared.send("approval", ["id": it.id, "ok": false]) }.controlSize(.small)
                    } else if let d = it.when {
                        Text(d, style: .time).font(.caption).foregroundStyle(.secondary)
                    } else if let w = it.whenText {
                        Text(w).font(.caption).foregroundStyle(.secondary).lineLimit(1)
                    }
                }
                .padding(.vertical, 8).padding(.horizontal, 12)
                if i < items.count - 1 { Divider().padding(.leading, 28) }
            }
        }
        .background(RoundedRectangle(cornerRadius: 14, style: .continuous).fill(Color.primary.opacity(0.045)))
        .overlay(RoundedRectangle(cornerRadius: 14, style: .continuous).strokeBorder(Color.primary.opacity(0.09), lineWidth: 1))
    }
}

/// Thin timeline of the day with a "now" marker and one dot per event.
struct DayStrip: View {
    let events: [TodayEvent]
    let next: UUID?
    @State private var now = Date()
    private let tick = Timer.publish(every: 30, on: .main, in: .common).autoconnect()

    private var range: (Date, Date) {
        let cal = Calendar.current
        let day = cal.startOfDay(for: now)
        var lo = 6.0, hi = 24.0
        for e in events {
            lo = min(lo, Double(cal.component(.hour, from: e.start)))
            if let en = e.end, cal.isDate(en, inSameDayAs: now) { hi = max(hi, ceil(Double(cal.component(.hour, from: en)) + 1)) }
        }
        return (day.addingTimeInterval(lo * 3600), day.addingTimeInterval(min(hi, 24) * 3600))
    }
    private func x(_ d: Date, _ r: (Date, Date)) -> CGFloat {
        CGFloat(max(0, min(1, d.timeIntervalSince(r.0) / r.1.timeIntervalSince(r.0))))
    }
    private static let f: DateFormatter = { let f = DateFormatter(); f.dateFormat = "HH:mm"; return f }()

    var body: some View {
        let r = range
        GeometryReader { g in
            let w = g.size.width
            ZStack(alignment: .topLeading) {
                Capsule().fill(Color.primary.opacity(0.1)).frame(height: 4).offset(y: 17)
                Capsule().fill(WTheme.accent.opacity(0.35)).frame(width: max(4, w * x(now, r)), height: 4).offset(y: 17)
                ForEach(Array(events.enumerated()), id: \.element.id) { i, e in
                    let px = w * x(e.start, r)
                    let past = (e.end ?? e.start) < now
                    let isNext = e.id == next
                    Circle().fill(isNext ? WTheme.accent : (past ? Color.primary.opacity(0.25) : Color(nsColor: .controlBackgroundColor)))
                        .overlay(Circle().strokeBorder(isNext ? WTheme.accent : Color.primary.opacity(past ? 0.2 : 0.5), lineWidth: 2))
                        .frame(width: 13, height: 13).position(x: px, y: 19)
                        .help("\(Self.f.string(from: e.start))  \(e.title)")
                    if showLabel(i, w, r) {
                        Text(Self.f.string(from: e.start)).font(.system(size: 10)).monospacedDigit()
                            .foregroundStyle(isNext ? WTheme.accent : .secondary).position(x: min(max(px, 16), w - 16), y: 38)
                    }
                }
                // now marker
                RoundedRectangle(cornerRadius: 1).fill(WTheme.accent).frame(width: 2, height: 24).position(x: w * x(now, r), y: 19)
            }
        }
        .frame(height: events.isEmpty ? 30 : 46)
        .onReceive(tick) { now = $0 }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(events.isEmpty ? "No events today" : "\(events.count) events today")
    }

    /// Hide a time label that would sit on top of the previous one.
    private func showLabel(_ i: Int, _ w: CGFloat, _ r: (Date, Date)) -> Bool {
        guard i > 0 else { return true }
        return (x(events[i].start, r) - x(events[i - 1].start, r)) * w > 38
    }
}
