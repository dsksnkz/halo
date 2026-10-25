function viewportHeight(){document.documentElement.style.setProperty('--viewport-height',innerHeight+'px');}viewportHeight();addEventListener('resize',viewportHeight);
const $=s=>document.querySelector(s);
document.body.dataset.state='IDLE';
let webEnabled=localStorage.getItem('halo-web')!=='off';
let busy=false,sessionId=null,messages=[],voice=true,recorder,stream,timer,source;
let conversationRevision=-1,pendingReply=null;
function syncConversation(snapshot){
 if(!snapshot||busy||startingMic||recorder?.state==='recording'||snapshot.revision===conversationRevision)return;
 conversationRevision=snapshot.revision;messages=snapshot.messages.map(m=>({role:m.role,content:m.content}));
 $('#transcript').replaceChildren();
 for(const message of snapshot.messages){line(message.content,message.role==='user'?'user':'answer');if(message.sources)showSources(message.sources);}
 $('.assistant').classList.toggle('has-conversation',messages.length>0);
 const hasReply=messages.some(m=>m.role==='assistant');$('#copy').disabled=$('#replay').disabled=!hasReply;
}
function state(name,hint){document.body.dataset.state=name;$('#status').textContent=name;$('#hint').textContent=hint;$('#hint').hidden=name==='IDLE'&&!/review|speech|microphone|unavailable|allow|failed|connection|play/i.test(hint);$('.assistant').classList.toggle('has-notice',!$('#hint').hidden&&name==='IDLE');if(typeof updateOrb==='function')updateOrb();}
function line(text,kind){const p=document.createElement('p');p.className=kind;p.textContent=kind==='user'?text.replace(/^› /,''):text;$('#transcript').append(p);$('.assistant').classList.add('has-conversation');p.scrollIntoView?.({block:'nearest'});return p;}
function showDraft(text){if(!busy||!text)return;prefetchDraftVoice(text);if(!pendingReply)pendingReply=line(text,'answer');else{const panel=$('#transcript'),following=panel.scrollHeight-panel.scrollTop-panel.clientHeight<70;pendingReply.textContent=text;if(following)panel.scrollTop=panel.scrollHeight;}}
async function api(path,body,raw=false){const r=await fetch(path,{method:'POST',headers:raw?{}:{'Content-Type':'application/json'},body:raw?body:JSON.stringify(body)});const data=await r.json();if(!r.ok)throw Error(data.error||'Request failed');return data;}
async function stats(){try{const d=await(await fetch('/api/stats')).json();const s=d.system;if(d.session_id&&sessionId!==d.session_id){sessionId=d.session_id;messages=[];stopSpeech();$('#transcript').replaceChildren();$('.assistant').classList.remove('has-conversation');$('#copy').disabled=$('#replay').disabled=true;}syncConversation(d.conversation);$('#model-name').textContent=d.model_label||'AI';if(s){const mem=s.Memory;const up=Math.floor(s.Uptime.uptime/60000);const rows=[['os',s.OS.prettyName],['kernel',s.Kernel.release],['uptime',`${Math.floor(up/60)}h ${up%60}m`],['memory',`${(mem.used/2**30).toFixed(1)} / ${(mem.total/2**30).toFixed(1)} GiB`],['desktop',s.WM.prettyName+' / Wayland']];$('#stats').replaceChildren();for(const [key,value]of rows){const dt=document.createElement('dt'),dd=document.createElement('dd');dt.textContent=key;dd.textContent=value;$('#stats').append(dt,dd);}}if(!d.ready&&!busy)state('OFFLINE','OpenCode service unavailable.');else if(d.ready&&$('#status').textContent==='OFFLINE')state('IDLE','');}catch{if(!busy)state('OFFLINE','Check the USB cable and PC server.');}}
stats();setInterval(stats,5000);
const term=new Terminal({fontFamily:'Mono, monospace',fontSize:6,lineHeight:1,letterSpacing:0,disableStdin:true,scrollback:0,cursorBlink:false,theme:{background:'#000000',foreground:'#ffffff',white:'#ffffff',brightWhite:'#ffffff'}});
const fit=new FitAddon.FitAddon();term.loadAddon(fit);term.open($('#terminal'));
const visualizers=['lavat','cava','pipes','clock'];let visualizer=localStorage.getItem('halo-visualizer')||'lavat';if(!visualizers.includes(visualizer))visualizer='lavat';
function drawCava(values){
 const canvas=$('#cava'),ratio=Math.min(devicePixelRatio||1,2),w=canvas.clientWidth,h=canvas.clientHeight;if(!w||!h)return;
 canvas.width=Math.round(w*ratio);canvas.height=Math.round(h*ratio);const c=canvas.getContext('2d');c.scale(ratio,ratio);c.fillStyle='#fff';
 const gap=Math.max(2,w*.007),bar=(w-gap*(values.length-1))/values.length;
 values.forEach((value,i)=>{const height=Math.max(2,h*value/100),x=i*(bar+gap),y=h-height,r=Math.min(3,bar/2,height/2);c.beginPath();c.moveTo(x+r,y);c.lineTo(x+bar-r,y);c.quadraticCurveTo(x+bar,y,x+bar,y+r);c.lineTo(x+bar,h-r);c.quadraticCurveTo(x+bar,h,x+bar-r,h);c.lineTo(x+r,h);c.quadraticCurveTo(x,h,x,h-r);c.lineTo(x,y+r);c.quadraticCurveTo(x,y,x+r,y);c.fill();});
}
function lava(){
 source?.close();$('.lava').classList.toggle('is-cava',visualizer==='cava');
 if(visualizer==='cava'){drawCava(Array(32).fill(0));source=new EventSource('/api/cava');source.onmessage=e=>drawCava(JSON.parse(e.data));return;}
 term.options.fontSize=matchMedia('(orientation: landscape) and (min-width: 540px)').matches?10:6;fit.fit();term.reset();source=new EventSource(`/api/lava?cols=${term.cols}&rows=${term.rows}&mode=${visualizer}`);source.onmessage=e=>term.write(Uint8Array.from(atob(e.data),c=>c.charCodeAt(0)));
}

