#!/usr/bin/env bash
# VM2 (Flask backend + MySQL) — Ubuntu 22.04/24.04
# İstifadə: layihə qovluğunda:  sudo bash deploy/setup_vm2_flask.sh
# MySQL VM2-də yalnız localhost-da dinləyir (xaricdən əlçatan deyil).
set -euo pipefail

APP_DIR=/opt/taskflow
LOG_DIR=/var/log/taskflow
ENV_FILE=/etc/taskflow.env
DB_NAME=taskflow
DB_USER=taskflow

apt-get update
apt-get install -y python3 python3-venv python3-pip rsync ufw mysql-server openssl

systemctl enable --now mysql

# --- verilənlər bazası və istifadəçi (parol yalnız ilk dəfə yaradılır) ---
if [ ! -f "$ENV_FILE" ]; then
  DB_PASSWORD="$(openssl rand -hex 16)"
  SECRET_KEY="$(openssl rand -hex 32)"
  cat > "$ENV_FILE" <<EOF
DB_HOST=127.0.0.1
DB_PORT=3306
DB_USER=${DB_USER}
DB_PASSWORD=${DB_PASSWORD}
DB_NAME=${DB_NAME}
SECRET_KEY=${SECRET_KEY}
# HTTPS qurulandan sonra aşağıdakı sətri açın:
# TASKFLOW_SECURE_COOKIE=1
EOF
  chmod 640 "$ENV_FILE"
  mysql <<SQL
CREATE DATABASE IF NOT EXISTS ${DB_NAME} CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER IF NOT EXISTS '${DB_USER}'@'localhost' IDENTIFIED BY '${DB_PASSWORD}';
GRANT ALL PRIVILEGES ON ${DB_NAME}.* TO '${DB_USER}'@'localhost';
FLUSH PRIVILEGES;
SQL
  echo ">> MySQL bazası və istifadəçisi yaradıldı. Parol: $ENV_FILE"
else
  echo ">> $ENV_FILE mövcuddur, DB/istifadəçi yaradılması keçildi."
fi

# --- tətbiq ---
id -u taskflow &>/dev/null || useradd --system --home "$APP_DIR" --shell /usr/sbin/nologin taskflow
chgrp taskflow "$ENV_FILE"

mkdir -p "$APP_DIR" "$LOG_DIR"
rsync -a --exclude venv --exclude logs --exclude .git --exclude .env ./ "$APP_DIR/"

python3 -m venv "$APP_DIR/venv"
"$APP_DIR/venv/bin/pip" install --upgrade pip
"$APP_DIR/venv/bin/pip" install -r "$APP_DIR/requirements.txt"

chown -R taskflow:taskflow "$APP_DIR" "$LOG_DIR"

cp deploy/taskflow.service /etc/systemd/system/taskflow.service
systemctl daemon-reload
systemctl enable --now taskflow
sleep 2

echo ">> Gunicorn/Flask 5000 portunda işləyir (cədvəllər ilk başlanğıcda avtomatik yaranır)."
echo ">> Firewall: yalnız VM1-in IP-sinə icazə verin, məs:"
echo "   sudo ufw allow OpenSSH && sudo ufw allow from <VM1_IP> to any port 5000 && sudo ufw enable"
curl -s http://127.0.0.1:5000/api/health || true
echo
