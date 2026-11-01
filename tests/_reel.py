"""The reel, step by step, inside a MemeDir: analyst -> entry -> exit -> time machine -> budget."""

import os

from _load import FIX, GATO, HISTORY, load, run

A = load("meme-analyst", "report")
E = load("meme-entry", "entry")
X = load("meme-exit", "exit")
T = load("meme-timemachine", "timemachine")
B = load("meme-budget", "size")
NOW = "2026-11-01 21:58"


def analyst():
    d = os.path.join(FIX, "meme-analyst")
    return run(A, [GATO, "--offline-dex", os.path.join(d, "dex-GATO-2158.json"),
                   "--offline-rugcheck", os.path.join(d, "rugcheck-GATO-2158.json"), "--now", NOW, "--write"])


def plan():
    run(E, ["check", GATO, "--symbol", "GATO", "--from", "21:42", "--now", NOW, "--offline", HISTORY])
    return run(X, ["plan", "--write", "--now", NOW])


def timemachine(replays="10000"):
    return run(T, ["run", "--offline", HISTORY, "--write", "--replays", replays])


def budget(extra=()):
    return run(B, ["--now", NOW, "--sol-price", "94.2023", "--roundtrip", "1.213", "--roundtrip-usd", "254.35",
                   "--write"] + list(extra))


def all_steps(replays="10000"):
    analyst()
    plan()
    timemachine(replays)
    return budget()