let resizeTimer;new ResizeObserver(()=>{clearTimeout(resizeTimer);resizeTimer=setTimeout(lava,300);}).observe($('#terminal'));document.fonts.ready.then(lava);
document.addEventListener('visibilitychange',()=>{if(document.hidden)source?.close();else{lava();stats();}});
async function fullscreen(){try{if(window.HaloNative){window.HaloNative.fullscreen();return;}if(document.fullscreenElement)await document.exitFullscreen();else await document.documentElement.requestFullscreen();await navigator.wakeLock?.request('screen');}catch{state('IDLE','Fullscreen unavailable.');}}
let systemSwipe=null,suppressSystemClick=false;
$('.system').onclick=e=>{if(suppressSystemClick&&e.detail!==0){suppressSystemClick=false;e.preventDefault();return;}suppressSystemClick=false;fullscreen();};
$('.system').onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();fullscreen();}};
let playback=new Audio(),audioURL,speechSequence=0;
function stopSpeech(){speechSequence++;playback.pause();playback.currentTime=0;}
$('#sound').onclick=()=>{voice=!voice;$('#sound').textContent='VOICE';$('#sound').setAttribute('aria-pressed',voice);if(!voice){stopSpeech();if(!busy)state('IDLE','Ready when you are.');}};
function speechChunks(text){
 text=text.replace(/```[\s\S]*?```/g,' The code is shown on screen. ').replace(/!?\[([^\]]+)\]\([^)]*\)/g,'$1').replace(/^\s{0,3}#{1,6}\s+/gm,'').replace(/[*`]/g,'').replace(/^\s*(?:[•+>-]|\d+[.)])\s+/gm,'').replace(/https?:\/\/\S+/g,'').replace(/\|/g,', ').replace(/&/g,' and ').replace(/[\u{1F000}-\u{1FAFF}\u2600-\u27BF]/gu,'').trim();
 const chunks=[];for(const sentence of text.match(/[^.!?]+[.!?]+|[^.!?]+$/g)||[text]){
  const words=sentence.trim().split(/\s+/);if(words.length<=12){chunks.push(words.join(' '));continue;}
  while(words.length)chunks.push(words.splice(0,10).join(' '));
 }return chunks.filter(Boolean);
}
const voiceClips=new Map();
function voiceClip(text){
 if(voiceClips.has(text))return voiceClips.get(text);
 const promise=fetch('/api/speak',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({text})}).then(r=>{if(!r.ok)throw Error('Voice unavailable');return r.blob();}).catch(error=>{voiceClips.delete(text);throw error;});
 voiceClips.set(text,promise);if(voiceClips.size>24)voiceClips.delete(voiceClips.keys().next().value);return promise;
}
function prefetchDraftVoice(text){
 if(!voice||(!/[.!?]\s*$/.test(text)&&text.trim().split(/\s+/).length<13))return;
 const first=speechChunks(text)[0];if(first)voiceClip(first).catch(()=>{});
}
async function speak(text){
 if(!voice)return;const sequence=++speechSequence;state('THINKING','Preparing local voice…');
 const chunks=speechChunks(text);if(!chunks.length){state('IDLE','');return;}
 async function prepare(chunk){
  if(!voice||sequence!==speechSequence)return null;
  return voiceClip(chunk);
 }
 try{
  let next=prepare(chunks[0]);
  for(let i=0;i<chunks.length;i++){
   const blob=await next;if(!blob||!voice||sequence!==speechSequence)return;
   // Prefetch the next short phrase while the current one plays.
   next=i+1<chunks.length?prepare(chunks[i+1]).then(blob=>({blob}),error=>({error})):null;
   if(audioURL)URL.revokeObjectURL(audioURL);audioURL=URL.createObjectURL(blob);playback.src=audioURL;
   await new Promise((resolve,reject)=>{
    playback.onplaying=()=>state('SPEAKING','Halo is responding.');playback.onended=resolve;playback.onerror=reject;
    playback.onpause=()=>{if(sequence!==speechSequence)resolve();};playback.play().catch(reject);
   });
   if(!voice||sequence!==speechSequence)return;
   if(next){const pending=next;next=pending.then(value=>{if(value.error)throw value.error;return value.blob;});}
  }
  state('IDLE','Ready when you are.');$('#replay').disabled=false;
 }catch{if(sequence!==speechSequence)return;$('#replay').disabled=false;state('IDLE','Tap REPLAY to hear the reply.');}
}

