// Soft rotating idle outline; microphone-driven recording geometry. Replies stay still.
const orbCanvas=document.querySelector('#orb');
const orbPanel=document.querySelector('.assistant');
let orbFrame=0,orbLevel=0,orbTarget=0,orbPhase=0,orbBands=Array(6).fill(0),orbTargets=Array(6).fill(0),orbPrevious=0,idleRotation=0,idleMorph=0,lastOrbDraw=-Infinity;
function setOrbAudio(level,bands){orbTarget=level;orbTargets=bands.length?bands:Array(6).fill(0);updateOrb();}
function updateOrb(){if(!orbFrame&&orbPanel.classList.contains('circle-view')&&!document.hidden)orbFrame=requestAnimationFrame(drawOrb);}
function drawOrb(time){
 orbFrame=0;if(!orbPanel.classList.contains('circle-view')||document.hidden)return;
 const reduced=typeof matchMedia==='function'&&matchMedia('(prefers-reduced-motion: reduce)').matches;
 const idle=!startingMic&&['IDLE','OFFLINE'].includes(document.body.dataset.state);
 if(idle&&!reduced&&time-lastOrbDraw<33){orbFrame=requestAnimationFrame(drawOrb);return;}
 lastOrbDraw=time;
 const rect=orbCanvas.getBoundingClientRect(),w=rect.width,h=rect.height,ratio=Math.min(devicePixelRatio||1,2);
 if(!w||!h)return;
 if(orbCanvas.width!==Math.round(w*ratio)||orbCanvas.height!==Math.round(h*ratio)){orbCanvas.width=Math.round(w*ratio);orbCanvas.height=Math.round(h*ratio);}
 const c=orbCanvas.getContext('2d');c.setTransform(ratio,0,0,ratio,0,0);c.clearRect(0,0,w,h);
 const listening=document.body.dataset.state==='LISTENING';
 const active=startingMic||['LISTENING','THINKING','SPEAKING'].includes(document.body.dataset.state);
 orbLevel+=(orbTarget-orbLevel)*.3;orbBands=orbBands.map((v,i)=>v+(orbTargets[i]-v)*.25);
 const delta=Math.min(60,time-(orbPrevious||time));orbPrevious=time;
 if(listening)orbPhase+=delta*.002*orbLevel;
 if(idle&&!reduced){idleRotation-=delta*Math.PI*2/60000;idleMorph+=delta;}
 const radius=Math.min(w,h)*.40,motion=listening?orbLevel:0;
 c.beginPath();
 for(let i=0;i<=160;i++){
  const angle=i/160*Math.PI*2;
  let wave=0;for(let band=0;band<6;band++)wave+=Math.sin(angle*(band+3)+orbPhase*(band%2?1:-1)+band)*orbBands[band];
  const soft=idle ? (.075+.015*Math.sin(idleMorph*.0007))*Math.sin(angle*3+idleMorph*.0011)+.045*Math.sin(angle*2-idleMorph*.0008)+.018*Math.sin(angle*5+idleMorph*.0014):0;
  const r=Math.min(Math.min(w,h)*.46,radius*(1+soft+motion*.06+wave*motion*.045));
  const rotated=angle+(idle?idleRotation:0),x=w/2+Math.cos(rotated)*r,y=h/2+Math.sin(rotated)*r;
  if(i===0)c.moveTo(x,y);else c.lineTo(x,y);
 }
 c.closePath();c.lineWidth=1.7;c.strokeStyle='#fff';c.fillStyle='#fff';if(active)c.fill();else c.stroke();
 if(listening||startingMic||(idle&&!reduced))orbFrame=requestAnimationFrame(drawOrb);
}
function toggleCircle(){orbPanel.classList.toggle('circle-view');localStorage.setItem('halo-circle',orbPanel.classList.contains('circle-view')?'on':'off');orbPrevious=0;updateOrb();}
if(localStorage.getItem('halo-circle')==='on')orbPanel.classList.add('circle-view');
let panelHold,holdPosition,consumedPress=false;
function consumePanelPress(){if(consumedPress){consumedPress=false;return true;}return false;}
orbPanel.addEventListener('pointerdown',event=>{
 if(event.target.closest('button,nav,a,input,textarea')||event.button>0)return;
 consumedPress=false;holdPosition=[event.clientX,event.clientY];
 panelHold=setTimeout(()=>{panelHold=null;consumedPress=true;toggleCircle();},650);
});
orbPanel.addEventListener('pointermove',event=>{if(holdPosition&&Math.hypot(event.clientX-holdPosition[0],event.clientY-holdPosition[1])>12)clearTimeout(panelHold);});
for(const type of ['pointerup','pointercancel','pointerleave'])orbPanel.addEventListener(type,()=>{clearTimeout(panelHold);holdPosition=null;});
orbPanel.addEventListener('contextmenu',event=>{if(!event.target.closest('button,nav'))event.preventDefault();});
new ResizeObserver(updateOrb).observe(orbCanvas);
document.addEventListener('visibilitychange',()=>{if(!document.hidden)updateOrb();});
updateOrb();
