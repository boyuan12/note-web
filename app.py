from flask import Flask, render_template, session, request, redirect, abort, jsonify
from helpers import login_required, random_str, upload_s3
import requests
from termcolor import colored
from sqlalchemy import create_engine
from sqlalchemy.orm import scoped_session, sessionmaker

import os

app = Flask(__name__)

app.config["SECRET_KEY"] = os.getenv("SECRET_KEY")

print(os.getenv("production"))

if bool(os.getenv("production")) == True:
    engine = create_engine(os.getenv("DATABASE_URL"))
    db = scoped_session(sessionmaker(bind=engine))
    conn = db()
    c = conn
else:
    import sqlite3
    conn = sqlite3.connect("db.sqlite3", check_same_thread=False)
    c = conn.cursor()

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")

def validate_note(user_id, note_id):
    note = c.execute("SELECT * FROM notes WHERE note_id=:note_id", {"note_id": note_id}).fetchall()
    if len(note) == 0:
        print(1)
        return False
    if note[0][1] != user_id:
        print(2)
        return False
    return True


@app.route("/")
def index():
    if session.get("user_id"):
        notes = c.execute("SELECT * FROM notes WHERE user_id=:user_id", {"user_id": session.get("user_id")}).fetchall()
        return render_template("index.html", notes=notes)
    return render_template("signin.html")


@app.route("/login")
def login():
    if request.args.get("next"):
        session["next"] = request.args.get("next")
    return redirect(f"https://accounts.google.com/o/oauth2/v2/auth?scope=https://www.googleapis.com/auth/userinfo.profile&access_type=offline&include_granted_scopes=true&response_type=code&redirect_uri=https://note-web.herokuapp.com/authorized&client_id={GOOGLE_CLIENT_ID}")


@app.route("/authorized")
def google_authorized():
    r = requests.post("https://oauth2.googleapis.com/token", data={
        "client_id": GOOGLE_CLIENT_ID,
        "client_secret": GOOGLE_CLIENT_SECRET,
        "code": request.args.get("code"),
        "grant_type": "authorization_code",
        "redirect_uri": "https://note-web.herokuapp.com/authorized"
    })
    print(colored(r.json(), "red"))
    r = requests.get(f'https://www.googleapis.com/oauth2/v2/userinfo?access_token={r.json()["access_token"]}').json()
    user = c.execute("SELECT * FROM users WHERE user_id=:user_id", {"user_id": r["id"]}).fetchall()
    if len(user) != 0:
        session["user_id"] = user[0][0]
        session["name"] = user[0][1]
        session["avatar"] = user[0][2]
    else:
        c.execute("INSERT INTO users (user_id, name, photo) VALUES (:id, :name, :photo)", {"id": r["id"], "name": r["name"], "photo": r["picture"]})
        conn.commit()
        session["user_id"] = r["id"]
        session["name"] = r["name"]
        session["avatar"] = r["picture"]

    if session.get("next"):
        return redirect(session.get("next"))
    return redirect("/")


@app.route("/new", methods=["GET", "POST"])
@login_required
def new_note():
    if request.method == "POST":
        url = upload_s3(request)
        code = random_str()
        while True:
            row = c.execute("SELECT * FROM notes WHERE note_id=:id", {"id": code}).fetchall()
            if len(row) == 0:
                break
            code = random_str()
        c.execute("INSERT INTO notes (content, status, img_url, title, description, note_id, user_id) VALUES  (:content, :status, :img, :title, :desc, :note_id, :user_id)", {"content": request.form.get("content"), "status": request.form.get("status"), "img": url, "title": request.form.get("title"), "desc": request.form.get("desc"), "note_id": code, "user_id": session.get("user_id")})
        conn.commit()
        return redirect(f"/n/{code}")
    else:
        return render_template("new.html", action="/new")


@app.route("/n/<note_id>")
@login_required
def note(note_id):
    note = c.execute("SELECT * FROM notes WHERE note_id=:note_id AND status='Private' AND user_id=:user_id", {"note_id": note_id, "user_id": session["user_id"]}).fetchall()
    if len(note) != 0:
        return render_template("note.html", note=note)
    note = c.execute("SELECT * FROM notes WHERE note_id=:id AND (status='Public' OR status='Unlisted')", {"id": note_id}).fetchall()
    if len(note) != 1:
        abort(404)
    return render_template("note.html", note=note)


@app.route("/update/<note_id>", methods=["GET", "POST"])
def update(note_id):
    if not validate_note(session["user_id"], note_id):
        return "DONT DO IT!"

    if request.method == "POST":

        if not request.files["image"]:
            print(1)
            img = c.execute("SELECT img_url FROM notes WHERE note_id=:id", {"id": note_id}).fetchall()[0][0]
        else:
            print(2)
            img = upload_s3(request)

        c.execute("UPDATE notes SET title=:title, description=:desc, status=:status, content=:content, img_url=:img WHERE note_id=:note_id", {"title": request.form.get("title"), "desc": request.form.get("desc"), "status": request.form.get("status"), "content": request.form.get("content"), "img": img, "note_id": note_id})
        conn.commit()

        return redirect(f"/n/{note_id}")
    else:
        note = c.execute("SELECT * FROM notes WHERE note_id=:note_id", {"note_id": note_id}).fetchall()
        return render_template("new.html", title=note[0][5], desc=note[0][6], status=note[0][3], content=note[0][2], img_url=note[0][4], action=f"/update/{note_id}")


@app.route("/delete")
@login_required
def delete_note():
    if validate_note(session["user_id"], request.args.get("n")):
        c.execute("DELETE FROM notes WHERE note_id=:note_id", {"note_id": request.args.get("n")})
        conn.commit()
        return redirect("/")
    return "DON'T DO IT!"


