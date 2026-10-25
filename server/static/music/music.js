// Halo music screen. Everything animates on transform/opacity or a small canvas,
// driven by one requestAnimationFrame loop; the laptop only sends state and cava.
const $=s=>document.querySelector(s);
const root=document.documentElement,body=document.body;
const reduced=matchMedia('(prefers-reduced-motion: reduce)').matches;

// ---- springs -------------------------------------------------------------
class Spring{
 constructor(value,stiffness=420,damping=28){this.value=this.target=value;this.velocity=0;this.k=stiffness;this.c=damping;}
 step(dt){
  if(reduced){this.value=this.target;this.velocity=0;return this.value;}
  // Semi-implicit Euler in small slices keeps stiff springs stable at 120 Hz.
  for(let t=dt;t>0;t-=1/240){const h=Math.min(t,1/240),a=this.k*(this.target-this.value)-this.c*this.velocity;this.velocity+=a*h;this.value+=this.velocity*h;}
  return this.value;
 }
}
const haptic=()=>{try{window.HaloNative?.haptic();}catch{}};

// ---- palette from the cover ----------------------------------------------
function hsl(r,g,b){r/=255;g/=255;b/=255;const max=Math.max(r,g,b),min=Math.min(r,g,b),l=(max+min)/2;let h=0,s=0;
 if(max!==min){const d=max-min;s=l>.5?d/(2-max-min):d/(max+min);h=max===r?(g-b)/d+(g<b?6:0):max===g?(b-r)/d+2:(r-g)/d+4;h*=60;}return [h,s,l];}
function rgb(h,s,l){const k=n=>(n+h/30)%12,a=s*Math.min(l,1-l),f=n=>l-a*Math.max(-1,Math.min(k(n)-3,9-k(n),1));return [f(0)*255,f(8)*255,f(4)*255].map(Math.round);}
const css=([r,g,b])=>`rgb(${r} ${g} ${b})`;
function palette(img){
 const size=40,c=document.createElement('canvas');c.width=c.height=size;const x=c.getContext('2d',{willReadFrequently:true});
 x.drawImage(img,0,0,size,size);const data=x.getImageData(0,0,size,size).data,buckets=new Map();
 for(let i=0;i<data.length;i+=4){
  const [h,s,l]=hsl(data[i],data[i+1],data[i+2]),key=`${Math.round(h/20)}|${Math.round(s*3)}|${Math.round(l*4)}`;
  const b=buckets.get(key)||{n:0,h:0,s:0,l:0};b.n++;b.h+=h;b.s+=s;b.l+=l;buckets.set(key,b);
 }
 const all=[...buckets.values()].map(b=>({n:b.n,h:b.h/b.n,s:b.s/b.n,l:b.l/b.n}));
 const vivid=c=>c.n*Math.pow(c.s,1.4)*(c.l>.18&&c.l<.86?1:.15);
 const dominant=all.reduce((a,b)=>b.n>a.n?b:a),vibrant=all.reduce((a,b)=>vivid(b)>vivid(a)?b:a);
 const far=c=>{const d=Math.abs(c.h-vibrant.h);return Math.min(d,360-d)>45;};
 const second=all.filter(far).reduce((a,b)=>!a||vivid(b)>vivid(a)?b:a,null)||dominant;
 if(vibrant.s<.14){ // monochrome artwork stays monochrome
  return {accent:[226,226,226],glow:[46,46,46],tintA:[20,20,20],tintB:[12,12,12],bar:[210,210,210]};
 }
 const s=Math.min(.92,Math.max(.5,vibrant.s));
 return {accent:rgb(vibrant.h,s,.7),glow:rgb(vibrant.h,s*.85,.3),
  tintA:rgb(dominant.h,Math.min(dominant.s,.55),.11),tintB:rgb(second.h,Math.min(second.s,.6),.085),bar:rgb(vibrant.h,Math.min(s,.55),.8)};
}
let barColour=[205,205,205],barTarget=[205,205,205];
function applyPalette(p){
 for(const [name,value] of [['--accent',p.accent],['--glow',p.glow],['--tint-a',p.tintA],['--tint-b',p.tintB]])root.style.setProperty(name,css(value));
 root.style.setProperty('--fill',css(p.accent.map((c,i)=>Math.round(c*.35+[230,230,230][i]*.65))));
 root.style.setProperty('--glow-soft',`rgba(${p.glow.join(',')},.4)`);
 barTarget=p.bar;
}

