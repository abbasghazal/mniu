import json
import os
import sqlite3
import uuid
from datetime import datetime
from functools import wraps

from flask import Flask, g, jsonify, request, send_from_directory, session
from flask_cors import CORS
from werkzeug.utils import secure_filename


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("RENDER_DISK_PATH") or os.environ.get("DATA_DIR") or BASE_DIR
os.makedirs(DATA_DIR, exist_ok=True)
DB_PATH = os.environ.get("RESTAURANT_DB_PATH", os.path.join(DATA_DIR, "restaurant.db"))
UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

app = Flask(__name__, static_folder=BASE_DIR, static_url_path="")
app.secret_key = os.environ.get("RESTAURANT_SECRET", "change-this-local-restaurant-secret")
CORS(app, supports_credentials=True)


DEFAULT_USERS = [
    ("admin", "admin123", "admin"),
    ("cashier", "cashier123", "cashier"),
    ("kitchen", "kitchen123", "kitchen"),
]

DEFAULT_TABLES = [
    (str(i), "", 1) for i in range(1, 13)
]

DEFAULT_MENU = [
    ("حمص بزيت الزيتون", "المقبلات", 3500, "حمص ناعم مع طحينة، زيت زيتون، وسماق.", "https://images.unsplash.com/photo-1604329760661-e71dc83f8f26?auto=format&fit=crop&w=700&q=80"),
    ("فتوش", "المقبلات", 4000, "خضار طازجة، خبز محمص، ودبس رمان.", "https://images.unsplash.com/photo-1540189549336-e6e99c3679fe?auto=format&fit=crop&w=700&q=80"),
    ("مشاوي مشكلة", "الأطباق الرئيسية", 18000, "كباب، تكة، وشيش طاووق مع رز وخضار مشوية.", "https://images.unsplash.com/photo-1529692236671-f1f6cf9683ba?auto=format&fit=crop&w=700&q=80"),
    ("سمك مشوي", "الأطباق الرئيسية", 22000, "سمك متبل بالليمون والثوم يقدم مع سلطة.", "https://images.unsplash.com/photo-1519708227418-c8fd9a32b7a2?auto=format&fit=crop&w=700&q=80"),
    ("ليمون بالنعناع", "المشروبات", 3000, "عصير بارد منعش مع نعناع طازج.", "https://images.unsplash.com/photo-1621263764928-df1444c5e859?auto=format&fit=crop&w=700&q=80"),
    ("قهوة عربية", "المشروبات", 2500, "قهوة هيل خفيفة تقدم ساخنة.", "https://images.unsplash.com/photo-1514432324607-a09d9b4aefdd?auto=format&fit=crop&w=700&q=80"),
    ("كنافة", "الحلويات", 6000, "كنافة جبن ساخنة مع قطر وفستق.", "https://images.unsplash.com/photo-1605197183305-6cae1788bc93?auto=format&fit=crop&w=700&q=80"),
    ("بقلاوة", "الحلويات", 5000, "طبقات فستق وعجين رقيق محلى بالقطر.", "https://images.unsplash.com/photo-1519676867240-f03562e64548?auto=format&fit=crop&w=700&q=80"),
]


def db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(_error):
    connection = g.pop("db", None)
    if connection:
        connection.close()


