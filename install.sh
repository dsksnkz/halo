#!/usr/bin/env bash
# Halo laptop server: Python env, speech models, and a user systemd service.
set -euo pipefail
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
for tool in python3 opencode playerctl cava fastfetch adb curl unzip; do
    command -v "$tool" >/dev/null || echo "warning: $tool not found (see README)"
done
python3 -m venv "$root/.venv"
"$root/.venv/bin/pip" install --quiet --upgrade pip
"$root/.venv/bin/pip" install --quiet -r "$root/server/requirements.txt"
mkdir -p "$root/models/kokoro"
fetch() { [[ -s "$2" ]] || curl -fL --progress-bar -o "$2" "$1"; }
fetch https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.fp16.onnx "$root/models/kokoro/model.onnx"
fetch https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin "$root/models/kokoro/voices.bin"
if [[ ! -d "$root/models/vosk-model-small-en-us-0.15" ]]; then
    fetch https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip "$root/models/vosk.zip"
    unzip -q "$root/models/vosk.zip" -d "$root/models" && rm "$root/models/vosk.zip"
fi
units="$HOME/.config/systemd/user"; mkdir -p "$units"
cat > "$units/halo-server.service" <<UNIT
[Unit]
Description=Halo laptop server
After=network-online.target
[Service]
ExecStart=$root/.venv/bin/python $root/server/server.py
Restart=on-failure
Nice=10
CPUWeight=20
[Install]
WantedBy=default.target
UNIT
systemctl --user daemon-reload
systemctl --user enable --now halo-server.service
echo
echo "Halo server running on 127.0.0.1:8765."
echo "Next: merge server/opencode-halo.json into ~/.config/opencode/opencode.jsonc,"
echo "install the Halo APK, then pair: .venv/bin/python android/pair-phone.py"
