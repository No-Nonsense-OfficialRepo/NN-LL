import QtQuick
import QtQuick.Controls
Item {
    id: view
    property var s
    // Status colours for the cubes under each portrait.
    readonly property color cubeGrey: "#FF5A5F66"
    readonly property color cubeYellow: "#FFC29A10"
    readonly property color cubeGreen: "#FF2E9E57"
    readonly property color cubeRed: "#FFC73A3A"
    readonly property color cubeBlue: "#FF2F7BD9"

    // Keeps the Stop/Play cube in step with games that open or close.
    Timer { interval: 2000; running: view.visible; repeat: true; onTriggered: backend.refreshRunning() }
    GUField { x: 0; y: 4; width: Math.max(240, parent.width * .58); height: 32; placeholderText: "Search your games…"; text: view.s.query; onTextEdited: backend.search(text) }
    Row {
        x: parent.width-width; y: 3; spacing: 7
        Repeater {
            model: ["All games", "Installed", "Playing"]
            GUButton { required property string modelData; required property int index; edge: index===2 ? "right" : "center"; text: modelData; width: 140; height: 36; iconOnly: false; labelFontSize: Theme.typeCaption; selected: view.s.filter === modelData; onClicked: backend.filterGames(modelData) }
        }
    }
    GridView {
        id: grid
        objectName: "gameGrid"
        x: 0; y: 62; width: parent.width; height: parent.height - 96
        clip: true
        // Room inside the clip so the hover growth on the first row/column isn't cut off.
        readonly property real gutter: 24
        topMargin: 24; bottomMargin: 24; leftMargin: 16; rightMargin: 16
        cellWidth: (width-leftMargin-rightMargin) / 8
        // Portrait (2:3). The cube row overlaps its bottom edge; the gap lets the hover grow breathe.
        cellHeight: (cellWidth - gutter) * 1.5 + (31 * .85) / 2 + gutter
        model: view.s.games
        boundsBehavior: Flickable.StopAtBounds
        ScrollBar.vertical: ScrollBar { policy: grid.contentHeight > grid.height ? ScrollBar.AsNeeded : ScrollBar.AlwaysOff }
        delegate: Item {
            id: card
            required property var modelData
            objectName: "libraryPortrait-" + modelData.id
            readonly property real cubeS: 31 * .85
            readonly property bool hot: cardMouse.containsMouse || playerCube.hovered || statusCube.hovered || actionCube.hovered
            // Download state for this game only (the backend reports one transfer at a time).
            readonly property bool downloading: !!view.s.progress && !!view.s.progress.active && view.s.progress.game_id === modelData.id
            readonly property bool paused: downloading && view.s.progress.state === "paused"
            readonly property bool pausing: downloading && view.s.progress.state === "pausing"
            readonly property int queuePosition: {
                var queue = view.s.downloadQueue || [];
                for (var i = 0; i < queue.length; ++i)
                    if (queue[i].id === modelData.id) return queue[i].position;
                return 0;
            }
            readonly property bool running: modelData.running === true
            width: grid.cellWidth
            height: grid.cellHeight
            z: hot ? 2 : 0

            BorderImage {
                objectName: "portraitShadow"
                source: "../assets/portrait/shadow.png"
                border { left: 24; top: 24; right: 24; bottom: 24 }
                x: frame.x-20; y: frame.y-20+(card.hot ? 12 : 6)
                width: frame.width+40; height: frame.height+40
                scale: frame.scale
                opacity: card.hot ? .42 : .85
                Behavior on opacity { NumberAnimation { duration: 180 } }
                Behavior on y { NumberAnimation { duration: 180; easing.type: Easing.OutCubic } }
            }
            // Art stays fitted; its shadow lifts and lightens on hover.
            Rectangle {
                id: frame
                x: grid.gutter / 2; y: 0
                width: parent.width-grid.gutter; height: width * 1.5
                radius: 2; color: Theme.panel; border.color: Theme.border; border.width: .6
                clip: true
                transformOrigin: Item.Center
                scale: card.hot ? 1.05 : 1
                Behavior on scale { NumberAnimation { duration: 180; easing.type: Easing.OutCubic } }
                Image {
                    id: art; objectName: "libraryGameArtwork"
                    anchors.fill: parent; visible: !!modelData.art
                    source: modelData.art || ""; fillMode: Image.PreserveAspectFit; asynchronous: true
                }
                Text {
                    anchors.fill: parent; anchors.margins: 10; visible: !modelData.art
                    text: modelData.name; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter
                    wrapMode: Text.WordWrap; elide: Text.ElideRight; maximumLineCount: 4
                    font.family: Theme.ui; font.pixelSize: Theme.typeSmall; color: Theme.paper
                }
                // The large image opens the game select screen (selectGame shows details).
                MouseArea { id: cardMouse; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: backend.selectGame(modelData.id) }
            }

            // Fixed controls and equal gaps; independent of portrait width and state.
            Row {
                id: cubes
                objectName: "portraitControls"
                x: frame.x+frame.width-width-4; y: frame.height-card.cubeS/2
                spacing: 4
                PortraitControl {
                    id: playerCube; objectName: "portraitPlayers"
                    width: card.cubeS; height: card.cubeS
                    statusColor: modelData.playing > 0 ? view.cubeGreen : view.cubeGrey
                    portraitIcon: "players"; count: String(modelData.playing)
                    text: modelData.playing + " players playing"
                }
                PortraitControl {
                    id: statusCube; objectName: "portraitInstallStatus"
                    width: card.cubeS; height: card.cubeS
                    statusColor: card.downloading ? view.cubeRed
                        : modelData.installed ? (modelData.seeding === true ? view.cubeYellow : view.cubeGreen)
                        : view.cubeGrey
                    portraitIcon: card.downloading ? "receiving" : modelData.installed ? (modelData.seeding ? "seeding" : "installed")
                        : modelData.incomplete ? "incomplete" : "missing"
                    text: card.downloading ? "Download in progress" : modelData.installed ? (modelData.seeding ? "Seeding to players" : "Installed")
                        : modelData.incomplete ? "Incomplete installation" : "Not installed"
                }
                PortraitControl {
                    id: actionCube; objectName: "portraitGameAction"
                    width: card.cubeS; height: card.cubeS
                    statusColor: card.running ? view.cubeRed
                        : card.downloading ? (card.paused ? view.cubeGrey : view.cubeBlue)
                        : card.queuePosition > 0 ? view.cubeYellow
                        : modelData.installed ? view.cubeGreen : view.cubeBlue
                    opacity: card.pausing ? .5 : 1
                    enabled: !card.pausing
                    portraitIcon: card.running ? "stop" : card.downloading ? (card.paused ? "resume" : "pause")
                        : card.queuePosition > 0 ? "queued" : modelData.installed ? "play" : "install"
                    count: card.queuePosition > 0 ? String(card.queuePosition) : ""
                    text: card.running ? "Stop" : card.downloading ? (card.paused ? "Resume download" : "Pause download")
                        : card.queuePosition > 0 ? "Queued #"+card.queuePosition+" - Click to remove" : modelData.installed ? "Play" : "Install"
                    onClicked: {
                        if (card.running) backend.stopGame(modelData.id);
                        else if (card.downloading) backend.toggleDownloadPause();
                        else if (card.queuePosition > 0) backend.removeQueuedDownload(modelData.id);
                        else if (modelData.installed) backend.playGame(modelData.id);
                        else backend.installGame(modelData.id);
                    }
                }
            }
        }
    }
    Panel {
        visible: view.s.games.length === 0
        x: 0; y: 62; width: parent.width; height: 260
        Text { x: 28; y: 38; text: view.s.gameCount ? "No games match your search" : "Waiting for the host playlist"; font.family: Theme.heading; font.pixelSize: Theme.typeHeading; color: Theme.paper }
        GText { x: 28; y: 99; width: parent.width-56; wrapMode: Text.WordWrap; color: Theme.muted; font.pixelSize: Theme.typeCaption; text: view.s.gameCount ? "Try another title or clear your filters." : "Connect to your host to load the shared event playlist." }
        GUButton { id: findHostButton; anchors.left: parent.left; anchors.leftMargin: 28; anchors.bottom: parent.bottom; anchors.bottomMargin: 28; text: "Find Host"; edge: "left"; visible: !view.s.connected; width: 210; height: 48; onClicked: backend.navigate("room") }
        GUButton { id: clearButton; anchors.bottom: parent.bottom; anchors.bottomMargin: 28; anchors.left: findHostButton.visible ? findHostButton.right : parent.left; anchors.leftMargin: findHostButton.visible ? 14 : 28; text: "Clear search & filters"; edge: "left"; visible: view.s.gameCount>0; width: 210; height: 48; onClicked: { backend.search(""); backend.filterGames("All games"); } }
    }
    IconLabel { y: parent.height-24; iconName: "grid"; text: String(view.s.gameCount); description: view.s.gameCount+" games in the library"; textColor: Theme.brass }
}
