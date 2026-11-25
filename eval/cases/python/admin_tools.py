import hashlib
import subprocess

import requests


def run_backup(target_dir):
    subprocess.run(f"tar czf /backups/latest.tgz {target_dir}", shell=True)  # expect: security


def compress(path):
    subprocess.run(["gzip", "-k", path], check=True)


def calculate(expression):
    return eval(expression)  # expect: security


def password_hash(password):
    return hashlib.md5(password.encode()).hexdigest()  # expect: security


def file_checksum(data: bytes):
    return hashlib.sha256(data).hexdigest()


def fetch_status(url):
    return requests.get(url, verify=False, timeout=5).json()  # expect: security
