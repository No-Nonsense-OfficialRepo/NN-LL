import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Popup {
    id: editor
    objectName: "customThemeEditor"
    parent: Overlay.overlay
    width: Math.min(390, (parent ? parent.width : 414) - 24)
    height: 440
    anchors.centerIn: parent
    modal: true
    focus: true
    padding: 16
    background: ChamferPopup {}

    property var draft: ({})
    property int index: 0
    readonly property string token: Theme.editableColors[index].key
    readonly property color currentColor: draft[token] || Theme.noNonsensePalette[token]

    function editColor(value) {
        const updated = Object.assign({}, draft);
        updated[token] = String(value);
        draft = updated;
    }

    onAboutToShow: {
        draft = Object.assign({}, Theme.customColors);
        index = 0;
        wheel.selectColor(currentColor);
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 8
        RowLayout {
            Layout.fillWidth: true
            GText { Layout.fillWidth: true; text: "Custom theme"; font.family: Theme.heading; font.pixelSize: Theme.scaledFont(24) }
            GUButton {
                objectName: "closeCustomThemeAction"
                Layout.preferredWidth: 32; Layout.preferredHeight: 30
                text: "Cancel custom theme edits"; iconName: "close"; iconOnly: true; edge: "right"
                onClicked: editor.close()
            }
        }
        GText {
            Layout.fillWidth: true
            text: "Select a color, then use the wheel and brightness slider."
            wrapMode: Text.WordWrap
        }
        RowLayout {
            Layout.fillWidth: true; Layout.fillHeight: true; spacing: 8
            ListView {
                Layout.fillWidth: true; Layout.fillHeight: true
                Layout.minimumWidth: 96
                clip: true
                model: Theme.editableColors
                ScrollBar.vertical: ScrollBar { policy: ScrollBar.AlwaysOn }
                delegate: Item {
                    required property var modelData
                    required property int index
                    width: ListView.view.width; height: 44
                    Rectangle {
                        x: 2
                        anchors.verticalCenter: parent.verticalCenter
                        width: 8; height: 8; radius: 2
                        color: editor.draft[modelData.key] || Theme.noNonsensePalette[modelData.key]
                        border.color: Theme.muted
                    }
                    GUButton {
                        x: 14; width: parent.width - 28; height: 32
                        anchors.verticalCenter: parent.verticalCenter
                        text: modelData.label
                        helpText: modelData.label
                        selected: index === editor.index
                        iconOnly: false
                        onClicked: {
                            editor.index = index;
                            wheel.selectColor(editor.currentColor);
                        }
                    }
                }
            }
            ColumnLayout {
                Layout.minimumWidth: 144; Layout.maximumWidth: 144
                Layout.alignment: Qt.AlignTop
                GText { Layout.fillWidth: true; text: Theme.editableColors[editor.index].label; wrapMode: Text.WordWrap }
                ColorWheel {
                    id: wheel
                    objectName: "customThemeColorWheel"
                    Layout.alignment: Qt.AlignHCenter
                    onEdited: value => editor.editColor(value)
                }
                GText { text: "Brightness"; font.pixelSize: Theme.typeSmall }
                Slider {
                    Layout.fillWidth: true
                    from: 0; to: 1; value: wheel.brightness
                    Accessible.name: "Color brightness"
                    onMoved: {
                        wheel.brightness = value;
                        editor.editColor(wheel.chosenColor);
                    }
                }
                GUField {
                    objectName: "customThemeHexField"
                    Layout.fillWidth: true
                    text: String(editor.currentColor)
                    maximumLength: 7
                    Accessible.name: "Hex color"
                    onEditingFinished: {
                        if (/^#[0-9a-f]{6}$/i.test(text)) editor.editColor(text);
                        text = Qt.binding(() => String(editor.currentColor));
                        wheel.selectColor(editor.currentColor);
                    }
                }
            }
        }
        RowLayout {
            Layout.alignment: Qt.AlignRight; spacing: 14
            GUButton {
                Layout.preferredWidth: 88
                text: "Reset"; iconOnly: false; iconName: ""
                onClicked: { editor.draft = ({}); wheel.selectColor(editor.currentColor); }
            }
            GUButton {
                objectName: "saveCustomThemeAction"
                Layout.preferredWidth: 88
                text: "Save"; iconOnly: false; iconName: ""; primary: true
                onClicked: { Theme.saveCustom(editor.draft); editor.close(); }
            }
        }
    }
}
