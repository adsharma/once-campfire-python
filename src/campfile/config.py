"""Configuration (environment overrides; mirrors bench defaults)."""

import os


class Config:
    USERS = int(os.environ.get("USERS", "60"))
    MESSAGES = int(os.environ.get("MESSAGES", "3000"))
    SEED = int(os.environ.get("SEED", "42"))
