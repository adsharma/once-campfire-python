"""Application factory (idiomatic Flask).

Persistence is SQLite via fquery.sqlmodel (same engine class as the Rails
app). One database file is shared by all workers (WAL mode); each request
gets its own Session. Seeding reuses workload.seed_store so the corpus
definition stays in one place.
"""

import time

from flask import Flask, g, request
from sqlalchemy.exc import IntegrityError

from . import queries as q
from .config import Config
from .db import create_schema, get_engine, load_store
from .domain import workload as w
from .routes.account import bp as account_bp
from .routes.bots_api import bp as bots_api_bp
from .routes.manage import bp as manage_bp
from .routes.meta import bp as meta_bp
from .routes.onboard import bp as onboard_bp
from .routes.people import bp as people_bp
from .routes.rooms import bp as rooms_bp
from .routes.search import bp as search_bp
from .routes.session import bp as session_bp
from .routes.session import load_user
from .routes.sidebar import bp as sidebar_bp


def _seed_if_empty(engine, app) -> None:
    from sqlmodel import Session, func, select

    from .db import Message

    with Session(engine) as session:
        count = session.exec(select(func.count(Message.__sqlmodel__.id))).one()
    if count > 0:
        app.logger.info("database already seeded (%d messages)", count)
        return
    t0 = time.perf_counter()
    store = w.seed_store(app.config["USERS"], app.config["MESSAGES"], app.config["SEED"])
    t1 = time.perf_counter()
    import bcrypt
    digest = bcrypt.hashpw(
        app.config["SEED_PASSWORD"].encode("utf-8"), bcrypt.gensalt(rounds=4)
    ).decode("utf-8")
    try:
        counts = load_store(engine, store, password_digest=digest)
    except IntegrityError:  # lost a boot race with a sibling worker
        from sqlmodel import Session, func, select

        from .db import Message

        with Session(engine) as session:
            total = session.exec(select(func.count(Message.__sqlmodel__.id))).one()
        app.logger.info("seed race lost; database has %d messages", total)
        return
    t2 = time.perf_counter()
    app.logger.info(
        "seeded users=%d messages=%d fts=%d store_ms=%.0f load_ms=%.0f",
        app.config["USERS"], counts["messages"], counts["fts"],
        (t1 - t0) * 1000, (t2 - t1) * 1000,
    )


def create_app(config=None):
    app = Flask(__name__)
    app.config.from_object(config or Config)

    engine = get_engine(app.config["DB_URL"])
    create_schema(engine)
    _seed_if_empty(engine, app)
    app.extensions["campfile_engine"] = engine
    if not app.config["SECRET_KEY"] or app.config["SECRET_KEY"] == "dev":
        app.logger.warning("using default SECRET_KEY; set SECRET_KEY_BASE")

    @app.before_request
    def _open_session():
        from sqlmodel import Session
        g.db = Session(engine)
        if request.path not in ("/session/new", "/session", "/__meta"):
            load_user()

    @app.teardown_request
    def _close_session(exc):
        from fquery import env
        env.use(None)
        db = g.pop("db", None)
        if db is not None:
            db.close()

    app.register_blueprint(meta_bp)
    app.register_blueprint(onboard_bp)
    app.register_blueprint(rooms_bp)
    app.register_blueprint(manage_bp)
    app.register_blueprint(bots_api_bp)
    app.register_blueprint(sidebar_bp)
    app.register_blueprint(search_bp)
    app.register_blueprint(session_bp)
    app.register_blueprint(account_bp)
    app.register_blueprint(people_bp)
    return app
