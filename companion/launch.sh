#!/usr/bin/env bash
set -euo pipefail
companion_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
systemctl --user start halo-background.service
exec /usr/bin/python "$companion_dir/companion.py" "$@"
