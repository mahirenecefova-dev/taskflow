[architecture.md](https://github.com/user-attachments/files/35132768/architecture.md)
# TaskFlow (MySQL) — Arxitektura

```mermaid
flowchart LR
    U[İstifadəçi / Brauzer] -- "HTTPS :443" --> DNS[(DNS A qeydi\ndomen)]
    DNS --> N

    subgraph VM1["VM1 — Ubuntu (Nginx)"]
        N[Nginx\nport 80 / 443\nReverse proxy + TLS]
        NL[/var/log/nginx/\naccess + error/]
        N --> NL
    end

    subgraph VM2["VM2 — Ubuntu (Flask + MySQL)"]
        G[Gunicorn + Flask\nport 5000]
        DB[(MySQL 8\nport 3306\nyalnız localhost\nusers, tasks)]
        L[/logs/taskflow.log/]
        G -- "PyMySQL" --> DB
        G --> L
    end

    N -- "HTTP :5000\nX-Real-IP başlığı" --> G

    GH[(GitHub\nrepozitori)] -. "git clone / pull" .-> VM2
    LE[Let's Encrypt\nCertbot] -. "sertifikat" .-> N
```

## Komponentlər

| Komponent | Rol | Port |
| --- | --- | --- |
| Brauzer (HTML/CSS/JS) | İstifadəçi interfeysi (SPA) | — |
| Nginx (VM1) | Reverse proxy, HTTPS, access log | 80 / 443 |
| Flask + Gunicorn (VM2) | REST API + statik faylların verilməsi | 5000 |
| MySQL 8 (VM2) | `users`, `tasks` cədvəlləri (InnoDB, utf8mb4) | 3306 (localhost) |
| Log sistemi | `taskflow.log` (rotasiya ilə) + Nginx logları | — |

## Verilənlər bazası

```mermaid
erDiagram
    users ||--o{ tasks : "sahibdir (ON DELETE CASCADE)"
    users {
        INT id PK
        VARCHAR username UK
        VARCHAR password_hash
        DATETIME created_at
    }
    tasks {
        INT id PK
        INT user_id FK
        VARCHAR title
        TEXT description
        ENUM status "todo | in_progress | done"
        ENUM priority "low | medium | high"
        DATE due_date
        DATETIME created_at
        DATETIME updated_at
        DATETIME completed_at
    }
```

İndekslər: `uq_users_username` (unikal), `idx_tasks_user_status (user_id, status)`, `idx_tasks_user_due (user_id, due_date)`.

## API xülasəsi

| Metod | Yol | Təsvir |
| --- | --- | --- |
| POST | `/api/register` | Qeydiyyat |
| POST | `/api/login` | Giriş |
| POST | `/api/logout` | Çıxış |
| GET | `/api/me` | Cari istifadəçi |
| GET | `/api/tasks?status=&priority=&q=&sort=` | Siyahı, filtr, axtarış |
| POST | `/api/tasks` | Yeni tapşırıq |
| PUT | `/api/tasks/<id>` | Redaktə |
| PATCH | `/api/tasks/<id>/status` | Status dəyişmək |
| DELETE | `/api/tasks/<id>` | Silmək |
| GET | `/api/stats` | Dashboard statistikası |
| GET | `/api/health` | Sağlamlıq yoxlaması (DB daxil) |

## Təhlükəsizlik qeydləri

- Bütün SQL sorğuları parametrlidir (`%s`); sütun adları və `ORDER BY` yalnız whitelist-dən seçilir → SQL injection-a qarşı.
- Parollar `werkzeug` ilə hash-lənir.
- Sessiya cookie-si `HttpOnly`, `SameSite=Lax`; HTTPS-dən sonra `TASKFLOW_SECURE_COOKIE=1`.
- Hər sorğu `user_id` ilə süzülür — istifadəçi başqasının məlumatına çata bilmir.
- MySQL yalnız `localhost`-da dinləyir; DB parolu `/etc/taskflow.env` faylındadır (`chmod 640`).
- VM2-də firewall yalnız VM1-dən 5000 portuna icazə verməlidir.