@app.route("/search")
def search():
    results = c.execute(f"SELECT * FROM notes WHERE title LIKE '%{request.args.get('s')}%' AND status='Public'").fetchall()
    print(results)
    data = []
    for result in results:
        name = c.execute("SELECT name FROM users WHERE user_id=:id", {"id": result[1]}).fetchall()[0][0]
        data.append([result[4], result[5], result[6], result[0], result[1], name])
    return render_template("searched.html", data=data)


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")


@app.route("/a/<user_id>")
def author(user_id):
    notes = c.execute("SELECT * FROM notes WHERE user_id=:user_id AND status='Public'", {"user_id": user_id}).fetchall()
    return render_template("author.html", notes=notes)


@app.route("/authorize", methods=["GET", "POST"])
def oauth():
    if request.method == "POST":
        client_id = request.args.get("client_id")
        app = c.execute("SELECT * FROM apps WHERE client_id=:id", {"id": client_id}).fetchall()
        c.execute("INSERT INTO user_app (user_id, app_id) VALUES (:u, :a)", {"u": session.get("user_id"), "a": app[0][0]})
        conn.commit()

        code = random_str(50)
        while True:
            _ = c.execute("SELECT * FROM oauth_codes WHERE code=:code", {"code": code}).fetchall()
            if len(_) == 0:
                break
            code = random_str(50)
        c.execute("INSERT INTO oauth_codes (app_id, user_id, code) VALUES (:id, :user, :code)", {"id": app[0][0], "user": session.get("user_id"), "code": code})
        conn.commit()
        return redirect(f"{app[0][6]}?code={code}")

    client_id = request.args.get("client_id")
    app = c.execute("SELECT * FROM apps WHERE client_id=:id", {"id": client_id}).fetchall()
    if len(app) == 0:
        return "INVALID CLIENT ID"
    if session.get("user_id"):
        user_app = c.execute("SELECT * FROM user_app WHERE app_id=:app_id", {"app_id": app[0][0]}).fetchall()
        if len(user_app) == 0:
            return render_template("authorize.html", app=app)
        # generate code
        code = random_str(50)
        while True:
            _ = c.execute("SELECT * FROM oauth_codes WHERE code=:code", {"code": code}).fetchall()
            if len(_) == 0:
                break
            code = random_str(50)
        c.execute("INSERT INTO oauth_codes (app_id, user_id, code) VALUES (:id, :user, :code)", {"id": app[0][0], "user": session.get("user_id"), "code": code})
        conn.commit()
        return redirect(f"{app[0][6]}?code={code}")
    return redirect(f"/login?next=/authorize?client_id={client_id}")


@app.route("/access_token", methods=["POST"])
def access_token():
    _app = c.execute("SELECT * FROM apps WHERE client_id=:id AND client_secret=:sec", {"id": request.form.get("client_id"), "sec": request.form.get("client_secret")}).fetchall()

    code = c.execute("SELECT * FROM oauth_codes WHERE code=:c", {"c": request.form.get("code")}).fetchall()
    if len(code) == 0:
        return "INVALID CODE"

    if len(_app) == 0:
        return "INVALID CLIENT ID/CLIENT SECRET!"

    while True:
        token = random_str(70)
        _ = c.execute("SELECT * FROM tokens WHERE token=:t", {"t": token}).fetchall()
        if len(_) == 0:
            break
    c.execute("DELETE FROM oauth_codes WHERE code=:code", {"code": request.form.get("code")})
    conn.commit()

    c.execute("INSERT INTO tokens (app_id, user_id, token) VALUES (:a, :u, :t)", {"a": _app[0][0], "u": code[0][1], "t": token}).fetchall()
    conn.commit()

    return token


@app.route("/app", methods=["GET", "POST"])
@login_required
def applications():
    if request.method == "POST":
        img = upload_s3(request)
        client_id = random_str(25)
        client_secret = random_str(40)

        while True:
            _ = c.execute("SELECT * FROM apps WHERE client_id=:id OR client_secret=:sec", {"id": client_id, "sec": client_secret}).fetchall()
            if len(_) == 0:
                break
            client_id = random_str(25)
            client_secret = random_str(25)

        c.execute("INSERT INTO apps (user_id, name, img, client_id, client_secret, redirect_uri) VALUES (:id, :name, :img, :cid, :sec, :uri)", {"id": session.get("user_id"), "name": request.form.get("name"), "img": img, "cid": client_id, "sec": client_secret, "uri": request.form.get("uri")})
        conn.commit()
        return redirect("/app")

    else:
        apps = c.execute("SELECT * FROM apps WHERE user_id=:user_id", {"user_id": session.get("user_id")}).fetchall()
        return render_template("app.html", apps=apps)


@app.route("/api/user")
def api_user():
    token = request.headers.get("Authorization").split("token ")[1]
    t = c.execute("SELECT * FROM tokens WHERE token=:t", {"t": token}).fetchall()
    if len(t) == 0:
        return jsonify({"error": "token not found"})
    user_id = t[0][1]
    user = c.execute("SELECT * FROM users WHERE user_id=:id", {"id": user_id}).fetchall()[0]
    return jsonify(user)


@app.route("/api/notes")
def view_notes():
    token = request.headers.get("Authorization").split("token ")[1]
    t = c.execute("SELECT * FROM tokens WHERE token=:t", {"t": token}).fetchall()
    if len(t) == 0:
        return jsonify({"error": "token not found"})
    user_id = t[0][1]
    notes = c.execute("SELECT * FROM notes WHERE user_id=:id", {"id": user_id}).fetchall()
    return jsonify(notes)