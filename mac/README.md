# Diamond Metrics for Mac

A personal macOS app with desktop widgets (Today's Games, Division
Standings, Next Game) for the MLB and NHL data the website already
maintains. Nothing runs on the Mac in the background: the widgets read
`data/widget_feed.json` from this repo on GitHub (written by the nightly
refresh) and pull live scores straight from the MLB/NHL public APIs.

## Layout

```
mac/DiamondMetrics/
  Shared/Feed.swift         feed models + fetcher with on-disk cache (both targets)
  Shared/LiveScores.swift   live scores from statsapi.mlb.com / api-web.nhle.com (both targets)
  App/DiamondMetricsApp.swift   the app: Scores / Standings / Leaders + Settings
  Widgets/DiamondWidgets.swift  the three widgets (WidgetKit)
```

## One-time setup in Xcode

Widgets are WidgetKit extensions, which only Xcode can build. No paid
developer account is needed for a personal build — sign with your Apple
ID ("Personal Team").

1. Xcode → File → New → Project → **macOS › App**. Product name
   `DiamondMetrics`, interface SwiftUI, language Swift. Save it inside
   `mac/` (so the project sits next to the `DiamondMetrics/` source dir).
2. Delete the generated `ContentView.swift` and `DiamondMetricsApp.swift`.
   Drag `DiamondMetrics/Shared/` and `DiamondMetrics/App/` into the project
   (check "Add to targets: DiamondMetrics").
3. File → New → Target → **Widget Extension**. Name it `DiamondWidgets`,
   uncheck "Include Configuration App Intent". Delete its generated Swift
   files; drag `DiamondMetrics/Widgets/DiamondWidgets.swift` in, and ALSO add
   both `Shared/` files to the widget target (select them → File Inspector
   → tick the `DiamondWidgets` target).
4. Signing & Capabilities, on BOTH targets: Team = your personal team;
   add **App Groups** and create `group.com.cromulentlabs.diamondmetrics`
   (must match `AppConfig.appGroup` in Feed.swift). This is what lets the
   app and widget share settings and the cached feed.
5. On the app target, Signing & Capabilities → App Sandbox → tick
   **Outgoing Connections (Client)**. Same on the widget target.
6. Select the `DiamondMetrics` scheme, Run. Then in Settings (⌘,) pick a
   sport and favorite team. Add the widgets from the desktop widget
   gallery (right-click desktop → Edit Widgets → search "Diamond").

Both targets type-check against the macOS SDK from the command line:

```bash
cd mac/DiamondMetrics
SDK=$(xcrun --show-sdk-path --sdk macosx)
swiftc -typecheck -sdk "$SDK" -target arm64-apple-macos14.0 -parse-as-library Shared/*.swift App/*.swift
swiftc -typecheck -sdk "$SDK" -target arm64-apple-macos14.0 -parse-as-library Shared/*.swift Widgets/*.swift
```
