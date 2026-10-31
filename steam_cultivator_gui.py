#!/usr/bin/env python3
"""
Steam Cultivator - window version (dark theme, CustomTkinter)
--------------------------------------------------------------
Needs:  pip install customtkinter
Run:    python steam_cultivator_gui.py        (steam_cultivator.py must be next to it)

It uses exactly the same engine, the same cache folder and the same Logs folder as the
terminal program (python steam_cultivator.py), so both versions share every cultivator, treasure,
sect point and reputation point.

The file has two halves:
  * Controller and the view helpers (cultivator_view ...) hold all the behavior and never
    touch the window, so they can be tested without a screen.
  * App is only the window: tabs, buttons and labels that call the Controller.
"""
import contextlib
import datetime
import io
import os
import queue
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import steam_cultivator as sc


# ---------------------------------------------------------------------------
# Controller: everything the window does, without any window code
# ---------------------------------------------------------------------------
class Controller:
    """Holds the Steam key, the in-memory profile cache and which cultivator was looked up
    last (for the pavilion). Every method either returns plain data or raises sc.SteamError
    with a message that is fit to show to the user."""

    def __init__(self, key):
        if not key:
            raise sc.SteamError("An API key is required (https://steamcommunity.com/dev/apikey).")
        self.key = key
        self.profiles = {}
        self.session = {}
        self.busy = threading.Lock()
        sc.RUN_LOG.secret = key

    # -- running one command with logging --------------------------------------------------
    def _run(self, command, fn):
        if not self.busy.acquire(blocking=False):
            raise sc.SteamError("Please wait, the previous action is still running.")
        sc.RUN_LOG.begin(command)
        status = "ok"
        try:
            with contextlib.redirect_stdout(io.StringIO()):     # nothing may print into a window
                return fn()
        except sc.SteamError as e:
            status = f"error: {e}"
            raise
        except BaseException as e:
            status = f"crashed: {type(e).__name__}: {e}"
            raise
        finally:
            sc.RUN_LOG.finish(status)
            self.busy.release()

    # -- the cultivator tab ----------------------------------------------------------------
    def lookup(self, text, refresh=False):
        text = (text or "").strip()
        if text.lower().startswith("refresh "):
            refresh, text = True, text[len("refresh "):].strip()
        if not text:
            raise sc.SteamError("Type a Steam profile URL, custom name or SteamID64 first.")

        def work():
            steamid = sc.resolve_steamid(text, self.key, refresh)
            info, friend_ids, note, c = sc.build_cultivator(steamid, self.key, self.profiles, refresh)
            self.session["latest"] = steamid
            friend = sc.resolve_friend(c, friend_ids, self.key)
            out = {"steamid": steamid, "info": info, "c": c, "friend": friend, "note": note,
                   "story": sc.generate_story(c, info, friend) if friend else None,
                   "death": sc.describe_death(c, info, friend) if c["death"] else None}
            out["view"] = cultivator_view(c, info)
            return out
        return self._run(("refresh lookup of " if refresh else "lookup of ") + text, work)

    # -- the pavilion tab ------------------------------------------------------------------
    def selected(self):
        """The SteamID of the latest cultivator, or None."""
        return self.session.get("latest")

    def shop(self):
        """{'steamid', 'c', 'rows'} for the pavilion; raises SteamError if nobody is selected
        or the cultivator is dead."""
        def work():
            steamid, c = sc.pavilion_target(self.key, self.profiles, self.session)
            return {"steamid": steamid, "c": c, "rows": shop_rows(c)}
        return self._run("pavilion", work)

    def buy(self, number):
        """Buys item number `number` (as listed in shop rows). Returns the receipt dict."""
        def work():
            steamid, c = sc.pavilion_target(self.key, self.profiles, self.session)
            item = sc.buy_pavilion_item(steamid, c, number)
            return {"item": item, "c": c, "rows": shop_rows(c), "steamid": steamid,
                    "goods": sc.describe_goods(c["pavilion"]["items"]) or "nothing yet",
                    "treasures": sc.describe_treasures(sc.treasures_of(c)) or "none"}
        return self._run(f"pavilion {number}", work)

    # -- the duel tab ----------------------------------------------------------------------
    def duel(self, text1, text2):
        text1, text2 = (text1 or "").strip(), (text2 or "").strip()
        if not text1 or not text2:
            raise sc.SteamError("Type both profiles to make them duel.")

        def work():
            ids = [sc.resolve_steamid(t, self.key) for t in (text1, text2)]
            d = sc.perform_battle(ids, self.key, self.profiles)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                sc.print_battle(d["a"], d["b"], d["info_a"], d["info_b"], d["result"],
                                d["story"], d["loot"], d["change"])
            d["ids"] = ids
            d["report"] = buf.getvalue()
            d["winner_side"] = "a" if d["result"]["winner"] is d["a"] else "b"
            return d
        return self._run(f"mocb {text1} {text2}", work)

    # -- the log tab -----------------------------------------------------------------------
    def log_text(self):
        """Today's log file, or a note if there is none yet."""
        path = os.path.join(sc.LOG_DIR, "steam_cultivator_"
                            + sc.stamp(sc.time.time())[:10] + ".log")
        try:
            with open(path, encoding="utf-8") as f:
                return f.read()
        except OSError:
            return "(No log for today yet. It is written after your first action.)"


