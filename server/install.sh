#!/usr/bin/env bash
# Install the Drop server on Debian / Ubuntu (a small VM, LXC or VPS is plenty).
#
#   sudo ./install.sh                      # installs, keeps an existing gallery
#   sudo DROP_TITLE="Leo Drops" ./install.sh
#
# What it does: installs nginx, ffmpeg, python3 and Pillow; copies drop-ingest to /usr/local/bin;
# puts the gallery page in $DROP_ROOT/site; enables the nginx site on 127.0.0.1:8080.
# It never deletes items. Re-running it upgrades the page and the ingest script in place.
set -euo pipefail

# Values passed in win; otherwise keep what a previous install saved; otherwise defaults.
_root="${DROP_ROOT:-}"; _title="${DROP_TITLE:-}"
[ -r /etc/default/drop ] && . /etc/default/drop
DROP_ROOT="${_root:-${DROP_ROOT:-/srv/drop}}"
DROP_TITLE="${_title:-${DROP_TITLE:-Drop}}"
HERE="$(cd "$(dirname "$0")" && pwd)"

[ "$(id -u)" -eq 0 ] || { echo "run as root (sudo ./install.sh)"; exit 1; }
command -v apt-get >/dev/null || { echo "this installer expects Debian/Ubuntu (apt-get)"; exit 1; }

echo "==> packages"
apt-get update -qq
DEBIAN_FRONTEND=noninteractive apt-get install -y -qq nginx ffmpeg python3 python3-pil fonts-dejavu-core curl >/dev/null

echo "==> files"
mkdir -p "$DROP_ROOT/site/i" "$DROP_ROOT/inbox" "$DROP_ROOT/trash"
chmod 700 "$DROP_ROOT/inbox" "$DROP_ROOT/trash"
install -m 755 "$HERE/drop-ingest.py" /usr/local/lib/drop-ingest.py
install -m 644 "$HERE/index.html" "$DROP_ROOT/site/index.html"

# Remember the root and title for every later drop-ingest run (SSH sessions included).
cat > /etc/default/drop <<EOF
DROP_ROOT=$DROP_ROOT
DROP_TITLE="$DROP_TITLE"
EOF
# Small wrapper so /etc/default/drop is honoured no matter how drop-ingest is called.
cat > /usr/local/bin/drop-ingest <<'EOF'
#!/bin/sh
set -a; [ -r /etc/default/drop ] && . /etc/default/drop; set +a
exec python3 /usr/local/lib/drop-ingest.py "$@"
EOF
chmod 755 /usr/local/bin/drop-ingest

echo "==> nginx"
sed "s#/srv/drop/site#$DROP_ROOT/site#" "$HERE/drop.nginx.conf" > /etc/nginx/sites-available/drop
ln -sf /etc/nginx/sites-available/drop /etc/nginx/sites-enabled/drop
if [ -L /etc/nginx/sites-enabled/default ]; then
  echo "    note: leaving /etc/nginx/sites-enabled/default in place; Drop listens on 127.0.0.1:8080"
fi
nginx -t
systemctl enable --now nginx >/dev/null
systemctl reload nginx

echo "==> index"
drop-ingest reindex

echo "==> check"
curl -s -o /dev/null -w "    page  %{http_code}\n" http://127.0.0.1:8080/
curl -s -o /dev/null -w "    index %{http_code}\n" http://127.0.0.1:8080/index.json
cat <<EOF

Drop is serving on http://127.0.0.1:8080 (local only, no login of its own).
Next: put an access layer in front of it.
  Tailscale:   docs/tailscale.md
  Cloudflare:  docs/cloudflare-access.md
Then point the drop client at this box (client/config.example.toml).
EOF
