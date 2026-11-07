import QtQuick
import QtQuick.Controls
Item {
    anchors.fill: parent
    id: view
    property var s
    readonly property bool practiceKey: !s.tutorial || s.tutorialStage === "clientKey"
    onPracticeKeyChanged: if (s.tutorial && practiceKey) roomKey.text = s.tutorialRoomKey
    readonly property bool practiceFind: !s.tutorial || s.tutorialStage === "clientFind"
    property bool roomFailed: !!(view.s && view.s.dialog && view.s.dialog.error)
    onSChanged: {
        if (s && s.hostChoiceVisible && !hostPicker.opened) hostPicker.open()
        else if (s && !s.hostChoiceVisible && hostPicker.opened) hostPicker.close()
    }
    Panel {
        objectName: "roomStatusPanel"
        anchors.left: parent.left; anchors.right: parent.right; height: 90
        IconLabel { x: 296; y: 20; iconName: view.s.connected ? "check" : "network"; text: view.s.busy ? "Connecting…" : view.s.connected ? "Connected to your room" : "Join your host's room"; textColor: Theme.paper }
        GText { x: 296; y: 51; width: parent.width - 318; text: view.s.status; elide: Text.ElideRight; color: Theme.muted; font.pixelSize: Theme.typeSmall }
        // One button: Find host (green) -> Leave Room (red) when connected -> Retry (amber) after a failed attempt.
        GUButton { objectName: "findHostAction"; x: 22; y: 23; width: 250; edge: "center"
            text: view.s.connected ? "Leave Room" : view.roomFailed ? "Retry" : "Find host automatically"
            iconName: view.s.connected ? "room-leave" : "search"
            accent: view.s.connected ? Theme.red : view.roomFailed ? Theme.warning : Theme.green
            enabled: view.practiceFind && (!view.s.busy || view.s.downloadActive)
            onClicked: view.s.connected ? leaveConfirm.open() : backend.findLanHost() }
    }
    Panel {
        objectName: "roomJoinPanel"
        x: 0; y: 110; width: (view.width-36)*365/1028; height: view.height-232
        GText { x: 22; y: 20; text: "Join a room"; font.pixelSize: Theme.scaledFont(18); font.weight: Font.DemiBold }
        GText { x: 22; y: 54; width: 321; text: "Use a room key for internet play, or find a host on your local network."; color: Theme.muted; wrapMode: Text.WordWrap; font.pixelSize: Theme.typeSmall }
        GText { x: 22; y: 105; text: "Room key" }
        GUField { id: roomKey; objectName: "roomKeyField"; x: 22; y: 132; width: 321; font.family: Theme.code; placeholderText: "8056-c2e2-1c00-0001"; helpText: "Paste the room key shown on the Host."; enabled: view.practiceKey && !view.s.connected && !view.s.busy; opacity: !view.s.tutorial || enabled ? 1 : .45; selectByMouse: true; onAccepted: if(joinKey.enabled) backend.joinRoomKey(text) }
        GUButton { id: joinKey; objectName: "joinRoomKeyAction"; x: 22; y: 180; width: 321; text: "Join room key"; edge: "center"; iconName: "key"; primary: true; enabled: view.practiceKey && !view.s.connected && !view.s.busy && roomKey.text.trim().length>0; onClicked: backend.joinRoomKey(roomKey.text) }
        Rectangle { x: 22; y: 242; width: 321; height: 1; color: Theme.border }
        GText { x: 22; y: 263; text: "On the same local network"; font.pixelSize: Theme.scaledFont(18); font.weight: Font.DemiBold }
        GUField { id: hostAddress; objectName: "hostIpField"; x: 22; y: 304; width: 185; font.family: Theme.code; placeholderText: "Host LAN IP · 192.168.1.10"; enabled: !view.s.tutorial && !view.s.connected && !view.s.busy; opacity: !view.s.tutorial ? 1 : .45; onAccepted: if(connectIp.enabled) backend.connectHostIp(text) }
        GUButton { id: connectIp; objectName: "connectHostIpAction"; x: 219; y: 304; width: 124; text: "Connect"; edge: "right"; helpText: "Connect to the Host at this LAN IP."; iconName: "connect"; enabled: !view.s.tutorial && !view.s.connected && !view.s.busy && hostAddress.text.trim().length>0; onClicked: backend.connectHostIp(hostAddress.text) }
    }
    Panel {
        x: (view.width-36)*365/1028+18; y: 110; width: (view.width-36)*315/1028; height: view.height-232
        GText { x: 22; y: 20; text: "Players ("+view.s.playerCount+")"; font.pixelSize: Theme.scaledFont(18); font.weight: Font.DemiBold }
        CopyText { objectName: "clientRoomCodeCopy"; x: 22; y: 49; width: 271; height: 34; verticalAlignment: Text.AlignVCenter; text: view.s.roomCode ? "Room: "+view.s.roomCode : "No active room"; copyValue: view.s.roomCode || ""; description: "Copy room code"; normalColor: Theme.muted; font.family: Theme.code; font.pixelSize: Theme.typeSmall; elide: Text.ElideMiddle }
        ListView { x: 22; y: 110; width: 271; height: parent.height-132; clip: true; spacing: 8; model: view.s.players
            delegate: Rectangle { required property var modelData; width: 271; height: 59; color: Theme.insetPanel; radius: 4
                Rectangle { x: 12; y: 11; width: 36; height: 36; radius: 3; color: Theme.panel; clip: true; border.color: Theme.brass; border.width: .6
                    Image { anchors.fill: parent; anchors.margins: 1; visible: !!modelData.avatar; source: modelData.avatar || ""; fillMode: Image.PreserveAspectCrop; asynchronous: true }
                    Text { anchors.centerIn: parent; visible: !modelData.avatar; text: String(modelData.name || "Player").substring(0,2).toUpperCase(); font.family: Theme.display; font.pixelSize: Theme.typeSmall; color: Theme.brass }
                }
                GText { x: 56; y: 10; width: 126; text: modelData.name || "Player"; elide: Text.ElideRight }
                GText { x: 199; y: 10; width: 60; horizontalAlignment: Text.AlignRight; text: modelData.ping_ms === undefined || modelData.ping_ms === null ? "—" : modelData.ping_ms + " ms"; font.pixelSize: Theme.typeSmall; color: Theme.green }
                Row { x: 190; y: 36; spacing: 2
                    Item { width: 17; height: 17
                        StatusLight { anchors.centerIn: parent; scale: 0.8; color: modelData.seedingActive ? "#FF2E9E57" : "#FF5A5F66"; glow: modelData.seedingActive === true
                            Text { anchors.centerIn: parent; text: "\u2191"; color: "#FFFFFF"; font.pixelSize: Theme.typeSmall; font.bold: true } } }
                    Repeater { model: (modelData.seeding || []).slice(0, 1)
                        Rectangle { width: 12; height: 12; radius: 2; color: Theme.panel; clip: true
                            Image { anchors.fill: parent; source: modelData.icon || ""; visible: source !== ""; fillMode: Image.PreserveAspectFit; asynchronous: true }
                            Text { anchors.centerIn: parent; visible: !modelData.icon; text: String(modelData.name || "?").substring(0, 1).toUpperCase(); font.pixelSize: Theme.scaledFont(7); color: Theme.brass } } }
                    Item { width: 6; height: 1 }
                    Item { width: 17; height: 17
                        StatusLight { anchors.centerIn: parent; scale: 0.8; color: modelData.leechingActive ? "#FF2E9E57" : "#FF5A5F66"; glow: modelData.leechingActive === true
                            Text { anchors.centerIn: parent; text: "\u2193"; color: "#FFFFFF"; font.pixelSize: Theme.typeSmall; font.bold: true } } }
                    Repeater { model: (modelData.leeching || []).slice(0, 1)
                        Rectangle { width: 12; height: 12; radius: 2; color: Theme.panel; clip: true
                            Image { anchors.fill: parent; source: modelData.icon || ""; visible: source !== ""; fillMode: Image.PreserveAspectFit; asynchronous: true }
                            Text { anchors.centerIn: parent; visible: !modelData.icon; text: String(modelData.name || "?").substring(0, 1).toUpperCase(); font.pixelSize: Theme.scaledFont(7); color: Theme.brass } } }
                }
                GText { x: 56; y: 34; width: 128; text: modelData.state + (modelData.game ? " · "+modelData.game : ""); font.pixelSize: Theme.typeCaption; color: Theme.muted; elide: Text.ElideRight }
            }
            ScrollBar.vertical: ScrollBar {}
        }
        GText { x: 22; y: 125; width: 271; wrapMode: Text.WordWrap; text: "Connected players and their activity will appear here."; visible: view.s.players.length===0; color: Theme.muted }
    }
    Panel {
        id: roomOverview
        objectName: "roomConnectionGraphic"
        x: (view.width-36)*680/1028+36; y: 110; width: (view.width-36)*312/1028; height: view.height-232
        readonly property bool compact: height < 610
        readonly property color signalColor: view.roomFailed ? Theme.red : view.s.connected ? Theme.green : view.s.busy ? Theme.brass : Theme.muted
        GText { x: 20; y: 20; text: "ROOM OVERVIEW"; font.pixelSize: Theme.typeSmall; font.weight: Font.DemiBold; color: Theme.brass }
        GText { x: 20; y: 48; width: parent.width-40; text: view.s.connected ? "Connected to the room" : view.s.busy ? "Finding your room…" : view.roomFailed ? "Connection needs attention" : "Ready to connect"; font.pixelSize: Theme.scaledFont(18); font.weight: Font.DemiBold; elide: Text.ElideRight }
        GText { x: 20; y: 83; width: parent.width-40; text: view.s.connected ? (view.s.roomCode ? "Room " + view.s.roomCode : "Room connection active") : view.s.busy ? view.s.status : "Find a host or enter a room key to begin."; color: Theme.muted; font.pixelSize: Theme.typeSmall; elide: Text.ElideRight }
        Canvas {
            id: rings
            x: (parent.width-width)/2; y: roomOverview.compact ? 112 : 132; width: roomOverview.compact ? 180 : 230; height: width
            property color ink: roomOverview.signalColor
            property real pulse: 0
            property var compass: view.s.compass || ({players: [], links: []})
            property real flow: 0
            NumberAnimation on flow { from: 0; to: 1; duration: 1400; loops: Animation.Infinite
                running: rings.visible && rings.compass.links.length > 0 }
            onCompassChanged: requestPaint()
            onFlowChanged: requestPaint()
            NumberAnimation on pulse { from: 0; to: 1; duration: 1800; loops: Animation.Infinite; running: view.s.busy && view.visible }
            onInkChanged: requestPaint()
            onPulseChanged: requestPaint()
            onPaint: {
                let c=getContext("2d");c.clearRect(0,0,width,height);
                c.lineWidth=1;
                let scale = width/230;
                for(let r of [34,58,82,106]) {
                    c.strokeStyle=String(Theme.alpha(ink, view.s.connected ? .30 : .16));
                    c.beginPath();c.arc(width/2,height/2,r*scale,0,Math.PI*2);c.stroke();
                }
                if(view.s.busy) {
                    c.strokeStyle=String(Theme.alpha(ink, .75*(1-pulse)));
                    c.lineWidth=2;c.beginPath();c.arc(width/2,height/2,(34+72*pulse)*scale,0,Math.PI*2);c.stroke();
                }
                let players = compass.players || [], links = compass.links || [];
                let cx=width/2, cy=height/2, radius=82*scale;
                function point(i) {
                    let a=-Math.PI/2+2*Math.PI*i/Math.max(players.length,1);
                    return [cx+radius*Math.cos(a),cy+radius*Math.sin(a)];
                }
                for (let link of links) {
                    let i=players.findIndex(p => p.ip===link.ip);
                    if (i<0) continue;
                    let p=point(i), inbound=link.direction==="download";
                    let color=inbound ? "#48D887" : "#E7BC53";
                    c.strokeStyle=color;c.lineWidth=2*scale;
                    c.beginPath();c.moveTo(cx,cy);c.lineTo(p[0],p[1]);c.stroke();
                    let t=inbound ? 1-flow : flow;
                    let ax=cx+(p[0]-cx)*t, ay=cy+(p[1]-cy)*t;
                    let angle=Math.atan2(p[1]-cy,p[0]-cx)+(inbound ? Math.PI : 0);
                    c.save();c.translate(ax,ay);c.rotate(angle);c.fillStyle=color;
                    c.beginPath();c.moveTo(6*scale,0);c.lineTo(-4*scale,-4*scale);
                    c.lineTo(-4*scale,4*scale);c.closePath();c.fill();c.restore();
                }
                c.font=Math.max(9,11*scale)+"px sans-serif";c.textAlign="center";
                for (let i=0;i<players.length;i++) {
                    let p=point(i), name=String(players[i].name||"Player");
                    c.fillStyle=String(Theme.brass);c.beginPath();c.arc(p[0],p[1],5*scale,0,Math.PI*2);c.fill();
                    c.fillStyle=String(Theme.paper);
                    c.fillText(name.length>12 ? name.slice(0,11)+"…" : name,p[0],p[1]+17*scale);
                }
                c.fillStyle=String(ink);
                if (!players.length) for(let a of [-Math.PI/2,Math.PI/6,5*Math.PI/6]) {
                    c.beginPath();c.arc(width/2+82*scale*Math.cos(a),height/2+82*scale*Math.sin(a),view.s.connected?3:2,0,Math.PI*2);c.fill();
                }
            }
        }
        Image { x: (parent.width-50)/2; y: roomOverview.compact ? 185 : 230; width: 50; height: 34; source: Theme.emblemPath; sourceClipRect: Qt.rect(110, 290, 1020, 680); fillMode: Image.PreserveAspectFit }
        Rectangle { x: 20; y: 390; width: parent.width-40; height: 1; color: Theme.border; visible: !roomOverview.compact }
        GText { x: 20; y: 410; text: "PLAYERS"; font.pixelSize: Theme.typeSmall; color: Theme.muted; visible: !roomOverview.compact }
        GText { x: 20; y: 435; text: String(view.s.playerCount || 0) + " in the room"; font.pixelSize: Theme.scaledFont(17); color: Theme.paper; visible: !roomOverview.compact }
        GText { x: 20; y: 474; width: parent.width-40; text: view.s.connected && view.s.players.length ? view.s.players.slice(0, 3).map(function(p) { return p.name || "Player"; }).join("  ·  ") : view.s.connected ? "Waiting for players" : "Connect to see room activity"; color: Theme.muted; font.pixelSize: Theme.typeSmall; elide: Text.ElideRight; visible: !roomOverview.compact }
        GUButton { x: 20; y: parent.height-74; width: parent.width-40; height: 38; text: view.s.connected ? (view.s.downloadActive ? "View downloads" : "Browse games") : view.s.busy ? "Connecting…" : "Find a host"; enabled: !view.s.busy; edge: "center"; onClicked: view.s.connected ? backend.navigate(view.s.downloadActive ? "downloads" : "library") : backend.findLanHost() }
        GText { x: 20; y: parent.height-26; width: parent.width-40; horizontalAlignment: Text.AlignHCenter; text: view.s.connected ? "● Connection active" : view.s.busy ? "○ Searching" : view.roomFailed ? "● Connection failed" : "○ Not connected"; color: roomOverview.signalColor; font.pixelSize: Theme.typeCaption }
    }
    Panel {
        objectName: "roomTroubleshootingPanel"
        enabled: !view.s.tutorial; opacity: enabled ? 1 : .45
        x: 0; y: view.height-100; width: view.width; height: 100
        GText { x: 22; y: 20; text: "Connection tools"; font.pixelSize: Theme.scaledFont(18); font.weight: Font.DemiBold }
        GText { x: 22; y: 51; width: 490; text: "Use these if room setup or local network access fails."; wrapMode: Text.WordWrap; color: Theme.muted; font.pixelSize: Theme.typeSmall }
        GUButton { objectName: "prepareVlaAction"; anchors.right: parent.right; anchors.rightMargin: 266; y: 28; width: 214; text: "Prepare VLA"; edge: "center"; iconName: "prepare-vla"; enabled: !view.s.connected && !view.s.busy; onClicked: backend.prepareVLA() }
        GUButton { objectName: "repairLanAction"; anchors.right: parent.right; anchors.rightMargin: 22; y: 28; width: 230; text: "Repair LAN"; edge: "right"; iconName: "repair"; enabled: !view.s.busy; onClicked: backend.repairNetwork() }
    }
    Popup {
        id: hostPicker; anchors.centerIn: parent; width: 560; height: 420; modal: true; focus: true
        closePolicy: Popup.NoAutoClose
        background: ChamferPopup { edgeColor: Theme.brass }
        GText { x: 24; y: 20; text: "Choose a LAN host"; font.pixelSize: Theme.scaledFont(26) }
        GText { x: 24; y: 62; width: parent.width-48; text: "Multiple hosts are available. Select the room you want to join."; color: Theme.muted; wrapMode: Text.WordWrap }
        ListView {
            x: 24; y: 106; width: parent.width-48; height: 238; clip: true; spacing: 8
            model: view.s.hostChoices || []
            delegate: GUButton {
                required property var modelData
                width: ListView.view.width; height: 66; edge: "center"; leftAligned: true
                text: modelData.name + "  ·  " + modelData.address + "  ·  " + modelData.room
                onClicked: backend.chooseLanHost(modelData.id)
            }
            ScrollBar.vertical: ScrollBar {}
        }
        GUButton { x: parent.width-162; y: 360; width: 138; height: 40; text: "Cancel"; onClicked: backend.dismissHostChoices() }
    }
    Popup {
        id: leaveConfirm; anchors.centerIn: parent; width: 590; height: 240; modal: true; focus: true
        background: ChamferPopup { edgeColor: Theme.brass }
        Text { x: 24; y: 22; text: "Leave this room?"; font.family: Theme.heading; font.pixelSize: Theme.typeHeading; color: Theme.paper }
        GText { x: 24; y: 78; width: parent.width - 48; wrapMode: Text.WordWrap; text: view.s.downloadActive ? "Leaving will cancel the active download. Partly downloaded files will remain so you can resume later. Queued downloads will be cleared." : "Downloaded game files will be kept."; color: Theme.muted }
        GUButton { x: 24; y: 158; height: 48; text: "Cancel"; edge: "left"; onClicked: leaveConfirm.close() }
        GUButton { x: 325; y: 158; width: 220; height: 48; text: "Leave Room"; edge: "right"; onClicked: {leaveConfirm.close();backend.leave();} }
    }
}
