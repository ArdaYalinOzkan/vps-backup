import paramiko
import stat
import json
import os
import threading
from pathlib import Path


CONFIG_DIR = Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config')) / 'vps-backup'
CONFIG_FILE = CONFIG_DIR / 'config.json'


def load_config():
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    return {}


def save_config(data):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, 'w') as f:
        json.dump(data, f, indent=2)


class SFTPConnection:
    def __init__(self):
        self.client = None
        self.sftp = None
        self.connected = False
        self.lock = threading.Lock()

    def connect(self, host, username, password, port=22):
        self.client = paramiko.SSHClient()
        self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self.client.connect(host, port=port, username=username, password=password, timeout=10)
        self.sftp = self.client.open_sftp()
        self.connected = True

    def disconnect(self):
        if self.sftp:
            self.sftp.close()
        if self.client:
            self.client.close()
        self.connected = False

    def list_dir(self, path):
        with self.lock:
            entries = []
            for attr in self.sftp.listdir_attr(path):
                is_dir = stat.S_ISDIR(attr.st_mode)
                entries.append({
                    'name': attr.filename,
                    'is_dir': is_dir,
                    'size': attr.st_size,
                    'path': os.path.join(path, attr.filename)
                })
            entries.sort(key=lambda x: (not x['is_dir'], x['name'].lower()))
            return entries

    def get_size(self, path):
        with self.lock:
            try:
                attr = self.sftp.stat(path)
                if stat.S_ISDIR(attr.st_mode):
                    return self._get_dir_size(path)
                return attr.st_size
            except Exception:
                return 0

    def _get_dir_size(self, path):
        total = 0
        try:
            for attr in self.sftp.listdir_attr(path):
                child = os.path.join(path, attr.filename)
                if stat.S_ISDIR(attr.st_mode):
                    total += self._get_dir_size(child)
                else:
                    total += attr.st_size
        except Exception:
            pass
        return total

    def download_file(self, remote_path, local_path, callback=None):
        with self.lock:
            self.sftp.get(remote_path, local_path, callback=callback)

    def download_dir(self, remote_path, local_path, callback=None):
        with self.lock:
            os.makedirs(local_path, exist_ok=True)
            for attr in self.sftp.listdir_attr(remote_path):
                remote_child = os.path.join(remote_path, attr.filename)
                local_child = os.path.join(local_path, attr.filename)
                if stat.S_ISDIR(attr.st_mode):
                    self.lock.release()
                    self.download_dir(remote_child, local_child, callback)
                    self.lock.acquire()
                else:
                    self.sftp.get(remote_child, local_child, callback=callback)
