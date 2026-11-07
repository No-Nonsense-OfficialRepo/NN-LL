import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
Item {
    id: view
    property var s
    anchors.fill: parent

    // Tab strip: fills the page width.
    RowLayout {
        id: tabs
        anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top
        height: 44; spacing: 12
        Repeater { model: ["Game Library","Network","Appearance","Player","Events","Diagnostics"]
            GUButton { required property string modelData; required property int index; Layout.fillWidth: true; Layout.preferredHeight: 44; edge: index===0 ? "left" : index===5 ? "right" : "center"; text: modelData; objectName: "settingsTab-" + modelData; enabled: !view.s.tutorial || (modelData === "Player" && view.s.tutorialStage === "clientPlayerTab"); iconOnly: false; selected: view.s.settingsTab===modelData; onClicked: backend.settingsTab(modelData) }
        }
    }

    // Content panel: takes all the space under the tabs.
    Panel {
        id: panel
        anchors.left: parent.left; anchors.right: parent.right; anchors.bottom: parent.bottom
        anchors.top: tabs.bottom; anchors.topMargin: 20
        IconLabel { x: 32; y: 24; visible: ["Player","Events"].indexOf(view.s.settingsTab)<0; iconName: ActionIcons.forLabel(view.s.settingsTab); text: view.s.settingsTab; description: view.s.settingsTab+" settings" }
        Loader {
            anchors.fill: parent
            active: view.s.settingsTab==="Player" || view.s.settingsTab==="Events"
            sourceComponent: view.s.settingsTab==="Player" ? playerSection : eventsSection
        }
        Component { id: playerSection; ProfileView { s: view.s } }
        Component { id: eventsSection; EventsView { s: view.s } }

        // ---- Game Library: where games live, then how many there are ----
        Item {
            visible: view.s.settingsTab==="Game Library"; anchors.fill: parent; enabled: !view.s.tutorial; opacity: enabled ? 1 : .45
            GText { x: 32; y: 92; text: "Game download directory"; font.pixelSize: Theme.typeSmall }
            GUField { id: directory; x: 32; y: 122; width: parent.width - 32 - 170 - 16 - 32; text: view.s.gameDirectory; enabled: !view.s.connected && !view.s.busy }
            GUButton { x: parent.width - 32 - 170; y: 122; width: 170; text: "Browse"; edge: "right"; iconName: "folder"; enabled: !view.s.connected && !view.s.busy; onClicked: {let path=backend.chooseDirectory(); if(path) directory.text=path;} }
            GText { x: 32; y: 192; text: "Leave your room before changing this directory."; color: Theme.brass; font.pixelSize: Theme.typeSmall }
            Text { x: 32; y: 280; text: view.s.gameCount+" games available"; font.family: Theme.ui; font.pixelSize: Theme.typeSection; font.weight: Font.DemiBold; color: Theme.paper }
            GUButton { x: 32; y: parent.height - 80; width: 220; text: "Save changes"; edge: "left"; iconName: "save"; iconOnly: false; primary: true; enabled: !view.s.connected && !view.s.busy; onClicked: backend.saveSettings(directory.text,view.s.keepInstalled) }
        }

        // ---- Network: connection, this PC, and VLA ----
        Item {
            id: net
            visible: view.s.settingsTab==="Network"; anchors.fill: parent
            readonly property real colW: (width - 96) / 2
            readonly property real rightX: 32 + colW + 32

            Flickable {
                anchors.fill: parent; contentWidth: width; contentHeight: 900; clip: true
                boundsBehavior: Flickable.StopAtBounds
                ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

            Rectangle { x: 32; y: 82; width: parent.width-64; height: 104; radius: 6; color: Theme.insetPanel; border.color: Theme.border; border.width: .6 }
            GText { x: 52; y: 95; text: "CONNECTION STATUS"; font.pixelSize: Theme.typeSmall; color: Theme.brass }
            Text { x: 52; y: 119; text: view.s.connected ? "Connected" : "Not connected"; font.family: Theme.ui; font.pixelSize: Theme.typeSection; font.weight: Font.DemiBold; color: view.s.connected ? Theme.green : Theme.muted }
            GText { x: net.rightX; y: 126; width: net.colW-20; elide: Text.ElideRight; text: view.s.status; font.pixelSize: Theme.typeSmall; color: Theme.muted }

            Rectangle { x: 32; y: 206; width: net.colW; height: 240; radius: 6; color: Theme.insetPanel; border.color: Theme.border; border.width: .6 }
            GText { x: 52; y: 224; text: "THIS PC"; font.pixelSize: Theme.typeSmall; font.weight: Font.DemiBold; color: Theme.brass }
            GUButton { objectName: "prepareThisPcButton"; x: 52; y: 267; text: "Prepare this PC"; edge: "left"; iconName: "connect"; width: 220; iconOnly: false
                enabled: !view.s.busy && !(view.s.pc && (view.s.pc.running || view.s.pc.checking)); visible: !view.s.preview; onClicked: backend.preparePC() }
            GText { objectName: "pcReadyIndicator"; x: 292; y: 277; width: net.colW - 280; wrapMode: Text.WordWrap
                visible: !!(view.s.pc && view.s.pc.text); font.pixelSize: Theme.typeSmall
                text: view.s.pc && view.s.pc.text ? ((view.s.pc.ready ? "Ready: " : "Needs attention: ") + view.s.pc.text) : ""
                color: view.s.pc && view.s.pc.ready ? Theme.green : Theme.brass }
            GUButton { objectName: "cleanupPcButton"; x: 52; y: 333; text: "Clean up this PC"; edge: "left"; iconName: "clean-pc"; width: 220; iconOnly: false; enabled: !view.s.busy; visible: !view.s.preview; onClicked: backend.cleanupPC() }
            GText { x: 292; y: 341; width: net.colW - 280; wrapMode: Text.WordWrap; font.pixelSize: Theme.typeSmall; color: Theme.muted; text: "Removes what Prepare this PC added. Shows a plan and asks first." }

            // Right column
            Rectangle { x: net.rightX; y: 206; width: net.colW; height: 240; radius: 6; color: Theme.insetPanel; border.color: Theme.border; border.width: .6 }
            GText { x: net.rightX+20; y: 224; text: "VLA"; font.pixelSize: Theme.typeSmall; font.weight: Font.DemiBold; color: Theme.brass }
            GText { x: net.rightX+20; y: 269; text: "Keep VLA installed after closing"; font.pixelSize: Theme.typeSmall }
            GUToggle { x: net.rightX + net.colW - 62; y: 264; checked: view.s.keepInstalled; helpText: "Keep VLA installed for future room connections."; onClicked: backend.setKeepInstalled(checked) }
            GUButton { objectName: "wipeVLAButton"; x: net.rightX+20; y: 330; text: "Repair Network/Wipe VLA"; edge: "left"; iconName: "trash"; width: 265; iconOnly: false; enabled: !view.s.busy; onClicked: backend.wipeVLA() }
            GText { x: net.rightX + 305; y: 333; width: net.colW - 325; wrapMode: Text.WordWrap; text: "Uninstalls launcher-owned VLA and resets launcher data. Keeps theme, resolution, launcher files and game directories. Closes afterward."; font.pixelSize: Theme.typeSmall; color: Theme.muted }

            Rectangle { x: 32; y: 466; width: parent.width-64; height: 224; radius: 6; color: Theme.insetPanel; border.color: Theme.border; border.width: .6 }
            GText { x: 52; y: 484; text: "SECURITY AND ROOM CONNECTIONS"; font.pixelSize: Theme.typeSmall; font.weight: Font.DemiBold; color: Theme.brass }
            GText { x: 52; y: 515; width: parent.width-104; wrapMode: Text.WordWrap; font.pixelSize: Theme.typeSmall; color: Theme.muted
                text: "Defender or another antivirus may block an unfamiliar launcher or VLA network traffic. A firewall may block room discovery or joining, especially on a Public network. Check your security app's alerts and allow this launcher if you trust it." }
            Row { x: 52; y: 579; spacing: 14
                GUButton { objectName: "openDefenderExclusionsButton"; width: 220; height: 36; text: "Open Defender settings"; iconOnly: false; onClicked: backend.openWindowsSecurity("exclusions") }
                GUButton { objectName: "copyLauncherFolderButton"; width: 220; height: 36; text: "Copy launcher folder path"; iconOnly: false; onClicked: backend.copyLauncherFolder() }
                GUButton { objectName: "openFirewallSettingsButton"; width: 220; height: 36; text: "Open firewall settings"; iconOnly: false; onClicked: backend.openWindowsSecurity("firewall") }
            }
            GText { x: 52; y: 640; width: parent.width-104; wrapMode: Text.WordWrap; font.pixelSize: Theme.typeCaption; color: Theme.muted
                text: "In Defender: Manage settings → Exclusions → Add or remove exclusions → Add an exclusion → Folder. A folder exclusion also reduces scanning of any games inside it. Third-party antivirus settings are separate." }
            Rectangle { x: 32; y: 710; width: parent.width-64; height: 120; radius: 6; color: Theme.insetPanel; border.color: Theme.border; border.width: .6 }
            GText { x: 52; y: 726; text: "CURRENT ADAPTER PROFILE"; font.pixelSize: Theme.typeSmall; font.weight: Font.DemiBold; color: Theme.brass }
            ComboBox {
                id: networkAdapter; objectName: "networkAdapterSelector"
                x: 52; y: 759; width: Math.min(410, net.colW); height: 38
                model: view.s.networkProfiles || []; textRole: "name"
                currentIndex: {
                    var profiles = view.s.networkProfiles || [];
                    for (var i = 0; i < profiles.length; ++i)
                        if (profiles[i].index === view.s.networkProfileIndex) return i;
                    return -1;
                }
                onActivated: function(index) { backend.selectNetworkProfile(model[index].index); }
            }
            GText { x: networkAdapter.x+networkAdapter.width+20; y: 769; text: networkAdapter.currentIndex >= 0 ? networkAdapter.model[networkAdapter.currentIndex].category : "No adapter found"; color: Theme.paper; font.pixelSize: Theme.typeSmall }
            GUButton {
                objectName: "toggleNetworkProfileButton"
                x: parent.width-262; y: 758; width: 210; height: 38
                text: networkAdapter.currentIndex >= 0 && networkAdapter.model[networkAdapter.currentIndex].category === "Public" ? "Switch to Private" : "Switch to Public"
                enabled: !view.s.networkProfileBusy && networkAdapter.currentIndex >= 0 && networkAdapter.model[networkAdapter.currentIndex].category !== "DomainAuthenticated"
                onClicked: backend.toggleNetworkProfile()
            }
            GText { x: 52; y: 803; text: "Windows may ask for permission. Domain-managed profiles cannot be changed here."; color: Theme.muted; font.pixelSize: Theme.typeCaption }
            GText { x: 52; y: 856; width: parent.width-104; text: "Joining and connection repair controls are on the Room page."; font.pixelSize: Theme.typeSmall; color: Theme.muted }
            }
        }

        // ---- Appearance: theme on top, then client and host resolution side by side ----
        Item {
            id: look
            visible: view.s.settingsTab==="Appearance"; anchors.fill: parent
            readonly property real colW: (width - 96) / 2
            readonly property real rightX: 32 + colW + 32
            GText { x: 32; y: 92; text: "Theme"; font.pixelSize: Theme.typeSmall }
            ThemePicker { x: 32; y: 122; width: parent.width - 64; height: 108 }
            GText { x: 32; y: 270; text: "Client · 16:9"; font.pixelSize: Theme.typeSmall }
            ResolutionPicker { x: 32; y: 296; width: look.colW; height: 40; enabled: !WindowPreferences.fillScreen }
            IconLabel { x: 32; y: 354; iconName: "computer"; text: WindowPreferences.effectiveWidth+" × "+WindowPreferences.effectiveHeight; description: "Current launcher window size" }
            GText { x: look.rightX; y: 270; text: "Host · 9:21"; font.pixelSize: Theme.typeSmall }
            ResolutionPicker { x: look.rightX; y: 296; width: look.colW; height: 40; host: true }
            CheckBox {
                objectName: "fillScreenCheckbox"
                x: 32; y: 406; text: "Full screen · keep taskbar visible"
                checked: WindowPreferences.fillScreen
                enabled: !view.s.tutorial
                onClicked: WindowPreferences.setFillScreen(checked)
                palette.windowText: Theme.paper; palette.text: Theme.paper
            }
            GText { x: 32; y: parent.height - 56; text: "Theme and resolution apply immediately."; color: Theme.brass; font.pixelSize: Theme.typeSmall }
        }

        // ---- Diagnostics: facts and results above, actions pinned along the bottom ----
        Item {
            id: diag
            visible: view.s.settingsTab==="Diagnostics"; anchors.fill: parent
            GUButton { objectName: "diagnosticsAboutButton"; anchors.top: parent.top; anchors.right: parent.right; anchors.topMargin: 20; anchors.rightMargin: 32; width: 130; height: 34; text: "About"; iconName: "diamond"; iconOnly: false; onClicked: backend.navigate("about") }
            Column { x: 32; y: 98; spacing: 14; width: parent.width - 64
                GText { text: "Launcher version: "+view.s.version; font.pixelSize: Theme.typeSmall }
                GText { text: "Computer: "+view.s.pcName; font.pixelSize: Theme.typeSmall }
                CopyText { text: "Room: "+(view.s.roomCode || "Not connected"); copyValue: view.s.roomCode || ""; description: "Copy room code"; font.pixelSize: Theme.typeSmall }
                GText { text: view.s.status; width: parent.width; wrapMode: Text.WordWrap; font.pixelSize: Theme.typeSmall; color: Theme.muted }
            }
            GText { objectName: "diagProgress"; x: 32; y: 206; width: parent.width - 64; wrapMode: Text.WordWrap; font.pixelSize: Theme.typeSmall; color: Theme.brass
                visible: !!(view.s.diag && (view.s.diag.running || view.s.diag.error))
                text: view.s.diag && view.s.diag.error ? "Connection check failed: "+view.s.diag.error : "Running connection check… "+(view.s.diag ? view.s.diag.step : "") }
            Flickable { id: diagFlick; x: 32; y: 236; width: parent.width - 64; height: Math.max(80, bottomBar.y - 252); clip: true; contentWidth: width; contentHeight: diagResults.implicitHeight; boundsBehavior: Flickable.StopAtBounds
                visible: !!(view.s.diag && view.s.diag.rows && view.s.diag.rows.length)
                ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded; width: 6 }
                Column { id: diagResults; objectName: "diagResults"; x: 0; y: 0; spacing: 1
                    Repeater { model: view.s.diag && view.s.diag.rows ? view.s.diag.rows : []
                        Row { required property var modelData; spacing: 10; height: 20
                            Text { width: 20; height: 20; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter
                                font.family: Theme.ui; font.pixelSize: Theme.scaledFont(18); font.bold: true
                                text: modelData.status==="ok" ? "OK" : modelData.status==="warn" ? "!" : modelData.status==="skipped" ? "–" : "X"
                                color: modelData.status==="ok" ? "#3FB950" : modelData.status==="warn" ? Theme.brass : modelData.status==="skipped" ? Theme.muted : "#F85149" }
                            GText { width: 220; height: 20; verticalAlignment: Text.AlignVCenter; text: modelData.title; font.pixelSize: Theme.typeSmall; elide: Text.ElideRight }
                            GText { width: diagFlick.width - 20 - 220 - 30 - (modelData.fix ? 130 : 0) - 12; height: 20; verticalAlignment: Text.AlignVCenter; text: (modelData.desc ? modelData.desc + "  ·  " : "") + modelData.detail; font.pixelSize: Theme.typeSmall; color: Theme.muted; elide: Text.ElideRight }
                            GText { objectName: "diagFix_"+modelData.fix; visible: !!modelData.fix; width: 120; height: 20; verticalAlignment: Text.AlignVCenter
                                text: modelData.fixLabel || ""; font.pixelSize: Theme.typeSmall; font.underline: true; color: Theme.brass; elide: Text.ElideRight
                                MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor
                                    enabled: !(view.s.diag && view.s.diag.running); onClicked: backend.runFix(modelData.fix) } }
                        }
                    }
                }
            }
            Item {
                id: bottomBar
                x: 32; width: parent.width - 64; height: 164
                anchors.bottom: parent.bottom; anchors.bottomMargin: 28
                readonly property real bw: (width - 32) / 3
                GUField { id: ladderHost; objectName: "ladderHostField"; x: 0; y: 0; width: parent.width - 336; placeholderText: "Host IP address"; enabled: !(view.s.diag && view.s.diag.running) }
                GUButton { objectName: "runLadderButton"; x: parent.width - 320; y: 0; width: 320; text: "Check this Host"; edge: "center"; iconName: "search"; iconOnly: false; enabled: !(view.s.diag && view.s.diag.running) && ladderHost.text.trim().length > 0; onClicked: backend.runLadder(ladderHost.text) }
                GUButton { objectName: "copyReportButton"; x: 0; y: 56; width: bottomBar.bw; text: "Copy report"; edge: "left"; iconName: "clipboard"; onClicked: backend.copyDiagnosticReport() }
                GUButton { objectName: "runDiagnosticsButton"; x: bottomBar.bw + 16; y: 56; width: bottomBar.bw; text: view.s.diag && view.s.diag.running ? "Checking…" : "Run connection check"; edge: "center"; iconName: "save"; iconOnly: false; primary: true; enabled: !(view.s.diag && view.s.diag.running); onClicked: backend.runDiagnostics() }
                GUButton { x: 2 * (bottomBar.bw + 16); y: 56; width: bottomBar.bw; text: "Open reports"; edge: "right"; iconName: "folder"; iconOnly: false; onClicked: backend.openDiagnosticsFolder() }
                GUButton { objectName: "runHostCheckButton"; x: 0; y: 112; width: parent.width; visible: view.s.host; text: "Check my room"; edge: "center"; iconName: "connect"; iconOnly: false; enabled: !(view.s.diag && view.s.diag.running); onClicked: backend.runHostCheck() }
            }
        }
    }
}
