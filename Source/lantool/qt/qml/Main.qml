import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
ApplicationWindow {
    id: window
    objectName: "launcherWindow"
    readonly property bool tutorial: !!backend.state.tutorial
    readonly property bool fillScreen: !backend.state.host && WindowPreferences.fillScreen
    property bool windowReady: false
    onFillScreenChanged: if (windowReady) applyWindowPreference()
    onScreenChanged: if (windowReady && fillScreen) Qt.callLater(fillDesktop)
    function fillDesktop() {
        if (!fillScreen) return;
        const area=DesktopArea.availableGeometry(window);
        adjustingSize=true;
        x=area.x; y=area.y; width=area.width; height=area.height;
        adjustingSize=false;
        recordWindowSize();
    }
    function applyWindowPreference() {
        if (fillScreen) fillDesktop();
        else if (tutorial) fitTutorial();
        else if (backend.state.host ? WindowPreferences.hasHostPreference : WindowPreferences.hasClientPreference)
            WindowPreferences.requestCurrent(backend.state.host);
        else if (!backend.state.host) fitToScreen();
    }
    function snapToDesktopCorner() {
        const area = DesktopArea.availableGeometry(window);
        const edge = 48;
        const left = Math.abs(x - area.x) <= edge;
        const rightX = area.x + area.width - width;
        const right = Math.abs(x - rightX) <= edge;
        const top = Math.abs(y - area.y) <= edge;
        const bottomY = area.y + area.height - height;
        const bottom = Math.abs(y - bottomY) <= edge;
        if ((left || right) && (top || bottom)) {
            x = left ? area.x : rightX;
            y = top ? area.y : bottomY;
        }
    }
    // Present the curtain before starting the expensive glass material paint.
    property int startupPhase: showStartupCurtain ? 0 : 2
    readonly property bool startupLoading: startupPhase < 2
    function advanceStartup() {
        if (startupPhase === 0) startupPhase = 1;
        else if (startupPhase === 1 && (backend.state.host ? hostCurtainElapsed :
                 (pageLoader.status === Loader.Ready && glassLoader.item && glassLoader.item.ready)))
            startupPhase = 2;
    }
    onFrameSwapped: if (startupLoading) Qt.callLater(advanceStartup)
    property bool hostCurtainElapsed: false
    Timer {
        // Start timing after the first frame so the Host curtain has time on screen.
        interval: 650
        running: window.startupPhase === 1 && backend.state.host && !window.hostCurtainElapsed
        onTriggered: window.hostCurtainElapsed = true
    }
    onAspectRatioChanged: if (!tutorial) constrainSize(true)
    function fitTutorial() {
        const host = backend.state.host;
        if (host ? WindowPreferences.hasHostPreference : WindowPreferences.hasClientPreference)
            WindowPreferences.requestCurrent(host);
        else if (host) applyResolution(true, 463, 1080);
        else fitToScreen();
    }
    width: backend.state.host ? 463 : 1920
    height: 1080
    minimumWidth: fillScreen ? 1 : backend.state.host ? 309 : 1280
    minimumHeight: fillScreen ? 1 : 720
    flags: Qt.Window | Qt.FramelessWindowHint
    readonly property real aspectRatio: backend.state.host ? 9 / 21 : 16 / 9
    property bool adjustingSize: false
    function constrainSize(fromWidth) {
        if (adjustingSize || fillScreen || visibility === Window.Minimized) return;
        adjustingSize = true;
        // Rounded 9:21 widths must not add an extra pixel to the chosen height.
        if (fromWidth) { let target=Math.round(width/aspectRatio); if(Math.abs(height-target)>1) height=target; }
        else { let target=Math.round(height*aspectRatio); if(Math.abs(width-target)>1) width=target; }
        adjustingSize = false;
    }
    function fitToScreen() {
        // Largest 16:9 window that fits the usable desktop (taskbar excluded), centred.
        const area=DesktopArea.availableGeometry(window);
        let availableWidth=area.width;
        let availableHeight=area.height;
        let w=Math.min(availableWidth,Math.floor(availableHeight*16/9));
        applyResolution(false,w,Math.round(w*9/16));
    }
    function recordWindowSize() {
        if(!backend.state.host) { WindowPreferences.effectiveWidth=width; WindowPreferences.effectiveHeight=height; }
        else { WindowPreferences.effectiveHostWidth=width; WindowPreferences.effectiveHostHeight=height; }
    }
    function applyResolution(host,w,h) {
        if(backend.state.host!==host) return;
        if(fillScreen) { fillDesktop(); return; }
        const area=DesktopArea.availableGeometry(window);
        let availableWidth=area.width;
        let availableHeight=area.height;
        let fit=Math.min(1,availableWidth/w,availableHeight/h);
        adjustingSize=true;
        width=Math.max(minimumWidth,Math.round(w*fit));
        height=Math.max(minimumHeight,Math.round(h*fit));
        adjustingSize=false;
        x=area.x+Math.max(0,Math.round((availableWidth-width)/2));
        y=area.y+Math.max(0,Math.round((availableHeight-height)/2));
        recordWindowSize();
    }
    onWidthChanged: { constrainSize(true); recordWindowSize(); }
    onHeightChanged: { constrainSize(false); recordWindowSize(); }
    Component.onCompleted: {
        windowReady=true;
        applyWindowPreference();
        recordWindowSize();
    }
    Connections {
        target: WindowPreferences
        function onResolutionRequested(host,width,height) { window.applyResolution(host,width,height); }
    }
    Connections { target: DesktopArea; function onChanged() { if(window.windowReady && window.fillScreen) window.fillDesktop(); } }
    visible: true; color: Theme.dark
    font.family: Theme.ui
    onActiveChanged: if(active) { Theme.reload(); WindowPreferences.reload(); }
    palette.window: Theme.dark
    palette.base: Theme.dark
    palette.button: Theme.insetPanel
    palette.text: Theme.paper
    palette.windowText: Theme.paper
    palette.buttonText: Theme.paper
    palette.highlight: Theme.brass
    TermsPopup {
        id: termsPopup
        startupAcknowledgment: window.tutorial && !backend.state.termsAcknowledged
        visible: startupAcknowledgment
    }
    function openAbout() {
        if (backend.state.host) hostAboutPopup.open();
        else backend.navigate("about");
    }
    Popup {
        id: hostAboutPopup
        objectName: "hostAboutPopup"
        parent: Overlay.overlay; anchors.centerIn: parent
        width: Math.min(840,parent.width-24); height: Math.min(800,parent.height-48)
        modal: true; focus: true
        background: ChamferPopup {}
        AboutView { anchors.fill: parent; anchors.topMargin: 30; s: backend.state; onShowTerms: termsPopup.open() }
        GUButton { anchors.top: parent.top; anchors.right: parent.right; width: 34; height: 30; text: "Close About"; iconName: "close"; iconOnly: true; onClicked: hostAboutPopup.close() }
    }
    LauncherUpgrade { s: backend.state }
    Popup {
        id: closeDownloadsPopup
        objectName: "closeDownloadsPopup"
        parent: Overlay.overlay; anchors.centerIn: parent
        width: Math.min(540, window.width-32); height: 260
        modal: true; focus: true; closePolicy: Popup.NoAutoClose
        visible: !!backend.state.closeDownloadConfirm && !backend.state.closing
        background: ChamferPopup { edgeColor: Theme.brass }
        GText { x: 24; y: 22; width: parent.width-48; text: "Close while downloads are queued?"; font.family: Theme.heading; font.pixelSize: Theme.scaledFont(25); wrapMode: Text.WordWrap }
        GText { x: 24; y: 86; width: parent.width-48; text: "Closing stops the active download and removes queued downloads. Verified partial files stay in the Game Directory so you can resume later."; wrapMode: Text.WordWrap; font.pixelSize: Theme.typeSmall; color: Theme.muted }
        GUButton { objectName: "keepDownloadingAction"; x: 24; y: parent.height-66; width: 210; height: 42; text: "Keep downloading"; onClicked: backend.confirmCloseDownloads(false) }
        GUButton { objectName: "closeCancelDownloadsAction"; x: parent.width-234; y: parent.height-66; width: 210; height: 42; text: "Close and cancel"; onClicked: backend.confirmCloseDownloads(true) }
    }
    Popup {
        parent: Overlay.overlay
        anchors.centerIn: parent
        width: Math.min(430,window.width-24); height: 190
        modal: true; focus: true; closePolicy: Popup.NoAutoClose
        visible: !!backend.state.repairing && !backend.state.closing
        background: ChamferPopup { edgeColor: Theme.brass }
        GText { x: 20; y: 20; width: parent.width-40; text: "Repair Network/Wipe VLA"; font.family: Theme.heading; font.pixelSize: Theme.scaledFont(24) }
        BusyIndicator { x: 20; y: 68; width: 36; height: 36; running: parent.visible }
        GText { x: 72; y: 68; width: parent.width-92; wrapMode: Text.WordWrap; text: backend.state.status; font.pixelSize: Theme.typeSmall }
        GText { x: 20; y: 144; width: parent.width-40; text: "Approve Windows permission if asked."; color: Theme.brass; font.pixelSize: Theme.typeSmall }
    }
    Popup {
        id: cleanupPopup
        objectName: "cleanupConfirmPopup"
        parent: Overlay.overlay
        x: (window.width-width)/2; y: (window.height-height)/2
        width: Math.min(640,window.width-32); height: Math.min(window.height-48, cleanupBody.implicitHeight+210)
        modal: true; focus: true; closePolicy: Popup.NoAutoClose
        visible: !!backend.state.cleanupConfirm
        background: ChamferPopup { edgeColor: Theme.brass }
        Text { x: 24; y: 22; text: "Clean up this PC?"; font.family: Theme.heading; font.pixelSize: Theme.typeHeading; color: Theme.paper }
        GText { id: cleanupBody; x: 24; y: 80; width: parent.width-48; wrapMode: Text.WordWrap; font.pixelSize: Theme.typeSmall; text: backend.state.cleanupConfirm ? backend.state.cleanupConfirm.lines.join("\n") : "" }
        GText { x: 24; y: cleanupBody.y+cleanupBody.height+16; width: parent.width-48; color: Theme.brass; font.pixelSize: Theme.typeSmall; text: "Windows will ask for permission once. Continue?" }
        GUButton { objectName: "cleanupCancelAction"; x: 24; y: parent.height-72; width: 200; height: 48; text: "Cancel"; edge: "left"; onClicked: backend.cancelCleanup() }
        GUButton { objectName: "cleanupConfirmAction"; x: parent.width-224; y: parent.height-72; width: 200; height: 48; text: "Yes"; edge: "right"; primary: true; onClicked: backend.confirmCleanup() }
    }
    Loader {
        id: glassLoader
        anchors.fill: parent
        visible: !backend.state.host
        active: startupPhase > 0
        sourceComponent: GlassSurface { objectName: "launcherGlassBackground" }
    }
    FocusScope {
        objectName: "launcherStartupCurtain"
        anchors.fill: parent
        z: 1000
        visible: window.startupLoading
        focus: visible
        Keys.onPressed: event => { event.accepted = true; }
        Rectangle { anchors.fill: parent; color: Theme.dark }
        MouseArea { anchors.fill: parent; acceptedButtons: Qt.AllButtons; onWheel: wheel => { wheel.accepted = true; } }
        Column {
            anchors.centerIn: parent; spacing: 14
            GText {
                anchors.horizontalCenter: parent.horizontalCenter
                    text: backend.state.host ? "Loading NN LAN Launcher Host…" : "Loading NN LAN Launcher Client…"
                font.family: Theme.heading; font.pixelSize: Theme.typeHeading
            }
            BusyIndicator { anchors.horizontalCenter: parent.horizontalCenter; running: window.startupLoading }
        }
    }
    Timer {
        // A missing theme asset must not leave startup covered indefinitely.
        interval: 12000; running: window.startupLoading
        onTriggered: window.startupPhase = 2
    }
    Rectangle { objectName: "hostFlatBackground"; anchors.fill: parent; visible: backend.state.host; color: Theme.dark }
    title: tutorial ? "NN LAN Launcher Quick Start " + backend.state.version : "NN LAN Launcher " + (backend.state.host ? "Host " : "Client ") + backend.state.version + (backend.state.preview ? " · DESIGN PREVIEW" : "")
    onClosing: function(close) { if (!backend.state.closing) {close.accepted=false;backend.requestClose();} }
    Panel {
        objectName: "hoverDescriptionPanel"
        scale: .7; transformOrigin: Item.BottomRight
        z: 500; anchors.right: parent.right; anchors.bottom: parent.bottom
        anchors.margins: 18; width: Math.min(360,window.width-36); height: descriptionText.implicitHeight+18
        visible: HoverHelp.description.length>0
        fill: Theme.descriptionSurface; stroke: Theme.border; cut: 8
        GText { id: descriptionText; objectName: "hoverDescriptionText"; anchors.left: parent.left; anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; anchors.margins: 12; text: HoverHelp.description; wrapMode: Text.WordWrap; font.pixelSize: Theme.typeSmall; maximumLineCount: 3; elide: Text.ElideRight }
    }
    Popup {
        id: roomPasswordPopup
        objectName: "clientRoomPasswordPopup"
        parent: Overlay.overlay
        x: (window.width-width)/2; y: (window.height-height)/2
        width: Math.min(460,window.width-32); height: 260
        z: 100
        property var prompt: backend.state.host || backend.state.closing ? null : backend.state.roomPasswordPrompt
        readonly property bool waiting: !!(prompt && prompt.waiting)
        readonly property bool submitting: !!(prompt && prompt.busy)
        function submit() {
            if (!prompt || waiting || submitting || !clientRoomPassword.text.length) return;
            const password = clientRoomPassword.text;
            clientRoomPassword.clear();
            backend.submitRoomPassword(password);
        }
        visible: !!prompt
        modal: true; focus: true; closePolicy: Popup.NoAutoClose
        onOpened: if (!waiting) clientRoomPassword.forceActiveFocus()
        onClosed: clientRoomPassword.clear()
        onSubmittingChanged: if (!submitting && visible && !waiting) clientRoomPassword.forceActiveFocus()
        background: ChamferPopup { edgeColor: Theme.brass }
        ColumnLayout {
            anchors.fill: parent; anchors.margins: 20; spacing: 10
            GText { Layout.fillWidth: true; text: roomPasswordPopup.waiting ? "Waiting for host approval" : "Enter room password"; font.family: Theme.heading; font.pixelSize: Theme.typeHeading; wrapMode: Text.WordWrap }
            GText { Layout.fillWidth: true; text: roomPasswordPopup.prompt ? roomPasswordPopup.prompt.name || "" : ""; elide: Text.ElideRight }
            GUField {
                id: clientRoomPassword
                objectName: "clientRoomPasswordField"
                Layout.fillWidth: true
                placeholderText: "Room password"
                echoMode: TextInput.Password; maximumLength: 256
                inputMethodHints: Qt.ImhSensitiveData | Qt.ImhNoPredictiveText
                visible: !roomPasswordPopup.waiting
                enabled: !roomPasswordPopup.submitting
                onAccepted: roomPasswordPopup.submit()
            }
            GText {
                Layout.fillWidth: true; Layout.fillHeight: true
                text: roomPasswordPopup.prompt ? roomPasswordPopup.prompt.status || "" : ""
                color: Theme.muted; font.pixelSize: Theme.typeSmall; wrapMode: Text.WordWrap
            }
            RowLayout {
                Layout.fillWidth: true; spacing: 12
                GUButton { objectName: "clientCancelRoomPasswordAction"; Layout.fillWidth: true; text: window.tutorial ? "Back" : "Cancel"; iconOnly: false; edge: "left"; onClicked: window.tutorial ? backend.backLesson() : backend.cancelRoomPassword() }
                GUButton { objectName: "clientSubmitRoomPasswordAction"; Layout.fillWidth: true; text: roomPasswordPopup.submitting ? "Checking…" : "Join"; iconOnly: false; primary: true; edge: "right"; visible: !roomPasswordPopup.waiting; enabled: clientRoomPassword.enabled && clientRoomPassword.text.length>0; onClicked: roomPasswordPopup.submit() }
            }
        }
    }
    Popup {
        objectName: "applicationMessagePopup"
        parent: Overlay.overlay
        x: (window.width-width)/2; y: (window.height-height)/2
        width: Math.min(600,window.width-32); height: backend.state.host && backend.state.dialog.stage ? 360 : 300
        modal: false; focus: true; visible: !!backend.state.dialog.title
        closePolicy: Popup.CloseOnEscape
        onClosed: if (backend.state.dialog.title) backend.dismissDialog()
        background: ChamferPopup { edgeColor: Theme.brass }
        GText { x: 20; y: 20; width: parent.width-(backend.state.dialog.stage && !backend.state.host ? 250 : 90); text: backend.state.dialog.title || ""; font.pixelSize: Theme.scaledFont(26); wrapMode: Text.WordWrap }
        GUButton { x: parent.width-54; y: 12; width: 36; height: 32; text: "Close message"; edge: "right"; iconName: "close"; onClicked: backend.dismissDialog() }
        GText { x: 20; y: 80; width: parent.width-40; height: 125; text: backend.state.dialog.message || ""; font.pixelSize: Theme.typeSmall; wrapMode: Text.WordWrap; elide: Text.ElideRight; maximumLineCount: 6 }
        GText {
            objectName: "applicationMessageDetail"
            x: 20; y: 212; width: parent.width-40; height: 76
            visible: !!backend.state.dialog.stage
            text: (backend.state.dialog.hint ? backend.state.dialog.hint + "\n" : "")
                  + "Stage: " + (backend.state.dialog.stage || "") + (backend.state.dialog.code ? " (" + backend.state.dialog.code + ")" : "")
            color: Theme.brass; font.pixelSize: Theme.typeSmall; wrapMode: Text.WordWrap; elide: Text.ElideRight; maximumLineCount: 4
        }
        GUButton { objectName: "dialogDiagnoseButton"; x: backend.state.host ? 20 : parent.width-220; y: backend.state.host ? parent.height-54 : 12; width: backend.state.host ? parent.width-40 : 160; height: 36; text: backend.state.host ? "Repair Network/Wipe VLA" : "Run diagnostic"; edge: "left"; iconName: backend.state.host ? "repair" : "search"; iconOnly: false
            visible: !!backend.state.dialog.stage; onClicked: { if(backend.state.host) backend.wipeVLA(); else backend.diagnoseFromDialog(); } }
    }
    MouseArea {
        z: 200; x: 0; y: 0; width: Math.max(0,window.width-160); height: 40
        enabled: !window.fillScreen
        property real pressGlobalX
        property real pressGlobalY
        property real pressWindowX
        property real pressWindowY
        onPressed: function(mouse) {
            const point = mapToGlobal(mouse.x, mouse.y);
            pressGlobalX = point.x; pressGlobalY = point.y;
            pressWindowX = window.x; pressWindowY = window.y;
        }
        onPositionChanged: function(mouse) {
            if (!pressed) return;
            const point = mapToGlobal(mouse.x, mouse.y);
            window.x = Math.round(pressWindowX + point.x - pressGlobalX);
            window.y = Math.round(pressWindowY + point.y - pressGlobalY);
        }
        onReleased: window.snapToDesktopCorner()
    }
    Row {
        z: 201; anchors.top: parent.top; anchors.right: parent.right
        anchors.topMargin: 5; anchors.rightMargin: 8; spacing: 6
        GUButton {
            width: 34; height: 28; padding: 3; text: "Minimize window"; iconOnly: true; iconName: "minimize"
            Accessible.name: "Minimize window"
            onClicked: window.showMinimized()
        }
        GUButton {
            objectName: "windowFillScreenButton"
            width: 34; height: 28; padding: 3; iconOnly: true; iconName: window.fillScreen ? "window-restore" : "window-expand"
            text: window.fillScreen ? "Restore window" : "Fill screen"
            Accessible.name: text
            visible: !backend.state.host
            onClicked: WindowPreferences.setFillScreen(!window.fillScreen)
        }
        GUButton {
            objectName: "windowCloseButton"
            width: 38; height: 28; padding: 3
            iconOnly: true; iconName: "close"; text: "Close application"; edge: "right"
            enabled: !backend.state.closing
            Accessible.name: "Close application"
            onClicked: window.close()
        }
    }
    MouseArea {
        z: 200; anchors.right: parent.right; anchors.bottom: parent.bottom
        width: 22; height: 22; cursorShape: Qt.SizeFDiagCursor
        visible: !window.fillScreen
        property real startX
        property real startY
        property real startWidth
        onPressed: function(mouse) {
            let point=mapToGlobal(mouse.x,mouse.y);
            startX=point.x; startY=point.y; startWidth=window.width;
        }
        onPositionChanged: function(mouse) {
            if (!pressed) return;
            let point=mapToGlobal(mouse.x,mouse.y);
            let dx=point.x-startX;
            let dy=(point.y-startY)*window.aspectRatio;
            let change=Math.abs(dx)>Math.abs(dy) ? dx : dy;
            window.width=Math.max(window.minimumWidth,Math.round(startWidth+change));
        }
        Canvas { anchors.fill: parent; onPaint: { let c=getContext("2d"); c.strokeStyle=String(Theme.brass); c.lineWidth=.6; for(let i=5;i<=13;i+=4){c.beginPath();c.moveTo(width-i,height-2);c.lineTo(width-2,height-i);c.stroke()} } }
    }
    Row {
        id: topNavigation
        x: 0; y: 0; z: 202; spacing: 0
        width: root.sidebarWidth
        visible: !backend.state.host
        scale: root.scale; transformOrigin: Item.TopLeft
        Repeater {
            model: [{key:"library",label:"Library",icon:"grid"},{key:"room",label:"Room and players",icon:"network"},{key:"downloads",label:"Downloads",icon:"downloads"},{key:"settings",label:"Settings",icon:"settings"}]
            DiamondButton {
                required property var modelData
                objectName: "nav-"+modelData.key
                width: topNavigation.width/4; height: 54
                text: modelData.label; iconName: modelData.icon
                selected: root.s.page===modelData.key || (modelData.key==="library" && ["details","gameSettings","catalog","editor"].indexOf(root.s.page)>=0)
                enabled: !window.tutorial || (modelData.key === "settings" && root.s.tutorialStage === "clientSettings")
                onClicked: backend.navigate(modelData.key)
            }
        }
    }
    HostView {
        visible: backend.state.host
        width: 463; height: 1040; anchors.centerIn: parent
        anchors.verticalCenterOffset: 0
        scale: Math.min(window.width/width,(window.height-40)/height)
        s: backend.state
    }
    Item {
        id: root
        visible: !backend.state.host
        property var s: backend.state
        property bool showGameList: true
        property string activePage: s.page
        onActivePageChanged: HoverHelp.clear()
        // Keep controls uniformly scaled. Screen-fill extends the stage along
        // the extra axis so its panels reach every edge without stretching art.
        property real sidebarFooterY: height-132
        readonly property real sidebarWidth: 182 * 1.2
        readonly property real layoutScale: Math.min(window.width/1920,window.height/1080)
        width: window.fillScreen ? window.width/layoutScale : 1920
        height: window.fillScreen ? window.height/layoutScale : 1080
        anchors.centerIn: parent
        scale: layoutScale
        Rectangle {
            objectName: "launcherSidebar"
            x: 0; y: 0; width: root.sidebarWidth; height: root.height; color: Theme.sidebarSurface; border.width: 0
            enabled: !window.tutorial
            opacity: enabled ? 1 : .45
            Rectangle { anchors.right: parent.right; width: .6; height: parent.height; color: Theme.border }
            Image { visible: !root.showGameList; x: 7; y: 244; width: 168; height: 185; source: Theme.geometryPath }
            Text { visible: !root.showGameList; x: 73; y: 309; text: "A"; font.family: Theme.display; font.pixelSize: Theme.scaledFont(47); color: Theme.brass }
            ListView {
                id: sidebarGames; objectName: "sidebarGameList"
                x: 6; y: 64; width: parent.width-12; height: root.sidebarFooterY-y-12
                visible: root.showGameList; clip: true; spacing: 2
                model: root.s.allGames
                currentIndex: {
                    for (let i=0; i<root.s.allGames.length; i++)
                        if (root.s.allGames[i].id === root.s.selected.id) return i;
                    return -1;
                }
                onCurrentIndexChanged: if (currentIndex >= 0) positionViewAtIndex(currentIndex,ListView.Contain)
                ScrollBar.vertical: ScrollBar { width: 5 }
                delegate: Rectangle {
                    required property var modelData
                    width: sidebarGames.width; height: 20; radius: 3
                    color: modelData.id === root.s.selected.id ? Theme.selectedRow : gameMouse.containsMouse ? Theme.rowHover : "transparent"
                    Image { id: sidebarPlayerIcon; x: 3; y: (parent.height-height)/2; width: sidebarGameName.contentHeight; height: sidebarGameName.contentHeight; visible: modelData.playing > 0; source: "../assets/controls/user-green.svg" }
                    Rectangle { id: sidebarGameIcon; x: 3+sidebarGameName.contentHeight+4; y: (parent.height-height)/2; width: sidebarGameName.contentHeight; height: sidebarGameName.contentHeight; color: Theme.dark
                        Image { anchors.fill: parent; source: modelData.icon || modelData.art; fillMode: Image.PreserveAspectCrop }
                        GText { anchors.centerIn: parent; visible: !(modelData.icon || modelData.art); text: modelData.name.charAt(0); color: Theme.brass; font.pixelSize: Theme.scaledFont(Math.max(4, Math.round(sidebarGameIcon.height*0.75))) }
                    }
                    GText { id: sidebarGameName; x: sidebarGameIcon.x+sidebarGameIcon.width+5; anchors.verticalCenter: parent.verticalCenter; width: parent.width-x-4; text: modelData.name; elide: Text.ElideRight; font.pixelSize: Theme.typeCaption }
                    MouseArea { id: gameMouse; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onEntered: HoverHelp.begin(gameMouse,modelData.name+" — open game details."); onExited: HoverHelp.end(gameMouse); onClicked: { HoverHelp.end(gameMouse); backend.selectGame(modelData.id); } }
                }
            }
            Rectangle { x: 15; y: root.sidebarFooterY+0; width: parent.width-30; height: .6; color: Theme.brass }
            Rectangle { x: 20; y: root.sidebarFooterY+21; width: 8; height: 8; radius: 4; color: root.s.connected ? Theme.green : Theme.muted }
            GText { objectName: "sidebarPcName"; x: 40; y: root.sidebarFooterY+15; height: 20; verticalAlignment: Text.AlignVCenter; width: parent.width-x-12; elide: Text.ElideRight; text: root.s.pcName; font.pixelSize: Theme.typeCaption }
            HoverHint { x: 12; y: root.sidebarFooterY+12; width: parent.width-24; height: 26; anchors.fill: undefined; description: root.s.connected ? "Connected to the LAN room." : "Not connected to a LAN room." }
            Image { x: 18; y: root.sidebarFooterY+45; width: 12; height: 12; source: Theme.iconPath+"key.svg" }
            CopyText { objectName: "sidebarRoomCode"; x: 40; y: root.sidebarFooterY+41; width: parent.width-x-12; height: 20; verticalAlignment: Text.AlignVCenter; elide: Text.ElideMiddle; text: root.s.roomCode || ""; description: "Copy room code"; font.family: Theme.code; font.pixelSize: Theme.typeCaption; normalColor: Theme.brass }
            AbstractButton {
                objectName: "sidebarRoomPlayersAction"
                x: 12; y: root.sidebarFooterY+65; width: parent.width-24; height: 28
                text: "Open Room and players"; Accessible.name: text; hoverEnabled: true
                onClicked: backend.navigate("room")
                contentItem: Row {
                    spacing: 10
                    Image { width: 16; height: 16; anchors.verticalCenter: parent.verticalCenter; source: Theme.iconPath+"people.svg" }
                    GText { text: String(root.s.playerCount); color: parent.parent.hovered ? Theme.brass : Theme.muted; font.pixelSize: Theme.typeSmall; anchors.verticalCenter: parent.verticalCenter }
                }
                leftPadding: 6; rightPadding: 6; topPadding: 4; bottomPadding: 4
            }
            AbstractButton {
                objectName: "sidebarAboutAction"
                anchors.horizontalCenter: parent.horizontalCenter
                y: root.sidebarFooterY+92; width: 50; height: 34
                text: "About NN LAN Launcher"; Accessible.name: text; hoverEnabled: true
                onClicked: backend.navigate("about")
                contentItem: Image { source: Theme.emblemPath; sourceClipRect: Qt.rect(110, 290, 1020, 680); fillMode: Image.PreserveAspectFit; opacity: parent.down ? .65 : parent.hovered ? 1 : .85 }
            }
        }
        Loader {
            id: pageLoader; objectName: "pageLoader"
            x: root.sidebarWidth+36; y: 44
            width: root.width-x-36; height: root.height-y-22
            sourceComponent: root.s.page==="library" ? libraryPage : root.s.page==="details" ? detailsPage : root.s.page==="room" ? roomPage : root.s.page==="about" ? aboutPage : root.s.page==="settings" ? settingsPage : root.s.page==="downloads" ? downloadsPage : root.s.page==="gameSettings" ? gameSettingsPage : root.s.page==="catalog" ? catalogPage : root.s.page==="editor" ? editorPage : settingsPage
        }

        Component { id: libraryPage; LibraryView { s: root.s } }
        Popup {
            id: firstLaunchSetup
            objectName: "firstLaunchSetupPopup"
            parent: Overlay.overlay
            x: 0; y: 0; width: window.width; height: window.height
            padding: 0; z: 500
            visible: !window.tutorial && !root.s.host && root.s.page === "setup"
            modal: true; focus: true; closePolicy: Popup.NoAutoClose
            background: Rectangle { color: Theme.dark }
            contentItem: Item {
                SetupView {
                    anchors.centerIn: parent
                    width: Math.min(1100, parent.width - 48)
                    height: Math.min(650, parent.height - 48)
                    s: root.s
                }
            }
        }
        Component { id: detailsPage; DetailsView { s: root.s } }
        Component { id: roomPage; RoomView { s: root.s } }
        Component { id: aboutPage; AboutView { s: root.s; onShowTerms: termsPopup.open() } }

        Component { id: settingsPage; SettingsView { s: root.s } }
        Component { id: downloadsPage; DownloadsView { s: root.s } }
        Component { id: gameSettingsPage; GameSettingsView { s: root.s } }
        Component { id: catalogPage; CatalogView { s: root.s } }
        Component { id: editorPage; EditorView { s: root.s } }
        Rectangle {
            anchors.fill: parent; visible: root.s.closing; color: Theme.closingOverlay; z: 100
            MouseArea { anchors.fill: parent }
            Text { anchors.centerIn: parent; text: "Closing your room safely…"; font.family: Theme.heading; font.pixelSize: Theme.typeHeading; color: Theme.paper }
        }
    }
    Text {
        objectName: "bottomDownloadsLink"
        anchors.horizontalCenter: parent.horizontalCenter; anchors.bottom: parent.bottom; anchors.bottomMargin: 3
        z: 50; visible: !backend.state.host; enabled: !window.tutorial && !backend.state.closing
        text: "Downloads"; font.family: Theme.ui; font.pixelSize: Theme.typeSmall
        color: downloadsMouse.containsMouse ? Theme.paper : Theme.brass
        font.underline: downloadsMouse.containsMouse
        Accessible.role: Accessible.Link; Accessible.name: text
        function activate() { if (enabled) backend.navigate("downloads"); }
        activeFocusOnTab: true
        Keys.onReturnPressed: activate()
        Keys.onSpacePressed: activate()
        Accessible.onPressAction: activate()
        MouseArea { id: downloadsMouse; anchors.fill: parent; anchors.margins: -4; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: parent.activate() }
    }
    Text {
        objectName: "versionAboutLink"
        anchors.right: parent.right; anchors.bottom: parent.bottom; anchors.margins: 8; z: 50
        text: "LAN " + (root.s.host ? "Host " : "Client ") + root.s.version + (window.tutorial ? " · practice" : root.s.preview ? " · preview" : "")
        font.pixelSize: Theme.typeCaption; color: versionPointer.containsMouse ? Theme.brass : Theme.muted
        enabled: !window.tutorial && !backend.state.closing; activeFocusOnTab: true
        Accessible.role: Accessible.Link; Accessible.name: "About NN LAN Launcher"
        function activate() { if(enabled) window.openAbout(); }
        Keys.onReturnPressed: activate()
        Keys.onSpacePressed: activate()
        Accessible.onPressAction: activate()
        MouseArea { id: versionPointer; anchors.fill: parent; anchors.margins: -4; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: parent.activate() }
    }
    Loader {
        anchors.fill: parent; z: 201
        active: window.tutorial
        sourceComponent: TutorialGuide { s: backend.state }
    }
}

