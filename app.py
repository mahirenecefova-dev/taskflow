"""TaskFlow - Flask backend (MySQL / PyMySQL, sessiya ilə autentifikasiya, loglama)."""
import logging
import os
import re
import secrets
from datetime import date, datetime
from functools import wraps
from logging.handlers import RotatingFileHandler

import pymysql
from flask import Flask, g, jsonify, request, send_from_directory, session
from pymysql.cursors import DictCursor
from werkzeug.security import check_password_hash, generate_password_hash

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.environ.get("TASKFLOW_LOG_DIR", os.path.join(BASE_DIR, "logs"))
SECRET_FILE = os.environ.get("TASKFLOW_SECRET_FILE", os.path.join(BASE_DIR, "secret.key"))
os.makedirs(LOG_DIR, exist_ok=True)

STATUSES = ("todo", "in_progress", "done")
PRIORITIES = ("low", "medium", "high")

# ---------------------------------------------------------------- konfiqurasiya
DB_CONFIG = {
    "host": os.environ.get("DB_HOST", "127.0.0.1"),
    "port": int(os.environ.get("DB_PORT", "3306")),
    "user": os.environ.get("DB_USER", "taskflow"),
    "password": os.environ.get("DB_PASSWORD", ""),
    "database": os.environ.get("DB_NAME", "taskflow"),
}

# ---------------------------------------------------------------- logging
log = logging.getLogger("taskflow")
log.setLevel(logging.INFO)
for _h in list(log.handlers):  # modul yenidən yüklənəndə köhnə handler-lər təmizlənir
    log.removeHandler(_h)
    _h.close()
_fmt = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
_fh = RotatingFileHandler(
    os.path.join(LOG_DIR, "taskflow.log"), maxBytes=1_000_000, backupCount=5, encoding="utf-8"
)
_fh.setFormatter(_fmt)
_sh = logging.StreamHandler()
_sh.setFormatter(_fmt)
log.addHandler(_fh)
log.addHandler(_sh)

# ---------------------------------------------------------------- app
app = Flask(__name__, static_folder="static", static_url_path="/static")


def _get_secret():
    env = os.environ.get("SECRET_KEY")
    if env:
        return env
    if os.path.exists(SECRET_FILE):
        with open(SECRET_FILE, encoding="utf-8") as f:
            return f.read().strip()
    key = secrets.token_hex(32)
    with open(SECRET_FILE, "w", encoding="utf-8") as f:
        f.write(key)
    return key


app.secret_key = _get_secret()
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    # HTTPS qurulandan sonra: TASKFLOW_SECURE_COOKIE=1
    SESSION_COOKIE_SECURE=os.environ.get("TASKFLOW_SECURE_COOKIE") == "1",
    MAX_CONTENT_LENGTH=64 * 1024,
)


# ---------------------------------------------------------------- MySQL
def connect():
    return pymysql.connect(
        **DB_CONFIG,
        charset="utf8mb4",
        cursorclass=DictCursor,
        autocommit=True,
        connect_timeout=5,
    )


def get_db():
    """Hər sorğu üçün bir bağlantı (sorğu bitəndə bağlanır)."""
    if "db" not in g:
        g.db = connect()
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def query(sql, params=(), one=False):
    with get_db().cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchone() if one else cur.fetchall()


def execute(sql, params=()):
    """INSERT/UPDATE/DELETE: (lastrowid, təsirlənən sətir sayı) qaytarır."""
    with get_db().cursor() as cur:
        cur.execute(sql, params)
        return cur.lastrowid, cur.rowcount


def init_schema():
    """schema.sql-dəki cədvəlləri yaradır (CREATE ... IF NOT EXISTS, təkrar işlətmək təhlükəsizdir)."""
    path = os.path.join(BASE_DIR, "schema.sql")
    with open(path, encoding="utf-8") as f:
        sql = f.read()
    # CREATE DATABASE / USE sətirləri atılır: bağlantı artıq DB_NAME-ə qoşulub
    statements = [
        s.strip()
        for s in re.sub(r"--.*", "", sql).split(";")
        if s.strip() and not re.match(r"(?i)^(create\s+database|use)\b", s.strip())
    ]
    conn = connect()
    try:
        with conn.cursor() as cur:
            for stmt in statements:
                cur.execute(stmt)
    finally:
        conn.close()
    log.info("DB_SCHEMA | cədvəllər hazırdır (%s@%s/%s)", DB_CONFIG["user"], DB_CONFIG["host"], DB_CONFIG["database"])


