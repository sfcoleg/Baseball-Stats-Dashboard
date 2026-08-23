// DiamondWidgets.swift — the desktop widgets. Three of them, all driven
// by the same timeline: the nightly feed (cached on disk, shared with the
// app through the App Group) plus a live-scores call on each refresh.
// WidgetKit decides the actual refresh cadence (roughly every 15 minutes
// at best; more often while a game is live is not something we control).
import SwiftUI
import WidgetKit

// MARK: - Timeline

struct Entry: TimelineEntry {
    let date: Date
    let sport: Sport
    let favorite: String
    let feed: Feed?
    let live: [LiveGame]
}

struct Provider: TimelineProvider {
    func placeholder(in context: Context) -> Entry {
        Entry(date: .now, sport: .nhl, favorite: "EDM", feed: FeedClient.cached(), live: [])
    }

    func getSnapshot(in context: Context, completion: @escaping (Entry) -> Void) {
        completion(Entry(date: .now, sport: AppConfig.sport, favorite: AppConfig.favoriteTeam, feed: FeedClient.cached(), live: []))
    }

    func getTimeline(in context: Context, completion: @escaping (Timeline<Entry>) -> Void) {
        Task {
            let sport = AppConfig.sport
            let feed = await FeedClient.load()
            let live = await LiveScores.fetch(sport)
            let entry = Entry(date: .now, sport: sport, favorite: AppConfig.favoriteTeam, feed: feed, live: live)
            // Ask for a refresh sooner while something's live; otherwise every 30 min.
            let next = Calendar.current.date(byAdding: .minute, value: live.contains(where: \.isLive) ? 10 : 30, to: .now)!
            completion(Timeline(entries: [entry], policy: .after(next)))
        }
    }
}

// MARK: - Shared bits

struct Badge: View {
    let text: String
    var body: some View {
        Text(text).font(.system(.caption2, design: .rounded).weight(.bold))
            .padding(.horizontal, 5).padding(.vertical, 2)
            .background(.white.opacity(0.12), in: RoundedRectangle(cornerRadius: 5))
    }
}

struct Header: View {
    let title: String
    let sport: Sport
    var body: some View {
        HStack {
            Text(title).font(.caption.bold()).foregroundStyle(.secondary)
            Spacer()
            Text(sport.label).font(.caption2.bold()).foregroundStyle(.secondary)
        }
    }
}

extension View {
    func widgetBackground() -> some View {
        containerBackground(for: .widget) {
            LinearGradient(colors: [Color(red: 0.10, green: 0.13, blue: 0.22), Color(red: 0.07, green: 0.09, blue: 0.16)],
                           startPoint: .top, endPoint: .bottom)
        }
    }
}

// MARK: - Widget 1: Today's Games

struct ScoresWidget: Widget {
    var body: some WidgetConfiguration {
        StaticConfiguration(kind: "DiamondScores", provider: Provider()) { entry in
            ScoresWidgetView(entry: entry).widgetBackground()
        }
        .configurationDisplayName("Today's Games")
        .description("Live scores for the current sport; your favorite team first.")
        .supportedFamilies([.systemSmall, .systemMedium, .systemLarge])
    }
}

struct ScoresWidgetView: View {
    @Environment(\.widgetFamily) var family
    let entry: Entry

    var games: [LiveGame] {
        entry.live.sorted {
            let f0 = $0.away == entry.favorite || $0.home == entry.favorite
            let f1 = $1.away == entry.favorite || $1.home == entry.favorite
            if f0 != f1 { return f0 }
            let r0 = $0.isLive ? 0 : ($0.isFinal ? 2 : 1), r1 = $1.isLive ? 0 : ($1.isFinal ? 2 : 1)
            if r0 != r1 { return r0 < r1 }
            return ($0.start ?? .distantFuture) < ($1.start ?? .distantFuture)
        }
    }

    var body: some View {
        let limit = family == .systemSmall ? 1 : (family == .systemMedium ? 3 : 8)
        VStack(alignment: .leading, spacing: 6) {
            Header(title: "Today", sport: entry.sport)
            if games.isEmpty {
                Spacer()
                Text("No games today").font(.callout).foregroundStyle(.secondary)
                Spacer()
            } else {
                ForEach(games.prefix(limit)) { g in
                    if family == .systemSmall { SmallGame(game: g, favorite: entry.favorite) }
                    else { GameLine(game: g, favorite: entry.favorite) }
                }
                Spacer(minLength: 0)
            }
        }
        .foregroundStyle(.white)
    }
}

struct SmallGame: View {
    let game: LiveGame; let favorite: String
    var body: some View {
        VStack(spacing: 6) {
            HStack { Badge(text: game.away); Spacer(); Text(game.awayScore.map(String.init) ?? "–").font(.title2.weight(.heavy)).monospacedDigit() }
            HStack { Badge(text: game.home); Spacer(); Text(game.homeScore.map(String.init) ?? "–").font(.title2.weight(.heavy)).monospacedDigit() }
            HStack {
                if game.isLive { Circle().fill(.red).frame(width: 6, height: 6) }
                Text(game.status).font(.caption2).foregroundStyle(.secondary).lineLimit(1)
                Spacer()
            }
        }
    }
}

