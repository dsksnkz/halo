// Foreground app lifecycle. Browser mode continues to use visibilitychange.
if(window.HaloNative){
 if(localStorage.getItem('halo-circle')===null){localStorage.setItem('halo-circle','on');$('.assistant').classList.add('circle-view');updateOrb();}
 window.addEventListener('halo-native-network',()=>{if(!document.hidden){stats();lava();wake.checkHealth();}});
 window.addEventListener('halo-native-pause',()=>{
  if(recorder?.state==='recording'){discardRecording=true;recorder.stop();}
  wake.stop(false);source?.close();stopSpeech();
 });
 window.addEventListener('halo-native-resume',()=>{
  if(document.hidden)return;
  stats();lava();
  if(localStorage.getItem('jarvis-wake')!=='off'){wake.wanted=true;wake.start();}
  updateOrb();
 });
}
