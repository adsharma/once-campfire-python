"""Application factory (idiomatic Flask)."""

import time

from flask import Flask

from .config import Config
from .domain import workload as w
from .routes.meta import bp as meta_bp
from .routes.rooms import bp as rooms_bp
from .routes.search import bp as search_bp
from .routes.sidebar import bp as sidebar_bp


def create_app(config=None):
    app = Flask(__name__)
    app.config.from_object(config or Config)

    t0 = time.perf_counter()
    store = w.seed_store(app.config["USERS"], app.config["MESSAGES"], app.config["SEED"])
    t1 = time.perf_counter()
    index = w.build_search_index(store)
    t2 = time.perf_counter()
    app.logger.info(
        "seeded users=%d messages=%d store_ms=%.0f index_ms=%.0f terms=%d",
        app.config["USERS"], len(store.messages),
        (t1 - t0) * 1000, (t2 - t1) * 1000, len(index.postings),
    )
    app.extensions["campfile_store"] = store
    app.extensions["campfire_index"] = index

    app.register_blueprint(meta_bp)
    app.register_blueprint(rooms_bp)
    app.register_blueprint(sidebar_bp)
    app.register_blueprint(search_bp)
    return app