# ---------------------------------------------------------------------------
# View helpers: plain data for what the window shows
# ---------------------------------------------------------------------------
REALM_COLORS = ["#8d99ae", "#7aa2f7", "#5ec2b7", "#7bd88f", "#d6d66b",
                "#f0b86e", "#f28c6b", "#e0645c", "#c667d8", "#ffd86b"]
PATH_COLORS = {"Righteous": "#5fb3ff", "Demonic": "#e0525e"}


def realm_color(index):
    return REALM_COLORS[min(max(index, 0), len(REALM_COLORS) - 1)]


def reputation_progress(rep):
    """(fraction 0..1 toward the next rank, caption)."""
    ranks = sc.REPUTATION_RANKS
    i, pts = rep["rank_index"], rep["points"]
    if i >= len(ranks) - 1:
        return 1.0, "highest rank reached"
    lo, hi = ranks[i][0], ranks[i + 1][0]
    frac = min(1.0, max(0.0, (pts - lo) / (hi - lo)))
    return frac, f"{hi - pts:,} points to {ranks[i + 1][1]}"


def cultivator_view(c, info):
    """Everything the cultivator card shows, as plain data: a header, the progress bars,
    the detail rows and the Steam source rows."""
    t, rep = c["talent"], c["reputation"]
    rows = [("Realm", f"{c['realm']} ({c['realm_flavor']})"),
            ("Talent", f"{t['name']} (power {t['power']:+d})"),
            ("Personality", ", ".join(sc.personality_label(p) for p in c["personalities"])
             if c["personalities"] else "none (a quiet temperament)"),
            ("Path", sc.path_label(c["path"])),
            ("Reputation", f"{rep['rank']} ({rep['points']:,} points)")]
    if rep["bonuses"]:
        rows.append(("Fame boosts", ", ".join(f"{n} {a:+d}" for n, a in rep["bonuses"])))
    rows += [("Death risk", f"{c['death_chance'] * 100:g}%"),
             ("Affinity", c["element"]),
             ("Matchups", f"strong vs {', '.join(sc.ELEMENT_BEATS.get(c['element'], []))}; "
                          f"weak vs {', '.join(sc.element_weak_to(c['element']))}"),
             ("Signature", c["technique"]),
             ("Arsenal", sc.arsenal_text(c))]
    owned = sc.treasures_of(c)
    rows.append(("Treasures", sc.describe_treasures(owned) if owned
                 else "none (robbed of everything)"))
    events = [e for e in c.get("inventory_history", []) if e.get("type") != "start"]
    if events:
        rows.append(("Recent", sc.describe_event(events[-1])))
    if info["achievements_hidden"]:
        rows.append(("Missions", "0 (Steam is hiding your achievements)"))
    else:
        n = c["missions"]
        rows.append(("Missions", f"{n:,} sect mission{'' if n == 1 else 's'} completed"))
        new = info.get("achievements_new")
        if new and new > 0:
            rows.append(("Since last", f"+{new:,} new mission{'' if new == 1 else 's'} "
                                       f"(+{new * sc.SECT_POINTS_PER_MISSION:,} sect points) "
                                       f"since your last visit"))
    spent = c.get("pavilion", {}).get("spent", 0)
    rows.append(("Sect points", f"{c['sect_points']:,}" + (
        f" (earned {c['sect_points_earned']:,}, spent {spent:,})" if spent else "")))
    goods = sc.describe_goods(c.get("pavilion", {}).get("items", {}))
    if goods:
        rows.append(("Pavilion", goods))
    rows.append(("Lifespan", f"{c['lifespan']:,} years" + (" (cut short)" if c["death"] else "")))
    rows.append(("Born", f"Year {c['birth_year']} of the Heavenly Calendar"))
    if c.get("age") is not None:
        yrs = c.get("account_years")
        rows.append(("Age", f"{c['age']:,} years" + (" at death" if c["death"] else "")
                     + (f" ({yrs:.0f}-year-old account)" if yrs is not None else "")))
    if c["death"]:
        rows.append(("Died", f"Year {c['death']['year']} of the Heavenly Calendar "
                             f"(aged {c['death']['age']:,})"))
    else:
        rows.append(("Status", "Alive and cultivating"))
    if c["lightning"]:
        rows.append(("Tribulations", f"survived {c['lightning']} heavenly lightning strikes"))

    source = []
    if info.get("account_created") and c.get("account_years") is not None:
        year = datetime.datetime.fromtimestamp(info["account_created"], datetime.timezone.utc).year
        source.append(("Account age", f"{c['account_years']:.1f} years (created {year})"))
    source.append(("Steam level", str(info["level"])))
    source.append(("Paid games", f"{info['game_count']:,}"))
    source.append(("Achievements", f"{info['achievements']:,}"))
    source.append(("Badges", "0 (Steam is hiding your badges)" if info["badges_hidden"]
                   else f"{info['badges']:,}"))
    if info["top_game"]:
        source.append(("Most played", f"{info['top_game']} ({info['top_hours']:,.0f} h)"))

    rep_frac, rep_caption = reputation_progress(rep)
    return {
        "name": c["name"], "subtitle": f"{c['title']} of the {c['sect']}",
        "dead": bool(c["death"]), "path": c["path"]["name"],
        "path_color": PATH_COLORS.get(c["path"]["name"], "#999999"),
        "realm": c["realm"], "realm_color": realm_color(c["realm_index"]),
        "power_fraction": (c["realm_index"] + 1) / len(sc.REALMS),
        "power_caption": f"realm {c['realm_index'] + 1}/{len(sc.REALMS)}, score {c['score']:,.0f}",
        "rep_fraction": rep_frac, "rep_caption": rep_caption, "rep_rank": rep["rank"],
        "rows": rows, "source": source, "backstory": c["backstory"],
    }


