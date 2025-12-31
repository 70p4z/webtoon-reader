
import os, re, logging, sqlite3
from flask import Flask, render_template, request, redirect, url_for, jsonify, g, send_from_directory

LIBRARY_PATH = os.environ.get("WEBTOON_LIBRARY", "library")
DB_PATH = "webtoon.db"

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logging.getLogger("werkzeug").setLevel(logging.WARNING)

def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close_db(exception):
    db = g.pop("db", None)
    if db:
        db.close()

def init_db():
    db = get_db()
    db.executescript("""
    CREATE TABLE IF NOT EXISTS titles (
        id INTEGER PRIMARY KEY,
        name TEXT UNIQUE NOT NULL
    );
    CREATE TABLE IF NOT EXISTS episodes (
        id INTEGER PRIMARY KEY,
        title_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        number INTEGER NOT NULL,
        thumb TEXT,
        UNIQUE(title_id, name)
    );
    CREATE TABLE IF NOT EXISTS images (
        id INTEGER PRIMARY KEY,
        episode_id INTEGER NOT NULL,
        path TEXT NOT NULL,
        position INTEGER NOT NULL
    );
    CREATE TABLE IF NOT EXISTS bookmarks (
        episode_id INTEGER PRIMARY KEY,
        scroll REAL DEFAULT 0,
        completed INTEGER DEFAULT 0
    );
    """)
    db.commit()

def extract_episode_number(name):
    m = re.search(r"(\d+)", name)
    return int(m.group(1)) if m else 0

def scan_library():
    db = get_db()
    logging.info("===== Starting library scan =====")

    for title_name in sorted(os.listdir(LIBRARY_PATH)):
        title_path = os.path.join(LIBRARY_PATH, title_name)
        if not os.path.isdir(title_path):
            continue

        db.execute("INSERT OR IGNORE INTO titles (name) VALUES (?)", (title_name,))
        title_id = db.execute(
            "SELECT id FROM titles WHERE name=?", (title_name,)
        ).fetchone()["id"]

        logging.info(f"Scanning title: {title_name}")

        for episode_name in sorted(os.listdir(title_path)):
            episode_path = os.path.join(title_path, episode_name)
            if not os.path.isdir(episode_path):
                continue

            ep_number = extract_episode_number(episode_name)

            image_files = sorted(
                f for f in os.listdir(episode_path)
                if f.lower().endswith((".jpg", ".jpeg", ".png", ".webp"))
            )
            if not image_files:
                continue

            thumb = os.path.join(title_name, episode_name, image_files[0])

            db.execute(
                """INSERT OR IGNORE INTO episodes
                (title_id, name, number, thumb)
                VALUES (?, ?, ?, ?)""",
                (title_id, episode_name, ep_number, thumb)
            )

            episode_id = db.execute(
                "SELECT id FROM episodes WHERE title_id=? AND name=?",
                (title_id, episode_name)
            ).fetchone()["id"]

            for pos, img in enumerate(image_files):
                rel = os.path.join(title_name, episode_name, img)
                db.execute(
                    "INSERT OR IGNORE INTO images (episode_id, path, position) VALUES (?,?,?)",
                    (episode_id, rel, pos)
                )

            logging.info(f"Indexed {title_name}/{episode_name} ({len(image_files)} pages)")

    db.commit()
    logging.info("===== Library scan complete =====")

@app.route("/image/<path:filename>")
def image(filename):
    return send_from_directory(LIBRARY_PATH, filename)

@app.route("/scan")
def scan():
    scan_library()
    return redirect(url_for("home"))

@app.route("/")
def home():
    titles = get_db().execute("SELECT * FROM titles ORDER BY name").fetchall()
    return render_template("home.html", titles=titles)

@app.route("/title/<int:title_id>")
def title(title_id):
    db = get_db()
    title = db.execute("SELECT * FROM titles WHERE id=?", (title_id,)).fetchone()
    episodes = db.execute("""
        SELECT e.*, b.scroll, b.completed
        FROM episodes e
        LEFT JOIN bookmarks b ON b.episode_id=e.id
        WHERE e.title_id=?
        ORDER BY e.number ASC
    """, (title_id,)).fetchall()
    return render_template("title.html", title=title, episodes=episodes)

@app.route("/episode/<int:episode_id>")
def episode(episode_id):
    db = get_db()
    episode = db.execute("""
        SELECT e.*, t.name AS title_name
        FROM episodes e
        JOIN titles t ON t.id=e.title_id
        WHERE e.id=?
    """, (episode_id,)).fetchone()

    images = db.execute(
        "SELECT * FROM images WHERE episode_id=? ORDER BY position",
        (episode_id,)
    ).fetchall()

    prev_ep = db.execute(
        "SELECT id FROM episodes WHERE title_id=? AND number < ? ORDER BY number DESC LIMIT 1",
        (episode["title_id"], episode["number"])
    ).fetchone()

    next_ep = db.execute(
        "SELECT id FROM episodes WHERE title_id=? AND number > ? ORDER BY number ASC LIMIT 1",
        (episode["title_id"], episode["number"])
    ).fetchone()

    return render_template(
        "episode.html",
        episode=episode,
        images=images,
        prev_ep=prev_ep,
        next_ep=next_ep
    )

@app.route("/bookmark", methods=["POST"])
def bookmark():
    data = request.json
    db = get_db()
    db.execute(
        """INSERT INTO bookmarks (episode_id, scroll, completed)
        VALUES (?, ?, ?)
        ON CONFLICT(episode_id) DO UPDATE SET
        scroll=excluded.scroll,
        completed=excluded.completed""",
        (data["episode"], data["scroll"], data["completed"])
    )
    db.commit()
    return jsonify(ok=True)

@app.route("/title/<int:title_id>/reset", methods=["POST"])
def reset_title(title_id):
    db = get_db()

    # Get all episode ids for this title
    episode_ids = db.execute(
        "SELECT id FROM episodes WHERE title_id=?",
        (title_id,)
    ).fetchall()

    # Reset bookmarks
    for ep in episode_ids:
        db.execute(
            """
            INSERT INTO bookmarks (episode_id, scroll, completed)
            VALUES (?, 0, 0)
            ON CONFLICT(episode_id) DO UPDATE SET
                scroll=0,
                completed=0
            """,
            (ep["id"],)
        )

    db.commit()
    logging.info(f"Bookmarks reset for title_id={title_id}")

    return redirect(url_for("title", title_id=title_id))

def setup():
    with app.app_context():
        init_db()
        if not os.path.exists(DB_PATH):
            scan_library()

setup()

if __name__ == "__main__":
    app.run(host="0.0.0.0",port=5000,debug=False)
