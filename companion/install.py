#!/usr/bin/python
"""Install local launchers and low-priority background units. No root required."""
from pathlib import Path
import subprocess

root = Path(__file__).resolve().parent
home = Path.home()
units = home/'.config/systemd/user'
apps = home/'.local/share/applications'
autostart = home/'.config/autostart'
for directory in (units, apps, autostart):
    directory.mkdir(parents=True,exist_ok=True)
# Existing Halo backend units own the model paths and Python environment.
(units/'halo-background.service').write_text('''[Unit]
Description=Halo background services and automatic USB connection
Requires=halo-server.service
After=halo-server.service
[Service]
Type=oneshot
ExecStart=/usr/bin/true
RemainAfterExit=yes
[Install]
WantedBy=default.target
''')
(units/'halo-companion.service').write_text(f'''[Unit]
Description=Halo Companion tray application
Requires=halo-background.service
After=halo-background.service
[Service]
ExecStart=/usr/bin/python "{root}/companion.py" --background
Restart=on-failure
RestartSec=15
Nice=10
CPUWeight=20
[Install]
WantedBy=default.target
''')
for name in ('halo-server.service',):
    dropin = units/(name+'.d')
    dropin.mkdir(exist_ok=True)
    (dropin/'halo-priority.conf').write_text('[Service]\nNice=10\nCPUWeight=20\n')
entry = f'''[Desktop Entry]
Type=Application
Name=Halo Companion
Comment=Phone connection, live AI routes and shared chat
Exec="{root}/launch.sh"
Icon={root}/halo.svg
Terminal=false
Categories=Utility;Network;
StartupWMClass=Halo Companion
'''
(apps/'halo-companion.desktop').write_text(entry)
(autostart/'halo-companion.desktop').write_text(entry.replace(f'Exec="{root}/launch.sh"',f'Exec="{root}/launch.sh" --background')+'X-GNOME-Autostart-enabled=true\n')
(root/'launch.sh').chmod(0o755)
subprocess.run(['systemctl','--user','daemon-reload'],check=True)
subprocess.run(['systemctl','--user','enable','--now','halo-background.service'],check=True)
subprocess.run(['systemctl','--user','enable','--now','halo-companion.service'],check=True)
subprocess.run(['update-desktop-database',str(apps)],check=False,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
print('Installed Halo Companion. Background services enabled for login; UI starts hidden in the tray.')
