#!/usr/bin/env bash
# VM1 (Nginx reverse proxy) — Ubuntu 22.04/24.04
# İstifadə:  sudo BACKEND_IP=192.168.56.12 DOMAIN=example.com bash deploy/setup_vm1_nginx.sh
set -euo pipefail

: "${BACKEND_IP:?BACKEND_IP (VM2-nin IP-si) təyin edilməlidir}"
: "${DOMAIN:?DOMAIN təyin edilməlidir}"

apt-get update
apt-get install -y nginx ufw

sed -e "s/BACKEND_IP/${BACKEND_IP}/g" \
    -e "s/example\.com/${DOMAIN}/g" \
    deploy/nginx-taskflow.conf > /etc/nginx/sites-available/taskflow

ln -sf /etc/nginx/sites-available/taskflow /etc/nginx/sites-enabled/taskflow
rm -f /etc/nginx/sites-enabled/default

nginx -t
systemctl enable --now nginx
systemctl reload nginx

ufw allow OpenSSH
ufw allow 'Nginx Full'
ufw --force enable

echo ">> Nginx 80 portunda işləyir və http://${BACKEND_IP}:5000 ünvanına yönləndirir."
echo ">> HTTPS üçün DNS A qeydi VM1-in ictimai IP-sinə yönələndən sonra:"
echo "   sudo apt install -y certbot python3-certbot-nginx"
echo "   sudo certbot --nginx -d ${DOMAIN} -d www.${DOMAIN}"
