import QtQuick

Item {
    id: wheel
    implicitWidth: 144
    implicitHeight: 144
    property real hue: 0
    property real saturation: 0
    property real brightness: 1
    readonly property color chosenColor: Qt.hsva(hue, saturation, brightness, 1)
    signal edited(color value)

    function selectColor(value) {
        hue = Math.max(0, value.hsvHue);
        saturation = value.hsvSaturation;
        brightness = value.hsvValue;
    }

    function pick(x, y) {
        const dx = x - width / 2, dy = y - height / 2;
        hue = (Math.atan2(dy, dx) / (2 * Math.PI) + 1) % 1;
        saturation = Math.min(1, Math.hypot(dx, dy) / (width / 2));
        edited(chosenColor);
    }

    Canvas {
        anchors.fill: parent
        onWidthChanged: requestPaint()
        onHeightChanged: requestPaint()
        onPaint: {
            const ctx = getContext("2d"), w = Math.floor(width), h = Math.floor(height);
            if (w < 1 || h < 1) return;
            const image = ctx.createImageData(w, h), data = image.data, radius = w / 2;
            for (let y = 0; y < h; ++y) {
                for (let x = 0; x < w; ++x) {
                    const dx = x + .5 - radius, dy = y + .5 - h / 2;
                    const distance = Math.hypot(dx, dy);
                    if (distance > radius) continue;
                    const hue = (Math.atan2(dy, dx) / (2 * Math.PI) + 1) % 1;
                    const saturation = distance / radius;
                    const index = (y * w + x) * 4;
                    for (let channel = 0; channel < 3; ++channel) {
                        const sector = (hue * 6 + 5 - 2 * channel) % 6;
                        data[index + channel] = Math.round(255 * (1 - saturation *
                            Math.max(0, Math.min(sector, 4 - sector, 1))));
                    }
                    data[index + 3] = Math.min(255, Math.round(255 * (radius - distance)));
                }
            }
            ctx.clearRect(0, 0, w, h);
            ctx.putImageData(image, 0, 0, 0, 0, w, h);
        }
    }

    Rectangle {
        width: 12; height: 12; radius: 6
        x: (wheel.width - width) / 2 + Math.cos(wheel.hue * 2 * Math.PI) * wheel.saturation * wheel.width / 2
        y: (wheel.height - height) / 2 + Math.sin(wheel.hue * 2 * Math.PI) * wheel.saturation * wheel.height / 2
        color: wheel.chosenColor; border.color: "white"; border.width: 2
    }

    MouseArea {
        anchors.fill: parent
        cursorShape: Qt.CrossCursor
        onPressed: mouse => wheel.pick(mouse.x, mouse.y)
        onPositionChanged: mouse => { if (pressed) wheel.pick(mouse.x, mouse.y); }
    }
}