// ---- now playing ---------------------------------------------------------
let current={active:false},trackKey=null,artKey=null,direction='next',directionAt=0;
const progress={position:0,length:0,sampledAt:0,playing:false,dragging:false,shown:-1};
function setText(id,value){
 const span=$('#'+id);if(span.dataset.next===value)return;
 span.dataset.next=value;clearTimeout(span.swap);span.classList.remove('entering');span.classList.add('leaving');
 span.swap=setTimeout(()=>{span.textContent=value;span.classList.remove('leaving');void span.offsetWidth;span.classList.add('entering');},reduced?0:380);
}
async function showArt(key){
 artKey=key;const art=$('.art');
 if(!key){for(const old of art.querySelectorAll('img'))old.remove();applyPalette(palette(blank()));return;}
 const img=new Image();img.alt='';img.decoding='async';img.src='/api/music/art?v='+key;
 try{await img.decode();}catch{return;}
 if(artKey!==key)return;
 const from=performance.now()-directionAt<4000?direction:'next';
 for(const old of art.querySelectorAll('img:not(.leaving)')){old.dataset.from=from;old.classList.remove('entering');old.classList.add('leaving');
  old.addEventListener('animationend',()=>old.remove(),{once:true});setTimeout(()=>old.remove(),900);}
 img.dataset.from=from;img.classList.add('entering');art.append(img);
 try{applyPalette(palette(img));}catch{}
}
function blank(){const c=document.createElement('canvas');c.width=c.height=1;return c;}
function apply(state){
 current=state;
 if(!state.active){body.dataset.state='idle';progress.playing=false;if(trackKey!==null){trackKey=null;showArt(null);}return;}
 // Chromium reuses one MPRIS track id, so identify tracks by their tags.
 const key=state.title+'|'+state.artist+'|'+state.album;
 if(key!==trackKey){trackKey=key;setText('title',state.title||'Unknown title');setText('artist',state.artist||'');}
 if(state.art!==artKey)showArt(state.art);
 body.dataset.state=state.status==='Playing'?'playing':'paused';
 if(!progress.dragging){
  progress.position=state.position;progress.length=state.length;progress.playing=state.status==='Playing';progress.sampledAt=performance.now();
 }
 const shuffle=$('#shuffle'),loop=$('#loop');
 shuffle.setAttribute('aria-pressed',String(state.shuffle));shuffle.classList.toggle('unsupported',!state.can_shuffle);
 loop.dataset.loop=state.loop;loop.classList.toggle('unsupported',!state.can_loop);
 coverScale.target=state.status==='Playing'?1:.93;
}
let polling=null;
async function poll(){
 clearTimeout(polling);
 try{apply(await(await fetch('/api/music',{cache:'no-store'})).json());}catch{}
 if(!document.hidden)polling=setTimeout(poll,1000);
}
async function control(action,value){
 try{
  const response=await fetch('/api/music/control',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action,value})});
  const data=await response.json();if(response.ok)apply(data);
 }catch{}
}