async function ask(text,replyBudget=4.2){if(busy||!text.trim())return;busy=true;pendingReply=null;stopSpeech();if($('.welcome'))$('.welcome').remove();line('› '+text,'user');messages.push({role:'user',content:text});state('THINKING','OpenCode is working on your laptop.');$('#mic').disabled=true;try{const d=await api('/api/chat',{messages,session_id:sessionId,web:webEnabled,budget_seconds:replyBudget});messages.push({role:'assistant',content:d.text,spoken:d.spoken});$('#copy').disabled=$('#replay').disabled=false;if(pendingReply)pendingReply.textContent=d.text;else pendingReply=line(d.text,'answer');pendingReply.scrollIntoView?.({block:'start'});showSources(d.sources||[]);state('IDLE','Ready when you are.');speak(d.spoken||d.text);}catch(e){messages.pop();line('Connection: '+e.message,'error');state('IDLE','Check OpenCode on the laptop.');}finally{busy=false;pendingReply=null;$('#mic').disabled=false;}}
$('#clear').onclick=async()=>{if(busy)return;try{await api('/api/conversation/clear',{});}catch(e){state('IDLE',e.message);return;}messages=[];stopSpeech();$('#transcript').replaceChildren();$('.assistant').classList.remove('has-conversation');$('#copy').disabled=$('#replay').disabled=true;state('IDLE','Conversation cleared.');};
let audioContext,micInput,levelTimer,startingMic=false,discardRecording=false;
function releaseMicrophone(){document.documentElement.style.setProperty('--mic-level',0);if(typeof setOrbAudio==='function')setOrbAudio(0,[]);clearTimeout(timer);clearInterval(levelTimer);if(stream!==wake.stream)stream?.getTracks().forEach(t=>t.stop());micInput?.disconnect();micInput=null;if(audioContext!==wake.context)audioContext?.close().catch(()=>{});audioContext=null;}
async function toggleMicrophone(){
 if(recorder?.state==='recording'){recorder.stop();return;}
 if(busy||startingMic)return;
 startingMic=true;stopSpeech();if(typeof updateOrb==='function')updateOrb();
 // Prime this audio element during the tap so mobile browsers can play a later reply.
 if(!audioURL){playback.src='data:audio/wav;base64,UklGRiYAAABXQVZFZm10IBAAAAABAAEARKwAAIhYAQACABAAZGF0YQIAAAAAAA==';playback.play().catch(()=>{});}
 try{
  stream=wake.stream||await navigator.mediaDevices.getUserMedia({audio:{channelCount:1,echoCancellation:true,noiseSuppression:true,autoGainControl:true}});
  const chunks=[];let heardSpeech=false,speechMs=0,lastVoice=performance.now(),started=lastVoice;
  recorder=new MediaRecorder(stream);discardRecording=false;
  recorder.ondataavailable=e=>{if(e.data.size)chunks.push(e.data);};
  recorder.onstop=async()=>{
   const stoppedAt=performance.now();
   releaseMicrophone();$('#mic').classList.remove('recording');$('#mic').textContent='MIC';
   if(discardRecording||!heardSpeech){state('IDLE','No speech detected. Tap to try again.');return;}
   busy=true;$('#mic').disabled=true;state('THINKING','Transcribing locally…');
   try{const d=await api('/api/transcribe',new Blob(chunks,{type:recorder.mimeType}),true);busy=false;if(d.text)await ask(d.text,Math.max(.25,3.05-(performance.now()-stoppedAt)/1000));else state('IDLE','No speech detected. Tap to try again.');}
   catch(e){state('IDLE','Microphone: '+e.message);}
   finally{busy=false;$('#mic').disabled=false;}
  };
  audioContext=wake.context||new (window.AudioContext||window.webkitAudioContext)();await audioContext.resume();
  const analyser=audioContext.createAnalyser();analyser.fftSize=2048;micInput=audioContext.createMediaStreamSource(stream);micInput.connect(analyser);
  const samples=new Float32Array(analyser.fftSize),spectrum=new Uint8Array(analyser.frequencyBinCount);
  recorder.start();$('#mic').classList.add('recording');$('#mic').textContent='STOP';state('LISTENING','Speak, then pause to send.');
  levelTimer=setInterval(()=>{
   if(recorder.state!=='recording')return;
   analyser.getFloatTimeDomainData(samples);let energy=0;for(const value of samples)energy+=value*value;
   const rms=Math.sqrt(energy/samples.length),now=performance.now();document.documentElement.style.setProperty('--mic-level',Math.min(1,rms*12));
   if(typeof setOrbAudio==='function'){analyser.getByteFrequencyData(spectrum);const bands=Array.from({length:6},(_,i)=>{const lo=Math.floor((100+i*260)/audioContext.sampleRate*analyser.fftSize),hi=Math.max(lo+1,Math.floor((360+i*260)/audioContext.sampleRate*analyser.fftSize));let sum=0;for(let n=lo;n<hi;n++)sum+=spectrum[n]||0;return sum/(hi-lo)/255;});setOrbAudio(Math.min(1,rms*12),bands);}
   if(rms>.007){speechMs+=80;lastVoice=now;if(speechMs>=160)heardSpeech=true;}
   if((heardSpeech&&now-lastVoice>650)||(!heardSpeech&&now-started>10000))recorder.stop();
  },80);
  timer=setTimeout(()=>{if(recorder.state==='recording')recorder.stop();},45000);
 }catch(e){releaseMicrophone();state('IDLE','Allow microphone access, then tap to try again.');}
 finally{startingMic=false;}
}
let pressAudioContext;
function assistantPressFeedback(){
 const browserHaptic=()=>{try{navigator.vibrate?.(35);}catch{}};
 // The installed app uses Android directly; browsers use the USB bridge.
 if(window.HaloNative){try{window.HaloNative.haptic();}catch{browserHaptic();}}
 else fetch('/api/device/haptic',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'})
  .then(response=>{if(!response.ok)browserHaptic();}).catch(browserHaptic);
 try{
  const context=wake.context||pressAudioContext||(pressAudioContext=new (window.AudioContext||window.webkitAudioContext)());
  context.resume().then(()=>{
   const tone=context.createOscillator(),gain=context.createGain(),now=context.currentTime;
   tone.type='sine';tone.frequency.setValueAtTime(880,now);tone.frequency.exponentialRampToValueAtTime(660,now+.055);
   gain.gain.setValueAtTime(.001,now);gain.gain.linearRampToValueAtTime(.018,now+.006);gain.gain.exponentialRampToValueAtTime(.001,now+.055);
   tone.connect(gain);gain.connect(context.destination);tone.onended=()=>{tone.disconnect();gain.disconnect();};tone.start(now);tone.stop(now+.065);
  }).catch(()=>{});
 }catch{}
}
function pressAssistant(){if(busy||startingMic)return;assistantPressFeedback();toggleMicrophone();}
$('#mic').onclick=pressAssistant;
$('.assistant').addEventListener('click',e=>{if(e.target.closest('input,button,form,nav,a,select,textarea'))return;if(typeof consumePanelPress==='function'&&consumePanelPress())return;pressAssistant();});
document.addEventListener('visibilitychange',()=>{if(document.hidden&&recorder?.state==='recording'){discardRecording=true;recorder.stop();}});

$('#replay').onclick=()=>{const reply=[...messages].reverse().find(m=>m.role==='assistant');if(reply){voice=true;$('#sound').setAttribute('aria-pressed','true');speak(reply.spoken||reply.content);}};
$('#copy').onclick=async()=>{const reply=[...messages].reverse().find(m=>m.role==='assistant');if(!reply)return;try{await navigator.clipboard.writeText(reply.content);$('#copy').textContent='COPIED';setTimeout(()=>$('#copy').textContent='COPY',1600);}catch{state('IDLE','Copy unavailable. Select the reply text instead.');}};

let swipeStart=null,visualizerTimer;
function cycleVisualizer(direction){
 visualizer=visualizers[(visualizers.indexOf(visualizer)+direction+visualizers.length)%visualizers.length];
 localStorage.setItem('halo-visualizer',visualizer);
 $('.visualizer-name').textContent={lavat:'lavat',cava:'cava',pipes:'pipes.sh',clock:'tty-clock'}[visualizer];
 $('.lava').classList.add('switching');clearTimeout(visualizerTimer);
 visualizerTimer=setTimeout(()=>$('.lava').classList.remove('switching'),1400);lava();
}
$('.lava').addEventListener('touchstart',e=>{const t=e.changedTouches[0];swipeStart=e.touches.length===1?[t.clientX,t.clientY]:null;},{passive:true});
$('.lava').addEventListener('touchcancel',()=>{swipeStart=null;},{passive:true});
$('.lava').addEventListener('touchend',e=>{
 if(!swipeStart)return;const t=e.changedTouches[0],dx=t.clientX-swipeStart[0],dy=t.clientY-swipeStart[1];swipeStart=null;
 if(Math.abs(dx)<45||Math.abs(dx)<Math.abs(dy))return;cycleVisualizer(dx<0?1:-1);
},{passive:true});
const landscapeBackground=()=>matchMedia('(orientation: landscape) and (min-width: 540px)').matches;
$('.system').addEventListener('pointerdown',e=>{
 if(e.isPrimary===false||e.button!==0){systemSwipe=null;suppressSystemClick=true;return;}
 suppressSystemClick=false;systemSwipe={x:e.clientX,y:e.clientY,id:e.pointerId,landscape:landscapeBackground()};
 $('.system').setPointerCapture(e.pointerId);
});
$('.system').addEventListener('pointermove',e=>{
 if(systemSwipe&&e.pointerId===systemSwipe.id&&Math.hypot(e.clientX-systemSwipe.x,e.clientY-systemSwipe.y)>12)suppressSystemClick=true;
});
$('.system').addEventListener('pointerup',e=>{
 if(!systemSwipe||e.pointerId!==systemSwipe.id)return;
 const start=systemSwipe;systemSwipe=null;const dx=e.clientX-start.x,dy=e.clientY-start.y;
 if(Math.hypot(dx,dy)>12)suppressSystemClick=true;
 if(start.landscape&&landscapeBackground()&&Math.abs(dx)>=45&&Math.abs(dx)>Math.abs(dy)*1.2){suppressSystemClick=true;cycleVisualizer(dx<0?1:-1);}
});
for(const event of ['pointercancel','lostpointercapture'])$('.system').addEventListener(event,()=>{if(systemSwipe){systemSwipe=null;suppressSystemClick=true;}});

function showSources(sources){
 if(!sources.length)return;const group=document.createElement('div');group.className='sources';
 for(const source of sources){try{const url=new URL(source.url);if(!['http:','https:'].includes(url.protocol))continue;const link=document.createElement('a');link.href=url.href;link.textContent=source.title||url.hostname;link.target='_blank';link.rel='noopener noreferrer';group.append(link);}catch{}}
 $('#transcript').append(group);$('#transcript').scrollTop=$('#transcript').scrollHeight;
}
$('#web').setAttribute('aria-pressed',webEnabled);
$('#web').onclick=()=>{webEnabled=!webEnabled;localStorage.setItem('halo-web',webEnabled?'on':'off');$('#web').setAttribute('aria-pressed',webEnabled);};
