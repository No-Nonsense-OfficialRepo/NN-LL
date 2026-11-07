import QtQuick
// Small status cube with a bottom-left chamfer (like the launcher's buttons) and a soft glow.
// Any children (e.g. a count) sit on the cube.
Item {
    id: light
    property color color: "#5A5F66"
    // Off (grey) lights don't glow.
    property bool glow: true
    default property alias content: core.data
    width: 22; height: 22
    onColorChanged: { halo.requestPaint(); cube.requestPaint(); }

    // Soft glow: a blurred shadow of the chamfered cube shape, so there are no stepped halos.
    // The canvas is 44px with the cube at 11..33, leaving room for the blur.
    Canvas {
        id: halo
        width: 44; height: 44
        anchors.centerIn: parent
        visible: light.glow
        onWidthChanged: requestPaint()
        onPaint: {
            let c = getContext("2d");
            c.clearRect(0, 0, width, height);
            c.shadowColor = String(Qt.rgba(light.color.r, light.color.g, light.color.b, .5));
            c.shadowBlur = 12;
            c.beginPath();
            c.moveTo(11, 11); c.lineTo(33, 11); c.lineTo(33, 33); c.lineTo(15, 33); c.lineTo(11, 29);
            c.closePath();
            c.fillStyle = String(light.color);
            c.fill();
        }
    }

    Item {
        id: core
        anchors.centerIn: parent; width: 22; height: 22
        Canvas {
            id: cube
            anchors.fill: parent
            onWidthChanged: requestPaint()
            onPaint: {
                let c = getContext("2d"), w = width, h = height, k = 4;
                c.clearRect(0, 0, w, h);
                c.beginPath();
                c.moveTo(0, 0); c.lineTo(w, 0); c.lineTo(w, h); c.lineTo(k, h); c.lineTo(0, h - k);
                c.closePath();
                c.fillStyle = String(light.color);
                c.fill();
            }
        }
    }
}