// ---- controls ------------------------------------------------------------
const pressSprings=new Map();
function pressable(el,onPress){
 const spring=new Spring(1,520,24);pressSprings.set(el,spring);
 el.addEventListener('pointerdown',()=>{spring.target=.84;});
 for(const ev of ['pointerup','pointercancel','pointerleave'])el.addEventListener(ev,()=>{spring.target=1;});
 el.addEventListener('click',e=>{e.stopPropagation();haptic();onPress();});
}
function travel(dir){direction=dir;directionAt=performance.now();control(dir);}
pressable($('#previous'),()=>travel('previous'));
pressable($('#next'),()=>travel('next'));
pressable($('#shuffle'),()=>{if($('#shuffle').classList.contains('unsupported'))return nudge($('#shuffle'));control('shuffle');});
pressable($('#loop'),()=>{if($('#loop').classList.contains('unsupported'))return nudge($('#loop'));control('loop');});
function nudge(el){el.animate([{translate:'0'},{translate:'-4px'},{translate:'4px'},{translate:'0'}],{duration:260,easing:'ease-out'});}

// Cover: tap to play/pause, swipe to change track; it follows the finger.
const cover=$('#cover'),coverScale=new Spring(1,300,22),coverPress=new Spring(1,520,26),coverX=new Spring(0,260,24);
let swipe=null;
cover.addEventListener('pointerdown',e=>{swipe={x:e.clientX,y:e.clientY,id:e.pointerId,moved:false};cover.setPointerCapture(e.pointerId);coverPress.target=.95;});
cover.addEventListener('pointermove',e=>{if(!swipe||e.pointerId!==swipe.id)return;const dx=e.clientX-swipe.x;
 if(Math.abs(dx)>8)swipe.moved=true;if(swipe.moved){coverX.value=coverX.target=dx*.35;coverX.velocity=0;}});
function release(e,cancelled){
 if(!swipe||e.pointerId!==swipe.id)return;const dx=e.clientX-swipe.x,moved=swipe.moved;swipe=null;coverPress.target=1;coverX.target=0;
 if(cancelled)return;
 if(moved&&Math.abs(dx)>50){haptic();travel(dx<0?'next':'previous');}
 else if(!moved){haptic();togglePlay();}
}
cover.addEventListener('pointerup',e=>release(e,false));
cover.addEventListener('pointercancel',e=>release(e,true));
cover.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();togglePlay();}});
cover.addEventListener('click',e=>e.preventDefault());
function togglePlay(){
 if(!current.active)return;const playing=current.status==='Playing';
 // Optimistic: respond instantly, the next state from the laptop confirms it.
 current.status=playing?'Paused':'Playing';body.dataset.state=playing?'paused':'playing';coverScale.target=playing?.93:1;
 progress.position=displayPosition(performance.now());progress.sampledAt=performance.now();progress.playing=!playing;
 const pulse=$('.pulse');pulse.querySelector('.play').classList.toggle('on',!playing);pulse.querySelector('.pause').classList.toggle('on',playing);
 pulse.classList.remove('show');void pulse.offsetWidth;pulse.classList.add('show');
 control('toggle');
}

// Seek bar: drag anywhere on it; it thickens under the finger.
const track=$('#track');
function fraction(e){const r=track.getBoundingClientRect();return Math.max(0,Math.min(1,(e.clientX-r.left)/r.width));}
track.addEventListener('pointerdown',e=>{if(!progress.length)return;track.setPointerCapture(e.pointerId);progress.dragging=true;track.classList.add('dragging');progress.position=fraction(e)*progress.length;progress.sampledAt=performance.now();haptic();});
track.addEventListener('pointermove',e=>{if(progress.dragging){progress.position=fraction(e)*progress.length;progress.sampledAt=performance.now();}});
for(const ev of ['pointerup','pointercancel'])track.addEventListener(ev,e=>{
 if(!progress.dragging)return;progress.dragging=false;track.classList.remove('dragging');
 if(ev==='pointerup'){progress.position=fraction(e)*progress.length;progress.sampledAt=performance.now();control('seek',progress.position);}
});
const time=s=>{s=Math.max(0,Math.floor(s||0));return `${Math.floor(s/60)}:${String(s%60).padStart(2,'0')}`;};
function displayPosition(now){
 const p=progress.position+(progress.playing&&!progress.dragging?(now-progress.sampledAt)/1000:0);
 return progress.length?Math.min(p,progress.length):p;
}

