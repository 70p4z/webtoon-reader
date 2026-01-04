
import os
import threading
import time
import re
import secrets
import traceback
import logging
from uuid import uuid4
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, jsonify, session, flash
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, login_user, logout_user, login_required, current_user, UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy.exc import IntegrityError
from io import BytesIO
import mimetypes
import zipfile
import rarfile


app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "supersecret")

logging.basicConfig(level=logging.INFO)
logging.getLogger('werkzeug').setLevel(logging.INFO)

DB_PATH = os.path.join(os.getcwd(), "db/webtoon.db")
#if not os.path.exists(DB_PATH):
# always touch DB to make sure we have the rights
os.system(f"touch {DB_PATH}")
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + DB_PATH
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db = SQLAlchemy(app)

login_manager = LoginManager(app)
login_manager.login_view = "login"

RESCAN_TOKEN = os.getenv("RESCAN_TOKEN", None)
LIBRARY_ROOT = os.getenv("WEBTOON_LIBRARY","library")

from werkzeug.middleware.proxy_fix import ProxyFix
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_host=1, x_prefix=1)
class PrefixMiddleware:
    def __init__(self, app, prefix):
        self.app = app
        self.prefix = prefix

    def __call__(self, environ, start_response):
        script_name = environ.get('HTTP_X_SCRIPT_NAME', '')
        if script_name:
            environ['SCRIPT_NAME'] = script_name
            if environ['PATH_INFO'].startswith(script_name):
                environ['PATH_INFO'] = environ['PATH_INFO'][len(script_name):]
        return self.app(environ, start_response)

APP_PREFIX="/webtoon"
app.wsgi_app = PrefixMiddleware(app.wsgi_app, APP_PREFIX)
app.config["APPLICATION_ROOT"] = APP_PREFIX


scan_status = {"running": False, "progress": 0, "message": "", "total": 0, "done": 0}

########## MODELS ###########
class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=True)
    is_admin = db.Column(db.Boolean, default=False)
    register_token = db.Column(db.String(255), nullable=True)
    enabled = db.Column(db.Boolean, default=True)

class Title(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), unique=True)
    path = db.Column(db.String(1024))
    available = db.Column(db.Boolean, default=True)

