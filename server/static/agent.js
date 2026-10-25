let permissionSignature='';
async function agentStatus(){
 if(document.hidden)return;
 try{
  const data=await(await fetch('/api/agent')).json(),pending=data.permissions||[];
  if(data.busy&&typeof showDraft==='function')showDraft(data.draft);
  $('#agent-stop').disabled=!data.busy;
  $('.assistant').classList.toggle('has-agent-activity',data.busy);
  if(data.busy&&document.body.dataset.state==='THINKING')$('#hint').textContent=data.activity;
  const signature=JSON.stringify(pending);
  if(signature!==permissionSignature){
   permissionSignature=signature;const panel=$('#agent-permissions');panel.replaceChildren();panel.hidden=!pending.length;
   for(const request of pending){
    const text=document.createElement('p');text.textContent=request.action+': '+request.resources.join(', ');panel.append(text);
    for(const [title,allow] of [['Allow once',true],['Deny',false]]){
     const button=document.createElement('button');button.textContent=title;
     button.onclick=async()=>{button.disabled=true;try{await api('/api/agent/permission',{id:request.id,allow});await agentStatus();}catch(error){state('IDLE',error.message);button.disabled=false;}};
     panel.append(button);
    }
   }
  }
 }catch{}
}
$('#agent-stop').onclick=async()=>{try{await api('/api/agent/cancel',{});}catch(error){state('IDLE',error.message);}};
async function pollAgent(){await agentStatus();setTimeout(pollAgent,typeof busy!=='undefined'&&busy?300:1500);}pollAgent();
