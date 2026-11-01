"""Load a script from a skill folder (the folder names have hyphens), and run tools in a temp meme/ dir."""

import contextlib
import importlib.util
import io
import json
import os
import shutil
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIX = os.path.join(ROOT, "tests", "fixtures")
GATO = "HsprHxBRgiVaQdRf3TnKNuZZtaX9JUSPgMFdAkk6pump"
HISTORY = os.path.join(FIX, "meme-timemachine", "GATO-1m-2026-11-01-2158.json.gz")


def load(folder, name):
    path = os.path.join(ROOT, folder, name + ".py")
    spec = importlib.util.spec_from_file_location("meme_" + name.replace("-", "_"), path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class MemeDir(object):
    """A fresh meme/ folder with the example config, as MEME_DIR, for one test."""

    def __init__(self, **config):
        self.config = config

    def __enter__(self):
        self.path = tempfile.mkdtemp(prefix="meme-test-")
        self.old = os.environ.get("MEME_DIR")
        os.environ["MEME_DIR"] = self.path
        with open(os.path.join(ROOT, "meme-budget", "config.example.json")) as fh:
            cfg = json.load(fh)
        cfg.update(self.config)
        self.write("config.json", cfg)
        return self

    def __exit__(self, *exc):
        if self.old is None:
            os.environ.pop("MEME_DIR", None)
        else:
            os.environ["MEME_DIR"] = self.old
        shutil.rmtree(self.path, ignore_errors=True)

    def file(self, *parts):
        return os.path.join(self.path, *parts)

    def write(self, name, data):
        path = self.file(name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as fh:
            json.dump(data, fh)

    def read(self, name):
        with open(self.file(name)) as fh:
            return json.load(fh)


def run(mod, argv):
    """Run a tool's main(argv); return (exit code, stdout)."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = mod.main(argv)
    return code, buf.getvalue()
