// Local wake audio stays in memory. Keep consecutive audio through slow requests.
class WakeListener {
 constructor(){
  this.enabled=false;this.starting=false;this.wanted=false;this.stream=null;this.context=null;
  this.sending=false;this.queue=[];this.session=crypto.randomUUID();this.generation=0;this.reset=true;this.failures=0;this.retryAt=0;
  this.health=setInterval(()=>this.checkHealth(),2000);
 }
 label(text,on=true){$('#wake').setAttribute('aria-pressed',String(on));$('#wake').textContent=text;}
 acknowledge(){
  if(this.context?.state!=='running')return;
  const tone=this.context.createOscillator(),gain=this.context.createGain(),now=this.context.currentTime;
  tone.frequency.value=660;gain.gain.setValueAtTime(0,now);gain.gain.linearRampToValueAtTime(.035,now+.01);gain.gain.exponentialRampToValueAtTime(.001,now+.075);
  tone.connect(gain);gain.connect(this.context.destination);tone.onended=()=>{tone.disconnect();gain.disconnect();};tone.start(now);tone.stop(now+.08);
 }
 async request(chunk,reset){
  const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),4000);
  try{
   const response=await fetch('/api/wake',{method:'POST',signal:controller.signal,headers:{'Content-Type':'application/octet-stream','X-Wake-Session':this.session,'X-Wake-Reset':reset?'1':'0'},body:chunk});
   if(!response.ok)throw Error('Wake detector unavailable');return await response.json();
  }finally{clearTimeout(timer);}
 }
 async start(){
  if(this.enabled||this.starting||document.hidden)return;
  this.wanted=true;this.starting=true;this.session=crypto.randomUUID();const generation=++this.generation;
  $('#wake').disabled=true;this.label('STARTING…',false);
  try{
   const stream=await navigator.mediaDevices.getUserMedia({audio:{channelCount:1,echoCancellation:true,noiseSuppression:true,autoGainControl:true}});
   if(generation!==this.generation||document.hidden){stream.getTracks().forEach(t=>t.stop());return;}
   this.stream=stream;await this.request(new Int16Array(2560),true);
   if(generation!==this.generation||document.hidden){stream.getTracks().forEach(t=>t.stop());return;}
   // Ask the browser for 16 kHz so it filters properly instead of the crude
   // decimation below, which aliases noise into speech on real microphones.
   const Context=window.AudioContext||window.webkitAudioContext;
   try{this.context=new Context({sampleRate:16000});}catch{this.context=new Context();}const context=this.context;
   context.onstatechange=()=>{if(this.enabled&&!this.failures&&this.context===context)this.label(context.state==='running'?'HALO · ON':'HALO · TAP');};
   context.resume().catch(()=>{});
   const input=this.context.createMediaStreamSource(stream);this.input=input;
   this.processor=this.context.createScriptProcessor(4096,1,1);input.connect(this.processor);this.processor.connect(this.context.destination);
   let pending=[],position=0;const ratio=this.context.sampleRate/16000;
   this.processor.onaudioprocess=event=>{
    if(generation!==this.generation)return;
    const blocked=busy||startingMic||recorder?.state==='recording'||!playback.paused||['THINKING','SPEAKING'].includes(document.body.dataset.state);
    if(blocked||document.hidden){pending=[];position=0;this.queue=[];this.reset=true;return;}
    const samples=event.inputBuffer.getChannelData(0);
    while(position<samples.length){const index=Math.floor(position),fraction=position-index;const value=samples[index]*(1-fraction)+samples[Math.min(index+1,samples.length-1)]*fraction;pending.push(Math.max(-32768,Math.min(32767,Math.round(value*32767))));position+=ratio;}
    position-=samples.length;
    while(pending.length>=2560)this.queue.push(new Int16Array(pending.splice(0,2560)));
    // Bound latency and memory after a prolonged stall, not every normal request.
    if(this.queue.length>8){this.queue.splice(0,this.queue.length-8);this.reset=true;}
    this.drain(generation);
   };
   this.enabled=true;this.reset=true;this.failures=0;this.queue=[];
   for(const track of stream.getAudioTracks())track.onended=()=>{if(this.enabled){this.label('HALO · RECONNECT');this.restart();}};
   if(!busy&&document.body.dataset.state==='IDLE')state('IDLE','');
   this.label(this.context.state==='running'?'HALO · ON':'HALO · TAP');localStorage.setItem('jarvis-wake','on');
  }catch(error){
   await this.stop(false);this.retryAt=Date.now()+3000;this.label('HALO · RETRY',false);
   if(error.name==='NotAllowedError')this.wanted=false;
   state('IDLE','Wake microphone unavailable. Tap HALO to allow access.');
  }finally{this.starting=false;$('#wake').disabled=false;}
 }
 async drain(generation){
  if(this.sending||!this.enabled||generation!==this.generation||!this.queue.length||Date.now()<this.retryAt)return;
  const packets=this.queue.splice(0,3),chunk=new Int16Array(packets.length*2560);
  packets.forEach((packet,i)=>chunk.set(packet,i*2560));
  this.sending=true;const reset=this.reset;this.reset=false;
  try{
   const result=await this.request(chunk,reset);
   if(generation!==this.generation)return;
   this.failures=0;this.label(this.context?.state==='running'?'HALO · ON':'HALO · TAP');
   if(result.wake&&this.enabled&&!busy&&!startingMic&&recorder?.state!=='recording'&&document.body.dataset.state==='IDLE'){
    this.queue=[];this.reset=true;this.acknowledge();await toggleMicrophone();
   }
  }catch(error){
   if(generation===this.generation){
    this.reset=true;this.queue=[];this.failures++;this.retryAt=Date.now()+Math.min(4000,500*this.failures);this.label('HALO · RETRY');
   }
  }finally{
   if(generation===this.generation){this.sending=false;this.drain(generation);}
  }
 }
 async restart(){await this.stop(false);if(this.wanted&&!document.hidden)await this.start();}
 async checkHealth(){
  if(!this.wanted||document.hidden||this.starting)return;
  if(!this.enabled){if(Date.now()>=this.retryAt)await this.start();return;}
  if(this.stream?.getAudioTracks().every(t=>t.readyState==='ended')){await this.restart();return;}
  if(this.context?.state==='suspended'){
   this.context.resume().catch(()=>{});
   if(this.context?.state!=='running')this.label('HALO · TAP');
  }
  if(this.context?.state==='closed'){await this.restart();return;}
  this.drain(this.generation);
 }
 async stop(save=true){
  this.generation++;this.enabled=false;this.sending=false;this.queue=[];this.reset=true;
  if(save){this.wanted=false;localStorage.setItem('jarvis-wake','off');}
  this.processor?.disconnect();this.processor=null;this.input?.disconnect();this.input=null;
  this.stream?.getTracks().forEach(t=>{t.onended=null;t.stop();});this.stream=null;
  const context=this.context;this.context=null;await context?.close().catch(()=>{});this.label('HALO · OFF',false);
 }
}
const wake=new WakeListener();
$('#wake').onclick=async()=>{
 if(wake.enabled&&wake.context?.state==='suspended')wake.context.resume().catch(()=>{});
 else if(wake.enabled&&wake.context?.state==='running'&&!wake.failures)await wake.stop();
 else {wake.wanted=true;await wake.restart();}
};
document.addEventListener('visibilitychange',()=>{if(document.hidden)wake.stop(false);else if(localStorage.getItem('jarvis-wake')==='on'){wake.wanted=true;wake.start();}});
document.addEventListener('pointerdown',event=>{if(!event.target.closest('#wake')&&wake.wanted&&wake.context?.state==='suspended')wake.context.resume().catch(()=>{});},{passive:true});
(async()=>{try{const permission=await navigator.permissions.query({name:'microphone'});if(permission.state==='granted'&&localStorage.getItem('jarvis-wake')!=='off')await wake.start();}catch{/* HALO control handles browsers without the Permissions API. */}})();
