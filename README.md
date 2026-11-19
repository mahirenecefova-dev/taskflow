# TaskFlow — Tapşırıq İdarəetmə Sistemi (MySQL versiyası)

Flask (backend) + HTML/CSS/JavaScript (frontend) + **MySQL** ilə hazırlanmış şəxsi tapşırıq meneceri.

## Xüsusiyyətlər
- İstifadəçi qeydiyyatı və giriş (hash-lənmiş parol, sessiya)
- Tapşırıq CRUD, status (`Gözləyir / Davam edir / Tamamlanıb`), prioritet, son tarix
- Axtarış, filtr, çeşidləmə
- Şəxsi dashboard (statistika, tamamlanma faizi, yaxınlaşan son tarixlər)
- Fəaliyyət logları (`logs/taskflow.log`: qeydiyyat, giriş, uğursuz giriş, tapşırıq əməliyyatları)

## Qovluq strukturu
```
taskflow-mysql/
├── app.py                # Flask backend + REST API (PyMySQL)
├── schema.sql            # MySQL cədvəlləri
├── static/               # index.html, style.css, app.js
├── tests/test_app.py     # pytest (real MySQL test bazası tələb edir)
├── deploy/               # nginx, systemd, VM quraşdırma skriptləri
├── docs/architecture.md  # arxitektura diaqramı (Mermaid)
├── docker-compose.yml    # lokal MySQL üçün
└── .env.example
```

## 1. Lokal işə salmaq

**MySQL-i hazırlayın** (iki yoldan biri):

*Docker ilə:*
```bash
docker compose up -d
export DB_PASSWORD=taskflowpass
```

*Öz MySQL-inizdə:*
```sql
CREATE DATABASE taskflow CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'taskflow'@'localhost' IDENTIFIED BY 'taskflowpass';
GRANT ALL PRIVILEGES ON taskflow.* TO 'taskflow'@'localhost';
```

**Tətbiqi işə salın:**
```bash
python3 -m venv venv && source venv/bin/activate     # Windows: venv\Scripts\activate
pip install -r requirements.txt
export DB_PASSWORD=taskflowpass                       # Windows: set DB_PASSWORD=taskflowpass
python app.py                                         # http://localhost:5000
```
Cədvəllər ilk başlanğıcda avtomatik yaranır (`schema.sql`). Əl ilə yaratmaq istəsəniz: `mysql -u root -p < schema.sql`.

Mühit dəyişənləri: `DB_HOST`, `DB_PORT`, `DB_USER`, `DB_PASSWORD`, `DB_NAME`, `SECRET_KEY` (bax: `.env.example`).

## 2. Testlər
Testlər **ayrıca test bazası** istifadə edir və hər testdən əvvəl cədvəlləri təmizləyir:
```sql
CREATE DATABASE taskflow_test CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
GRANT ALL PRIVILEGES ON taskflow_test.* TO 'taskflow'@'localhost';
```
```bash
export TEST_DB_PASSWORD=taskflowpass TEST_DB_NAME=taskflow_test
pytest -v
```

## 3. İki Ubuntu VM ilə yerləşdirmə

| VM | Rol | Port |
| --- | --- | --- |
| VM1 | Nginx (reverse proxy, HTTPS) | 80 / 443 |
| VM2 | Flask + Gunicorn + MySQL | 5000 (MySQL: yalnız localhost:3306) |

**VM2 (Flask + MySQL):**
```bash
git clone https://github.com/<istifadəçi>/taskflow.git && cd taskflow
sudo bash deploy/setup_vm2_flask.sh
curl http://localhost:5000/api/health      # {"database":"up","status":"ok",...}
```
Skript MySQL-i qurur, `taskflow` bazası və istifadəçisini yaradır, təsadüfi parolu `/etc/taskflow.env` faylına yazır və servisi işə salır.

**VM1 (Nginx):**
```bash
git clone https://github.com/<istifadəçi>/taskflow.git && cd taskflow
sudo BACKEND_IP=<VM2_IP> DOMAIN=<domeniniz> bash deploy/setup_vm1_nginx.sh
```

## 4. Loglar
| Yer | Fayl |
| --- | --- |
| VM2 tətbiq logu | `/var/log/taskflow/taskflow.log` |
| VM2 servis logu | `journalctl -u taskflow -f` |
| VM2 MySQL logu | `/var/log/mysql/error.log` |
| VM1 Nginx | `/var/log/nginx/taskflow.access.log`, `taskflow.error.log` |

## 5. MySQL ehtiyat nüsxəsi
```bash
mysqldump taskflow > taskflow_$(date +%F).sql      # VM2-də, root kimi
mysql taskflow < taskflow_2026-11-13.sql           # bərpa
```

## 6. GitHub-a yükləmək
```bash
git init && git add . && git commit -m "TaskFlow: MySQL versiyası"
git branch -M main
git remote add origin https://github.com/<istifadəçi>/taskflow.git
git push -u origin main
```
`.env`, `secret.key` və `logs/` `.gitignore`-dadır, GitHub-a düşmür.

## 7. Domain, DNS və HTTPS
1. Domen qeydiyyatçısında **A qeydi** yaradın: `@` və `www` → VM1-in ictimai IP-si.
2. DNS yayılandan sonra, VM1-də:
   ```bash
   sudo apt install -y certbot python3-certbot-nginx
   sudo certbot --nginx -d <domen> -d www.<domen>
   sudo certbot renew --dry-run
   ```
3. VM2-də `/etc/taskflow.env` faylında `TASKFLOW_SECURE_COOKIE=1` sətrini açın və `sudo systemctl restart taskflow` edin.