# ---------------------------------------------------------------- köməkçilər
def client_ip():
    return request.headers.get("X-Real-IP") or request.remote_addr


def err(message, code=400):
    return jsonify({"error": message}), code


def iso(v):
    if isinstance(v, datetime):
        return v.isoformat(timespec="seconds")
    if isinstance(v, date):
        return v.isoformat()
    return v


def public_task(row):
    return {
        "id": row["id"],
        "title": row["title"],
        "description": row["description"] or "",
        "status": row["status"],
        "priority": row["priority"],
        "due_date": iso(row["due_date"]),
        "created_at": iso(row["created_at"]),
        "updated_at": iso(row["updated_at"]),
        "completed_at": iso(row["completed_at"]),
    }


# ---------------------------------------------------------------- auth
def login_required(fn):
    @wraps(fn)
    def wrapper(*a, **kw):
        if not session.get("uid"):
            return err("Daxil olmalısınız.", 401)
        return fn(*a, **kw)

    return wrapper


USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,32}$")


@app.post("/api/register")
def register():
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    if not USERNAME_RE.match(username):
        return err("İstifadəçi adı 3-32 simvol olmalı (hərf, rəqəm, _ . -).")
    if len(password) < 6 or len(password) > 128:
        return err("Parol ən azı 6 simvol olmalıdır.")
    try:
        uid, _ = execute(
            "INSERT INTO users (username, password_hash) VALUES (%s, %s)",
            (username, generate_password_hash(password)),
        )
    except pymysql.err.IntegrityError:  # UNIQUE (username)
        log.warning("REGISTER_FAIL | user=%s | ip=%s | səbəb=mövcuddur", username, client_ip())
        return err("Bu istifadəçi adı artıq mövcuddur.", 409)
    session.clear()
    session["uid"] = uid
    log.info("REGISTER | user=%s | ip=%s", username, client_ip())
    return jsonify({"id": uid, "username": username}), 201


@app.post("/api/login")
def login():
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    user = query("SELECT id, username, password_hash FROM users WHERE username = %s", (username,), one=True)
    if not user or not check_password_hash(user["password_hash"], password):
        log.warning("LOGIN_FAIL | user=%s | ip=%s", username, client_ip())
        return err("İstifadəçi adı və ya parol yanlışdır.", 401)
    session.clear()
    session["uid"] = user["id"]
    log.info("LOGIN | user=%s | ip=%s", user["username"], client_ip())
    return jsonify({"id": user["id"], "username": user["username"]})


@app.post("/api/logout")
def logout():
    uid = session.get("uid")
    session.clear()
    if uid:
        log.info("LOGOUT | uid=%s | ip=%s", uid, client_ip())
    return jsonify({"ok": True})


@app.get("/api/me")
def me():
    uid = session.get("uid")
    if not uid:
        return err("Daxil olmayıb.", 401)
    user = query("SELECT id, username FROM users WHERE id = %s", (uid,), one=True)
    if not user:
        session.clear()
        return err("İstifadəçi tapılmadı.", 401)
    return jsonify(user)