class Episode(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title_id = db.Column(db.Integer, db.ForeignKey('title.id'))
    name = db.Column(db.String(255))
    number = db.Column(db.Integer)
    path = db.Column(db.String(1024))
    thumb = db.Column(db.String(1024), nullable=True)
    kind = db.Column(db.String(8), default="dir")   # dir | cbz | cbr
    archive_path = db.Column(db.Text, nullable=True)
    available = db.Column(db.Boolean, default=True)

class EpisodeImage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    episode_id = db.Column(db.Integer, db.ForeignKey('episode.id'))
    filename = db.Column(db.String(1024))
    index = db.Column(db.Integer)
    available = db.Column(db.Boolean, default=True)

class UserEpisode(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    episode_id = db.Column(db.Integer, db.ForeignKey("episode.id"))
    read = db.Column(db.Boolean, default=False)
    scroll = db.Column(db.Integer, default=0)
    updated = db.Column(db.DateTime, default=datetime.utcnow)

@login_manager.user_loader
def load_user(uid):
    return db.session.get(User, int(uid))

########### UTIL ############
def smart_extract_number(name):
    m = re.search(r'(\d+)', name)
    return int(m.group(1)) if m else 0

def ensure_admin_if_none():
    if User.query.count() == 0:
        token = secrets.token_hex(16)
        admin = User(username="admin", is_admin=True, register_token=token)
        db.session.add(admin)
        db.session.commit()

IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp")

def is_image(name):
    return name.lower().endswith(IMAGE_EXTS)

def image_mimetype(filename):
    return mimetypes.guess_type(filename)[0] or "image/*"

def list_cbz_images(path):
    try:
        with zipfile.ZipFile(path) as z:
            return sorted(
                n for n in z.namelist()
                if not n.endswith("/") and is_image(n)
            )
    except Exception as e:
        app.logger.warning(f"CBZ read failed: {path} ({e})")
        return []

def stream_cbz_image(cbz_path, inner_name):
    def generate():
        with zipfile.ZipFile(cbz_path) as z:
            with z.open(inner_name) as f:
                while True:
                    chunk = f.read(64 * 1024)
                    if not chunk:
                        break
                    yield chunk
    return Response(
        generate(),
        mimetype=image_mimetype(inner_name)
    )

def list_cbr_images(path):
    try:
        with rarfile.RarFile(path) as r:
            return sorted(
                n for n in r.namelist()
                if not n.endswith("/") and is_image(n)
            )
    except Exception as e:
        app.logger.warning(f"CBR read failed: {path} ({e})")
        return []

from flask import Response

def stream_cbr_image(cbr_path, inner_name):
    def generate():
        with rarfile.RarFile(cbr_path) as r:
            with r.open(inner_name) as f:
                while True:
                    chunk = f.read(64 * 1024)  # 64 KB
                    if not chunk:
                        break
                    yield chunk
    return Response(
        generate(),
        mimetype=image_mimetype(inner_name)
    )

def detect_archive_format(path):
    # returns "zip", "rar", or None
    try:
        if zipfile.is_zipfile(path):
            return "zip"
    except Exception:
        traceback.print_exc()
        pass

    try:
        import rarfile
        if rarfile.is_rarfile(path):
            return "rar"
    except Exception:
        traceback.print_exc()
        pass

    return None

########### SCANNER ###########
def scan_library(mode="regular"):
    """
    mode:
      - regular  : only new titles + new episodes
      - thorough : rebuild images for everything
    """
    with app.app_context():
        global scan_status

        scan_status.update({
            "running": True,
            "progress": 0,
            "message": f"Starting {mode} scan",
        })

        if not os.path.isdir(LIBRARY_ROOT):
            scan_status.update({"running": False, "message": "Library missing"})
            return

        titles = sorted(
            d for d in os.listdir(LIBRARY_ROOT)
            if os.path.isdir(os.path.join(LIBRARY_ROOT, d))
        )

        total = len(titles)

        for ti, title_name in enumerate(titles, 1):
            scan_status.update({
                "progress": int(ti / max(1, total) * 100),
                "message": f"{title_name}"
            })

            title_path = os.path.abspath(os.path.join(LIBRARY_ROOT, title_name))
            title = Title.query.filter_by(name=title_name).first()

            if not title:
                title = Title(name=title_name, path=title_path)
                db.session.add(title)
                db.session.commit()

            entries = os.listdir(title_path)

            # ---------- DIRECTORY EPISODES ----------
            episode_dirs = [
                d for d in entries
                if os.path.isdir(os.path.join(title_path, d))
            ]

            # ---------- ARCHIVE EPISODES ----------
            cbz_files = [f for f in entries if f.lower().endswith((".cbz", ".cbr")) and detect_archive_format(os.path.join(title_path, f)) == "zip"]
            cbr_files = [f for f in entries if f.lower().endswith((".cbz", ".cbr")) and detect_archive_format(os.path.join(title_path, f)) == "rar"]

            # unify all episodes
            all_eps = []

            for d in episode_dirs:
                app.logger.info(f"dir: {os.path.join(title_path, d)}")
                all_eps.append(("dir", d, os.path.join(title_path, d)))

            for f in cbz_files:
                app.logger.info(f"cbz: {os.path.join(title_path, f)}")
                all_eps.append(("cbz", f, os.path.join(title_path, f)))

            for f in cbr_files:
                app.logger.info(f"cbr: {os.path.join(title_path, f)}")
                all_eps.append(("cbr", f, os.path.join(title_path, f)))

            # order by episode number
            all_eps.sort(key=lambda e: smart_extract_number(e[1]))

            for kind, name, path in all_eps:
                ep = Episode.query.filter_by(
                    title_id=title.id,
                    name=name
                ).first()

                # regular scan skips existing episodes
                if ep and mode == "regular":
                    continue

                if not ep:
                    ep = Episode(
                        title_id=title.id,
                        name=name,
                        number=smart_extract_number(name),
                        kind=kind,
                        path=path if kind == "dir" else None,
                        archive_path=path if kind != "dir" else None
                    )
                    db.session.add(ep)
                    db.session.commit()

                # ---------- IMAGE INDEXING ----------
                if kind == "dir":
                    app.logger.info(f"dir indexing: {path}")
                    images = sorted(
                        f for f in os.listdir(path)
                        if is_image(f) and os.path.isfile(os.path.join(path, f))
                    )

                elif kind == "cbz":
                    app.logger.info(f"cbz indexing: {path}")
                    images = list_cbz_images(path)

                elif kind == "cbr":
                    app.logger.info(f"cbr indexing: {path}")
                    images = list_cbr_images(path)

                else:
                    images = []

                EpisodeImage.query.filter_by(episode_id=ep.id).delete()

                for idx, img in enumerate(images):
                    db.session.add(
                        EpisodeImage(
                            episode_id=ep.id,
                            filename=img,
                            index=idx
                        )
                    )

                ep.thumb = images[0] if images else None
                db.session.commit()

        scan_status.update({
            "running": False,
            "progress": 100,
            "message": f"{mode.capitalize()} scan complete"
        })

        app.logger.info(f"{mode} scan finished")



def start_scan_background(mode="regular"):
    if scan_status["running"]:
        return
    threading.Thread(
        target=scan_library,
        kwargs={"mode": mode},
        daemon=True
    ).start()


########### ROUTES ###########
@app.before_request
def fix_cookie_path():
    sr = request.script_root or '/'
    # only update if different to avoid thrashing cookies
    if app.config.get("SESSION_COOKIE_PATH") != sr:
        app.config["SESSION_COOKIE_PATH"] = sr

@app.before_request
def ensure_db_and_admin():
    db.create_all()
    ensure_admin_if_none()

    # only lock system if NO admin has a password yet
    pending_admin = User.query.filter(
        User.is_admin == True,
        User.password_hash == None
    ).first()

    if pending_admin:
        allowed = [
            "login",
            "register",
            "static",
            "scan_status"
        ]

        if request.endpoint not in allowed:
            return redirect(url_for("login"))


@app.route("/login", methods=["GET","POST"])
def login():
    if request.method == "POST":
        u = User.query.filter_by(username=request.form["username"]).first()
        if u and u.password_hash and check_password_hash(u.password_hash, request.form["password"]):
            login_user(u)
            #return redirect(url_for("home"))
            return redirect(request.args.get('next', url_for('home')))
        flash("Invalid credentials or user pending registration.")
    pending_admin = User.query.filter(User.password_hash == None).first()
    return render_template("login.html", pending=pending_admin)

@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("login"))

@app.route("/register/<token>", methods=["GET","POST"])
def register(token):
    u = User.query.filter_by(register_token=token).first_or_404()
    if request.method=="POST":
        pwd=request.form["password"]
        u.password_hash = generate_password_hash(pwd)
        u.register_token = None
        db.session.commit()
        login_user(u)
        return redirect(url_for("home"))
    return render_template("register.html", user=u)

@app.route("/admin/add_user", methods=["GET", "POST"])
@login_required
def add_user_page():
    if not current_user.is_admin:
        return "Forbidden", 403

    new_user = None
    link = None

    if request.method == "POST":
        username = request.form["username"].strip()
        is_admin = True if request.form.get("is_admin") else False

        token = secrets.token_hex(16)

        u = User(username=username, is_admin=is_admin, register_token=token)
        db.session.add(u)
        db.session.commit()

        new_user = u
        link = url_for("register", token=token, _external=True)

    users = User.query.all()

    return render_template(
        "admin.html",
        users=users,
        new_user=new_user,
        link=link
    )

@app.route("/admin/delete_user/<int:uid>", methods=["POST"])
@login_required
def delete_user(uid):
    if not current_user.is_admin:
        return "Forbidden", 403

    user = User.query.get_or_404(uid)

    # prevent deleting self to avoid lockout
    if user.id == current_user.id:
        return "Cannot delete yourself", 400

    db.session.delete(user)
    db.session.commit()

    return redirect(url_for("add_user_page"))


@app.route("/prefs", methods=["GET","POST"])
@login_required
def prefs():
    if request.method=="POST":
        pwd=request.form["password"]
        current_user.password_hash = generate_password_hash(pwd)
        db.session.commit()
        flash("Password changed.")
    return render_template("prefs.html")

@app.route("/")
@app.route("/list")
@login_required
def home():
    #titles = Title.query.all()
    titles = (
        db.session.query(Title)
        .join(Episode)
        .join(EpisodeImage)
        .distinct()
        .order_by(Title.name)
        .all()
    )
    return render_template("home.html", titles=titles)

@app.route("/title/<int:tid>")
@login_required
def title_view(tid):
    title = Title.query.get_or_404(tid)
    episodes = Episode.query.filter_by(title_id=tid).order_by(Episode.number).all()
    bookmarks = { ue.episode_id: ue for ue in UserEpisode.query.filter_by(user_id=current_user.id).all()}
    return render_template("episodes.html", title=title, episodes=episodes, bookmarks=bookmarks)

@app.route("/episode/<int:eid>")
@login_required
def episode(eid):
    epi = Episode.query.get_or_404(eid)
    title = db.session.get(Title, epi.title_id)
    imgs = EpisodeImage.query.filter_by(episode_id=eid).order_by(EpisodeImage.index).all()

    ue = UserEpisode.query.filter_by(user_id=current_user.id, episode_id=eid).first()
    scroll = ue.scroll if ue else 0

    next_epi = Episode.query.filter(Episode.title_id==epi.title_id, Episode.number>epi.number).order_by(Episode.number).first()
    prev_epi = Episode.query.filter(Episode.title_id==epi.title_id, Episode.number<epi.number).order_by(Episode.number.desc()).first()

    return render_template("reader.html", episode=epi, title=title, images=imgs, scroll=scroll, next_ep=next_epi, prev_ep=prev_epi)

@app.route("/progress", methods=["POST"])
@login_required
def progress():
    eid = int(request.form["episode"])
    img_index = int(request.form["index"])

    ue = UserEpisode.query.filter_by(
        user_id=current_user.id,
        episode_id=eid
    ).first()

    if not ue:
        ue = UserEpisode(user_id=current_user.id, episode_id=eid)
        db.session.add(ue)

    ue.scroll = img_index          # now means image index
    ue.read = img_index > 0        # “started reading”
    ue.updated = datetime.utcnow()

    db.session.commit()
    return "ok"


from flask import send_file

@app.route("/media/<int:eid>/<path:fname>")
@login_required
def media(eid, fname):
    ep = db.session.get(Episode, eid)
    if not ep:
        abort(404)

    # ---------- DIRECTORY EPISODE ----------
    if ep.kind == "dir":
        image_path = os.path.join(ep.path, fname)
        image_path = os.path.abspath(image_path)

        if not image_path.startswith(ep.path) or not os.path.isfile(image_path):
            abort(404)

        return send_file(image_path)

    # ---------- CBZ EPISODE ----------
    if ep.kind == "cbz":
        if not ep.archive_path or not os.path.isfile(ep.archive_path):
            abort(404)
        return stream_cbz_image(ep.archive_path, fname)

    # ---------- CBR EPISODE ----------
    if ep.kind == "cbr":
        if not ep.archive_path or not os.path.isfile(ep.archive_path):
            abort(404)
        return stream_cbr_image(ep.archive_path, fname)

    abort(404)


@app.route("/scan/start")
@login_required
def scan_regular():
    if not current_user.is_admin:
        return "Forbidden", 403
    start_scan_background(mode="regular")
    return jsonify({"started": True, "mode": "regular"})


@app.route("/scan/force")
@login_required
def scan_thorough():
    if not current_user.is_admin:
        return "Forbidden", 403
    start_scan_background(mode="thorough")
    return jsonify({"started": True, "mode": "thorough"})


@app.route("/scan/status")
def scan_status_route():
    return jsonify(scan_status)

@app.route("/scan/rescan")
def rescan_no_cookie():
    if not RESCAN_TOKEN:
        return {"error": "Rescan token not configured"}, 403
    # allow ?token=XXX or header Authorization: Bearer XXX
    token = request.args.get("token") or \
            request.headers.get("Authorization","").replace("Bearer ","")
    if token != RESCAN_TOKEN:
        return {"error": "Forbidden"}, 403
    start_scan_background()
    return {"started": True}

if __name__=="__main__":
    print("Starting on 0.0.0.0:5000")
    app.run(host="0.0.0.0", port=5000, debug=False)
