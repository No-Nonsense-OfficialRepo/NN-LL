import QtQuick
import QtQuick.Layouts
RowLayout {
 spacing: 12
 implicitHeight: 108
 CustomThemeEditor { id: customEditor }
 Repeater {
  model: Theme.names
  ThemeOption { required property string modelData; themeName: modelData; objectName: "themeOption"+modelData; Layout.fillWidth: true; Layout.minimumWidth: 0; Layout.preferredWidth: 1; Layout.preferredHeight: 108; onEditCustom: customEditor.open() }
 }
}
