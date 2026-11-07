import QtQuick
import QtQuick.Controls
Item {
    id: view
    property var s
    property var game: s.selected

    // Download state for this game only, same rules as the library cubes.
    readonly property bool downloading: !!s.progress && !!s.progress.active && s.progress.game_id === game.id
    readonly property bool paused: downloading && s.progress.state === "paused"
    readonly property bool pausing: downloading && s.progress.state === "pausing"
    readonly property int queuePosition: {
        var queue = s.downloadQueue || [];
        for (var i = 0; i < queue.length; ++i)
            if (queue[i].id === game.id) return queue[i].position;
        return 0;
    }
    readonly property string actionLabel: game.running ? "Stop" : downloading ? (pausing ? "Pausing..." : paused ? "Resume" : "Pause") : queuePosition > 0 ? "Queued #" + queuePosition + " · Remove" : game.installed ? "Play" : game.incomplete ? "Finish download" : "Install"
    readonly property bool actionEnabled: game.running || queuePosition > 0 || (downloading && !pausing)
        || (game.installed ? (!s.busy && game.exeRequired !== false) : !!s.connected)
    // Blue install, grey paused, green play, red stop (same as the library quick button).
    readonly property color actionAccent: game.running ? (Theme.usesPaletteTokens ? Theme.red : "#C73A3A")
        : downloading ? (paused ? "#5A5F66" : Theme.info)
        : game.installed ? (Theme.usesPaletteTokens ? Theme.green : "#2E9E57") : Theme.info
    readonly property color cubeGrey: "#E65A5F66"
    readonly property color cubeYellow: "#E6C29A10"
    readonly property color cubeGreen: "#E62E9E57"
    readonly property color cubeRed: "#E6C73A3A"
    // Players whose current state is this game (state is the game name while playing).
    readonly property var playingPlayers: (s.players || []).filter(function(p) { return p.state === game.name; })

    function runAction() {
        if (game.running) backend.stopGame(game.id);
        else if (downloading) backend.toggleDownloadPause();
        else if (queuePosition > 0) backend.removeQueuedDownload(game.id);
        else if (game.installed) backend.play();
        else backend.install();
    }

    // Portrait, 2:3 like the library. The art is fitted, never cropped.
    BorderImage {
        source: "../assets/portrait/shadow.png"
        border { left: 24; top: 24; right: 24; bottom: 24 }
        x: -20; y: -14; width: 472; height: 687
        opacity: .85
    }
    Rectangle {
        x: 0; y: 0; width: 432; height: 647
        color: Theme.panel
        Image { objectName: "selectedGameCover"; anchors.fill: parent; source: view.game.art || ""; fillMode: Image.PreserveAspectFit; smooth: true; mipmap: true; asynchronous: true }
        Text { anchors.centerIn: parent; visible: !view.game.art; text: (view.game.name || "G").charAt(0); color: Theme.brass; font.family: Theme.display; font.pixelSize: Theme.scaledFont(70) }
    }

    // Status rows. Each has a small status light.
    Row {
        x: 472; y: 0; spacing: 12
        StatusLight { anchors.verticalCenter: parent.verticalCenter; scale: 0.7; color: view.downloading ? view.cubeRed : view.game.installed ? view.cubeGreen : view.cubeGrey; glow: view.downloading || view.game.installed === true }
        GText { anchors.verticalCenter: parent.verticalCenter; text: view.game.installed ? "Installed on this PC" : "Not installed on this PC" }
    }
    Row {
        x: 472; y: 44; spacing: 12
        StatusLight { anchors.verticalCenter: parent.verticalCenter; scale: 0.7; color: view.game.seeding === true ? view.cubeYellow : view.cubeGrey; glow: view.game.seeding === true }
        GText { anchors.verticalCenter: parent.verticalCenter; text: view.game.seeding === true ? "Seeding to other players" : "Not seeding" }
    }
    Row {
        x: 472; y: 88; spacing: 12
        StatusLight { anchors.verticalCenter: parent.verticalCenter; scale: 0.7; color: view.s.playerCount > 0 ? view.cubeGreen : view.cubeGrey; glow: view.s.playerCount > 0
            Text { anchors.centerIn: parent; text: String(view.s.playerCount || 0); color: "#FFFFFF"; font.pixelSize: Theme.typeCaption } }
        GText { anchors.verticalCenter: parent.verticalCenter; text: "Players in the room" }
    }

    // Main action, under the status lights. Built on the launcher's own button, same gradient, glow and edge.
    GUButton {
        objectName: "gameActionButton"
        x: 472; y: 132; width: 260; height: 60
        edge: "left"; primary: true
        text: view.actionLabel
        accent: view.actionAccent
        enabled: view.actionEnabled && (!s.tutorial || ["clientInstall", "clientPlay"].includes(s.tutorialStage))
        onClicked: view.runAction()
    }

    // Secondary actions, unchanged.
    Row {
        objectName: "secondaryGameActions"
        enabled: !view.s.tutorial; opacity: enabled ? 1 : .45
        x: 472; y: 210; spacing: 12
        GUButton { text: "Browse folder"; edge: "left"; iconName: "folder-open"; iconOnly: true; width: 42; height: 34; enabled: !!view.game.installed; onClicked: backend.openSelectedFolder() }
        GUButton { text: "Launch parameters"; edge: "center"; iconName: "sliders"; iconOnly: true; width: 42; height: 34; onClicked: backend.navigate("gameSettings") }
        GUButton { objectName: "verifyIntegrityButton"; text: "Verify integrity"; helpText: "Read every installed file and repair differences against the Host index. Ordinary installs reuse recent verification results for speed."; edge: "center"; width: 150; height: 34; enabled: !!view.game.installed && !view.downloading && !s.busy && !!s.connected; onClicked: backend.verifyIntegrity() }
    }

    // Players currently in this game.
    Panel {
        objectName: "gamePlayersPanel"
        x: 472; y: 270; width: 600; height: 240
        GText { x: 22; y: 20; text: "Players currently in game (" + view.playingPlayers.length + ")"; font.pixelSize: Theme.scaledFont(18); font.weight: Font.DemiBold }
        ListView { x: 22; y: 62; width: 556; height: 160; clip: true; spacing: 12; model: view.playingPlayers
            delegate: Row { required property var modelData; spacing: 12
                GText { text: modelData.name || "Player"; width: 300; elide: Text.ElideRight }
            }
            ScrollBar.vertical: ScrollBar {}
        }
        GText { x: 22; y: 68; width: 556; visible: view.playingPlayers.length === 0; text: "Nobody is playing this game right now."; wrapMode: Text.WordWrap; color: Theme.muted }
    }
}
