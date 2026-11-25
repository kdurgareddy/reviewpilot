import os
import pickle

import yaml

DATABASE_PASSWORD = "Pr0d-Passw0rd-2026!"  # expect: security
AWS_KEY = "AKIAIOSFODNN7EXAMPLE"  # expect: security


def load_config(path):
    with open(path) as f:
        return yaml.load(f)  # expect: security


def load_safe(path):
    with open(path) as f:
        return yaml.safe_load(f)


def restore_session(blob: bytes):
    return pickle.loads(blob)  # expect: security


def api_key():
    return os.environ["API_KEY"]
