
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

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "supersecret")

logging.basicConfig(level=logging.ERROR)
logging.getLogger('werkzeug').setLevel(logging.ERROR)

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

class Title(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), unique=True)
    path = db.Column(db.String(1024))

class Episode(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title_id = db.Column(db.Integer, db.ForeignKey('title.id'))
    name = db.Column(db.String(255))
    number = db.Column(db.Integer)
    path = db.Column(db.String(1024))
    thumb = db.Column(db.String(1024), nullable=True)

class EpisodeImage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    episode_id = db.Column(db.Integer, db.ForeignKey('episode.id'))
    filename = db.Column(db.String(1024))
    index = db.Column(db.Integer)

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

########### SCANNER ###########
def scan_library():
    with app.app_context():
        global scan_status

        scan_status.update({
            "running": True,
            "progress": 0,
            "message": "Starting scan",
            "done": 0,
            "total": 0
        })

        if not os.path.isdir(LIBRARY_ROOT):
            scan_status.update({
                "running": False,
                "message": "Library not found"
            })
            return

        # -------- TITLES --------
        try:
            title_names = sorted(
                d for d in os.listdir(LIBRARY_ROOT)
                if os.path.isdir(os.path.join(LIBRARY_ROOT, d))
            )
        except OSError as e:
            app.logger.error(f"Failed to list library: {e}")
            scan_status["running"] = False
            return

        scan_status["total"] = len(title_names)

        for title_idx, title_name in enumerate(title_names, start=1):
            scan_status["message"] = f"Indexing title: {title_name}"
            scan_status["done"] = title_idx
            scan_status["progress"] = int(title_idx / max(1, len(title_names)+1) * 100)

            title_path = os.path.abspath(os.path.join(LIBRARY_ROOT, title_name))

            title = Title.query.filter_by(name=title_name).first()
            if not title:
                title = Title(name=title_name, path=title_path)
                db.session.add(title)
                db.session.commit()

            # -------- EPISODES --------
            try:
                episode_names = sorted(
                    d for d in os.listdir(title_path)
                    if os.path.isdir(os.path.join(title_path, d))
                )
            except OSError as e:
                app.logger.warning(f"Cannot read episodes in {title_name}: {e}")
                continue

            episode_names.sort(key=smart_extract_number)

            for episode_name in episode_names:
                episode_path = os.path.abspath(os.path.join(title_path, episode_name))
                ep_number = smart_extract_number(episode_name)

                episode = Episode.query.filter_by(
                    title_id=title.id,
                    name=episode_name
                ).first()

                if not episode:
                    episode = Episode(
                        title_id=title.id,
                        name=episode_name,
                        number=ep_number,
                        path=episode_path
                    )
                    db.session.add(episode)
                    db.session.commit()

                # -------- IMAGES --------
                try:
                    image_files = [
                        f for f in os.listdir(episode_path)
                        if f.lower().endswith((".jpg", ".jpeg", ".png", ".webp"))
                        and os.path.isfile(os.path.join(episode_path, f))
                    ]
                except OSError as e:
                    app.logger.warning(
                        f"Cannot read images in {episode_path}: {e}"
                    )
                    continue

                image_files.sort()

                # reset images for episode
                EpisodeImage.query.filter_by(
                    episode_id=episode.id
                ).delete()

                for idx, filename in enumerate(image_files):
                    db.session.add(
                        EpisodeImage(
                            episode_id=episode.id,
                            filename=filename,
                            index=idx
                        )
                    )
                if image_files:
                    episode.thumb = image_files[0]
                db.session.commit()
        # -------- FINISH --------
        scan_status.update({
            "running": False,
            "message": "Scan complete",
            "progress": 100
        })
        app.logger.info("Library scan completed successfully")

def start_scan_background():
    if not scan_status["running"]:
        threading.Thread(target=scan_library, daemon=True).start()

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
    ep = Episode.query.get_or_404(eid)
    title = db.session.get(Title, ep.title_id)
    # Prefer episode.path if exists
    if ep.path:
        base = ep.path
    else:
        # fallback safe absolute build
        base = os.path.join(LIBRARY_ROOT, title.name, ep.name)
    image_path = os.path.join(base, fname)
    image_path = os.path.abspath(image_path)
    if not os.path.exists(image_path):
        return f"Image not found: {image_path}", 404
    return send_file(image_path)

@app.route("/scan/start")
@login_required
def start_scan():
    if not current_user.is_admin:
        return "Forbidden", 403
    start_scan_background()
    return jsonify({"started":True})

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