# ---------------------------------------------------------------- tapşırıqlar
def parse_task_input(data, partial=False):
    """Girişi yoxlayır; (təmiz_dict, xəta) qaytarır."""
    out = {}
    if not partial or "title" in data:
        title = (data.get("title") or "").strip()
        if not title:
            return None, "Başlıq boş ola bilməz."
        if len(title) > 120:
            return None, "Başlıq 120 simvoldan uzun ola bilməz."
        out["title"] = title
    if "description" in data or not partial:
        desc = (data.get("description") or "").strip()
        if len(desc) > 2000:
            return None, "Təsvir çox uzundur (maks. 2000)."
        out["description"] = desc
    if "status" in data or not partial:
        st = data.get("status") or "todo"
        if st not in STATUSES:
            return None, "Yanlış status."
        out["status"] = st
    if "priority" in data or not partial:
        pr = data.get("priority") or "medium"
        if pr not in PRIORITIES:
            return None, "Yanlış prioritet."
        out["priority"] = pr
    if "due_date" in data or not partial:
        dd = (data.get("due_date") or "").strip()
        if dd:
            try:
                date.fromisoformat(dd)
            except ValueError:
                return None, "Son tarix formatı YYYY-MM-DD olmalıdır."
        out["due_date"] = dd or None
    return out, None


TASK_COLS = "id, title, description, status, priority, due_date, created_at, updated_at, completed_at"


def get_task(tid, uid):
    return query(f"SELECT {TASK_COLS} FROM tasks WHERE id = %s AND user_id = %s", (tid, uid), one=True)


def like_escape(s):
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


ORDER_BY = {
    "created": "created_at DESC, id DESC",
    "due": "due_date IS NULL, due_date ASC, id DESC",
    "priority": "FIELD(priority, 'high', 'medium', 'low'), id DESC",
}


@app.get("/api/tasks")
@login_required
def list_tasks():
    where, params = ["user_id = %s"], [session["uid"]]
    status = request.args.get("status")
    priority = request.args.get("priority")
    q = (request.args.get("q") or "").strip()
    if status in STATUSES:
        where.append("status = %s")
        params.append(status)
    if priority in PRIORITIES:
        where.append("priority = %s")
        params.append(priority)
    if q:
        where.append("(title LIKE %s OR description LIKE %s)")
        like = f"%{like_escape(q)}%"
        params += [like, like]
    order = ORDER_BY.get(request.args.get("sort", "created"), ORDER_BY["created"])  # whitelist
    rows = query(f"SELECT {TASK_COLS} FROM tasks WHERE {' AND '.join(where)} ORDER BY {order}", params)
    return jsonify([public_task(r) for r in rows])


@app.post("/api/tasks")
@login_required
def create_task():
    clean, e = parse_task_input(request.get_json(silent=True) or {})
    if e:
        return err(e)
    tid, _ = execute(
        "INSERT INTO tasks (user_id, title, description, status, priority, due_date, completed_at) "
        "VALUES (%s, %s, %s, %s, %s, %s, IF(%s = 'done', NOW(), NULL))",
        (
            session["uid"], clean["title"], clean["description"], clean["status"],
            clean["priority"], clean["due_date"], clean["status"],
        ),
    )
    log.info("TASK_CREATE | uid=%s | id=%s | title=%s", session["uid"], tid, clean["title"])
    return jsonify(public_task(get_task(tid, session["uid"]))), 201


def _update(tid, uid, clean):
    """clean-dəki sahələri yeniləyir; tapşırıq yoxdursa None qaytarır."""
    task = get_task(tid, uid)
    if not task:
        return None
    sets, params = [], []
    for col in ("title", "description", "status", "priority", "due_date"):  # sütun adları whitelist-dir
        if col in clean:
            sets.append(f"{col} = %s")
            params.append(clean[col])
    if "status" in clean:
        if clean["status"] == "done":
            sets.append("completed_at = COALESCE(completed_at, NOW())")
        else:
            sets.append("completed_at = NULL")
    if sets:
        execute(f"UPDATE tasks SET {', '.join(sets)} WHERE id = %s AND user_id = %s", (*params, tid, uid))
    return get_task(tid, uid)


@app.put("/api/tasks/<int:tid>")
@login_required
def update_task(tid):
    clean, e = parse_task_input(request.get_json(silent=True) or {}, partial=True)
    if e:
        return err(e)
    task = _update(tid, session["uid"], clean)
    if not task:
        return err("Tapşırıq tapılmadı.", 404)
    log.info("TASK_UPDATE | uid=%s | id=%s", session["uid"], tid)
    return jsonify(public_task(task))