struct GameLine: View {
    let game: LiveGame; let favorite: String
    var body: some View {
        HStack(spacing: 8) {
            if game.isLive { Circle().fill(.red).frame(width: 6, height: 6) } else { Circle().fill(.clear).frame(width: 6, height: 6) }
            Badge(text: game.away)
            Text(game.awayScore.map(String.init) ?? "").font(.callout.weight(.bold)).monospacedDigit().frame(width: 18, alignment: .trailing)
            Text("@").font(.caption2).foregroundStyle(.secondary)
            Badge(text: game.home)
            Text(game.homeScore.map(String.init) ?? "").font(.callout.weight(.bold)).monospacedDigit().frame(width: 18, alignment: .trailing)
            Spacer()
            Text(game.status).font(.caption2).foregroundStyle(.secondary).lineLimit(1)
        }
    }
}

// MARK: - Widget 2: Standings (favorite's division)

struct StandingsWidget: Widget {
    var body: some WidgetConfiguration {
        StaticConfiguration(kind: "DiamondStandings", provider: Provider()) { entry in
            StandingsWidgetView(entry: entry).widgetBackground()
        }
        .configurationDisplayName("Division Standings")
        .description("Your favorite team's division.")
        .supportedFamilies([.systemMedium, .systemLarge])
    }
}

struct StandingsWidgetView: View {
    let entry: Entry
    var rows: (String, [(String, String, String)]) {
        guard let feed = entry.feed else { return ("", []) }
        switch entry.sport {
        case .mlb:
            let div = feed.mlb.standings.first { $0.teamAbbr == entry.favorite }?.division ?? feed.mlb.standings.first?.division ?? ""
            return (div, feed.mlb.standings.filter { $0.division == div }.map { ($0.teamAbbr, "\($0.wins)-\($0.losses)", $0.gamesBack) })
        case .nhl:
            let div = feed.nhl.standings.first { $0.abbr == entry.favorite }?.division ?? feed.nhl.standings.first?.division ?? ""
            let t = feed.nhl.standings.filter { $0.division == div }.sorted { ($0.divRank ?? 99) < ($1.divRank ?? 99) }
            return (div, t.map { ($0.abbr, "\($0.w ?? 0)-\($0.l ?? 0)-\($0.otl ?? 0)", "\($0.pts ?? 0)") })
        }
    }
    var body: some View {
        let (title, list) = rows
        VStack(alignment: .leading, spacing: 4) {
            Header(title: title.isEmpty ? "Standings" : title, sport: entry.sport)
            ForEach(Array(list.enumerated()), id: \.offset) { _, r in
                HStack {
                    Badge(text: r.0)
                    if r.0 == entry.favorite { Image(systemName: "star.fill").font(.caption2).foregroundStyle(.yellow) }
                    Spacer()
                    Text(r.1).font(.caption).monospacedDigit()
                    Text(r.2).font(.caption).monospacedDigit().foregroundStyle(.secondary).frame(width: 34, alignment: .trailing)
                }
            }
            Spacer(minLength: 0)
        }
        .foregroundStyle(.white)
    }
}

// MARK: - Widget 3: Next Game (favorite team)

struct NextGameWidget: Widget {
    var body: some WidgetConfiguration {
        StaticConfiguration(kind: "DiamondNextGame", provider: Provider()) { entry in
            NextGameWidgetView(entry: entry).widgetBackground()
        }
        .configurationDisplayName("Next Game")
        .description("Your team's next game with our win probability.")
        .supportedFamilies([.systemSmall, .systemMedium])
    }
}

struct NextGameWidgetView: View {
    let entry: Entry
    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Header(title: "Next Game", sport: entry.sport)
            if entry.favorite.isEmpty {
                Spacer(); Text("Pick a favorite team in the app").font(.caption).foregroundStyle(.secondary); Spacer()
            } else if let feed = entry.feed {
                switch entry.sport {
                case .nhl:
                    if let g = feed.nhl.week.first(where: { !$0.isFinal && ($0.away == entry.favorite || $0.home == entry.favorite) }) {
                        let home = g.home == entry.favorite
                        let opp = home ? g.away : g.home
                        let p = g.pHome.map { home ? $0 : 1 - $0 }
                        Spacer()
                        HStack { Text(home ? "vs" : "@").foregroundStyle(.secondary); Badge(text: opp).font(.title3) }
                        Text(g.startDate.map { $0.formatted(date: .abbreviated, time: .shortened) } ?? g.date).font(.caption).foregroundStyle(.secondary)
                        if let p { Text("\(Int((p * 100).rounded()))% win").font(.title2.weight(.heavy)) }
                        Spacer()
                    } else {
                        Spacer(); Text("No upcoming game this week").font(.caption).foregroundStyle(.secondary); Spacer()
                    }
                case .mlb:
                    if let g = feed.mlb.today.first(where: { $0.awayAbbr == entry.favorite || $0.homeAbbr == entry.favorite }) {
                        let home = g.homeAbbr == entry.favorite
                        Spacer()
                        HStack { Text(home ? "vs" : "@").foregroundStyle(.secondary); Badge(text: home ? g.awayAbbr : g.homeAbbr).font(.title3) }
                        Text(g.startDate.map { $0.formatted(date: .omitted, time: .shortened) } ?? "").font(.caption).foregroundStyle(.secondary)
                        if let sp = home ? g.homePitcherName : g.awayPitcherName { Text("SP: \(sp)").font(.caption2).foregroundStyle(.secondary).lineLimit(1) }
                        Spacer()
                    } else {
                        Spacer(); Text("Off day").font(.caption).foregroundStyle(.secondary); Spacer()
                    }
                }
            } else {
                Spacer(); Text("Loading…").font(.caption).foregroundStyle(.secondary); Spacer()
            }
        }
        .foregroundStyle(.white)
    }
}

// MARK: - Bundle

@main
struct DiamondWidgetBundle: WidgetBundle {
    var body: some Widget {
        ScoresWidget()
        StandingsWidget()
        NextGameWidget()
    }
}
