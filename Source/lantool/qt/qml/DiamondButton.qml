import QtQuick
import QtQuick.Controls
AbstractButton {
 id: control
 property bool selected: false
 property string glyph: "·"
 property string iconName: ""
 implicitWidth: 54; implicitHeight: 54; hoverEnabled: true
 opacity: enabled ? 1 : .35
 Accessible.name: text
 onHoveredChanged: { if(hovered) HoverHelp.begin(control,HoverHelp.describe(control.Accessible.name)); else HoverHelp.end(control); }
 onPressed: HoverHelp.end(control)
 onVisibleChanged: if(!visible) HoverHelp.end(control)
 Component.onDestruction: HoverHelp.end(control)
 Image { anchors.centerIn: parent; width: 16; height: 16; visible: !!control.iconName; source: control.iconName ? Theme.iconPath+control.iconName+".svg" : "" }
 contentItem: Text { visible: !control.iconName; text: control.glyph; color: Theme.paper; font.family: Theme.ui; font.pixelSize: Theme.typeCaption; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
 background: Canvas {
  id: diamondPaint
  Connections { target: Theme; function onCurrentNameChanged(){diamondPaint.requestPaint()} }
  anchors.centerIn: parent
  width: control.width+16; height: control.height+16
  property bool selected: control.selected
  property bool focusVisible: control.activeFocus
  property bool hovered: control.hovered
  property bool pressed: control.down
  onSelectedChanged: requestPaint()
  onFocusVisibleChanged: requestPaint()
  onHoveredChanged: requestPaint()
  onPressedChanged: requestPaint()
  onWidthChanged: requestPaint()
  onHeightChanged: requestPaint()
  onPaint: {
   let c=getContext("2d"),x=width/2,y=height/2,r=Math.min(control.width,control.height)/2-7,k=Math.min(10,r*.5);
   c.clearRect(0,0,width,height);
   // Clear centre: only the icon and fading corner marks are painted.
   // Each corner uses a radial fade: full light at the vertex, zero at both ends.
   let points=selected ? [[x-r,y],[x+r,y]] : [[x,y-r],[x,y+r]];
   let color=String(selected?Theme.diamondSelected:Theme.diamondIdle);
   function corner(index){
    let px=points[index][0],py=points[index][1];c.beginPath();
    if(selected){let dir=index===0?1:-1;c.moveTo(px+dir*k,py-k);c.lineTo(px,py);c.lineTo(px+dir*k,py+k)}
    else{let dir=index===0?1:-1;c.moveTo(px-k,py+dir*k);c.lineTo(px,py);c.lineTo(px+k,py+dir*k)}
   }
   function faded(index,ink){
    let px=points[index][0],py=points[index][1],fade=c.createRadialGradient(px,py,0,px,py,k*Math.SQRT2);
    fade.addColorStop(0,ink);fade.addColorStop(.24,ink);fade.addColorStop(.70,String(Theme.alpha(selected?Theme.diamondSelected:Theme.diamondIdle,selected?.34:.30)));fade.addColorStop(1,"transparent");return fade;
   }
   c.lineJoin="round";c.lineCap="round";
   let widths=selected?[19,13,7,3.2]:[9,5,2.5];
   let alphas=selected?[.10,.20,.38,.55]:[.025,.045,.08];
   for(let n=0;n<points.length;n++){
    for(let i=0;i<widths.length;i++){corner(n);c.strokeStyle=faded(n,color);c.lineWidth=widths[i];c.globalAlpha=alphas[i]*(hovered||focusVisible?1.25:1);c.stroke()}
    c.globalAlpha=1;corner(n);c.lineWidth=1;c.strokeStyle=faded(n,color);c.stroke();
    if(selected){corner(n);c.lineWidth=.45;c.strokeStyle=faded(n,String(Theme.diamondHot));c.stroke()}
   }
   if(focusVisible){for(let n=0;n<points.length;n++){corner(n);c.strokeStyle=faded(n,color);c.lineWidth=1.6;c.stroke()}}
  }
 }
}
