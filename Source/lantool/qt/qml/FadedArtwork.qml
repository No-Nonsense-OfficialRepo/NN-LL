import QtQuick
Item {
    id: artwork
    property url source
    property string fallback: ""
    implicitHeight: width * 3 / 4
    Image {
        id: metrics
        visible: false; source: artwork.source; asynchronous: true
        onStatusChanged: surface.requestPaint()
        onSourceSizeChanged: surface.requestPaint()
    }
    Canvas {
        id: surface
        anchors.fill: parent
        property url imageSource: artwork.source
        onImageSourceChanged: { if (imageSource.toString()) loadImage(imageSource); requestPaint(); }
        Component.onCompleted: if (imageSource.toString()) loadImage(imageSource)
        onImageLoaded: requestPaint()
        onWidthChanged: requestPaint()
        onHeightChanged: requestPaint()
        Connections { target: Theme; function onCurrentNameChanged() { surface.requestPaint(); } }
        onPaint: {
            let c = getContext("2d"), w = width, h = height;
            c.clearRect(0, 0, w, h);
            c.fillStyle = String(Theme.insetPanel);
            c.fillRect(0, 0, w, h);
            let iw = metrics.sourceSize.width, ih = metrics.sourceSize.height;
            if (imageSource.toString() && isImageLoaded(imageSource) && iw > 0 && ih > 0) {
                let fit = Math.min(w / iw, h / ih), dw = iw * fit, dh = ih * fit;
                c.drawImage(imageSource, (w - dw) / 2, (h - dh) / 2, dw, dh);
            }
            let fade = c.createLinearGradient(0, 0, w, 0);
            fade.addColorStop(0, "rgba(255,255,255,0)");
            fade.addColorStop(.15, "rgba(255,255,255,1)");
            fade.addColorStop(.85, "rgba(255,255,255,1)");
            fade.addColorStop(1, "rgba(255,255,255,0)");
            c.globalCompositeOperation = "destination-in";
            c.fillStyle = fade; c.fillRect(0, 0, w, h);
            c.globalCompositeOperation = "source-over";
        }
    }
    Text {
        anchors.centerIn: parent; visible: metrics.status !== Image.Ready
        text: artwork.fallback; font.family: Theme.display; font.pixelSize: Theme.scaledFont(Math.min(40, parent.height * .42)); color: Theme.brass
    }
}