def shop_rows(c):
    """One dict per pavilion item for the shop list. 'number' is what buy() takes."""
    rows = []
    for n, item in enumerate(sc.PAVILION_ITEMS, 1):
        owned = c["pavilion"]["items"].get(item["id"], 0)
        weapon_owned = item["kind"] == "Weapon" and owned > 0
        affordable = item["price"] <= c["sect_points"]
        rows.append({"number": n, "id": item["id"], "kind": item["kind"], "name": item["name"],
                     "price": item["price"], "blurb": item["blurb"], "owned": owned,
                     "can_buy": affordable and not weapon_owned,
                     "status": sc.pavilion_status(c, item)})
    return rows


def win_chance_text(result, side):
    p = result["p_a"] if side == "a" else result["p_b"]
    return f"{p * 100:.1f}%"


# ---------------------------------------------------------------------------
# The window
# ---------------------------------------------------------------------------
BG = "#14161c"
PANEL = "#1d212b"
PANEL_2 = "#252a36"
TEXT = "#e6e8ee"
MUTED = "#9aa3b5"
ACCENT = "#c8a24a"        # a muted gold
GOOD = "#6fcf97"
BAD = "#eb6b6b"
WIDE = 820                # wrap width for long texts


class App:
    """The window. It only builds widgets and calls the Controller on a worker thread."""

    def __init__(self, ctk, key=None):
        import tkinter
        self.tk = tkinter
        self.ctk = ctk
        self.bodies = {}
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("dark-blue")
        self.root = ctk.CTk()
        self.root.title("Steam Cultivator")
        self.root.geometry("1040x780")
        self.root.minsize(860, 600)
        self.root.configure(fg_color=BG)
        self.controller = None
        self.events = queue.Queue()
        self.working = False
        self.title_font = ctk.CTkFont(size=24, weight="bold")
        self.head_font = ctk.CTkFont(size=15, weight="bold")
        self.body_font = ctk.CTkFont(size=13)
        self.small_font = ctk.CTkFont(size=12)
        self.mono_font = ctk.CTkFont(family="Courier New", size=12)
        sc.PROGRESS_HOOK = lambda done, total: self.events.put(("progress", done, total))
        self.root.after(80, self.poll)
        if key:
            self.start(key)
        else:
            self.build_key_screen()

    # -- starting up -----------------------------------------------------------------------
    def build_key_screen(self):
        ctk = self.ctk
        self.key_frame = ctk.CTkFrame(self.root, fg_color=PANEL, corner_radius=14)
        self.key_frame.place(relx=0.5, rely=0.45, anchor="center")
        ctk.CTkLabel(self.key_frame, text="Steam Cultivator", font=self.title_font,
                     text_color=ACCENT).pack(padx=48, pady=(32, 4))
        ctk.CTkLabel(self.key_frame, text="Enter your Steam Web API key to begin.",
                     font=self.body_font, text_color=MUTED).pack(padx=48)
        ctk.CTkLabel(self.key_frame, text="Get one at steamcommunity.com/dev/apikey. It is "
                     "only kept while this window is open.", font=self.small_font,
                     text_color=MUTED, wraplength=380).pack(padx=48, pady=(2, 14))
        self.key_entry = ctk.CTkEntry(self.key_frame, width=380, show="*",
                                      placeholder_text="Steam API key")
        self.key_entry.pack(padx=48)
        self.key_entry.bind("<Return>", lambda e: self.submit_key())
        self.key_error = ctk.CTkLabel(self.key_frame, text="", text_color=BAD, font=self.small_font)
        self.key_error.pack(pady=(6, 0))
        ctk.CTkButton(self.key_frame, text="Enter the Dao", command=self.submit_key,
                      fg_color=ACCENT, hover_color="#a8862f", text_color="#1a1a1a",
                      width=180).pack(pady=(8, 32))
        self.key_entry.focus()

    def submit_key(self):
        key = self.key_entry.get().strip()
        if not key:
            self.key_error.configure(text="An API key is required.")
            return
        self.key_frame.destroy()
        self.start(key)

    def start(self, key):
        self.controller = Controller(key)
        self.build_main()

    # -- the main layout -------------------------------------------------------------------
    def build_main(self):
        ctk = self.ctk
        self.tabs = ctk.CTkTabview(self.root, fg_color=PANEL, command=self.on_tab,
                                   segmented_button_selected_color=ACCENT,
                                   segmented_button_selected_hover_color="#a8862f")
        self.tabs.pack(fill="both", expand=True, padx=14, pady=(14, 6))
        for name in ("Cultivator", "Pavilion", "Duel", "Log"):
            self.tabs.add(name)
        self.build_cultivator_tab(self.tabs.tab("Cultivator"))
        self.build_pavilion_tab(self.tabs.tab("Pavilion"))
        self.build_duel_tab(self.tabs.tab("Duel"))
        self.build_log_tab(self.tabs.tab("Log"))
        bar = ctk.CTkFrame(self.root, fg_color="transparent")
        bar.pack(fill="x", padx=18, pady=(0, 10))
        self.status = ctk.CTkLabel(bar, text="Ready.", font=self.small_font, text_color=MUTED,
                                   anchor="w")
        self.status.pack(side="left")
        self.progress = ctk.CTkProgressBar(bar, width=220, progress_color=ACCENT)
        self.progress.set(0)

    def on_tab(self):
        name = self.tabs.get()
        if name == "Pavilion":
            self.refresh_pavilion()
        elif name == "Log":
            self.refresh_log()

    # -- background work -------------------------------------------------------------------
    def run_async(self, label, fn, on_done, on_error=None):
        """Runs fn() on a worker thread; on_done(result) or on_error(message) then run on the
        window's own thread. Only one action at a time."""
        if self.working:
            return
        self.working = True
        self.set_buttons("disabled")
        self.status.configure(text=label, text_color=MUTED)
        self.progress.configure(mode="indeterminate")
        self.progress.pack(side="right")
        self.progress.start()

        def worker():
            try:
                self.events.put(("done", on_done, fn()))
            except sc.SteamError as e:
                self.events.put(("error", on_error, str(e)))
            except BaseException as e:                      # never let a thread die silently
                self.events.put(("error", on_error, f"Something unexpected went wrong: "
                                                    f"{type(e).__name__}: {e}"))
        threading.Thread(target=worker, daemon=True).start()

    def poll(self):
        """Runs on the window thread every 80 ms and handles what the worker reported."""
        try:
            while True:
                event = self.events.get_nowait()
                if event[0] == "progress":
                    _, done, total = event
                    self.progress.stop()
                    self.progress.configure(mode="determinate")
                    self.progress.set(done / total if total else 0)
                    self.status.configure(text=f"Counting achievements... {done}/{total} games",
                                          text_color=MUTED)
                else:
                    self.finish_work(event)
        except queue.Empty:
            pass
        self.root.after(80, self.poll)

    def finish_work(self, event):
        kind, callback, payload = event
        self.working = False
        self.progress.stop()
        self.progress.pack_forget()
        self.set_buttons("normal")
        if kind == "done":
            self.status.configure(text="Done.", text_color=GOOD)
            callback(payload)
        else:
            self.status.configure(text=payload, text_color=BAD)
            if callback:
                callback(payload)

    def set_buttons(self, state):
        for b in (self.look_button, self.fight_button, self.log_button):
            b.configure(state=state)
        for b in self.buy_buttons:
            b.configure(state=state if state == "disabled" else b.intended_state)

    # -- tab: cultivator -------------------------------------------------------------------
    def build_cultivator_tab(self, tab):
        ctk = self.ctk
        top = ctk.CTkFrame(tab, fg_color="transparent")
        top.pack(fill="x", pady=(4, 8))
        self.look_entry = ctk.CTkEntry(top, placeholder_text="Steam profile URL, custom name "
                                       "or SteamID64", height=36)
        self.look_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.look_entry.bind("<Return>", lambda e: self.do_lookup())
        self.refresh_var = self.tk.BooleanVar(value=False)
        ctk.CTkCheckBox(top, text="Force refresh", variable=self.refresh_var,
                        font=self.small_font, fg_color=ACCENT, hover_color="#a8862f"
                        ).pack(side="left", padx=8)
        self.look_button = ctk.CTkButton(top, text="Look up", command=self.do_lookup, height=36,
                                         fg_color=ACCENT, hover_color="#a8862f",
                                         text_color="#1a1a1a", width=110)
        self.look_button.pack(side="left")
        self.card = ctk.CTkScrollableFrame(tab, fg_color=PANEL, corner_radius=10)
        self.card.pack(fill="both", expand=True)
        self.say(self.card, "Look up a Steam profile to meet its cultivator.")

    def do_lookup(self):
        text, refresh = self.look_entry.get(), bool(self.refresh_var.get())
        self.run_async("Looking up the profile...", lambda: self.controller.lookup(text, refresh),
                       self.show_cultivator, self.show_card_error)

    def fresh(self, scroll):
        """A new, empty holder inside a scrollable frame (the old one is thrown away), so the
        scroll frame's own parts are never touched."""
        old = self.bodies.pop(scroll, None)
        if old is not None:
            old.destroy()
        body = self.ctk.CTkFrame(scroll, fg_color="transparent")
        body.pack(fill="x", expand=True)
        self.bodies[scroll] = body
        return body

    def say(self, scroll, message, color=MUTED, pad=40):
        body = self.fresh(scroll)
        self.ctk.CTkLabel(body, text=message, text_color=color, font=self.body_font,
                          wraplength=WIDE, justify="left").pack(pady=pad, padx=20)

    def show_card_error(self, message):
        self.say(self.card, message, BAD, 30)

    def show_cultivator(self, data):
        ctk, v = self.ctk, data["view"]
        body = self.fresh(self.card)
        head = ctk.CTkFrame(body, fg_color=PANEL_2, corner_radius=10)
        head.pack(fill="x", padx=6, pady=(6, 10))
        ctk.CTkLabel(head, text=v["name"], font=self.title_font, text_color=ACCENT,
                     anchor="w").pack(fill="x", padx=16, pady=(12, 0))
        ctk.CTkLabel(head, text=v["subtitle"], font=self.body_font, text_color=MUTED,
                     anchor="w").pack(fill="x", padx=16)
        chips = ctk.CTkFrame(head, fg_color="transparent")
        chips.pack(fill="x", padx=12, pady=(8, 12))
        self.chip(chips, v["path"], v["path_color"])
        self.chip(chips, v["realm"], v["realm_color"])
        self.chip(chips, "Fallen" if v["dead"] else "Alive", BAD if v["dead"] else GOOD)

        bars = ctk.CTkFrame(body, fg_color="transparent")
        bars.pack(fill="x", padx=6)
        self.bar(bars, "Power", v["power_fraction"], v["power_caption"], v["realm_color"])
        self.bar(bars, v["rep_rank"], v["rep_fraction"], v["rep_caption"], ACCENT)

        self.section(body, "Cultivator")
        self.table(body, v["rows"])
        self.section(body, "Source stats from Steam")
        self.table(body, v["source"])
        self.section(body, "Backstory")
        self.paragraph(body, v["backstory"])
        if data["friend"] and data["story"]:
            self.section(body, f"A tale from their life (Steam friend: {data['friend']['name']})")
            self.paragraph(body, data["story"])
        elif data["note"]:
            self.paragraph(body, f"({data['note']})", muted=True)
        if data["death"]:
            label, text = data["death"]
            self.section(body, "The end of the road", color=BAD)
            self.paragraph(body, f"Slain by: {label}")
            self.paragraph(body, text)
        self.status.configure(text=f"Loaded {v['name']}.", text_color=GOOD)

    def chip(self, parent, text, color):
        self.ctk.CTkLabel(parent, text=f"  {text}  ", fg_color=color, text_color="#101010",
                          corner_radius=12, font=self.small_font).pack(side="left", padx=4)

    def bar(self, parent, label, fraction, caption, color):
        ctk = self.ctk
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", pady=3)
        ctk.CTkLabel(row, text=label, width=190, anchor="w", font=self.body_font).pack(side="left")
        pb = ctk.CTkProgressBar(row, progress_color=color, height=12)
        pb.set(fraction)
        pb.pack(side="left", fill="x", expand=True, padx=8)
        ctk.CTkLabel(row, text=caption, width=250, anchor="w", font=self.small_font,
                     text_color=MUTED).pack(side="left")

    def section(self, parent, text, color=ACCENT):
        self.ctk.CTkLabel(parent, text=text, font=self.head_font, text_color=color,
                          anchor="w").pack(fill="x", padx=10, pady=(16, 4))

    def table(self, parent, rows):
        ctk = self.ctk
        grid = ctk.CTkFrame(parent, fg_color=PANEL_2, corner_radius=8)
        grid.pack(fill="x", padx=6)
        for label, value in rows:
            row = ctk.CTkFrame(grid, fg_color="transparent")
            row.pack(fill="x", padx=10, pady=2)
            ctk.CTkLabel(row, text=label, width=110, anchor="nw", text_color=MUTED,
                         font=self.body_font).pack(side="left", anchor="n")
            ctk.CTkLabel(row, text=value, anchor="w", justify="left", wraplength=WIDE - 130,
                         font=self.body_font).pack(side="left", fill="x", expand=True)

    def paragraph(self, parent, text, muted=False):
        self.ctk.CTkLabel(parent, text=text, anchor="w", justify="left", wraplength=WIDE,
                          font=self.body_font, text_color=MUTED if muted else TEXT
                          ).pack(fill="x", padx=12, pady=3)

    # -- tab: pavilion ---------------------------------------------------------------------
    def build_pavilion_tab(self, tab):
        ctk = self.ctk
        self.pav_head = ctk.CTkLabel(tab, text="", font=self.head_font, anchor="w",
                                     text_color=ACCENT)
        self.pav_head.pack(fill="x", padx=6, pady=(4, 0))
        self.pav_msg = ctk.CTkLabel(tab, text="", font=self.body_font, anchor="w",
                                    justify="left", wraplength=WIDE + 100)
        self.pav_msg.pack(fill="x", padx=6, pady=(2, 6))
        self.pav_list = ctk.CTkScrollableFrame(tab, fg_color=PANEL, corner_radius=10)
        self.pav_list.pack(fill="both", expand=True)
        self.buy_buttons = []

    def refresh_pavilion(self):
        if self.working or self.controller is None:
            return
        self.run_async("Opening the Martial Pavilion...", self.controller.shop,
                       self.show_shop, self.show_shop_error)

    def show_shop_error(self, message):
        self.fresh(self.pav_list)
        self.buy_buttons = []
        self.pav_head.configure(text="Sect Martial Pavilion")
        self.pav_msg.configure(text=message, text_color=BAD)

    def show_shop(self, data, receipt=None):
        ctk, c = self.ctk, data["c"]
        body = self.fresh(self.pav_list)
        self.buy_buttons = []
        self.pav_head.configure(text=f"Sect Martial Pavilion - {c['name']} of the {c['sect']}"
                                     f"     Sect points: {c['sect_points']:,}")
        if receipt:
            self.pav_msg.configure(
                text=f"{c['name']} bought {receipt['item']['name']} for "
                     f"{receipt['item']['price']:,} sect points.  Goods: {receipt['goods']}",
                text_color=GOOD)
        else:
            self.pav_msg.configure(text="Choose something to buy. Weapons can be bought once; "
                                        "pills, treasures and talismans stack.", text_color=MUTED)
        kind = None
        for r in data["rows"]:
            if r["kind"] != kind:
                kind = r["kind"]
                self.section(body, kind + "s")
            row = ctk.CTkFrame(body, fg_color=PANEL_2, corner_radius=8)
            row.pack(fill="x", padx=6, pady=3)
            text = ctk.CTkFrame(row, fg_color="transparent")
            text.pack(side="left", fill="x", expand=True, padx=10, pady=6)
            ctk.CTkLabel(text, text=f"{r['name']}   -   {r['price']:,} sect points",
                         font=self.head_font, anchor="w").pack(fill="x")
            ctk.CTkLabel(text, text=r["blurb"], font=self.small_font, text_color=MUTED,
                         anchor="w", justify="left", wraplength=WIDE - 160).pack(fill="x")
            ctk.CTkLabel(text, text=r["status"], font=self.small_font, anchor="w",
                         text_color=GOOD if r["can_buy"] else MUTED).pack(fill="x")
            b = ctk.CTkButton(row, text="Buy" if r["can_buy"] else "Unavailable", width=110,
                              fg_color=ACCENT, hover_color="#a8862f", text_color="#1a1a1a",
                              state="normal" if r["can_buy"] else "disabled",
                              command=lambda n=r["number"]: self.do_buy(n))
            b.intended_state = "normal" if r["can_buy"] else "disabled"
            b.pack(side="right", padx=10)
            self.buy_buttons.append(b)

    def do_buy(self, number):
        self.run_async("Buying...", lambda: self.controller.buy(number),
                       lambda rec: self.show_shop(rec, rec), self.show_buy_error)

    def show_buy_error(self, message):
        self.pav_msg.configure(text=message, text_color=BAD)

    # -- tab: duel -------------------------------------------------------------------------
    def build_duel_tab(self, tab):
        ctk = self.ctk
        top = ctk.CTkFrame(tab, fg_color="transparent")
        top.pack(fill="x", pady=(4, 8))
        self.duel_entries = []
        for n, hint in enumerate(("First profile", "Second profile")):
            e = ctk.CTkEntry(top, placeholder_text=hint, height=36)
            e.pack(side="left", fill="x", expand=True, padx=(0, 8))
            e.bind("<Return>", lambda ev: self.do_duel())
            self.duel_entries.append(e)
        self.fight_button = ctk.CTkButton(top, text="Fight!", command=self.do_duel, height=36,
                                          fg_color=BAD, hover_color="#b84848", width=110)
        self.fight_button.pack(side="left")
        self.duel_area = ctk.CTkScrollableFrame(tab, fg_color=PANEL, corner_radius=10)
        self.duel_area.pack(fill="both", expand=True)
        self.say(self.duel_area, "Enter two profiles and let their cultivators duel. "
                                 "Dead cultivators cannot fight.")

    def do_duel(self):
        a, b = (e.get() for e in self.duel_entries)
        self.run_async("The duel begins...", lambda: self.controller.duel(a, b),
                       self.show_duel, self.show_duel_error)

    def show_duel_error(self, message):
        self.say(self.duel_area, message, BAD, 30)

    def show_duel(self, d):
        ctk, result = self.ctk, d["result"]
        body = self.fresh(self.duel_area)
        sides = ctk.CTkFrame(body, fg_color="transparent")
        sides.pack(fill="x", padx=6, pady=(6, 10))
        sides.grid_columnconfigure((0, 1), weight=1)
        for col, side in enumerate(("a", "b")):
            c, p = d[side], result["p_" + side]
            won = d["winner_side"] == side
            box = ctk.CTkFrame(sides, fg_color=PANEL_2, corner_radius=10,
                               border_width=2 if won else 0, border_color=GOOD)
            box.grid(row=0, column=col, sticky="nsew", padx=6)
            ctk.CTkLabel(box, text=("WINNER  " if won else "") + c["name"], font=self.head_font,
                         text_color=GOOD if won else TEXT).pack(padx=12, pady=(10, 0))
            ctk.CTkLabel(box, text=f"of the {c['sect']}", font=self.small_font,
                         text_color=MUTED).pack()
            self.chip(box, c["path"]["name"], PATH_COLORS.get(c["path"]["name"], "#999999"))
            for line in (c["realm"], f"Power {c['score']:,.0f}", f"{c['talent']['name']}",
                         f"Affinity: {c['element']}"):
                ctk.CTkLabel(box, text=line, font=self.small_font).pack()
            pb = ctk.CTkProgressBar(box, progress_color=realm_color(c["realm_index"]), width=200)
            pb.set(p)
            pb.pack(pady=(8, 2))
            ctk.CTkLabel(box, text=f"Win chance {p * 100:.1f}%", font=self.small_font,
                         text_color=MUTED).pack(pady=(0, 10))
        self.section(body, "The battle")
        self.paragraph(body, d["story"])
        self.section(body, "Report")
        box = ctk.CTkTextbox(body, height=420, font=self.mono_font, wrap="none",
                             fg_color=PANEL_2)
        box.pack(fill="x", padx=8, pady=(0, 10))
        box.insert("end", d["report"])
        box.configure(state="disabled")
        self.status.configure(text=f"{result['winner']['name']} wins the duel.", text_color=GOOD)

    # -- tab: log --------------------------------------------------------------------------
    def build_log_tab(self, tab):
        ctk = self.ctk
        self.log_button = ctk.CTkButton(tab, text="Reload log", command=self.refresh_log,
                                        width=120, fg_color=PANEL_2)
        self.log_button.pack(anchor="e", pady=(4, 6))
        self.log_box = ctk.CTkTextbox(tab, font=self.mono_font, wrap="none", fg_color=PANEL_2)
        self.log_box.pack(fill="both", expand=True)

    def refresh_log(self):
        if self.controller is None:
            return
        text = self.controller.log_text()
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.insert("end", text)
        self.log_box.configure(state="disabled")
        self.log_box.see("end")

    def run(self):
        self.root.mainloop()


def main():
    try:
        import customtkinter as ctk
    except ImportError:
        sys.exit("The window version needs CustomTkinter. Install it with:\n"
                 "    pip install customtkinter\n"
                 "(the terminal version, steam_cultivator.py, works without it).")
    App(ctk, os.environ.get("STEAM_API_KEY")).run()


if __name__ == "__main__":
    main()
