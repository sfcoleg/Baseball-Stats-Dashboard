// DiamondMetricsApp.swift — the Mac app. Deliberately small: a sidebar of
// sections (Scores, Standings, Leaders) plus Settings for sport and
// favorite team. The widgets are the point; the app is where you set
// them up and get the fuller view when you click one.
import SwiftUI
import WidgetKit

@main
struct DiamondMetricsApp: App {
    var body: some Scene {
        WindowGroup("Diamond Metrics") {
            ContentView()
                .frame(minWidth: 760, minHeight: 520)
        }
        .windowStyle(.hiddenTitleBar)
        Settings { SettingsView() }
    }
}

@MainActor
final class Store: ObservableObject {
    @Published var feed: Feed? = FeedClient.cached()
    @Published var live: [LiveGame] = []
    @Published var sport: Sport = AppConfig.sport { didSet { AppConfig.sport = sport; Task { await refreshLive() }; WidgetCenter.shared.reloadAllTimelines() } }
    @Published var favorite: String = AppConfig.favoriteTeam { didSet { AppConfig.favoriteTeam = favorite; WidgetCenter.shared.reloadAllTimelines() } }
    @Published var lastRefresh: Date?

    func refreshAll() async {
        feed = await FeedClient.load()
        await refreshLive()
    }

    func refreshLive() async {
        live = await LiveScores.fetch(sport)
        lastRefresh = Date()
    }

    var teams: [String] {
        guard let feed else { return [] }
        switch sport {
        case .mlb: return feed.mlb.standings.map(\.teamAbbr).sorted()
        case .nhl: return feed.nhl.standings.map(\.abbr).sorted()
        }
    }
}

enum Section: String, CaseIterable, Identifiable {
    case scores = "Scores", standings = "Standings", leaders = "Leaders"
    var id: String { rawValue }
    var icon: String {
        switch self { case .scores: "sportscourt"; case .standings: "list.number"; case .leaders: "trophy" }
    }
}

struct ContentView: View {
    @StateObject private var store = Store()
    @State private var section: Section = .scores
    private let ticker = Timer.publish(every: 30, on: .main, in: .common).autoconnect()

    var body: some View {
        NavigationSplitView {
            List(Section.allCases, selection: $section) { s in
                Label(s.rawValue, systemImage: s.icon).tag(s)
            }
            .navigationSplitViewColumnWidth(180)
            .safeAreaInset(edge: .bottom) {
                VStack(spacing: 6) {
                    Picker("", selection: $store.sport) {
                        ForEach(Sport.allCases) { Text($0.label).tag($0) }
                    }
                    .pickerStyle(.segmented)
                    if let t = store.lastRefresh {
                        Text("Updated \(t.formatted(date: .omitted, time: .shortened))")
                            .font(.caption2).foregroundStyle(.secondary)
                    }
                }
                .padding(10)
            }
        } detail: {
            Group {
                switch section {
                case .scores: ScoresView(store: store)
                case .standings: StandingsView(store: store)
                case .leaders: LeadersView(store: store)
                }
            }
            .navigationTitle(section.rawValue)
            .toolbar {
                Button { Task { await store.refreshAll() } } label: { Image(systemName: "arrow.clockwise") }
            }
        }
        .task { await store.refreshAll() }
        .onReceive(ticker) { _ in Task { await store.refreshLive() } }
    }
}

// MARK: - Views

struct ScoresView: View {
    @ObservedObject var store: Store
    var body: some View {
        let games = store.live.sorted { ($0.isLive ? 0 : $0.isFinal ? 2 : 1, $0.start ?? .distantFuture) < ($1.isLive ? 0 : $1.isFinal ? 2 : 1, $1.start ?? .distantFuture) }
        ScrollView {
            if games.isEmpty {
                ContentUnavailableView("No games today", systemImage: "moon.zzz")
                    .padding(.top, 80)
            }
            LazyVGrid(columns: [GridItem(.adaptive(minimum: 220), spacing: 12)], spacing: 12) {
                ForEach(games) { g in GameCard(game: g, favorite: store.favorite) }
            }
            .padding()
        }
    }
}

struct GameCard: View {
    let game: LiveGame
    let favorite: String
    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                if game.isLive {
                    Text("LIVE").font(.caption2.bold()).padding(.horizontal, 6).padding(.vertical, 2)
                        .background(Color.red, in: Capsule()).foregroundStyle(.white)
                }
                Text(game.status).font(.caption).foregroundStyle(.secondary)
                Spacer()
            }
            TeamRow(abbr: game.away, score: game.awayScore, bold: (game.awayScore ?? 0) > (game.homeScore ?? 0) && game.isFinal, fav: game.away == favorite)
            TeamRow(abbr: game.home, score: game.homeScore, bold: (game.homeScore ?? 0) > (game.awayScore ?? 0) && game.isFinal, fav: game.home == favorite)
        }
        .padding(12)
        .background(.quaternary.opacity(0.5), in: RoundedRectangle(cornerRadius: 10))
        .overlay(RoundedRectangle(cornerRadius: 10).stroke((game.away == favorite || game.home == favorite) ? Color.accentColor : .clear, lineWidth: 1.5))
    }
}

