#!/usr/bin/env bash
# Sets up one Ubuntu 24.04 VPS for both sites:
#   configlabs.online -> nginx (static files) + gunicorn (Flask) on 127.0.0.1:8000
#   racktrack.online  -> nginx -> next start on 127.0.0.1:3000 (+ daily digest timer)
# Safe to run more than once. First run installs everything and creates /etc/configlabs.env and
# /etc/racktrack.env from the examples; fill them in, then run it again to build and start the apps.
# HTTPS comes after the DNS points here:  certbot --nginx -d configlabs.online -d racktrack.online
set -euo pipefail

CONFIGLABS_REPO="https://github.com/NaufalBudiman/ConfigLabs.git"
RACKTRACK_REPO="https://github.com/NaufalBudiman/racktrack.online.git"
KIT="$(cd "$(dirname "$0")" && pwd)"

say() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
[ "$(id -u)" -eq 0 ] || { echo "Run this as root: sudo bash $0"; exit 1; }
. /etc/os-release
[ "${ID:-}" = "ubuntu" ] || echo "Warning: written for Ubuntu 24.04, this is ${PRETTY_NAME:-unknown}."

say "Packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -q
apt-get install -y -q git nginx python3-venv python3-pip curl ca-certificates gnupg ufw certbot python3-certbot-nginx

if ! node -v 2>/dev/null | grep -qE '^v(2[0-9]|[3-9][0-9])\.'; then
  say "Node.js 20 (NodeSource, signed apt repository)"
  install -d -m 0755 /etc/apt/keyrings
  curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key | gpg --dearmor --yes -o /etc/apt/keyrings/nodesource.gpg
  echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_20.x nodistro main" > /etc/apt/sources.list.d/nodesource.list
  apt-get update -q && apt-get install -y -q nodejs
fi

if ! swapon --show | grep -q .; then
  say "2 GB swap (next build needs the headroom)"
  fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap -q /swapfile && swapon /swapfile
  grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

say "Users and code"
for app in configlabs racktrack; do
  id "$app" >/dev/null 2>&1 || useradd --system --no-create-home --home-dir "/srv/$app" --shell /usr/sbin/nologin "$app"
  install -d -m 0755 -o "$app" -g "$app" "/srv/$app"
done
[ -d /srv/configlabs/.git ] || runuser -u configlabs -- git clone --quiet "$CONFIGLABS_REPO" /srv/configlabs
[ -d /srv/racktrack/.git ]  || runuser -u racktrack  -- git clone --quiet "$RACKTRACK_REPO"  /srv/racktrack
id deploy >/dev/null 2>&1 || useradd --create-home --shell /bin/bash deploy
install -d -m 0700 -o deploy -g deploy /home/deploy/.ssh
touch /home/deploy/.ssh/authorized_keys && chown deploy:deploy /home/deploy/.ssh/authorized_keys && chmod 600 /home/deploy/.ssh/authorized_keys

say "Environment files"
for app in configlabs racktrack; do
  if [ ! -f "/etc/$app.env" ]; then
    install -m 0640 -o root -g "$app" "$KIT/env/$app.env.example" "/etc/$app.env"
    echo "Created /etc/$app.env: fill it in (sudo nano /etc/$app.env)."
  fi
done
filled() { grep -qE "^$2=.+" "/etc/$1.env"; }

say "ConfigLabs: Python environment"
[ -x /srv/configlabs/.venv/bin/python ] || runuser -u configlabs -- python3 -m venv /srv/configlabs/.venv
runuser -u configlabs -- /srv/configlabs/.venv/bin/pip install --quiet --upgrade pip
runuser -u configlabs -- /srv/configlabs/.venv/bin/pip install --quiet -r /srv/configlabs/requirements.txt

say "Deploy scripts, sudo rule, services"
install -m 0755 "$KIT/bin/deploy-configlabs" "$KIT/bin/deploy-racktrack" /usr/local/bin/
echo "deploy ALL=(root) NOPASSWD: /usr/local/bin/deploy-configlabs, /usr/local/bin/deploy-racktrack" > /etc/sudoers.d/deploy-apps
chmod 0440 /etc/sudoers.d/deploy-apps && visudo -cf /etc/sudoers.d/deploy-apps >/dev/null
install -m 0644 "$KIT"/systemd/*.service "$KIT"/systemd/*.timer /etc/systemd/system/
systemctl daemon-reload
systemctl enable --quiet configlabs racktrack racktrack-digest.timer

say "nginx"
install -m 0644 "$KIT/nginx/configlabs-proxy.conf" /etc/nginx/snippets/configlabs-proxy.conf
for site in configlabs.online racktrack.online; do
  # keep a certbot-edited file (it holds the HTTPS blocks); only install ours the first time
  [ -f "/etc/nginx/sites-available/$site" ] && grep -q "managed by Certbot" "/etc/nginx/sites-available/$site" || \
    install -m 0644 "$KIT/nginx/$site.conf" "/etc/nginx/sites-available/$site"
  ln -sf "/etc/nginx/sites-available/$site" "/etc/nginx/sites-enabled/$site"
done
rm -f /etc/nginx/sites-enabled/default
nginx -t -q && systemctl reload nginx

say "Firewall"
ufw allow OpenSSH >/dev/null && ufw allow 'Nginx Full' >/dev/null && ufw --force enable >/dev/null

say "Start the apps"
if filled configlabs SESSION_SECRET && filled configlabs JWT_SECRET; then
  /usr/local/bin/deploy-configlabs
else
  echo "ConfigLabs not started yet: /etc/configlabs.env still needs SESSION_SECRET and JWT_SECRET."
fi
if filled racktrack AUTH_SECRET && filled racktrack DATABASE_URL; then
  /usr/local/bin/deploy-racktrack
  systemctl start racktrack-digest.timer
else
  echo "RackTrack not built yet: /etc/racktrack.env still needs AUTH_SECRET and DATABASE_URL."
fi

say "Done"
cat <<'NEXT'
Next steps (server/README.md has the details):
  1. Fill /etc/configlabs.env and /etc/racktrack.env, then run this script again.
  2. Point the DNS A records of configlabs.online and racktrack.online to this server.
  3. HTTPS:  certbot --nginx -d configlabs.online -d racktrack.online   (add the www names if they have DNS)
  4. Auto-deploy: put the GitHub Actions public key in /home/deploy/.ssh/authorized_keys.
NEXT
