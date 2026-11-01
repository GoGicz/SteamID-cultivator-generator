"""Run log and shared basics: SteamError, timestamps, and the RunLog that counts every Steam
request (the API key never reaches a log file)."""

import datetime
import os
import re
import threading
import time


LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Logs")


class SteamError(Exception):
    """An error whose message is fit to show to the user (bad input, Steam refusing...)."""


# ---------------------------------------------------------------------------
# Logging. Every Steam request goes through steam_get(), which counts it, so each
# command you run is written to Logs/steam_cultivator_<date>.log with what was run, what
# happened and how many Steam API calls it used (retries count too, because Steam counts
# every request). The API key is never written to the log.
# ---------------------------------------------------------------------------
def stamp(ts):
    """'2026-10-30 02:15:00' in local time."""
    return datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")


class RunLog:
    def __init__(self):
        self.lock = threading.Lock()
        self.secret = ""                 # the API key, hidden if it ever shows up in a message
        self.session_calls = 0
        self.session_commands = 0
        self.session_started = None
        self.session_written = False
        self.warned = False
        self.begin("")

    def begin(self, command):
        with self.lock:
            self.command = command
            self.started = time.time()
            self.calls = {}              # endpoint -> number of requests
            self.problems = {}           # (endpoint, outcome) -> number of requests
            self.notes = []

    def record(self, endpoint, outcome):
        with self.lock:
            self.calls[endpoint] = self.calls.get(endpoint, 0) + 1
            if outcome != "HTTP 200":
                k = (endpoint, outcome)
                self.problems[k] = self.problems.get(k, 0) + 1

    def note(self, text):
        with self.lock:
            self.notes.append(text)

    def total(self):
        with self.lock:
            return sum(self.calls.values())

    def scrub(self, text):
        text = re.sub(r"(key=)[0-9A-Za-z]+", r"\1<hidden>", str(text))
        if self.secret:
            text = text.replace(self.secret, "<hidden>")
        return text

    def _write(self, text):
        """Appends to today's log file. A log that can't be written never stops the program."""
        try:
            os.makedirs(LOG_DIR, exist_ok=True)
            path = os.path.join(LOG_DIR, "steam_cultivator_" + stamp(time.time())[:10] + ".log")
            with open(path, "a", encoding="utf-8") as f:
                f.write(text)
            return True
        except OSError as e:
            if not self.warned:
                self.warned = True
                print(f"\n  (Could not write the log in '{LOG_DIR}': {e}. Carrying on without it.)")
            return False

    def finish(self, status):
        """Writes the entry for the command that just ran."""
        now = time.time()
        with self.lock:
            calls, problems, notes = dict(self.calls), dict(self.problems), list(self.notes)
            command, took = self.command, now - self.started
        total = sum(calls.values())
        lines = []
        if not self.session_written:
            self.session_started = self.session_started or self.started
            lines.append(f"=== Session started {stamp(self.session_started)} ===\n")
        lines.append(f"[{stamp(self.started)}] "
                     f"{self.scrub(command)}\n")
        lines.append(f"  Result : {self.scrub(status)}\n")
        lines.append(f"  Steam API calls: {total} ({took:.1f}s)\n")
        for ep in sorted(calls):
            lines.append(f"    {ep:<34} {calls[ep]:>5}\n")
        for (ep, outcome), n in sorted(problems.items()):
            lines.append(f"  Problem: {ep}: {n} x {outcome}\n")
        for n in notes:
            lines.append(f"  Note   : {self.scrub(n)}\n")
        lines.append("\n")
        if self._write("".join(lines)):
            self.session_written = True
        self.session_calls += total
        self.session_commands += 1
        self.begin("")

    def end_session(self):
        if self.session_commands:
            self._write(f"=== Session ended {stamp(time.time())}: "
                        f"{self.session_commands} command(s), {self.session_calls} Steam API "
                        f"call(s) in total ===\n\n")


RUN_LOG = RunLog()
