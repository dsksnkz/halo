"""Halo's persistent OpenCode agent, powered by Gemini 3.5 Flash-Lite."""
import http.client
import json
from pathlib import Path
import subprocess
import threading
import time
from datetime import datetime
from reply_text import readable, spoken

MODEL_REF={'providerID':'google','id':'gemini-3.5-flash-lite'}
MODEL='google/gemini-3.5-flash-lite'
DISPLAY_NAME='GEMINI 3.5 LITE'
STATE=Path.home()/'.local/state/halo/opencode-session.json'
_lock=threading.RLock()
_status={'busy':False,'activity':'Ready','permissions':[],'session_id':None,'draft':'','request_id':None}


ROUTES={'server.info':('GET','/api/info'),'agent.get':('GET','/api/agent/{agentID}'),
        'session.create':('POST','/api/session'),'session.get':('GET','/api/session/{sessionID}'),
        'session.update':('PATCH','/api/session/{sessionID}'),'session.switchAgent':('POST','/api/session/{sessionID}/agent'),
        'session.prompt':('POST','/api/session/{sessionID}/prompt'),'session.interrupt':('POST','/api/session/{sessionID}/interrupt'),
        'session.message.list':('GET','/api/session/{sessionID}/message'),
        'session.permission.create':('POST','/api/session/{sessionID}/permission'),
        'session.permission.list':('GET','/api/session/{sessionID}/permission'),
        'session.permission.reply':('POST','/api/session/{sessionID}/permission/{requestID}/reply')}
_local=threading.local()
_server={}


def server_info():
    """The CLI discovers the loopback service; cache it until a call fails."""
    if not _server:_server.update(cli('server.info'))
    return {key:value for key,value in _server.items() if key!='auth'}


def _authorization():
    # Same loopback credential the event stream uses; it stays in this process.
    if 'auth' not in _server:
        import base64
        password=json.loads((Path.home()/'.config/opencode/service.json').read_text())['password']
        _server['auth']='Basic '+base64.b64encode(('opencode:'+password).encode()).decode()
    return _server['auth']


def http_api(operation,data,params):
    from urllib.parse import quote,urlencode,urlparse
    method,path=ROUTES[operation];query=dict(params)
    for key in list(query):
        if '{'+key+'}' in path:path=path.replace('{'+key+'}',quote(str(query.pop(key)),safe=''))
    if query:path+='?'+urlencode(query)
    url=next(urlparse(u) for u in server_info()['urls'] if urlparse(u).scheme=='http' and urlparse(u).hostname=='127.0.0.1')
    headers={'Authorization':_authorization(),'Content-Type':'application/json'}
    if method!='GET':
        # Writes get a fresh connection, so a stale keep-alive socket can never
        # make a prompt or permission reply ambiguous.
        connection=http.client.HTTPConnection(url.hostname,url.port,timeout=15)
        try:
            connection.request(method,path,body=None if data is None else json.dumps(data),headers=headers)
            response=connection.getresponse();body=response.read()
        finally:connection.close()
    else:
        for attempt in (0,1):
            connection=getattr(_local,'connection',None)
            if connection is None or (connection.host,connection.port)!=(url.hostname,url.port):
                connection=_local.connection=http.client.HTTPConnection(url.hostname,url.port,timeout=15)
            try:
                connection.request(method,path,headers=headers);response=connection.getresponse();body=response.read();break
            except (OSError,http.client.HTTPException):
                connection.close();_local.connection=None
                if attempt:raise
    if response.status>=400:raise RuntimeError('OpenCode request failed. Check the OpenCode service on the laptop.')
    if not body.strip():return {}
    try:return json.loads(body)
    except ValueError:raise RuntimeError('OpenCode returned an unexpected response.')


def api(operation,data=None,**params):
    # Direct loopback HTTP avoids ~90 ms of CLI start-up per call; the CLI
    # remains the fallback, e.g. after the service restarts on a new port.
    if operation in ROUTES:
        try:return http_api(operation,data,params)
        except (OSError,http.client.HTTPException,StopIteration,KeyError,ValueError):
            _server.clear()
    return cli(operation,data,**params)


def cli(operation,data=None,**params):
    command=['/usr/bin/opencode','api',operation]
    for key,value in params.items():command+=['--param',key+'='+str(value)]
    if data is not None:command+=['--data',json.dumps(data)]
    result=subprocess.run(command,capture_output=True,text=True,timeout=15)
    if result.returncode:raise RuntimeError('OpenCode request failed. Check the OpenCode service on the laptop.')
    if not result.stdout.strip():return {}
    try:return json.loads(result.stdout)
    except ValueError:raise RuntimeError('OpenCode returned an unexpected response.')


def status():
    with _lock:return json.loads(json.dumps(_status))


def update(**values):
    with _lock:_status.update(values)


