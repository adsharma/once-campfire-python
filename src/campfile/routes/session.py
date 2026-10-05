"""Session auth (mirrors SessionsController + middleware).

POST /session with email_address/password verifies bcrypt, creates a
sessions row and sets a signed session_token cookie. Per-request loading
resolves the token to a user (throttled-touch like Rails); anonymous
requests to protected paths redirect to /session/new.
"""

import time

from flask import Blueprint, g, redirect, request
from itsdangerous import BadSignature, URLSafeSerializer

from .. import queries as q
from .. import state as st
from .helpers import error

bp = Blueprint("session", __name__)
COOKIE = "session_token"


def _signer():
    from flask import current_app
    return URLSafeSerializer(current_app.config["SECRET_KEY"], salt=COOKIE)


def load_user():
    raw = request.cookies.get(COOKIE, "")
    if not raw:
        g.user = None
        return
    try:
        token = _signer().loads(raw)
    except BadSignature:
        g.user = None
        return
    g.user = q.user_from_token(st.get_db(), token, int(time.time()))


def require_user():
    if g.get("user") is None:
        return redirect("/session/new")
    return None


@bp.get("/session/new")
def session_new():
    return (
        "<form method=post action=/session>"
        "<input name=email_address type=email>"
        "<input name=password type=password>"
        "<button>Sign in</button></form>"
    )


@bp.post("/session")
def session():
    db = st.get_db()
    if request.is_json:
        payload = request.get_json(silent=True) or {}
        email = str(payload.get("email_address", ""))
        password = str(payload.get("password", ""))
    else:
        email = request.form.get("email_address", "")
        password = request.form.get("password", "")
    user = q.authenticate(db, email, password)
    if user is None:
        return error("invalid email or password", 422)
    token = q.start_session(
        db, user.id, request.remote_addr or "", request.user_agent.string or "",
        int(time.time()),
    )
    response = redirect("/")
    response.set_cookie(COOKIE, _signer().dumps(token), httponly=True)
    return response


@bp.delete("/session")
def destroy_session():
    raw = request.cookies.get(COOKIE, "")
    if raw:
        try:
            q.end_session(st.get_db(), _signer().loads(raw))
        except BadSignature:
            pass
    response = redirect("/session/new")
    response.delete_cookie(COOKIE)
    return response