def init_db():
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    cur = connection.cursor()
    cur.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          username TEXT UNIQUE NOT NULL,
          password TEXT NOT NULL,
          role TEXT NOT NULL CHECK(role IN ('admin','cashier','kitchen'))
        );

        CREATE TABLE IF NOT EXISTS settings (
          key TEXT PRIMARY KEY,
          value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS tables (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          number TEXT UNIQUE NOT NULL,
          image TEXT DEFAULT '',
          active INTEGER NOT NULL DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS menu_items (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          name TEXT NOT NULL,
          category TEXT NOT NULL,
          price INTEGER NOT NULL,
          description TEXT NOT NULL,
          image TEXT NOT NULL,
          active INTEGER NOT NULL DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS orders (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          table_number TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'new',
          total INTEGER NOT NULL,
          created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS order_items (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          order_id INTEGER NOT NULL,
          menu_item_id INTEGER,
          name TEXT NOT NULL,
          price INTEGER NOT NULL,
          qty INTEGER NOT NULL,
          note TEXT DEFAULT '',
          FOREIGN KEY(order_id) REFERENCES orders(id) ON DELETE CASCADE
        );
        """
    )

    if cur.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
        cur.executemany("INSERT INTO users (username, password, role) VALUES (?, ?, ?)", DEFAULT_USERS)
    if cur.execute("SELECT COUNT(*) FROM tables").fetchone()[0] == 0:
        cur.executemany("INSERT INTO tables (number, image, active) VALUES (?, ?, ?)", DEFAULT_TABLES)
    if cur.execute("SELECT COUNT(*) FROM menu_items").fetchone()[0] == 0:
        cur.executemany(
            "INSERT INTO menu_items (name, category, price, description, image) VALUES (?, ?, ?, ?, ?)",
            DEFAULT_MENU,
        )
    connection.commit()
    connection.close()


def row_dict(row):
    return dict(row) if row else None


def role_allowed(*roles):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            role = session.get("role")
            if role not in roles and role != "admin":
                return jsonify({"error": "unauthorized"}), 403
            return fn(*args, **kwargs)

        return wrapper

    return decorator


def order_payload(order):
    items = db().execute(
        "SELECT menu_item_id AS menuItemId, name, price, qty, note FROM order_items WHERE order_id = ?",
        (order["id"],),
    ).fetchall()
    return {
        "id": order["id"],
        "table": order["table_number"],
        "status": order["status"],
        "total": order["total"],
        "createdAt": order["created_at"],
        "items": [row_dict(item) for item in items],
    }


@app.route("/")
def index():
    return send_from_directory(BASE_DIR, "index.html")


@app.get("/uploads/<path:filename>")
def uploaded_file(filename):
    return send_from_directory(UPLOAD_DIR, filename)


@app.get("/api/bootstrap")
def bootstrap():
    return jsonify(
        {
            "user": {"role": session.get("role"), "username": session.get("username")},
            "dark": db().execute("SELECT value FROM settings WHERE key = 'dark'").fetchone()["value"]
            if db().execute("SELECT value FROM settings WHERE key = 'dark'").fetchone()
            else "false",
            "menu": [row_dict(r) for r in db().execute("SELECT * FROM menu_items WHERE active = 1 ORDER BY id DESC").fetchall()],
            "tables": [row_dict(r) for r in db().execute("SELECT * FROM tables WHERE active = 1 ORDER BY CAST(number AS INTEGER), number").fetchall()],
        }
    )


@app.post("/api/login")
def login():
    payload = request.get_json(force=True)
    password = payload.get("password", "")
    username = payload.get("username") or ("admin" if password == "admin123" else "")
    user = db().execute("SELECT * FROM users WHERE username = ? AND password = ?", (username, password)).fetchone()
    if not user:
        user = db().execute("SELECT * FROM users WHERE password = ?", (password,)).fetchone()
    if not user:
        return jsonify({"error": "كلمة المرور غير صحيحة"}), 401
    session["username"] = user["username"]
    session["role"] = user["role"]
    return jsonify({"username": user["username"], "role": user["role"]})


@app.post("/api/logout")
def logout():
    session.clear()
    return jsonify({"ok": True})


@app.post("/api/uploads")
@role_allowed("admin")
def upload_image():
    file = request.files.get("file")
    if not file or not file.filename:
        return jsonify({"error": "لم يتم اختيار صورة"}), 400

    filename = secure_filename(file.filename)
    ext = os.path.splitext(filename)[1].lower()
    if ext not in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".avif"}:
        return jsonify({"error": "نوع الملف غير مدعوم"}), 400

    stored_name = f"{uuid.uuid4().hex}{ext}"
    file_path = os.path.join(UPLOAD_DIR, stored_name)
    file.save(file_path)
    return jsonify({"url": f"/uploads/{stored_name}"})


@app.get("/api/orders")
@role_allowed("cashier", "kitchen")
def orders():
    rows = db().execute("SELECT * FROM orders ORDER BY datetime(created_at) DESC, id DESC").fetchall()
    return jsonify([order_payload(row) for row in rows])


@app.get("/api/orders/recent")
def recent_orders():
    table = request.args.get("table", "")
    rows = db().execute(
        "SELECT * FROM orders WHERE table_number = ? ORDER BY datetime(created_at) DESC, id DESC LIMIT 4",
        (table,),
    ).fetchall()
    return jsonify([order_payload(row) for row in rows])


@app.post("/api/orders")
def create_order():
    payload = request.get_json(force=True)
    table = str(payload.get("table", "")).strip()
    items = payload.get("items", [])
    active_table = db().execute("SELECT 1 FROM tables WHERE number = ? AND active = 1", (table,)).fetchone()
    if not table or not active_table or not items:
        return jsonify({"error": "بيانات الطلب غير مكتملة"}), 400

    menu_by_id = {
        row["id"]: row for row in db().execute("SELECT * FROM menu_items WHERE active = 1").fetchall()
    }
    normalized = []
    for item in items:
        menu_item = menu_by_id.get(int(item.get("id", 0)))
        qty = max(1, int(item.get("qty", 1)))
        if menu_item:
            normalized.append(
                {
                    "menu_item_id": menu_item["id"],
                    "name": menu_item["name"],
                    "price": menu_item["price"],
                    "qty": qty,
                    "note": str(item.get("note", ""))[:300],
                }
            )
    if not normalized:
        return jsonify({"error": "لا توجد أصناف صالحة"}), 400

    total = sum(item["price"] * item["qty"] for item in normalized)
    cur = db().execute(
        "INSERT INTO orders (table_number, status, total, created_at) VALUES (?, 'new', ?, ?)",
        (table, total, datetime.utcnow().isoformat()),
    )
    order_id = cur.lastrowid
    db().executemany(
        "INSERT INTO order_items (order_id, menu_item_id, name, price, qty, note) VALUES (?, ?, ?, ?, ?, ?)",
        [(order_id, i["menu_item_id"], i["name"], i["price"], i["qty"], i["note"]) for i in normalized],
    )
    db().commit()
    return jsonify(order_payload(db().execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone())), 201


@app.patch("/api/orders/<int:order_id>/status")
@role_allowed("cashier", "kitchen")
def update_order_status(order_id):
    status = request.get_json(force=True).get("status")
    allowed = {"new", "confirmed", "preparing", "ready", "delivered"}
    if status not in allowed:
        return jsonify({"error": "حالة غير صحيحة"}), 400
    if session.get("role") == "kitchen" and status != "ready":
        return jsonify({"error": "صلاحية المطبخ تسمح بجعل الطلب جاهز فقط"}), 403
    db().execute("UPDATE orders SET status = ? WHERE id = ?", (status, order_id))
    db().commit()
    return jsonify({"ok": True})


@app.get("/api/menu")
def menu():
    rows = db().execute("SELECT * FROM menu_items WHERE active = 1 ORDER BY id DESC").fetchall()
    return jsonify([row_dict(row) for row in rows])


@app.post("/api/menu")
@role_allowed("admin")
def add_menu_item():
    payload = request.get_json(force=True)
    cur = db().execute(
        "INSERT INTO menu_items (name, category, price, description, image) VALUES (?, ?, ?, ?, ?)",
        (
            payload.get("name", "").strip(),
            payload.get("category", "").strip(),
            int(payload.get("price", 0)),
            payload.get("description", "").strip(),
            payload.get("image", "").strip(),
        ),
    )
    db().commit()
    return jsonify(row_dict(db().execute("SELECT * FROM menu_items WHERE id = ?", (cur.lastrowid,)).fetchone())), 201


@app.delete("/api/menu/<int:item_id>")
@role_allowed("admin")
def delete_menu_item(item_id):
    db().execute("UPDATE menu_items SET active = 0 WHERE id = ?", (item_id,))
    db().commit()
    return jsonify({"ok": True})


@app.post("/api/menu/reset")
@role_allowed("admin")
def reset_menu():
    db().execute("DELETE FROM menu_items")
    db().executemany(
        "INSERT INTO menu_items (name, category, price, description, image) VALUES (?, ?, ?, ?, ?)",
        DEFAULT_MENU,
    )
    db().commit()
    return menu()


@app.get("/api/tables")
def tables():
    only_active = request.args.get("active") == "1"
    sql = "SELECT * FROM tables"
    if only_active:
        sql += " WHERE active = 1"
    sql += " ORDER BY CAST(number AS INTEGER), number"
    return jsonify([row_dict(row) for row in db().execute(sql).fetchall()])


@app.post("/api/tables")
@role_allowed("admin")
def add_table():
    payload = request.get_json(force=True)
    try:
        cur = db().execute(
            "INSERT INTO tables (number, image, active) VALUES (?, ?, ?)",
            (str(payload.get("number", "")).strip(), payload.get("image", ""), 1 if payload.get("active", True) else 0),
        )
        db().commit()
    except sqlite3.IntegrityError:
        return jsonify({"error": "رقم الطاولة موجود مسبقاً"}), 409
    return jsonify(row_dict(db().execute("SELECT * FROM tables WHERE id = ?", (cur.lastrowid,)).fetchone())), 201


@app.put("/api/tables/<int:table_id>")
@role_allowed("admin")
def update_table(table_id):
    payload = request.get_json(force=True)
    try:
        db().execute(
            "UPDATE tables SET number = ?, image = ?, active = ? WHERE id = ?",
            (
                str(payload.get("number", "")).strip(),
                payload.get("image", ""),
                1 if payload.get("active", True) else 0,
                table_id,
            ),
        )
        db().commit()
    except sqlite3.IntegrityError:
        return jsonify({"error": "رقم الطاولة موجود مسبقاً"}), 409
    return jsonify({"ok": True})


@app.delete("/api/tables/<int:table_id>")
@role_allowed("admin")
def delete_table(table_id):
    db().execute("DELETE FROM tables WHERE id = ?", (table_id,))
    db().commit()
    return jsonify({"ok": True})


@app.get("/api/reports")
@role_allowed("cashier", "kitchen")
def reports():
    row = db().execute("SELECT COUNT(*) AS totalOrders, COALESCE(SUM(total), 0) AS totalRevenue FROM orders").fetchone()
    completed = db().execute("SELECT COUNT(*) AS c, COALESCE(SUM(total), 0) AS s FROM orders WHERE status = 'delivered'").fetchone()
    top = db().execute(
        """
        SELECT name, SUM(qty) AS qty
        FROM order_items
        GROUP BY name
        ORDER BY qty DESC
        LIMIT 8
        """
    ).fetchall()
    total_orders = row["totalOrders"]
    revenue = completed["s"] or row["totalRevenue"]
    return jsonify(
        {
            "totalOrders": total_orders,
            "totalRevenue": revenue,
            "average": (revenue / total_orders) if total_orders else 0,
            "topItems": [row_dict(item) for item in top],
        }
    )


@app.get("/api/export")
@role_allowed("cashier", "kitchen")
def export_data():
    data = {
        "exportedAt": datetime.utcnow().isoformat(),
        "menu": [row_dict(r) for r in db().execute("SELECT * FROM menu_items").fetchall()],
        "tables": [row_dict(r) for r in db().execute("SELECT * FROM tables").fetchall()],
        "orders": [order_payload(r) for r in db().execute("SELECT * FROM orders ORDER BY id").fetchall()],
    }
    return app.response_class(json.dumps(data, ensure_ascii=False, indent=2), mimetype="application/json")


@app.post("/api/settings/dark")
def set_dark():
    value = "true" if request.get_json(force=True).get("dark") else "false"
    db().execute(
        "INSERT INTO settings (key, value) VALUES ('dark', ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (value,),
    )
    db().commit()
    return jsonify({"ok": True})


@app.get("/healthz")
def healthz():
    return jsonify({"ok": True})


init_db()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
