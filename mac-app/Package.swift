// swift-tools-version:6.0
import PackageDescription

let package = Package(
    name: "Alfred",
    platforms: [.macOS(.v14)],
    targets: [
        .executableTarget(
            name: "Alfred",
            path: "Sources/Alfred",
            swiftSettings: [.swiftLanguageMode(.v5)]
        ),
        .executableTarget(
            name: "alfred-ctl",
            path: "Sources/alfred-ctl",
            swiftSettings: [.swiftLanguageMode(.v5)]
        )
    ]
)