struct TeamRow: View {
    let abbr: String; let score: Int?; let bold: Bool; let fav: Bool
    var body: some View {
        HStack {
            Text(abbr).font(.system(.body, design: .rounded).weight(bold ? .heavy : .semibold))
            if fav { Image(systemName: "star.fill").font(.caption2).foregroundStyle(.yellow) }
            Spacer()
            Text(score.map(String.init) ?? "–").font(.system(.title3, design: .rounded).weight(bold ? .heavy : .regular)).monospacedDigit()
        }
    }
}

struct StandingsView: View {
    @ObservedObject var store: Store
    var body: some View {
        ScrollView {
            if let feed = store.feed {
                switch store.sport {
                case .mlb:
                    let groups = Dictionary(grouping: feed.mlb.standings, by: \.division)
                    ForEach(groups.keys.sorted(), id: \.self) { div in
                        StandingsTable(title: div, rows: groups[div]!.map { ($0.teamAbbr, "\($0.wins)-\($0.losses)", $0.gamesBack, $0.streak ?? "") }, favorite: store.favorite)
                    }
                case .nhl:
                    let groups = Dictionary(grouping: feed.nhl.standings, by: { $0.division ?? "" })
                    ForEach(groups.keys.sorted(), id: \.self) { div in
                        StandingsTable(title: div, rows: groups[div]!.sorted { ($0.divRank ?? 99) < ($1.divRank ?? 99) }.map { ($0.abbr, "\($0.w ?? 0)-\($0.l ?? 0)-\($0.otl ?? 0)", "\($0.pts ?? 0) pts", $0.streak ?? "") }, favorite: store.favorite)
                    }
                }
            } else {
                ProgressView().padding(.top, 80)
            }
        }
    }
}

struct StandingsTable: View {
    let title: String
    let rows: [(String, String, String, String)]
    let favorite: String
    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(title).font(.headline).padding(.top, 8)
            ForEach(Array(rows.enumerated()), id: \.offset) { _, r in
                HStack {
                    Text(r.0).bold().frame(width: 46, alignment: .leading)
                    if r.0 == favorite { Image(systemName: "star.fill").font(.caption2).foregroundStyle(.yellow) }
                    Spacer()
                    Text(r.1).monospacedDigit().frame(width: 80, alignment: .trailing)
                    Text(r.2).monospacedDigit().foregroundStyle(.secondary).frame(width: 70, alignment: .trailing)
                    Text(r.3).foregroundStyle(.secondary).frame(width: 40, alignment: .trailing)
                }
                .font(.callout)
            }
        }
        .padding(.horizontal)
    }
}

struct LeadersView: View {
    @ObservedObject var store: Store
    var body: some View {
        ScrollView {
            if let feed = store.feed {
                HStack(alignment: .top, spacing: 24) {
                    switch store.sport {
                    case .mlb:
                        LeaderList(title: "OPS", rows: feed.mlb.leaders.ops.map { ($0.name, $0.tm, String(format: "%.3f", $0.ops ?? 0)) })
                        LeaderList(title: "Home Runs", rows: feed.mlb.leaders.hr.map { ($0.name, $0.tm, "\($0.hr ?? 0)") })
                        LeaderList(title: "ERA", rows: feed.mlb.leaders.era.map { ($0.name, $0.tm, String(format: "%.2f", $0.era ?? 0)) })
                    case .nhl:
                        if let l = feed.nhl.leaders {
                            LeaderList(title: "Points", rows: l.points.map { ($0.name, $0.team, "\($0.points ?? 0)") })
                            LeaderList(title: "Goals", rows: l.goals.map { ($0.name, $0.team, "\($0.goals ?? 0)") })
                            LeaderList(title: "Wins", rows: l.wins.map { ($0.name, $0.team, "\($0.wins ?? 0)") })
                        }
                    }
                }
                .padding()
            } else {
                ProgressView().padding(.top, 80)
            }
        }
    }
}

struct LeaderList: View {
    let title: String
    let rows: [(String, String, String)]
    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(title).font(.headline)
            ForEach(Array(rows.enumerated()), id: \.offset) { i, r in
                HStack {
                    Text("\(i + 1)").foregroundStyle(.secondary).frame(width: 18, alignment: .trailing)
                    Text(r.0).lineLimit(1)
                    Text(r.1).font(.caption).foregroundStyle(.secondary)
                    Spacer()
                    Text(r.2).monospacedDigit().bold()
                }
                .font(.callout)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

struct SettingsView: View {
    @StateObject private var store = Store()
    var body: some View {
        Form {
            Picker("Sport", selection: $store.sport) { ForEach(Sport.allCases) { Text($0.label).tag($0) } }
            Picker("Favorite team", selection: $store.favorite) {
                Text("None").tag("")
                ForEach(store.teams, id: \.self) { Text($0).tag($0) }
            }
            Text("Widgets follow these settings. Data refreshes nightly from the site; scores update live.")
                .font(.caption).foregroundStyle(.secondary)
        }
        .padding(20)
        .frame(width: 360)
        .task { if store.feed == nil { store.feed = await FeedClient.load() } }
    }
}
