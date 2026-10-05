"""Configuration (environment overrides; mirrors bench defaults)."""

import os


class Config:
    USERS = int(os.environ.get("USERS", "60"))
    MESSAGES = int(os.environ.get("MESSAGES", "3000"))
    SEED = int(os.environ.get("SEED", "42"))
    DB_URL = os.environ.get("DB_URL", "sqlite:///./campfile-bench.db")
    SECRET_KEY = os.environ.get("SECRET_KEY_BASE", "dev")
    SEED_PASSWORD = os.environ.get("SEED_PASSWORD", "password")
