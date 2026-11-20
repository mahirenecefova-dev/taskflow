"""Testlər REAL MySQL bazası tələb edir (ayrıca test bazası istifadə edin, məs. taskflow_test).

    export TEST_DB_HOST=127.0.0.1 TEST_DB_USER=taskflow TEST_DB_PASSWORD=... TEST_DB_NAME=taskflow_test
    pytest -v

Test bazasına qoşulmaq mümkün deyilsə, testlər SKIP olunur. Hər testdən əvvəl cədvəllər təmizlənir!
"""
import importlib
import os
import sys

import pytest

pymysql = pytest.importorskip("pymysql")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

TEST_DB = {
    "host": os.environ.get("TEST_DB_HOST", "127.0.0.1"),
    "port": os.environ.get("TEST_DB_PORT", "3306"),
    "user": os.environ.get("TEST_DB_USER", "taskflow"),
    "password": os.environ.get("TEST_DB_PASSWORD", ""),
    "name": os.environ.get("TEST_DB_NAME", "taskflow_test"),
}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    if "test" not in TEST_DB["name"]:
        pytest.skip("TEST_DB_NAME 'test' sözünü ehtiva etməlidir (real məlumat silinməsin deyə).")
    monkeypatch.setenv("DB_HOST", TEST_DB["host"])
    monkeypatch.setenv("DB_PORT", TEST_DB["port"])
    monkeypatch.setenv("DB_USER", TEST_DB["user"])
    monkeypatch.setenv("DB_PASSWORD", TEST_DB["password"])
    monkeypatch.setenv("DB_NAME", TEST_DB["name"])
    monkeypatch.setenv("TASKFLOW_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("TASKFLOW_SECRET_FILE", str(tmp_path / "secret.key"))
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    monkeypatch.setenv("TASKFLOW_AUTO_INIT", "0")

    import app as app_module

    importlib.reload(app_module)
    try:
        app_module.init_schema()
        conn = app_module.connect()
    except pymysql.err.OperationalError as e:
        pytest.skip(f"Test MySQL bazasına qoşulmaq olmur: {e}")
    with conn.cursor() as cur:
        cur.execute("SET FOREIGN_KEY_CHECKS = 0")
        cur.execute("TRUNCATE TABLE tasks")
        cur.execute("TRUNCATE TABLE users")
        cur.execute("SET FOREIGN_KEY_CHECKS = 1")
    conn.close()

    app_module.app.config["TESTING"] = True
    c = app_module.app.test_client()
    c.app_module = app_module
    return c


def register(c, username="ali", password="secret123"):
    return c.post("/api/register", json={"username": username, "password": password})


def test_register_login_logout(client):
    assert register(client).status_code == 201
    assert client.get("/api/me").get_json()["username"] == "ali"
    client.post("/api/logout")
    assert client.get("/api/me").status_code == 401
    assert client.post("/api/login", json={"username": "ali", "password": "yanlis"}).status_code == 401
    assert client.post("/api/login", json={"username": "ali", "password": "secret123"}).status_code == 200


def test_register_validation(client):
    assert register(client, "a", "secret123").status_code == 400
    assert register(client, "valid_user", "123").status_code == 400
    assert register(client).status_code == 201
    assert register(client).status_code == 409
    assert register(client, "ALI").status_code == 409  # böyük/kiçik hərf fərqi yoxdur


def test_tasks_require_login(client):
    assert client.get("/api/tasks").status_code == 401
    assert client.post("/api/tasks", json={"title": "x"}).status_code == 401


def test_crud(client):
    register(client)
    r = client.post("/api/tasks", json={"title": "Dərs", "priority": "high", "due_date": "2030-01-01"})
    assert r.status_code == 201
    task = r.get_json()
    tid = task["id"]
    assert task["status"] == "todo" and task["due_date"] == "2030-01-01"

    assert len(client.get("/api/tasks").get_json()) == 1

    r = client.put(f"/api/tasks/{tid}", json={"title": "Yeni ad", "status": "in_progress"})
    assert r.get_json()["title"] == "Yeni ad"
    assert r.get_json()["status"] == "in_progress"

    r = client.patch(f"/api/tasks/{tid}/status", json={"status": "done"})
    assert r.get_json()["completed_at"] is not None
    r = client.patch(f"/api/tasks/{tid}/status", json={"status": "todo"})
    assert r.get_json()["completed_at"] is None

    assert client.delete(f"/api/tasks/{tid}").status_code == 200
    assert client.get("/api/tasks").get_json() == []
    assert client.delete(f"/api/tasks/{tid}").status_code == 404


def test_task_validation(client):
    register(client)
    assert client.post("/api/tasks", json={"title": ""}).status_code == 400
    assert client.post("/api/tasks", json={"title": "a", "priority": "x"}).status_code == 400
    assert client.post("/api/tasks", json={"title": "a", "status": "x"}).status_code == 400
    assert client.post("/api/tasks", json={"title": "a", "due_date": "01.01.2030"}).status_code == 400


def test_users_isolated(client):
    register(client, "ali")
    tid = client.post("/api/tasks", json={"title": "gizli"}).get_json()["id"]
    client.post("/api/logout")
    register(client, "veli")
    assert client.get("/api/tasks").get_json() == []
    assert client.put(f"/api/tasks/{tid}", json={"title": "hack"}).status_code == 404
    assert client.patch(f"/api/tasks/{tid}/status", json={"status": "done"}).status_code == 404
    assert client.delete(f"/api/tasks/{tid}").status_code == 404


def test_filter_search_sort(client):
    register(client)
    client.post("/api/tasks", json={"title": "Alma almaq", "priority": "low", "due_date": "2030-05-01"})
    client.post("/api/tasks", json={"title": "Hesabat 100%", "priority": "high", "status": "done"})
    client.post("/api/tasks", json={"title": "Zəng et", "priority": "medium", "due_date": "2030-01-01"})

    assert len(client.get("/api/tasks?status=done").get_json()) == 1
    assert len(client.get("/api/tasks?priority=low").get_json()) == 1
    assert client.get("/api/tasks?q=hesab").get_json()[0]["title"] == "Hesabat 100%"
    assert len(client.get("/api/tasks?q=%25").get_json()) == 1  # '%' literal axtarılır, hamısı yox
    assert client.get("/api/tasks?q=nəsə'; DROP TABLE tasks;--").get_json() == []
    by_prio = [t["priority"] for t in client.get("/api/tasks?sort=priority").get_json()]
    assert by_prio == ["high", "medium", "low"]
    by_due = [t["due_date"] for t in client.get("/api/tasks?sort=due").get_json()]
    assert by_due[0] == "2030-01-01" and by_due[-1] is None
    assert client.get("/api/tasks?sort=id;DROP").status_code == 200  # whitelist-ə düşür


def test_stats(client):
    register(client)
    client.post("/api/tasks", json={"title": "a", "status": "done"})
    client.post("/api/tasks", json={"title": "b", "due_date": "2000-01-01"})  # gecikmiş
    client.post("/api/tasks", json={"title": "c", "status": "in_progress", "priority": "high",
                                    "due_date": "2999-01-01"})
    s = client.get("/api/stats").get_json()
    assert s["total"] == 3
    assert s["by_status"] == {"todo": 1, "in_progress": 1, "done": 1}
    assert s["overdue"] == 1
    assert s["completion_rate"] == 33
    assert s["by_priority"]["high"] == 1
    assert [t["title"] for t in s["upcoming"]] == ["c"]


def test_password_is_hashed_and_logs_written(client, tmp_path):
    register(client)
    client.post("/api/login", json={"username": "ali", "password": "wrong"})
    conn = client.app_module.connect()
    with conn.cursor() as cur:
        cur.execute("SELECT password_hash FROM users WHERE username='ali'")
        h = cur.fetchone()["password_hash"]
    conn.close()
    assert "secret123" not in h and ("scrypt" in h or "pbkdf2" in h)
    for handler in client.app_module.log.handlers:
        handler.flush()
    log_text = (tmp_path / "logs" / "taskflow.log").read_text(encoding="utf-8")
    assert "REGISTER" in log_text and "LOGIN_FAIL" in log_text


def test_frontend_and_health(client):
    assert client.get("/").status_code == 200
    assert b"TaskFlow" in client.get("/").data
    h = client.get("/api/health").get_json()
    assert h["status"] == "ok" and h["database"] == "up"
    assert client.get("/static/app.js").status_code == 200