// ---- cava ----------------------------------------------------------------
const BARS=30,canvas=$('#bars'),ctx=canvas.getContext('2d');
const levels=new Float32Array(BARS),targets=new Float32Array(BARS);
let source=null,bass=new Spring(0,180,20);
function resize(){const w=260;canvas.width=w;canvas.height=Math.round(w*canvas.clientHeight/Math.max(1,canvas.clientWidth));}
new ResizeObserver(resize).observe(canvas);resize();
function listen(){
 source?.close();source=new EventSource('/api/cava?music=1');
 source.onmessage=e=>{const values=JSON.parse(e.data);for(let i=0;i<BARS;i++)targets[i]=(values[i]||0)/100;};
}
function drawBars(dt){
 const w=canvas.width,h=canvas.height,gap=w*.012,bar=(w-gap*(BARS-1))/BARS,quiet=body.dataset.state!=='playing';
 ctx.clearRect(0,0,w,h);
 for(let c=0;c<3;c++)barColour[c]+=(barTarget[c]-barColour[c])*(1-Math.exp(-dt*2.2));
 const [r,g,b]=barColour,grad=ctx.createLinearGradient(0,0,0,h);
 grad.addColorStop(0,`rgba(${r},${g},${b},.95)`);grad.addColorStop(1,'rgba(190,190,190,.45)');ctx.fillStyle=grad;
 let low=0;
 for(let i=0;i<BARS;i++){
  const target=quiet?0:targets[i],rate=target>levels[i]?24:7;   // quick attack, slow release
  levels[i]+=(target-levels[i])*(1-Math.exp(-dt*rate));if(i<5)low+=levels[i];
  // A gentle curve lifts quiet passages so the bars stay alive.
  const height=Math.max(h*.035,Math.pow(levels[i],.8)*h*.92),x=i*(bar+gap),y=h-height,rad=Math.min(bar/2,height/2);
  ctx.beginPath();ctx.roundRect?ctx.roundRect(x,y,bar,height+rad,[rad,rad,0,0]):ctx.rect(x,y,bar,height);ctx.fill();
 }
 bass.target=low/5;
}

// ---- frame loop ----------------------------------------------------------
const glow=$('.glow'),fill=$('#fill');let last=performance.now();
function frame(now){
 const dt=Math.min(.05,(now-last)/1000);last=now;
 drawBars(dt);
 glow.style.setProperty('--bass',bass.step(dt).toFixed(3));
 const scale=coverScale.step(dt)*coverPress.step(dt)*(1+bass.value*.025);
 cover.style.transform=`translate3d(${coverX.step(dt).toFixed(2)}px,0,0) scale(${scale.toFixed(4)})`;
 for(const [el,spring] of pressSprings)el.style.transform=`scale(${spring.step(dt).toFixed(4)})`;
 const position=displayPosition(now);
 fill.style.transform=`scaleX(${progress.length?(position/progress.length).toFixed(5):0})`;
 const second=Math.floor(position);
 if(second!==progress.shown||$('#duration').dataset.v!==String(progress.length)){
  progress.shown=second;$('#elapsed').textContent=time(position);$('#duration').textContent=time(progress.length);$('#duration').dataset.v=String(progress.length);
  track.setAttribute('aria-valuemax',String(Math.round(progress.length)));track.setAttribute('aria-valuenow',String(second));
 }
 requestAnimationFrame(frame);
}
requestAnimationFrame(frame);

// Pause everything (including the laptop's cava) when the screen is not shown.
function wake(){poll();listen();}
document.addEventListener('visibilitychange',()=>{if(document.hidden){source?.close();source=null;clearTimeout(polling);}else wake();});
addEventListener('halo-native-pause',()=>{source?.close();source=null;clearTimeout(polling);});
addEventListener('halo-native-resume',wake);
addEventListener('halo-native-network',wake);
wake();