def session():
    with _lock:
        if _status['session_id']:return _status['session_id']
        if STATE.exists():
            try:
                sid=json.loads(STATE.read_text())['session_id']
                info=api('session.get',sessionID=sid)['data']
                if all(info.get('model',{}).get(key)==value for key,value in MODEL_REF.items()):
                    # A dashboard restart loses its waiting HTTP request. Stop
                    # an orphaned turn in Halo's own session before accepting
                    # another prompt, rather than queuing behind it forever.
                    api('session.interrupt',{'continue':False},sessionID=sid)
                    if info.get('agent')!='halo':api('session.switchAgent',{'agent':'halo'},sessionID=sid)
                    _status['session_id']=sid;return sid
                api('session.interrupt',{'continue':False},sessionID=sid)
                api('session.update',{'archived':True},sessionID=sid)
            except Exception:pass
        info=api('session.create',{'title':'Halo voice agent','agent':'halo',
                 'model':MODEL_REF,
                 'location':{'directory':str(Path.home())}})['data']
        sid=info['id'];STATE.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        STATE.write_text(json.dumps({'session_id':sid}));STATE.chmod(0o600)
        _status['session_id']=sid;return sid


def reset():
    old=_status['session_id']
    if old:api('session.update',{'archived':True},sessionID=old)
    if STATE.exists():STATE.unlink()
    update(session_id=None,activity='Ready',permissions=[])


def available():
    try:
        agent=api('agent.get',agentID='halo').get('data') or {}
        return agent.get('model')==MODEL_REF
    except Exception:return False


def permission_reply(request_id,allow):
    sid=session()
    # Only a pending request belonging to Halo may be answered by this page.
    pending=api('session.permission.list',sessionID=sid).get('data',[])
    if not any(p['id']==request_id for p in pending):raise ValueError('This permission request is no longer pending.')
    api('session.permission.reply',{'decision':'once' if allow else 'reject'},sessionID=sid,requestID=request_id)


def cancel():
    sid=_status['session_id']
    if sid:api('session.interrupt',{'continue':False},sessionID=sid)


def answer(history,web=True):
    sid=session();user=next(m['content'] for m in reversed(history) if m['role']=='user')
    prompt=('Current laptop time: '+datetime.now().astimezone().isoformat(timespec='seconds')+'. '
            'This phone uses this laptop for speech, voice and running tools. Your answers come from Google Gemini 3.5 Flash-Lite in Google\'s cloud, not a local model.  '
            +('Use internet research only when needed for current facts. ' if web else 'Do not use the internet for this request. ')
            +'Reply in brief, plain spoken English. Current user request:\n'+user)
    update(busy=True,activity=DISPLAY_NAME+' is working',permissions=[],draft='',request_id=None)
    live=None
    try:
        from opencode_events import AnswerStream
        try:live=AnswerStream(server_info(),sid,lambda text:update(draft=readable(text)))
        except Exception:pass
        submitted=api('session.prompt',{'text':prompt},sessionID=sid)['data']
        start_id=submitted['id'];started=submitted['time']['created'];deadline=time.monotonic()+600
        update(request_id=start_id)
        while time.monotonic()<deadline:
            messages=api('session.message.list',sessionID=sid,order='desc',limit=60).get('data',[])
            recent=[m for m in messages if m.get('time',{}).get('created',0)>=started]
            pending=api('session.permission.list',sessionID=sid).get('data',[])
            assistant=next((m for m in recent if m.get('type')=='assistant' and any(p.get('type')=='text' and p.get('text') for p in m.get('content',[]))),None)
            raw='\n'.join(p['text'] for p in assistant.get('content',[]) if p.get('type')=='text') if assistant else ''
            activity=DISPLAY_NAME+' is working'
            for message in recent:
                for part in message.get('content',[]):
                    if part.get('type')=='tool':
                        state=part.get('state',{});command=state.get('input',{}).get('command')
                        activity=part.get('name','Tool')+': '+(str(command)[:180] if command else state.get('status','running'))
                        break
                if activity!=DISPLAY_NAME+' is working':break
            update(activity='Permission needed' if pending else activity,permissions=pending)
            if raw:update(draft=readable(raw))
            idle=next((m for m in recent if m.get('type')=='idle'),None)
            if idle:
                if idle.get('outcome')=='interrupted':return {'text':'Stopped.','sources':[],'searched':False}
                if idle.get('outcome')=='failed':raise RuntimeError('OpenCode could not finish. Check its session on the laptop.')
                for message in recent:
                    if message.get('type')=='assistant' and message.get('finish') not in ('tool-calls',None):
                        text='\n'.join(p['text'] for p in message.get('content',[]) if p.get('type')=='text').strip()
                        if text:return {'text':readable(text),'spoken':spoken(text),'sources':[],'searched':False,'agent_session':sid}
                return {'text':'The agent finished. Check the laptop for the result.','sources':[],'searched':False}
            # Native events wake the loop as soon as Halo's session changes;
            # the timeout keeps polling as the fallback.
            if live and live.changed.wait(.25):live.changed.clear()
            elif not live:time.sleep(.25)
        cancel();raise RuntimeError('The agent exceeded ten minutes and was stopped.')
    finally:
        if live:live.close()
        update(busy=False,activity='Ready',permissions=[])
