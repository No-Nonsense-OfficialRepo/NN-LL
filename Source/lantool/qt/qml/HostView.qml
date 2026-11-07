import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
Item {
 id: view
 objectName: "hostView"
 property var s
 property bool roomFailed: !!(view.s && view.s.dialog && view.s.dialog.error)
 readonly property bool practiceOpen: !s.tutorial || s.tutorialStage === "hostOpen"
 property bool wasConnected: false
 ListModel { id: hostCatalogModel }
 function updateCatalog() {
  if(!s) return;
  let rows=s.catalog || [], same=hostCatalogModel.count===rows.length;
  if(same) for(let i=0;i<rows.length;i++) if(hostCatalogModel.get(i).entry.folder!==rows[i].folder) { same=false; break; }
  if(!same) {
   hostCatalogModel.clear();
   for(let row of rows) hostCatalogModel.append({entry: row});
  } else {
   for(let i=0;i<rows.length;i++) if(JSON.stringify(hostCatalogModel.get(i).entry)!==JSON.stringify(rows[i])) hostCatalogModel.setProperty(i,"entry",rows[i]);
  }
 }
 onSChanged: {
  updateCatalog()
  if (!s) return;
  if (s.connected && !wasConnected) hostPassword.clear();
  if (wasConnected && !s.connected) requirePassword.checked = false;
  wasConnected = s.connected;
 }
 Component.onCompleted: updateCatalog()
 Popup {
  id: launchParameters
  objectName: "hostLaunchParametersPopup"
  property string gameFolder: ""
  property string gameName: ""
  property string saveError: ""
  function edit(game) {
   if(view.s.hostArgsSaving) return;
   gameFolder=game.folder; gameName=game.name; saveError=""; hostArguments.text=game.args || ""; open();
  }
  function save() { if(!view.s.hostArgsSaving) { saveError=""; backend.saveHostLaunchArgs(gameFolder,hostArguments.text); } }
  anchors.centerIn: parent; width: view.width-40; height: 310
  modal: true; focus: true
  closePolicy: view.s.hostArgsSaving ? Popup.NoAutoClose : Popup.CloseOnEscape
  onOpened: { hostArguments.forceActiveFocus(); hostArguments.cursorPosition=hostArguments.text.length; }
  Connections {
   target: backend
   function onHostLaunchArgsFinished(folder,success,message) {
    if(folder!==launchParameters.gameFolder) return;
    if(success) launchParameters.close();
    else { launchParameters.saveError=message; hostArguments.forceActiveFocus(); }
   }
  }
  background: ChamferPopup {}
  GText { x: 18; y: 18; text: "Launch parameters"; font.pixelSize: Theme.scaledFont(26); font.family: Theme.heading }
  GText { x: 18; y: 58; width: parent.width-36; text: launchParameters.gameName; elide: Text.ElideRight }
  GUField { id: hostArguments; objectName: "hostLaunchArgumentsField"; x: 18; y: 92; width: parent.width-36; placeholderText: "e.g. +connect {host_ip}"; selectByMouse: true; readOnly: !!view.s.hostArgsSaving; onAccepted: launchParameters.save() }
  GText { x: 18; y: 150; width: parent.width-36; wrapMode: Text.WordWrap; text: "Applied to Clients in this room. Use {name} for each player and {host_ip} for the Host address."; color: Theme.muted; font.pixelSize: Theme.typeSmall }
  GText { x: 18; y: 203; width: parent.width-36; text: view.s.hostArgsSaving ? "Saving…" : launchParameters.saveError; color: launchParameters.saveError ? Theme.red : Theme.muted; font.pixelSize: Theme.typeCaption; elide: Text.ElideRight }
  RowLayout { x: 18; y: 238; width: parent.width-36; spacing: 12
   GUButton { Layout.fillWidth: true; text: "Cancel"; edge: "left"; enabled: !view.s.hostArgsSaving; onClicked: launchParameters.close() }
   GUButton { objectName: "hostSaveLaunchArgumentsAction"; Layout.fillWidth: true; text: "Save"; iconName: "save-launch"; primary: true; edge: "right"; enabled: !view.s.hostArgsSaving; onClicked: launchParameters.save() }
  }
 }
 Dialog {
  id: closeRoom
  objectName: "hostCloseConfirmation"
  title: "Close LAN room?"
  anchors.centerIn: parent
  width: Math.min(410,view.width-32)
  modal: true
  onOpened: cancelCloseRoom.forceActiveFocus()
  onAccepted: backend.leave()
  footer: Item {
   implicitHeight: 78
   RowLayout {
    anchors.fill: parent; anchors.margins: 18; spacing: 12
    GUButton { id: cancelCloseRoom; objectName: "hostCloseCancelAction"; Layout.fillWidth: true; Layout.preferredHeight: 42; text: "Cancel"; iconOnly: false; edge: "left"; onClicked: closeRoom.reject() }
    GUButton { objectName: "hostCloseAcceptAction"; Layout.fillWidth: true; Layout.preferredHeight: 42; text: "Close Room"; iconOnly: false; primary: true; edge: "right"; onClicked: closeRoom.accept() }
   }
  }
  contentItem: GText { text: "Connected players will be disconnected. Game files stay on this PC."; wrapMode: Text.WordWrap; width: 360 }
  background: ChamferPopup {}
 }
 Popup {
  objectName: "hostPreparationPopup"
  anchors.centerIn: parent
  width: Math.min(410,view.width-32); height: 220
  visible: view.s.host && view.s.busy && !view.s.progress.active && !view.s.closing
  modal: true; focus: true; closePolicy: Popup.NoAutoClose
  background: ChamferPopup { edgeColor: Theme.brass }
  Column {
   anchors.fill: parent; anchors.margins: 18; spacing: 16
   GText { text: "Preparing your LAN room"; font.family: Theme.heading; font.pixelSize: Theme.typeHeading }
   ProgressBar { width: parent.width; indeterminate: true
    background: Rectangle { implicitHeight: 3; color: Theme.insetPanel }
    contentItem: Item { implicitHeight: 3; clip: true
     Rectangle { id: progressSegment; height: 3; width: parent.width * .22; color: Theme.brass
      SequentialAnimation on x { loops: Animation.Infinite; NumberAnimation { from: -progressSegment.width; to: progressSegment.parent.width; duration: 1400; easing.type: Easing.InOutQuad } }
     }
    }
   }
   GText { width: parent.width; text: view.s.status; wrapMode: Text.WordWrap }
   GText { width: parent.width; text: "Setup continues automatically. Approve Windows permission if asked."; wrapMode: Text.WordWrap; font.pixelSize: Theme.typeSmall; color: Theme.muted }
  }
 }
 Popup {
  id: approvalPopup
  objectName: "hostRoomApprovalPopup"
  property var request: view.s && !view.s.closing ? view.s.roomApproval : null
  anchors.centerIn: parent
  width: Math.min(410, view.width-32); height: 245
  z: 100
  visible: !!request
  modal: true; focus: true; closePolicy: Popup.NoAutoClose
  background: ChamferPopup { edgeColor: Theme.brass }
  ColumnLayout {
   anchors.fill: parent; anchors.margins: 18; spacing: 8
   GText { Layout.fillWidth: true; text: "Allow player to join?"; font.family: Theme.heading; font.pixelSize: Theme.scaledFont(22); wrapMode: Text.WordWrap }
   GText { Layout.fillWidth: true; text: approvalPopup.request ? approvalPopup.request.name : ""; elide: Text.ElideRight; font.weight: Font.DemiBold }
   GText { Layout.fillWidth: true; text: approvalPopup.request ? "IP: "+approvalPopup.request.ip : ""; elide: Text.ElideRight; color: Theme.muted }
   GText { Layout.fillWidth: true; Layout.fillHeight: true; text: "They entered the correct password after at least three wrong attempts."; color: Theme.muted; font.pixelSize: Theme.typeSmall; wrapMode: Text.WordWrap }
   RowLayout {
    Layout.fillWidth: true; spacing: 8
    GUButton { objectName: "hostDenyPlayerAction"; Layout.fillWidth: true; Layout.minimumWidth: 120; text: "Deny and block"; iconOnly: false; edge: "left"; accent: Theme.red; enabled: !!approvalPopup.request; onClicked: backend.resolveRoomApproval(approvalPopup.request.requestId, false) }
    GUButton { objectName: "hostAllowPlayerAction"; Layout.fillWidth: true; Layout.minimumWidth: 65; text: "Allow"; iconOnly: false; edge: "right"; primary: true; enabled: !!approvalPopup.request; onClicked: backend.resolveRoomApproval(approvalPopup.request.requestId, true) }
   }
  }
 }
 Popup {
  id: blacklistPopup
  objectName: "hostRoomBlacklistPopup"
  anchors.centerIn: parent
  width: Math.min(410, view.width-32); height: 360
  modal: true; focus: true
  background: ChamferPopup {}
  ColumnLayout {
   anchors.fill: parent; anchors.margins: 18; spacing: 12
   GText { text: "Room blacklist"; font.family: Theme.heading; font.pixelSize: Theme.scaledFont(24) }
   GText { Layout.fillWidth: true; text: "Blocked players can try again after you unblock them. This list clears when the room closes."; color: Theme.muted; font.pixelSize: Theme.typeSmall; wrapMode: Text.WordWrap }
   Item {
    Layout.fillWidth: true; Layout.fillHeight: true
    ListView {
     id: blockedPlayers
     objectName: "hostRoomBlacklist"
     anchors.fill: parent; model: view.s ? view.s.roomBlacklist || [] : []; spacing: 4; clip: true
     ScrollBar.vertical: ScrollBar {}
     delegate: RowLayout {
      required property var modelData
      width: ListView.view.width-12; height: 46; spacing: 6
      ColumnLayout {
       Layout.fillWidth: true; Layout.minimumWidth: 0; spacing: 2
       GText { Layout.fillWidth: true; text: modelData.name; elide: Text.ElideRight }
       GText { Layout.fillWidth: true; text: modelData.ip; elide: Text.ElideRight; color: Theme.muted; font.pixelSize: Theme.typeSmall }
      }
      GUButton { objectName: "hostUnblockPlayerAction"; Layout.preferredWidth: 86; Layout.preferredHeight: 34; text: "Unblock"; iconOnly: false; edge: "right"; onClicked: backend.removeRoomBlacklistEntry(modelData.id) }
     }
    }
    GText { anchors.centerIn: parent; visible: blockedPlayers.count===0; text: "No blocked players"; color: Theme.muted }
   }
   GUButton { text: "Back"; iconOnly: false; edge: "right"; Layout.alignment: Qt.AlignRight; Layout.preferredWidth: 90; Layout.preferredHeight: 36; onClicked: blacklistPopup.close() }
  }
 }
 Popup {
  id: themePopup
  objectName: "hostAppearancePopup"
  anchors.centerIn: parent; width: view.width-40; height: Math.min(640,view.height-40)
  modal: true; focus: true
  onClosed: if (view.s.tutorial) backend.finishHostOptions()
  background: ChamferPopup {}
  ColumnLayout {
   anchors.fill: parent; anchors.margins: 18; spacing: 12
   GText { text: "Settings"; font.family: Theme.heading; font.pixelSize: Theme.typeHeading }
   ThemePicker { Layout.fillWidth: true; Layout.preferredHeight: 108; enabled: !view.s.tutorial; opacity: enabled ? 1 : .45 }
   GText { text: "Host resolution · 9:21"; font.pixelSize: Theme.typeSmall }
   ResolutionPicker { host: true; Layout.fillWidth: true; Layout.preferredHeight: 40; enabled: !view.s.tutorial; opacity: enabled ? 1 : .45 }
   RowLayout {
    Layout.fillWidth: true; Layout.preferredHeight: 48; spacing: 12
    enabled: !view.s.tutorial; opacity: enabled ? 1 : .45
    GUToggle { checked: view.s.keepInstalled; helpText: "Keep VLA installed when the launcher closes."; Accessible.name: helpText; onClicked: backend.setKeepInstalled(checked) }
    GText { text: "Keep VLA installed on exit"; font.pixelSize: Theme.typeSmall }
    Item { Layout.fillWidth: true }
   }
   HostActionButton { objectName: "hostNetworkDiagnosticAction"; Layout.fillWidth: true; Layout.preferredHeight: 40; text: "Network Diagnostic"; edge: "left"; iconName: "search"; enabled: !view.s.tutorial && !view.s.busy; onClicked: { themePopup.close(); networkDiagnostic.open(); backend.runDiagnostics(); } }
   HostActionButton { objectName: "wipeVLAButton"; Layout.fillWidth: true; Layout.preferredHeight: 40; text: "Repair Network/Wipe VLA"; edge: "right"; iconName: "trash"; enabled: !view.s.tutorial && !view.s.busy; onClicked: backend.wipeVLA() }
   GUButton { objectName: "hostRoomBlacklistAction"; text: "Room blacklist"; iconOnly: false; edge: "center"; Layout.fillWidth: true; Layout.preferredHeight: 36; enabled: !view.s.tutorial; onClicked: blacklistPopup.open() }
   GUButton { text: "Close"; edge: "right"; iconName: "close"; Layout.alignment: Qt.AlignRight; Layout.preferredWidth: 44; Layout.preferredHeight: 36; onClicked: themePopup.close() }
  }
 }
 NetworkDiagnosticPopup { id: networkDiagnostic; s: view.s }
 ColumnLayout {
  anchors.fill: parent
  anchors.leftMargin: 20; anchors.rightMargin: 20
  anchors.topMargin: 8; anchors.bottomMargin: 24
  spacing: 18
  Item {
   Layout.fillWidth: true; Layout.preferredHeight: 68
   Row {
    spacing: 10
    Item {
     width: 50; height: 34
     y: hostHeading.baselineOffset - height
     Image {
      anchors.fill: parent; source: Theme.emblemPath
      // Crop transparent padding so the visible mark aligns with the title baseline.
      sourceClipRect: Qt.rect(110, 290, 1020, 680)
      fillMode: Image.PreserveAspectFit
     }
     MouseArea { anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: window.openAbout() }
    }
    GText { id: hostHeading; objectName: "hostTitle"; text: "HOST"; font.family: Theme.heading; font.pixelSize: Theme.typeHeading; font.letterSpacing: 3 }
   }
   Row { y: 38; spacing: 10
    IconLabel { iconName: "computer"; text: view.s.pcName; description: "LAN host: "+view.s.pcName }
    CopyText { objectName: "hostIpCopy"; enabled: !view.s.tutorial; opacity: enabled ? 1 : .45; height: 20; width: 130; verticalAlignment: Text.AlignVCenter; text: view.s.hostLanIp || "-"; copyValue: view.s.hostLanIp || ""; description: "Copy LAN IP"; normalColor: Theme.muted; font.family: Theme.code; font.pixelSize: Theme.typeSmall }
   }
  }
  Panel {
   objectName: "hostRoomPanel"
   Layout.fillWidth: true; Layout.preferredHeight: 172
   bottomHighlight: true
   ColumnLayout {
    anchors.fill: parent; anchors.margins: 12; spacing: 8
    IconLabel { iconName: view.s.connected ? "check" : "network"; text: view.s.busy ? "Preparing" : view.s.connected ? "Online" : "Offline"; description: view.s.busy ? view.s.status : view.s.connected ? "Room connected" : "Open the room to connect players"; Layout.preferredHeight: 24 }
    Row { Layout.alignment: Qt.AlignHCenter; Layout.preferredHeight: 22; spacing: 7
     IconLabel { iconName: "key"; description: "Room identifier" }
     CopyText { objectName: "hostRoomCodeCopy"; enabled: !view.s.tutorial || view.s.tutorialStage === "hostInvite"; opacity: enabled ? 1 : .45; height: 22; width: 160; verticalAlignment: Text.AlignVCenter; text: view.s.roomCode || "-"; copyValue: view.s.roomCode || ""; description: "Copy room ID"; font.family: Theme.code; font.pixelSize: Theme.typeSmall }
    }
    RowLayout {
     Layout.fillWidth: true; Layout.preferredHeight: 48; spacing: 12
     HostActionButton {
      id: hostStart
      objectName: "hostStartAction"
      Layout.fillWidth: true; Layout.preferredHeight: 48
      text: view.s.connected ? "Close Room" : view.roomFailed ? "Retry" : "Open Room"
      iconName: view.s.connected ? "room-stop" : "room-start"; edge: "center"
      accent: view.s.connected ? Theme.red : view.roomFailed ? Theme.warning : Theme.green
      enabled: view.practiceOpen && !view.s.busy && (view.s.connected || !requirePassword.checked || hostPassword.text.trim().length>0)
      onClicked: {
       if (view.s.connected) closeRoom.open();
       else if (requirePassword.checked) backend.openHostRoomWithPassword(hostPassword.text);
       else backend.openHostRoom();
      }
     }
    }
    RowLayout {
     Layout.fillWidth: true; Layout.preferredHeight: 30; spacing: 8
     CheckBox {
      id: requirePassword
      objectName: "hostRequireRoomPassword"
      Layout.preferredWidth: 190; Layout.preferredHeight: 28
      text: "Require password"; padding: 0
      enabled: view.practiceOpen && !view.s.busy && !view.s.connected
      opacity: !view.s.tutorial || enabled ? 1 : .45
      contentItem: GText { text: requirePassword.text; leftPadding: 18; font.pixelSize: Theme.typeSmall; verticalAlignment: Text.AlignVCenter }
      indicator: Rectangle {
       x: 0; y: (requirePassword.height-height)/2; width: 12; height: 12; radius: 1
       color: requirePassword.checked ? Theme.selectedRow : Theme.panel
       border.color: requirePassword.activeFocus ? Theme.brass : Theme.border; border.width: .7
       Image { anchors.fill: parent; anchors.margins: 2; source: Theme.iconPath+"check.svg"; visible: requirePassword.checked }
      }
      onClicked: if (checked) hostPassword.forceActiveFocus(); else hostPassword.clear()
     }
     GUField {
      id: hostPassword
      objectName: "hostRoomPasswordField"
      Layout.fillWidth: true; Layout.minimumWidth: 0; Layout.preferredHeight: 30
      placeholderText: view.s.connected && requirePassword.checked ? "Password required" : "Room password"
      echoMode: TextInput.Password; maximumLength: 256
      inputMethodHints: Qt.ImhSensitiveData | Qt.ImhNoPredictiveText
      enabled: view.practiceOpen && requirePassword.checked && !view.s.busy && !view.s.connected
      opacity: !view.s.tutorial || enabled ? 1 : .45
      onAccepted: if (hostStart.enabled) hostStart.click()
     }
    }
   }
  }
  Panel {
   objectName: "hostGamesPanel"
   enabled: !view.s.tutorial || ["hostAdd", "hostExe", "hostArt", "hostShare"].includes(view.s.tutorialStage); opacity: enabled ? 1 : .45
   Layout.fillWidth: true; Layout.fillHeight: true; Layout.minimumHeight: 180
   bottomHighlight: true
   ColumnLayout {
    anchors.fill: parent; anchors.margins: 18; spacing: 12
    RowLayout {
     Layout.fillWidth: true; Layout.preferredHeight: 24; spacing: 8
     GText { text: "Games ("+view.s.catalog.length+")"; Layout.fillWidth: true; font.weight: Font.DemiBold }
     HostActionButton { objectName: "hostAddGameAction"; Layout.preferredWidth: 18; Layout.preferredHeight: 18; padding: 0; iconSize: 12; text: "Add game"; iconName: "add"; iconOnly: true; edge: "center"; enabled: !view.s.hostArgsSaving && (!view.s.tutorial || view.s.tutorialStage === "hostAdd"); onClicked: backend.addGame() }
     HostActionButton { objectName: "hostRescanAction"; Layout.preferredWidth: 18; Layout.preferredHeight: 18; padding: 0; iconSize: 12; text: "Rescan folders"; iconName: "refresh"; iconOnly: true; edge: "right"; enabled: !view.s.hostArgsSaving && !view.s.tutorial; onClicked: backend.navigate("catalog") }
    }
    Item {
     Layout.fillWidth: true; Layout.fillHeight: true
     ListView {
      id: hostGamesList
      objectName: "hostGameList"
      anchors.fill: parent; model: hostCatalogModel; clip: true; spacing: 1; enabled: !view.s.hostArgsSaving
      ScrollBar.vertical: ScrollBar { policy: hostGamesList.contentHeight > hostGamesList.height ? ScrollBar.AsNeeded : ScrollBar.AlwaysOff }
      delegate: RowLayout {
       required property var entry
       property var modelData: entry
       readonly property var indexInfo: modelData.index || ({})
       readonly property string indexState: indexInfo.state || "waiting"
       readonly property real indexFraction: indexState === "ready" ? 1 :
        indexInfo.total > 0 ? Math.min(1, indexInfo.done / indexInfo.total) :
        indexInfo.files_total > 0 ? Math.min(1, indexInfo.files_done / indexInfo.files_total) : 0
       width: ListView.view.width-16; height: 18; spacing: 4
       CheckBox {
        id: shareToggle
        objectName: "hostShareGameCheck"
        enabled: !view.s.tutorial || view.s.tutorialStage === "hostShare"
        opacity: !view.s.tutorial || enabled ? 1 : .45
        Layout.preferredWidth: 18; Layout.preferredHeight: 18; padding: 0
        checked: modelData.enabled; Accessible.name: "Share "+modelData.name
        indicator: Rectangle {
         x: (shareToggle.width-width)/2; y: (shareToggle.height-height)/2
         width: 12; height: 12; radius: 1
         color: shareToggle.checked ? Theme.selectedRow : Theme.panel
         border.color: shareToggle.activeFocus ? Theme.brass : Theme.border
         border.width: shareToggle.activeFocus ? 1.3 : .7
         Image { anchors.fill: parent; anchors.margins: 2; source: Theme.iconPath+"check.svg"; visible: shareToggle.checked }
        }
        HoverHint { description: "Include "+modelData.name+" in the shared library" }
        onClicked: backend.setHostGameEnabled(modelData.folder,checked)
       }
       Image { Layout.preferredWidth: 12; Layout.preferredHeight: 12; source: modelData.art || ""; fillMode: Image.PreserveAspectFit; cache: false }
       Item { Layout.fillWidth: true; Layout.minimumWidth: 0; Layout.preferredHeight: 18
        Rectangle { anchors.fill: parent; color: Theme.alpha(Theme.brass, .10); visible: indexState === "ready" }
        Rectangle { anchors.left: parent.left; anchors.top: parent.top; anchors.bottom: parent.bottom;
         width: parent.width * indexFraction; color: Theme.alpha(Theme.green, .50);
         visible: indexState === "running" }
        GText { anchors.fill: parent; verticalAlignment: Text.AlignVCenter; text: modelData.name; elide: Text.ElideRight; font.pixelSize: Theme.typeSmall }
        HoverHint { description: modelData.name+" — "+modelData.exe+" · "+(indexState === "ready" ? "Index ready" : indexState === "running" ? "Hashing "+Math.round(indexFraction*100)+"%" : indexState === "error" ? "Index failed: "+indexInfo.error : "Waiting for index request") }
       }
       CheckBox {
        id: exeToggle
        objectName: "hostExeRequiredCheck"
        enabled: !view.s.tutorial
        opacity: !view.s.tutorial ? 1 : .45
        Layout.preferredWidth: 44; Layout.preferredHeight: 18
        padding: 0; spacing: 4
        checked: modelData.exeRequired !== false
        text: "EXE"; Accessible.name: "EXE required for "+modelData.name
        contentItem: GText { text: "EXE"; leftPadding: 16; font.pixelSize: Theme.typeCaption; verticalAlignment: Text.AlignVCenter }
        indicator: Rectangle {
         x: 0; y: (exeToggle.height-height)/2; width: 12; height: 12; radius: 1
         color: exeToggle.checked ? Theme.selectedRow : Theme.panel
         border.color: exeToggle.activeFocus ? Theme.brass : Theme.border; border.width: .7
         Image { anchors.fill: parent; anchors.margins: 2; source: Theme.iconPath+"check.svg"; visible: exeToggle.checked }
        }
        HoverHint { description: "EXE required — untick to share this folder without a launch executable." }
        onClicked: backend.setHostExeRequired(modelData.folder, checked)
       }
       HostActionButton { objectName: "hostSelectExeAction"; Layout.preferredWidth: 18; Layout.preferredHeight: 18; padding: 0; iconSize: 12; text: ".exe"; iconName: "terminal"; edge: "center"; enabled: modelData.exeRequired !== false && (!view.s.tutorial || view.s.tutorialStage === "hostExe"); onClicked: backend.browseHostGame(modelData.folder,"exe") }
       HostActionButton { objectName: "hostSelectArtAction"; Layout.preferredWidth: 18; Layout.preferredHeight: 18; padding: 0; iconSize: 12; text: "Choose game artwork"; iconName: "image"; edge: "center"; enabled: !view.s.tutorial || view.s.tutorialStage === "hostArt"; onClicked: backend.browseHostGame(modelData.folder,"art") }
       HostActionButton { objectName: "hostRecheckGameIndexAction"; Layout.preferredWidth: 18; Layout.preferredHeight: 18; padding: 0; iconSize: 12; text: "Recheck game index"; iconName: "refresh"; edge: "center"; enabled: !view.s.tutorial && !!modelData.id && modelData.enabled && indexState !== "running"; onClicked: backend.recheckGameIndex(modelData.id) }
       HostActionButton { Layout.preferredWidth: 18; Layout.preferredHeight: 18; padding: 0; iconSize: 12; text: "Launch parameters"; helpText: "Set launch parameters for Clients in this room."; iconName: "sliders"; edge: "right"; enabled: !view.s.tutorial && !!modelData.id && modelData.exeRequired !== false; onClicked: launchParameters.edit(modelData) }
      }
     }
     GText { anchors.centerIn: parent; width: parent.width; horizontalAlignment: Text.AlignHCenter; wrapMode: Text.WordWrap; visible: view.s.catalog.length===0; text: "No shared games yet.\nAdd a game folder above."; color: Theme.muted }
    }
   }
  }
  Panel {
   objectName: "hostClientsPanel"
   enabled: !view.s.tutorial; opacity: enabled || view.s.tutorialStage === "hostPlayers" ? 1 : .45
   Layout.fillWidth: true; Layout.preferredHeight: 210; Layout.minimumHeight: 108
   bottomHighlight: true
   ColumnLayout {
    id: clientsContent
    anchors.fill: parent; anchors.margins: 18; spacing: 12
    IconLabel { iconName: "people"; text: "Players ("+view.s.playerCount+")"; description: view.s.playerCount+" connected players"; Layout.preferredHeight: 24; textColor: Theme.paper }
    RowLayout {
     Layout.fillWidth: true; Layout.preferredHeight: 20; spacing: 0
     GText { text: "Player"; color: Theme.muted; Layout.preferredWidth: clientsContent.width*.40; font.pixelSize: Theme.typeSmall }
     GText { text: "IP address"; color: Theme.muted; Layout.preferredWidth: clientsContent.width*.42; font.pixelSize: Theme.typeSmall }
     GText { text: "Ping"; color: Theme.muted; Layout.fillWidth: true; font.pixelSize: Theme.typeSmall }
    }
    ListView {
     id: playersList
     Layout.fillWidth: true; Layout.fillHeight: true
     model: view.s.players; clip: true; spacing: 2
     ScrollBar.vertical: ScrollBar { policy: playersList.contentHeight > playersList.height ? ScrollBar.AsNeeded : ScrollBar.AlwaysOff }
     delegate: Rectangle {
      required property var modelData
      width: ListView.view.width; height: 18; radius: 2; color: Theme.insetPanel
      GText { x: 8; y: 0; height: 18; verticalAlignment: Text.AlignVCenter; width: parent.width*.30-12; text: modelData.name; elide: Text.ElideRight }
      CopyText { x: parent.width*.30; y: 0; width: parent.width*.26-6; height: 18; verticalAlignment: Text.AlignVCenter; text: modelData.ip || "—"; copyValue: modelData.ip || ""; description: "Copy player IP address"; elide: Text.ElideMiddle; font.pixelSize: Theme.typeSmall; normalColor: Theme.muted }
      GText { x: parent.width*.76; y: 0; height: 18; verticalAlignment: Text.AlignVCenter; width: parent.width*.16-4; text: modelData.ping_ms===undefined || modelData.ping_ms===null ? "—" : modelData.ping_ms+" ms"; elide: Text.ElideRight; font.pixelSize: Theme.typeSmall; color: Theme.green }
      HostActionButton { objectName: "hostKickPlayerAction"; x: parent.width-19; y: 1; width: 16; height: 16; padding: 0; iconSize: 10; iconOnly: true; iconName: "close"; text: "Kick "+modelData.name; helpText: "Remove "+modelData.name+" from this room"; onClicked: backend.kickPlayer(modelData.player_id) }
      Row {
       x: parent.width*.56; y: 4; spacing: 2
       Item { width: 9; height: 9
        StatusLight { anchors.centerIn: parent; scale: 0.41; color: modelData.seedingActive ? "#FF2E9E57" : "#FF5A5F66"; glow: modelData.seedingActive === true
         Text { anchors.centerIn: parent; text: "\u2191"; color: "#FFFFFF"; font.pixelSize: Theme.scaledFont(17); font.bold: true } } }
       Repeater { model: (modelData.seeding || []).slice(0, 1)
        Rectangle { width: 9; height: 9; radius: 2; color: Theme.panel; clip: true
         Image { anchors.fill: parent; source: modelData.icon || ""; visible: source !== ""; fillMode: Image.PreserveAspectFit; asynchronous: true }
         Text { anchors.centerIn: parent; visible: !modelData.icon; text: String(modelData.name || "?").substring(0, 1).toUpperCase(); font.pixelSize: Theme.scaledFont(6); color: Theme.brass } } }
       Text { visible: (modelData.seeding || []).length > 1; text: "+" + ((modelData.seeding || []).length - 1); font.pixelSize: Theme.scaledFont(8); color: Theme.muted; height: 9; verticalAlignment: Text.AlignVCenter }
       Item { width: 6; height: 1 }
       Item { width: 9; height: 9
        StatusLight { anchors.centerIn: parent; scale: 0.41; color: modelData.leechingActive ? "#FF2E9E57" : "#FF5A5F66"; glow: modelData.leechingActive === true
         Text { anchors.centerIn: parent; text: "\u2193"; color: "#FFFFFF"; font.pixelSize: Theme.scaledFont(17); font.bold: true } } }
       Repeater { model: (modelData.leeching || []).slice(0, 1)
        Rectangle { width: 9; height: 9; radius: 2; color: Theme.panel; clip: true
         Image { anchors.fill: parent; source: modelData.icon || ""; visible: source !== ""; fillMode: Image.PreserveAspectFit; asynchronous: true }
         Text { anchors.centerIn: parent; visible: !modelData.icon; text: String(modelData.name || "?").substring(0, 1).toUpperCase(); font.pixelSize: Theme.scaledFont(6); color: Theme.brass } } }
       Text { visible: (modelData.leeching || []).length > 1; text: "+" + ((modelData.leeching || []).length - 1); font.pixelSize: Theme.scaledFont(8); color: Theme.muted; height: 9; verticalAlignment: Text.AlignVCenter }
      }
     }
    }
   }
  }
  ColumnLayout {
   Layout.fillWidth: true; Layout.preferredHeight: 48
   spacing: 12
   RowLayout {
    Layout.fillWidth: true; Layout.preferredHeight: 48; spacing: 12
    HostActionButton { Layout.fillWidth: true; Layout.preferredHeight: 48; text: view.s.gameDirectory; edge: "left"; iconName: "folder"; enabled: !view.s.tutorial && !view.s.connected && !view.s.busy && !view.s.hostArgsSaving; onClicked: {let p=backend.chooseDirectory();if(p) backend.saveSettings(p,view.s.keepInstalled);} }
    HostActionButton { objectName: "hostAppearanceAction"; Layout.preferredWidth: 48; Layout.preferredHeight: 48; text: "Settings"; edge: "right"; iconName: "settings"; iconOnly: true; enabled: !view.s.tutorial || view.s.tutorialStage === "hostOptions"; onClicked: themePopup.open() }
   }
  }
 }
 Rectangle {
  anchors.fill: parent; visible: view.s.closing; color: Theme.dark; z: 100
  MouseArea { anchors.fill: parent }
  GText { anchors.centerIn: parent; text: "Closing your room safely…"; font.pixelSize: Theme.scaledFont(24) }
 }
}
