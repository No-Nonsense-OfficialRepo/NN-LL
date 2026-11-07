import QtQuick
import QtQuick.Controls
Panel {
    id: view
    property var s
    property var p: s.progress
    Text { x: 28; y: 20; text: view.p.active ? "Installing "+view.p.game : "Downloads"; font.family: Theme.heading; font.pixelSize: Theme.typePage; color: Theme.paper }
    Text { x: 28; y: 105; text: !view.p.active ? "No active downloads" : view.p.state==="complete" ? "Download complete" : view.p.state==="paused" ? "Download paused" : view.p.state==="pausing" ? "Pausing…" : view.p.state==="resuming" ? "Resuming…" : "Receiving game files"; font.family: Theme.ui; font.pixelSize: Theme.typeSection; font.weight: Font.DemiBold; color: Theme.paper }
    GText { x: 28; y: 155; visible: view.p.active; text: view.p.total>0 ? (view.p.done/1073741824).toFixed(2)+" GB of "+(view.p.total/1073741824).toFixed(2)+" GB · "+Math.round(view.p.done/view.p.total*100)+"%" : view.p.index && view.p.index.id ? "Host indexing " + (view.p.index.file || view.p.game) + " · " + Math.round(100*(view.p.index.total>0 ? view.p.index.done/view.p.index.total : view.p.index.files_total>0 ? view.p.index.files_done/view.p.index.files_total : 0)) + "%" : "Checking the host index…"; color: Theme.green; font.pixelSize: Theme.typeSmall }
    ProgressBar {
        objectName: "downloadProgressBar"
        x: 28; y: 207; width: parent.width - 56; height: 9; visible: view.p.active; value: view.p.total>0 ? view.p.done/view.p.total : view.p.index && view.p.index.total>0 ? view.p.index.done/view.p.index.total : 0; indeterminate: view.p.active && view.p.total===0 && !(view.p.index && view.p.index.id) && view.p.state==="receiving"
        background: Rectangle { color: Theme.dark; radius: 4 }
        contentItem: Item { Rectangle { width: parent.width*parent.parent.visualPosition; height: 9; radius: 4; color: Theme.usesPaletteTokens ? Theme.info : Theme.red } }
    }
    GText { x: 28; y: 245; width: parent.width - 56; visible: view.p.active; elide: Text.ElideMiddle; text: view.p.file || ""; color: Theme.brass; font.pixelSize: Theme.typeSmall }
    GText { x: 28; y: parent.height - 120; width: parent.width - 56; wrapMode: Text.WordWrap; text: view.p.active ? "You can browse the library or minimize the launcher while installing. Choose Play when you are ready." : "Interrupted transfers can be retried from the game details."; color: Theme.muted; font.pixelSize: Theme.typeSmall }
    IconLabel { x: 28; y: parent.height - 64; iconName: "lock"; text: "Files are verified against the host's signed index." }
    function peers(items) {
        return items.map(function(i) {
            var mb = i.bytes > 0 ? " (" + (i.bytes / 1048576).toFixed(i.bytes < 10485760 ? 1 : 0) + " MB)" : "";
            return (i.active ? "● " : "") + i.name + mb
        }).join("   ·   ")
    }
    ListView {
        objectName: "transferList"
        x: 28; y: 340; width: parent.width - 56; height: Math.max(0, parent.height - 340 - 130)
        clip: true; spacing: 12; model: view.s.transfers || []
        header: Column {
            width: ListView.view.width; spacing: 8
            GText { visible: view.s.downloadActive || (view.s.downloadQueue || []).length > 0; text: "Download queue"; color: Theme.brass; font.pixelSize: Theme.typeSmall }
            GText { visible: !!view.s.queueMessage; text: view.s.queueMessage || ""; width: parent.width; wrapMode: Text.WordWrap; color: Theme.muted; font.pixelSize: Theme.typeSmall }
            Panel {
                objectName: "activeQueueRow"; visible: view.s.downloadActive; width: parent.width; height: visible ? 62 : 0
                fill: Theme.alpha(Theme.green, .09); stroke: Theme.alpha(Theme.green, .55); cut: 10; bottomHighlight: true
                GText { x: 18; width: 38; height: parent.height; verticalAlignment: Text.AlignVCenter; text: "01"; color: Theme.green; font.pixelSize: Theme.typeSmall }
                GText { x: 60; width: parent.width - 220; height: parent.height; verticalAlignment: Text.AlignVCenter; elide: Text.ElideRight
                    text: view.p.game || "Preparing download"; color: Theme.paper; font.pixelSize: Theme.scaledFont(16) }
                GText { anchors.right: parent.right; anchors.rightMargin: 61; height: parent.height; verticalAlignment: Text.AlignVCenter
                    text: view.p.state === "paused" ? "PAUSED" : "ACTIVE"; color: view.p.state === "paused" ? Theme.warning : Theme.green; font.pixelSize: Theme.typeSmall }
                GUButton { objectName: "activeQueueNextAction"; anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; anchors.rightMargin: 7
                    width: 38; height: 34; text: "Start next queued game"; iconName: "queue-next"; iconOnly: true
                    helpText: "Pause this game and start the next queued game. This game resumes later."
                    enabled: (view.s.downloadQueue || []).length > 0; onClicked: backend.moveActiveDownloadDown() }
            }
            Repeater {
                objectName: "downloadQueueRepeater"
                model: view.s.downloadQueue || []
                delegate: Panel {
                    required property var modelData
                    objectName: "queuedGameRow-" + modelData.id
                    width: parent.width; height: 62; cut: 10; fill: Theme.alpha(Theme.insetPanel, .85); stroke: Theme.border
                    GText { x: 18; width: 38; height: parent.height; verticalAlignment: Text.AlignVCenter
                        text: String(modelData.position + (view.s.downloadActive ? 1 : 0)).padStart(2, "0"); color: Theme.brass; font.pixelSize: Theme.typeSmall }
                    GText { x: 60; width: parent.width - 260; height: parent.height; verticalAlignment: Text.AlignVCenter; elide: Text.ElideRight
                        text: modelData.name; color: Theme.paper; font.pixelSize: Theme.scaledFont(16) }
                    Row { anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; anchors.rightMargin: 7; spacing: 5
                        GUButton { objectName: "queueTop-" + modelData.id; width: 38; height: 34; text: "Move " + modelData.name + " to top"; iconName: "queue-top"; iconOnly: true; helpText: "Start " + modelData.name + " next"; onClicked: backend.prioritizeDownload(modelData.id) }
                        GUButton { objectName: "queueUp-" + modelData.id; width: 38; height: 34; text: "Move " + modelData.name + " up"; iconName: "queue-up"; iconOnly: true; helpText: "Move " + modelData.name + " up one place"; enabled: modelData.position > 1; onClicked: backend.moveQueuedDownload(modelData.id, -1) }
                        GUButton { objectName: "queueDown-" + modelData.id; width: 38; height: 34; text: "Move " + modelData.name + " down"; iconName: "queue-down"; iconOnly: true; helpText: "Move " + modelData.name + " down one place"; enabled: modelData.position < (view.s.downloadQueue || []).length; onClicked: backend.moveQueuedDownload(modelData.id, 1) }
                        GUButton { objectName: "queueRemove-" + modelData.id; width: 38; height: 34; text: "Remove " + modelData.name + " from queue"; iconName: "cancel"; iconOnly: true; accent: Theme.red; helpText: "Remove " + modelData.name + " from the queue"; onClicked: backend.removeQueuedDownload(modelData.id) }
                    }
                }
            }
            Item { width: 1; height: (view.s.downloadQueue || []).length > 0 ? 12 : 0 }
        }
        delegate: Column {
            width: ListView.view.width; spacing: 3
            GText { width: parent.width; elide: Text.ElideRight; text: modelData.name + (modelData.downloading ? " · downloading" : "") + (modelData.seeding ? " · seeding" : ""); color: Theme.paper; font.pixelSize: Theme.typeSmall }
            GText { visible: modelData.from.length > 0; width: parent.width; wrapMode: Text.WordWrap; text: "Downloading from: " + view.peers(modelData.from); color: Theme.green; font.pixelSize: Theme.typeSmall }
            GText { visible: modelData.downloading && modelData.from.length === 0; width: parent.width; text: "Downloading from: no sources yet"; color: Theme.muted; font.pixelSize: Theme.typeSmall }
            GText { visible: modelData.to.length > 0; width: parent.width; wrapMode: Text.WordWrap; text: "Sending to: " + view.peers(modelData.to); color: Theme.brass; font.pixelSize: Theme.typeSmall }
            GText { visible: modelData.seeding && modelData.to.length === 0; width: parent.width; text: "Seeding · nobody is downloading from you right now"; color: Theme.muted; font.pixelSize: Theme.typeSmall }
        }
    }
    GUButton { objectName: "downloadPauseAction"; x: 28; y: 282; width: 48; visible: view.p.active; text: "Pause download"; edge: "left"; iconName: "pause"; iconOnly: true; accent: Theme.warning; enabled: !view.s.tutorial && view.p.state==="receiving"; onClicked: backend.pauseDownload() }
    GUButton { objectName: "downloadResumeAction"; x: 88; y: 282; width: 48; visible: view.p.active; text: "Resume download"; edge: "center"; iconName: "resume"; iconOnly: true; accent: Theme.green; enabled: !view.s.tutorial && view.p.state==="paused"; onClicked: backend.resumeDownload() }
    GUButton { objectName: "downloadCancelAction"; x: 148; y: 282; width: 48; visible: view.s.downloadActive; text: "Cancel download"; edge: "right"; iconName: "cancel"; iconOnly: true; accent: Theme.red; helpText: "Cancel and remove the partial game download"; enabled: !view.s.tutorial; onClicked: backend.cancelDownload() }
}
