import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
Panel {
    id: view
    property var s
    signal showTerms()
    ScrollView {
        anchors.fill: parent; anchors.margins: 32
        contentWidth: availableWidth; clip: true
        ColumnLayout {
            width: parent.width; spacing: 22
            GText { text: "About NN LAN Launcher"; font.family: Theme.heading; font.pixelSize: Theme.typePage }
            GText { objectName: "aboutVersion"; text: "NN LAN Launcher " + view.s.version; color: Theme.brass; font.pixelSize: Theme.typeSmall }
            GUButton { objectName: "aboutTermsButton"; text: "TOS"; iconName: "info"; iconOnly: false; Layout.preferredWidth: 150; onClicked: view.showTerms() }
            GText { text: "Find us online"; font.pixelSize: Theme.typeSection; font.weight: Font.DemiBold }
            Repeater {
                model: [
                    {label: "YouTube", url: "https://www.youtube.com/@NoNonsenseLAN"},
                    {label: "Discord", url: "https://discord.com/invite/a9NgtcnH5r"},
                    {label: "GitHub", url: "https://github.com/No-Nonsense-OfficialRepo"}
                ]
                delegate: GText {
                    required property var modelData
                    objectName: "aboutLink" + modelData.label
                    text: modelData.label; font.pixelSize: Theme.typeSmall; font.underline: true
                    color: pointer.containsMouse || activeFocus ? Theme.paper : Theme.brass
                    activeFocusOnTab: true
                    Accessible.role: Accessible.Link; Accessible.name: text
                    function openLink() { Qt.openUrlExternally(modelData.url); }
                    Accessible.onPressAction: openLink()
                    Keys.onReturnPressed: openLink()
                    Keys.onSpacePressed: openLink()
                    MouseArea { id: pointer; anchors.fill: parent; anchors.margins: -4; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: parent.openLink() }
                }
            }
            GText { Layout.fillWidth: true; wrapMode: Text.WordWrap; text: "Find our LAN Ready Repository on your Favorite Torrent Site under No-NonsenseLAN"; font.pixelSize: Theme.typeSmall }
            GText { text: "Special Thanks to:"; font.pixelSize: Theme.typeSection; font.weight: Font.DemiBold; color: Theme.brass }
            Repeater {
                model: ["Dante47", "LegionZA", "Mango", "Zeloth"]
                delegate: GText { required property string modelData; text: modelData; font.pixelSize: Theme.typeSmall }
            }
        }
    }
}
