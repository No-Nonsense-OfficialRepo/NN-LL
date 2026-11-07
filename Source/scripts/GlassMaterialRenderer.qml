import QtQuick
Item {
 id: glass
 property bool ready: false
 property url source
 function selectTheme(name) { Theme.apply(name); }
 function saveMaterial(path) { return surface.save(path); }
 // The material is painted once at the 1920x1080 design size and then scaled by the scene graph. Resizing the
 // window therefore never repaints it: the debanding pass and the grain loop are expensive in JavaScript.
 Canvas {
  id: surface
  property bool materialDrawn: false
  readonly property url materialSource: glass.source
  readonly property int debandCell: 16        // px between samples of the wide average
  readonly property int debandRadius: 40      // px; wider than one 8-bit band of the dark gradients
  readonly property real debandThreshold: 2   // levels; flatter than this is banding, anything stronger is detail
  width: 1920; height: 1080
  transformOrigin: Item.TopLeft
  transform: Scale { xScale: glass.width/surface.width; yScale: glass.height/surface.height }
  Component.onCompleted: loadImage(materialSource)
  onMaterialSourceChanged: { glass.ready = false; materialDrawn = false; loadImage(materialSource); requestPaint(); }
  onImageLoaded: requestPaint()
  onPainted: if (materialDrawn) glass.ready = true

  // Average of interleaved channels over a (2r+1) window along rows, edges clamped. Only ever run on the small grid.
  function blurRows(src, dst, w, h, ch, r) {
   for(let y=0;y<h;y++) {
    let row=y*w*ch;
    for(let k=0;k<ch;k++) {
     let sum=0, hi=Math.min(r,w-1);
     for(let x=0;x<=hi;x++) sum+=src[row+x*ch+k];
     let count=hi+1;
     for(let x=0;x<w;x++) {
      dst[row+x*ch+k]=sum/count;
      let add=x+r+1, drop=x-r;
      if(add<w) { sum+=src[row+add*ch+k]; count++; }
      if(drop>=0) { sum-=src[row+drop*ch+k]; count--; }
     }
    }
   }
  }
  // The same along columns.
  function blurCols(src, dst, w, h, ch, r) {
   let stride=w*ch;
   for(let x=0;x<w;x++) {
    for(let k=0;k<ch;k++) {
     let base=x*ch+k, sum=0, hi=Math.min(r,h-1);
     for(let y=0;y<=hi;y++) sum+=src[base+y*stride];
     let count=hi+1;
     for(let y=0;y<h;y++) {
      dst[base+y*stride]=sum/count;
      let add=y+r+1, drop=y-r;
      if(add<h) { sum+=src[base+add*stride]; count++; }
      if(drop>=0) { sum-=src[base+drop*stride]; count--; }
     }
    }
   }
  }
  // An 8-bit gradient is a staircase: dithering its steps cannot hide them, because the in-between values were
  // lost when it was rasterised. Rebuild them first. A wide average, sampled every few pixels, is a smooth ramp;
  // where a pixel is nearly flat against it, replace the pixel by that ramp plus uniform noise and let the
  // truncating write round it, so each level appears in proportion to the ramp. Detail stronger than the
  // threshold is left exactly as drawn. Only the small grid is blurred, and flat pixels never read their own
  // red and blue: the whole pass costs about as much as a plain noise loop.
  function debandAndDither(c) {
   let w=width, h=height, S=debandCell, img=c.getImageData(0,0,w,h), d=img.data;
   let lw=Math.ceil(w/S)+1, lh=Math.ceil(h/S)+1;
   let grid=[], mid=[], wide=[], rowV=[];
   for(let i=0;i<lw*lh*3;i++) { grid.push(0); mid.push(0); wide.push(0); }
   for(let i=0;i<lw*3;i++) rowV.push(0);
   for(let gy=0;gy<lh;gy++) {
    let y=Math.min(gy*S,h-1);
    for(let gx=0;gx<lw;gx++) {
     let p=(y*w+Math.min(gx*S,w-1))*4, g=(gy*lw+gx)*3;
     grid[g]=d[p]; grid[g+1]=d[p+1]; grid[g+2]=d[p+2];
    }
   }
   let cells=Math.round(debandRadius/S);
   blurRows(grid,mid,lw,lh,3,cells);
   blurCols(mid,wide,lw,lh,3,cells);
   let limit=debandThreshold, inv=1/S, rowLen=lw*3;
   for(let y=0;y<h;y++) {
    let gy=y*inv, y0=Math.floor(gy), fy=gy-y0, y1=Math.min(y0+1,lh-1);
    let upper=y0*rowLen, lower=y1*rowLen, row=y*w*4;
    for(let i=0;i<rowLen;i++) rowV[i]=wide[upper+i]+(wide[lower+i]-wide[upper+i])*fy;
    for(let gx=0;gx<lw-1;gx++) {
     let a=gx*3;
     let r0=rowV[a], g0=rowV[a+1], b0=rowV[a+2];
     let dr=(rowV[a+3]-r0)*inv, dg=(rowV[a+4]-g0)*inv, db=(rowV[a+5]-b0)*inv;
     let x=gx*S, end=Math.min(x+S,w), p=row+x*4;
     for(;x<end;x++,p+=4) {
      let e=d[p+1]-g0;
      if(e<=limit && e>=-limit) { let n=Math.random(); d[p]=r0+n; d[p+1]=g0+n; d[p+2]=b0+n; }
      r0+=dr; g0+=dg; b0+=db;
     }
    }
   }
   // Qt ignores the three-argument form; the dirty-rectangle form is the one that writes.
   c.putImageData(img,0,0,0,0,w,h);
  }

  onPaint: {
   if(!isImageLoaded(materialSource)) return;
   let c=getContext("2d");
   c.globalCompositeOperation="source-over";c.clearRect(0,0,width,height);
   c.drawImage(materialSource,0,0,width,height);
   // Fully opaque at the frosted left edge; at most 10% transparent on the right.
   // Match the material's golden-ratio divisions instead of arbitrary stop positions.
   let phi=(1+Math.sqrt(5))/2;
   let opacityField=c.createLinearGradient(0,0,width,0);
   opacityField.addColorStop(0,"rgba(255,255,255,1)");
   opacityField.addColorStop(1/Math.pow(phi,3),"rgba(255,255,255,.995)");
   opacityField.addColorStop(1/Math.pow(phi,2),"rgba(255,255,255,.97)");
   opacityField.addColorStop(1/phi,"rgba(255,255,255,.93)");
   opacityField.addColorStop(1,"rgba(255,255,255,.90)");
   c.globalCompositeOperation="destination-in";
   c.fillStyle=opacityField;c.fillRect(0,0,width,height);
   c.globalCompositeOperation="source-over";
   // Smooth and dither the finished gradient first, then lay the etched-to-polished grain over it untouched.
   debandAndDither(c);
   let seed=137;
   for(let i=0;i<width*height/6;i++) {
    seed=(seed*16807)%2147483647;let x=seed%width;
    seed=(seed*16807)%2147483647;let y=seed%height;
    let frost=(.11+.28*(1-x/width)*(1-x/width))*.26;
    c.fillStyle=Theme.light ? (i%3===0 ? "rgba(255,255,255,"+frost+")" : "rgba(87,97,108,"+frost+")") : String(Theme.alpha(Theme.paper,frost*.18));
    c.fillRect(x,y,.7,.7);
   }
   materialDrawn = true;
  }
 }
}
