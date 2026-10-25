#!/usr/bin/env python3
"""Provision the installed app over authorized USB; secrets never printed."""
import json
from pathlib import Path
import re
import shlex
import socket
import subprocess
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server'))
from wifi_link import identity,PORT

def run(*args):return subprocess.check_output(args,text=True).strip()

rows=[line.split() for line in run('adb','devices','-l').splitlines()[1:] if line.strip()]
phones=[row for row in rows if len(row)>1 and row[1]=='device']
phones.sort(key=lambda row:'model:NOH_AL00' not in row)
if not phones:sys.exit('Connect and authorize the Huawei over USB first.')
serial=phones[0][0]
phone_route=run('adb','-s',serial,'shell','ip','route')
match=re.search(r'\bsrc\s+(\d+\.\d+\.\d+\.\d+)',phone_route)
if not match:sys.exit('Connect the phone to the same Wi-Fi network as the laptop first.')
route=json.loads(run('ip','-j','route','get',match[1]))[0]
info=identity()
config={'name':socket.gethostname(),'host':route['prefsrc'],'port':PORT,
        'fingerprint':info['fingerprint'],'token':info['token']}
# --visualiser pairs the separate Visualiser app instead of Halo.
activity='dev.halo.visualiser/.MainActivity' if '--visualiser' in sys.argv else 'dev.halo.phone/.MainActivity'
subprocess.run(['adb','-s',serial,'shell','am','start','-n',activity,
                '--es','halo_pair',shlex.quote(json.dumps(config))],check=True,capture_output=True)
print('Confirm Pair on the phone. Laptop fingerprint:',info['fingerprint'][:16])