@app.patch("/api/tasks/<int:tid>/status")
@login_required
def change_status(tid):
    status = (request.get_json(silent=True) or {}).get("status")
    if status not in STATUSES:
        return err("Yanlış status.")
    task = _update(tid, session["uid"], {"status": status})
    if not task:
        return err("Tapşırıq tapılmadı.", 404)
    log.info("TASK_STATUS | uid=%s | id=%s | status=%s", session["uid"], tid, status)
    return jsonify(public_task(task))


@app.delete("/api/tasks/<int:tid>")
@login_required
def delete_task(tid):
    _, n = execute("DELETE FROM tasks WHERE id = %s AND user_id = %s", (tid, session["uid"]))
    if not n:
        return err("Tapşırıq tapılmadı.", 404)
    log.info("TASK_DELETE | uid=%s | id=%s", session["uid"], tid)
    return jsonify({"ok": True})


@app.get("/api/stats")
@login_required
def stats():
    uid = session["uid"]
    by_status = {s: 0 for s in STATUSES}
    for r in query("SELECT status, COUNT(*) AS n FROM tasks WHERE user_id = %s GROUP BY status", (uid,)):
        by_status[r["status"]] = r["n"]
    by_priority = {p: 0 for p in PRIORITIES}
    for r in query("SELECT priority, COUNT(*) AS n FROM tasks WHERE user_id = %s GROUP BY priority", (uid,)):
        by_priority[r["priority"]] = r["n"]
    due = query(
        "SELECT COALESCE(SUM(due_date < CURDATE()), 0) AS overdue, "
        "       COALESCE(SUM(due_date = CURDATE()), 0) AS due_today "
        "FROM tasks WHERE user_id = %s AND status <> 'done' AND due_date IS NOT NULL",
        (uid,),
        one=True,
    )
    upcoming = query(
        f"SELECT {TASK_COLS} FROM tasks WHERE user_id = %s AND status <> 'done' "
        "AND due_date >= CURDATE() ORDER BY due_date ASC, id ASC LIMIT 5",
        (uid,),
    )
    total = sum(by_status.values())
    return jsonify(
        {
            "total": total,
            "by_status": by_status,
            "by_priority": by_priority,
            "overdue": int(due["overdue"]),
            "due_today": int(due["due_today"]),
            "completion_rate": round(by_status["done"] * 100 / total) if total else 0,
            "upcoming": [public_task(t) for t in upcoming],
        }
    )


@app.get("/api/health")
def health():
    try:
        query("SELECT 1 AS ok", one=True)
        db_ok = True
    except Exception as e:  # noqa: BLE001
        log.error("HEALTH_DB_FAIL | %s", e)
        db_ok = False
    return jsonify({"status": "ok" if db_ok else "degraded", "database": "up" if db_ok else "down",
                    "time": datetime.now().isoformat(timespec="seconds")}), (200 if db_ok else 503)


# ---------------------------------------------------------------- frontend
@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.errorhandler(pymysql.err.OperationalError)
def db_unavailable(e):
    log.error("DB_UNAVAILABLE | %s", e)
    return err("Verilənlər bazasına qoşulmaq mümkün olmadı.", 503)


@app.errorhandler(404)
def not_found(_):
    if request.path.startswith("/api/"):
        return err("Tapılmadı.", 404)
    return send_from_directory(app.static_folder, "index.html")


@app.errorhandler(500)
def server_error(e):
    log.exception("SERVER_ERROR | %s", e)
    return err("Daxili server xətası.", 500)


# Gunicorn-un hər worker-i başlayanda cədvəlləri yoxlayır (təhlükəsiz: IF NOT EXISTS)
if os.environ.get("TASKFLOW_AUTO_INIT", "1") == "1":
    try:
        init_schema()
    except Exception as exc:  # noqa: BLE001
        log.error("DB_SCHEMA_FAIL | DB hazır deyil: %s", exc)

if __name__ == "__main__":
    log.info("TaskFlow işə düşür")
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=False)
