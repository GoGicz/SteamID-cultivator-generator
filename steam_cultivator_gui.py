#!/usr/bin/env python3
"""
Steam Cultivator - window version (dark theme, CustomTkinter)
--------------------------------------------------------------
Needs:  pip install customtkinter
Run:    python steam_cultivator_gui.py        (the engine modules, steam_cultivator.py and the other .py files, must be next to it)

Tabs: Cultivator (with Breakthrough and Adventure), Pavilion, Battles (Duel, Team Battle,
Sect War), History and Log.

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
import time
import achievements
import combat
import display
import gamedata
import generator
import logs
import pavilion_shop
import progress
import steam_api
import storage
import teambattle


# Standard-library UI used by developer tools; CustomTkinter is loaded by main().
import copy
import difflib
import json
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox, filedialog


def set_game_window_icon(window):
    """Use the supplied PNG without requiring Pillow, and retain its Tk image."""
    path = Path(__file__).resolve().parent / "assets" / "game_icon.png"
    try:
        import base64
        image = tk.PhotoImage(master=window, data=base64.b64encode(path.read_bytes()).decode("ascii"))
        image = image.subsample(max(1, round(max(image.width(), image.height()) / 64)))
        window.game_icon_image = image
        window.iconphoto(True, image)
        return True
    except (OSError, tk.TclError):
        return False



# ============================================================================
# Developer tools — local profile creation tab
# ============================================================================

class OfflineCreatorTab(ttk.Frame):
    def __init__(self, parent, editor):
        super().__init__(parent)
        self.editor = editor
        self.fields = {}
        self.preview_data = None
        self.preview_settings = None
        self._syncing_power = False
        self._power_offset = 0
        self.editing_profile = None
        ttk.Label(self, text="Create a living local cultivator. All values are randomizable; no Steam API or key is used.", padding=8).pack(fill="x")
        ttk.Label(self, text="Power follows talent, path, personalities and training stats. Typing a score sets a manual adjustment; later choices still update it.", padding=(8, 0, 8, 8), wraplength=880).pack(fill="x")
        self.pages = ttk.Notebook(self)
        self.pages.pack(fill="both", expand=True)
        form_page = ttk.Frame(self.pages)
        self.pages.add(form_page, text="Character")
        canvas = tk.Canvas(form_page, highlightthickness=0)
        scroll = ttk.Scrollbar(form_page, command=canvas.yview)
        canvas.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        canvas.pack(fill="both", expand=True)
        form = ttk.Frame(canvas, padding=10)
        item = canvas.create_window((0, 0), window=form, anchor="nw")
        form.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(item, width=e.width))
        def wheel(event):
            canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")
        canvas.bind("<MouseWheel>", wheel)
        self.sect_choices=storage.sect_catalog(self.editor.cache)
        specs = [
            ("name", "Cultivator name", "text"), ("gender", "Gender", ["male", "female"]),
            ("sect", "Sect", [r["name"] for r in self.sect_choices]), ("element", "Affinity", list(gamedata.ELEMENTS)),
            ("talent", "Talent", list(gamedata.TALENT_BY_NAME)), ("path", "Path", [p["name"] for p in gamedata.PATHS]),
            ("score", "Power points (exact)", "int"), ("realm_index", "Current realm", "realm"),
            ("born_realm", "Born realm", "realm"), ("age", "Age (years)", "int"),
            ("birth_year", "Birth year (calendar-derived)", "int"), ("lifespan", "Base lifespan (years)", "int"),
            ("title", "Title (blank = template)", "text"), ("technique", "Signature (blank = template)", "text"),
            ("missions", "Completed missions / achievements", "int"), ("sect_points", "Starting sect-point balance", "int"),
            ("reputation", "Starting reputation points", "int"), ("death_chance", "Death risk (0–1)", "float"),
            ("level", "Synthetic training level", "int"), ("game_count", "Synthetic library size", "int"),
            ("top_game", "Signature inspiration", "text"), ("top_hours", "Synthetic meditation hours", "int"),
            ("badges", "Synthetic badge count", "int"), ("seed", "Local ID / random seed (20 digits)", "text"),
            ("spirit_stones", "Spirit Stones (starting balance)", "int"),
        ]
        for index, (key, label, kind) in enumerate(specs):
            row, col = index // 2, (index % 2) * 2
            ttk.Label(form, text=label).grid(row=row * 2, column=col, columnspan=2, sticky="w", pady=(8, 0))
            var = tk.StringVar()
            if kind == "realm":
                widget = ttk.Combobox(form, textvariable=var, state="readonly", values=[f"{i}: {r[1]}" for i, r in enumerate(gamedata.REALMS)])
            elif isinstance(kind, list):
                widget = ttk.Combobox(form, textvariable=var, state="readonly", values=kind)
            else:
                widget = ttk.Entry(form, textvariable=var)
            if key == "birth_year": widget.configure(state="readonly")
            widget.grid(row=row * 2 + 1, column=col, columnspan=2, sticky="ew", padx=(0, 14))
            widget.bind("<MouseWheel>", wheel)
            self.fields[key] = (var, kind)
            if key=="sect":self.sect_widget=widget
        form.columnconfigure(0, weight=1)
        form.columnconfigure(2, weight=1)
        ttk.Label(form, text="Personalities (optional; selected independently of synthetic stats)").grid(row=26, column=0, columnspan=4, sticky="w", pady=(14, 4))
        self.personalities = {}
        for i, p in enumerate(p for p in gamedata.PERSONALITIES if not p.get("steam_only")):
            var = tk.BooleanVar()
            ttk.Checkbutton(form, text=p["name"], variable=var).grid(row=27 + i // 3, column=(i % 3), sticky="w", pady=3)
            self.personalities[p["name"]] = var
        preview_page = ttk.Frame(self.pages)
        self.pages.add(preview_page, text="Preview JSON")
        self.summary = ttk.Label(preview_page, text="Randomize or edit, then preview.", padding=8, wraplength=880)
        self.summary.pack(fill="x")
        self.preview = editor.text_area(preview_page)
        self.preview.configure(state="disabled")
        bar = ttk.Frame(self, padding=8)
        bar.pack(fill="x")
        ttk.Button(bar, text="Randomize everything", command=self.randomize).pack(side="left")
        ttk.Button(bar, text="Random name", command=self.random_name).pack(side="left", padx=6)
        ttk.Button(bar, text="Preview JSON", command=self.build_preview).pack(side="left")
        ttk.Button(bar, text="Create in world", command=self.create).pack(side="right")
        self.notice = ttk.Label(self, text="", padding=(8, 0, 8, 8), wraplength=900)
        self.notice.pack(fill="x")
        extra = ttk.Frame(self, padding=(8, 0, 8, 6))
        extra.pack(fill="x")
        ttk.Button(extra, text="Reset power to calculated", command=self.reset_power).pack(side="left")
        ttk.Button(extra, text="Edit loaded local profile", command=self.edit_loaded_profile).pack(side="left", padx=6)
        ttk.Button(extra, text="Save edited profile", command=self.save_edited_profile).pack(side="right")
        self.power_note = ttk.Label(self, text="", padding=(8, 0, 8, 6))
        self.power_note.pack(fill="x")
        for key in ("talent", "path", "level", "game_count", "top_hours"):
            self.fields[key][0].trace_add("write", self.update_power)
        for var in self.personalities.values():
            var.trace_add("write", self.update_power)
        self.fields["score"][0].trace_add("write", self.manual_power)
        self.fields["realm_index"][0].trace_add("write", self.realm_changed)
        self.sect_preview=ttk.Label(self,text="",wraplength=900,padding=(8,0,8,6));self.sect_preview.pack(fill="x")
        self.fields["sect"][0].trace_add("write",self.update_sect_preview)
        self.randomize()

    def update_sect_preview(self,*_):
        selected=next((r for r in self.sect_choices if r["name"]==self.fields["sect"][0].get()),None)
        self.sect_preview.configure(text=(f"Members: {selected['members']} · Master: {selected['master']} · Elders: {selected['elders']}" if selected else "This old sect is unlisted. Choose one of this world's twenty sects before saving."))

    def reload_sect_choices(self):
        self.sect_choices=storage.sect_catalog(self.editor.cache)
        self.sect_widget.configure(values=[r["name"] for r in self.sect_choices])
        if self.fields["sect"][0].get() not in {r["name"] for r in self.sect_choices}:self.fields["sect"][0].set(self.sect_choices[0]["name"])
        self.update_sect_preview()

    def randomize(self):
        self.editing_profile = None
        settings = generator.random_local_settings()
        settings["sect"]=__import__("random").choice(self.sect_choices)["name"]
        self.fill_settings(settings, automatic=True)
        self.notice.configure(text="Random values ready. Edit any field, then preview or create.")

    def fill_settings(self, settings, automatic=False):
        self._syncing_power = True
        for key, (var, kind) in self.fields.items():
            value = settings.get(key, 0)
            var.set(f"{value}: {gamedata.REALMS[value][1]}" if kind == "realm" else str(value))
        for name, var in self.personalities.items():
            var.set(name in settings["personalities"])
        self._power_offset = settings["score"] - generator.local_power_base(settings) if automatic else settings.get("power_offset", settings["score"] - generator.local_power_base(settings))
        self._syncing_power = False
        self.update_power()
        self.preview_data = None
        self.preview_settings = None

    def realm_changed(self, *_):
        if self._syncing_power:
            return
        try:
            realm = int(self.fields["realm_index"][0].get().split(":")[0])
            low, high = generator.realm_power_range(realm)
            self._power_offset = low - generator.local_power_base(self.power_inputs())
            self.update_power()
            self.notice.configure(text=f"Selected realm power range: {low:,}–{high:,}. Set to the minimum; you can still enter a manual score.")
        except (ValueError, KeyError, StopIteration):
            pass

    def power_inputs(self):
        return {key: int(self.fields[key][0].get()) if key in ("level", "game_count", "top_hours") else self.fields[key][0].get()
                for key in ("talent", "path", "level", "game_count", "top_hours")} | {"personalities": [name for name, var in self.personalities.items() if var.get()]}

    def update_power(self, *_):
        if self._syncing_power:
            return
        try:
            calculated = generator.local_power_base(self.power_inputs())
            score = max(0, calculated + self._power_offset)
        except (ValueError, KeyError, StopIteration):
            return  # Let users finish typing a numeric field before recalculating.
        self._syncing_power = True
        self.fields["score"][0].set(str(score))
        self._syncing_power = False
        self.power_note.configure(text=f"Calculated power {calculated:,} + manual adjustment {self._power_offset:+,} = {score:,}")

    def manual_power(self, *_):
        if not self._syncing_power:
            try:
                self._power_offset = int(self.fields["score"][0].get()) - generator.local_power_base(self.power_inputs())
                calculated = generator.local_power_base(self.power_inputs())
                self.power_note.configure(text=f"Calculated power {calculated:,} + manual adjustment {self._power_offset:+,} = {self.fields['score'][0].get()}")
            except (ValueError, KeyError, StopIteration):
                pass

    def reset_power(self):
        self._power_offset = 0
        self.update_power()

    def edit_loaded_profile(self):
        try:
            if self.editor.profile is None or "offline" not in self.editor.profile.data:
                raise ValueError("Load a local profile with Load / reload first. Steam power is derived from Steam inputs.")
            if not self.editor.discard():
                return
            self.editing_profile = storage.EditableProfile(self.editor.profile.path)
            data = self.editing_profile.data
            settings = copy.deepcopy(data["offline"]["character"])
            settings["spirit_stones"] = data.get("wallet", {}).get("spirit_stones", 0)
            incarnation = data.get("life", {}).get("incarnation")
            if incarnation:
                for key in ("name", "gender", "sect", "element", "talent", "age", "birth_year"):
                    settings[key] = incarnation[key]
            settings['sect'] = data.get('sect_override', settings['sect'])
            state = data.get("realm_state", {})
            if state.get("realm_index") is not None:
                settings["realm_index"] = state["realm_index"]
            if state.get("born_realm") is not None:
                settings["born_realm"] = state["born_realm"]
            if state.get("vitals"):
                settings.update(age=state["vitals"]["age"], birth_year=state["vitals"]["birth_year"], lifespan=state["vitals"]["base_lifespan"])
            if data.get('calendar'):
                calendar=data['calendar']
                settings['age']=data.get('life',{}).get('dead',{}).get('age') if data.get('life',{}).get('dead') else max(0,int((storage.world_state(self.editor.cache)['day']-calendar['birth_day'])//storage.DAYS_PER_YEAR))
                settings['birth_year']=int(calendar['birth_day'])//storage.DAYS_PER_YEAR
            settings["score"] = generator.local_power_score(settings)
            personalities = [p for p in gamedata.PERSONALITIES if p["name"] in settings["personalities"]]
            path = next(p for p in gamedata.PATHS if p["name"] == settings["path"])
            settings["reputation"] = generator.roll_reputation(settings["seed"], generator.local_profile_info(settings), personalities, path,
                                                               data.get("duel_reputation", {}).get("points", 0))["points"]
            pav = data.get("pavilion", {})
            settings["sect_points"] = max(0, max(settings["missions"] * gamedata.SECT_POINTS_PER_MISSION, pav.get("earned", 0)) + pav.get("bonus", 0) - pav.get("spent", 0))
            self.original_edit_settings = copy.deepcopy(settings)
            self.fill_settings(settings)
            self.notice.configure(text="Editing loaded local character. Save edited profile preserves inventory/history and creates a backup. Create in world still creates a new character.")
            self.pages.select(0)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            messagebox.showerror("Cannot edit character", str(exc))

    def save_edited_profile(self):
        try:
            if self.editing_profile is None:
                raise ValueError("Click Edit loaded local profile first, or Create in world for a new character.")
            settings = self.settings()
            if settings["seed"] != self.editing_profile.steamid:
                raise ValueError("An existing profile's local ID cannot be changed.")
            data = copy.deepcopy(self.editing_profile.data)
            data["offline"].update(character=settings, info=generator.local_profile_info(settings))
            data.setdefault("wallet", {})["spirit_stones"] = settings["spirit_stones"]
            old = self.original_edit_settings
            state = data.setdefault("realm_state", {})
            for key in ("realm_index", "born_realm"):
                if settings[key] != old[key]:
                    state[key] = settings[key]
            if any(settings[k] != old[k] for k in ("age", "birth_year", "lifespan")):
                state["vitals"] = {"age": settings["age"], "birth_year": settings["birth_year"], "base_lifespan": settings["lifespan"]}
            inc = data.get("life", {}).get("incarnation")
            if inc:
                for key in ("name", "gender", "sect", "element", "talent", "age", "birth_year"):
                    inc[key] = settings[key]
                if settings["element"] != old["element"] or settings["path"] != old["path"]:
                    inc["arsenal"] = generator.build_arsenal(settings["seed"], settings["element"], settings["path"])
            if settings["reputation"] != old["reputation"]:
                personalities = [p for p in gamedata.PERSONALITIES if p["name"] in settings["personalities"]]
                path = next(p for p in gamedata.PATHS if p["name"] == settings["path"])
                base_rep = generator.roll_reputation(settings["seed"], generator.local_profile_info(settings), personalities, path)["base_points"]
                data.setdefault("duel_reputation", {"history": []})["points"] = settings["reputation"] - base_rep
            if settings["sect_points"] != old["sect_points"]:
                pav = data["pavilion"]
                earned = max(settings["missions"] * gamedata.SECT_POINTS_PER_MISSION, pav.get("earned", 0))
                pav["bonus"] = settings["sect_points"] - earned + pav.get("spent", 0)
            data["sect_override"]=settings["sect"]
            backup = self.editing_profile.save(data)
            self.original_edit_settings = copy.deepcopy(settings)
            # Reload the main editor to prevent its old snapshot overwriting this edit.
            self.editor.profile = storage.EditableProfile(self.editing_profile.path)
            self.editor.staged = copy.deepcopy(data)
            self.editor.populate()
            self.notice.configure(text=f"Saved character edits. Backup: {backup.name}. Look up the profile again in the game.")
        except (OSError, ValueError, KeyError, TypeError) as exc:
            messagebox.showerror("Cannot save character", str(exc))

    def random_name(self):
        import random
        self.fields["name"][0].set(generator.make_name(random.SystemRandom(), self.fields["gender"][0].get()))

    def settings(self):
        settings = {}
        for key, (var, kind) in self.fields.items():
            value = var.get().strip()
            try:
                settings[key] = int(value.split(":")[0]) if kind == "realm" else int(value) if kind == "int" else float(value) if kind == "float" else value
            except ValueError:
                raise ValueError(f"Invalid value for {key}.")
        settings['birth_year']=int(storage.world_state(self.editor.cache)['day'])//storage.DAYS_PER_YEAR-settings['age']
        self.fields['birth_year'][0].set(str(settings['birth_year']))
        settings["personalities"] = [name for name, var in self.personalities.items() if var.get()]
        settings["power_offset"] = self._power_offset
        generator.validate_local_settings(settings)
        if not storage.chartered_sect(settings["sect"],self.editor.cache):raise ValueError("Choose one of the twenty registered sects from the dropdown.")
        return settings

    def build_preview(self):
        try:
            settings = self.settings()
            data = generator.make_local_profile(settings)
            self.preview_data = data
            self.preview_settings = copy.deepcopy(settings)
            self.preview.configure(state="normal")
            self.editor.put(self.preview, json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False))
            self.preview.configure(state="disabled")
            eligible = generator.get_realm(settings["score"])[1][1]
            self.summary.configure(text=f"{settings['name']} · {settings['sect']} · {settings['element']} · {settings['score']:,} power · {gamedata.REALMS[settings['realm_index']][1]}\nAge {settings['age']:,}, born year {settings['birth_year']:,}, lifespan {settings['lifespan']:,}. Power qualifies for: {eligible}. World profile: {data['steamid']}")
            self.pages.select(1)
            return True
        except (ValueError, TypeError, KeyError) as exc:
            messagebox.showerror("Cannot generate profile", str(exc))
            return False

    def create(self):
        try:
            if self.preview_data is None or self.settings() != self.preview_settings:
                if not self.build_preview():
                    return
            path = generator.create_local_profile(self.editor.cache, self.preview_data)
            name = self.preview_data["offline"]["character"]["name"]
            self.editor.refresh()
            self.editor.choice.set(path.name)
            self.notice.configure(text=f"Created {path.name}. In the updated game, look up: {name} (or local:{self.preview_data['steamid']}).")
            self.editor.status.configure(text=f"Created local profile {name}. Select Load / reload to edit its inventory and other saved values.")
            messagebox.showinfo("Profile created", f"Saved in world.db:\n{path.name}\n\nIn the updated game choose Continue offline, then look up:\n{name}\n\nUnique lookup: local:{self.preview_data['steamid']}")
        except (OSError, ValueError, TypeError, KeyError) as exc:
            messagebox.showerror("Cannot create profile", str(exc))


# ============================================================================
# Developer tools — profile editor window
# ============================================================================

class DeveloperEditor(tk.Toplevel):
    def __init__(self, cache, master=None):
        self._owned_root = None
        if master is None:
            self._owned_root = tk.Tk()
            self._owned_root.withdraw()
            master = self._owned_root
        super().__init__(master)
        set_game_window_icon(self)
        self.title("Steam Cultivator — Developer Save Editor")
        self.geometry("1000x790")
        self.minsize(800, 650)
        self.cache = Path(cache)
        self.profile = None
        self.fields = {}
        self.protocol("WM_DELETE_WINDOW", self.close)
        top = ttk.Frame(self, padding=10)
        top.pack(fill="x")
        self.choice = ttk.Combobox(top, state="readonly", width=36)
        self.choice.pack(side="left", padx=(0, 8))
        ttk.Button(top, text="Load / reload", command=self.load).pack(side="left")
        ttk.Button(top, text="Choose cache folder", command=self.choose).pack(side="left", padx=8)
        self.location = ttk.Label(self, text=str(self.cache), padding=(10, 0))
        self.location.pack(fill="x")
        notice = ("Close the game before saving. Restart it and look up the profile again to see changes."
                  if self._owned_root is not None else
                  "Gameplay is paused while this window is open. Look up the profile again after editing.")
        ttk.Label(self, text=notice, padding=10).pack(fill="x")
        self.tabs = ttk.Notebook(self)
        self.tabs.pack(fill="both", expand=True, padx=10)
        self.form = ttk.Frame(self.tabs, padding=12)
        self.tabs.add(self.form, text="Profile values")
        self.make_form()
        raw_frame = ttk.Frame(self.tabs)
        self.tabs.add(raw_frame, text="JSON (advanced)")
        ttk.Label(raw_frame, text="JSON edits are applied only with 'Apply JSON to form'. Save uses the form and its staged JSON.", padding=8).pack(fill="x")
        self.raw = self.text_area(raw_frame)
        ttk.Button(raw_frame, text="Apply JSON to form", command=self.apply_raw).pack(pady=6)
        diff_frame = ttk.Frame(self.tabs)
        self.tabs.add(diff_frame, text="Review changes")
        self.diff = self.text_area(diff_frame)
        self.creator = OfflineCreatorTab(self.tabs, self)
        self.tabs.add(self.creator, text="Generate offline profile")
        bottom = ttk.Frame(self, padding=10)
        bottom.pack(fill="x")
        for label, command in (("Review / stage form", self.review), ("Save with backup", self.save), ("Restore backup…", self.restore)):
            ttk.Button(bottom, text=label, command=command).pack(side="left", padx=(0, 8))
        self.status = ttk.Label(self, text="Select a profile and load it.", padding=(10, 0, 10, 10))
        self.status.pack(fill="x")
        self.refresh()

    def text_area(self, parent):
        frame = ttk.Frame(parent)
        frame.pack(fill="both", expand=True)
        text = tk.Text(frame, wrap="none", undo=True, font=("Consolas", 10))
        y = ttk.Scrollbar(frame, command=text.yview)
        x = ttk.Scrollbar(frame, orient="horizontal", command=text.xview)
        text.configure(yscrollcommand=y.set, xscrollcommand=x.set)
        y.pack(side="right", fill="y")
        x.pack(side="bottom", fill="x")
        text.pack(fill="both", expand=True)
        return text

    def make_form(self):
        specs = [("realm_state.realm_index", "Current realm", "realm"),
                 ("realm_state.born_realm", "Born realm (affects age rules)", "realm"),
                 ("realm_state.lifespan_lost", "Years of lifespan lost", "int"),
                 ("pavilion.bonus", "Sect-point adjustment (added to earned minus spent)", "int"),
                 ("pavilion.earned", "Highest sect points credited", "int"),
                 ("pavilion.spent", "Sect points spent", "int"),
                 ("duel_reputation.points", "Reputation adjustment (added to base reputation)", "int"),
                 ("wallet.spirit_stones", "Spirit Stones", "int")]
        for row, (path, label, kind) in enumerate(specs):
            ttk.Label(self.form, text=label).grid(row=row, column=0, sticky="w", pady=5)
            var = tk.StringVar()
            widget = (ttk.Combobox(self.form, textvariable=var, state="readonly", values=["Automatic / unset"] + [f"{i}: {r[1]}" for i, r in enumerate(gamedata.REALMS)]) if kind == "realm" else ttk.Entry(self.form, textvariable=var))
            widget.grid(row=row, column=1, sticky="ew", padx=10)
            self.fields[path] = (var, kind)
        self.form.columnconfigure(1, weight=1)
        self.clear_break = tk.BooleanVar()
        self.clear_rebirth = tk.BooleanVar()
        ttk.Checkbutton(self.form, text="Clear failed-breakthrough cooldown", variable=self.clear_break).grid(row=8, column=0, columnspan=2, sticky="w", pady=4)
        ttk.Checkbutton(self.form, text="Clear rebirth-roll cooldown", variable=self.clear_rebirth).grid(row=9, column=0, columnspan=2, sticky="w", pady=4)
        ttk.Label(self.form, text="Treasures: one exact name per line (catalog below; keep blank for none)").grid(row=10, column=0, columnspan=2, sticky="w", pady=(10, 0))
        self.treasures = tk.Text(self.form, height=5, width=50)
        self.treasures.grid(row=11, column=0, columnspan=2, sticky="nsew")
        catalog = sorted({t for tier in gamedata.ALL_TREASURES for t in tier} | set(gamedata.PAVILION_TREASURE_RANKS))
        self.catalog = ttk.Combobox(self.form, values=catalog, state="readonly", width=48)
        self.catalog.grid(row=12, column=0, sticky="ew", pady=6)
        ttk.Button(self.form, text="Add treasure", command=lambda: self.add_treasure()).grid(row=12, column=1, sticky="w")
        ttk.Label(self.form, text="Pavilion items: JSON object of item IDs to positive counts ({} for none)").grid(row=13, column=0, columnspan=2, sticky="w")
        self.items = tk.Text(self.form, height=4, width=50)
        self.items.grid(row=14, column=0, columnspan=2, sticky="nsew")
        ids = ", ".join(i["id"] for i in gamedata.PAVILION_ITEMS if i["kind"] != "Treasure")
        ttk.Label(self.form, text=ids, wraplength=880).grid(row=15, column=0, columnspan=2, sticky="w", pady=6)

    def add_treasure(self):
        value = self.catalog.get()
        existing = self.treasures.get("1.0", "end").splitlines()
        if value and value not in existing:
            self.put(self.treasures, "\n".join([s for s in existing if s] + [value]))

    @staticmethod
    def put(widget, text):
        widget.delete("1.0", "end")
        widget.insert("1.0", text)

    def refresh(self):
        self.choice["values"] = [sid+".profile.json" for sid in storage.profile_ids(self.cache)]
        if self.choice["values"]:
            self.choice.current(0)
        else:
            self.choice.set("")

    def dirty(self):
        if self.profile is None:
            return False
        try:
            return self.gather() != self.profile.data or storage.decode_profile_json(self.raw.get("1.0", "end")) != self.staged
        except (ValueError, TypeError, KeyError):
            return True

    def discard(self):
        return not self.dirty() or messagebox.askyesno("Unsaved changes", "Discard your unsaved changes?")

    def choose(self):
        if not self.discard():
            return
        folder = filedialog.askdirectory(initialdir=self.cache)
        if folder:
            self.cache = Path(folder)
            self.creator.reload_sect_choices()
            self.location.configure(text=folder)
            self.profile = None
            self.refresh()
            self.status.configure(text="Select a profile and load it.")

    def load(self):
        if not self.discard():
            return
        try:
            if not self.choice.get():
                raise ValueError("No profiles found in this world database.")
            profile = storage.EditableProfile(self.cache / self.choice.get())
            self.profile = profile
            self.staged = copy.deepcopy(profile.data)
            self.populate()
            self.status.configure(text=f"Loaded {profile.path.name}. No changes saved.")
        except (OSError, ValueError, TypeError) as exc:
            messagebox.showerror("Cannot load profile", str(exc))

    def populate(self):
        for path, (var, kind) in self.fields.items():
            section, key = path.split(".")
            value = self.staged.get(section, {}).get(key, None if kind == "realm" else 0)
            var.set(("Automatic / unset" if value is None else f"{value}: {gamedata.REALMS[value][1]}") if kind == "realm" else str(value))
        self.put(self.treasures, "\n".join(self.staged.get("inventory", {}).get("treasures", [])))
        self.put(self.items, json.dumps(self.staged.get("pavilion", {}).get("items", {}), indent=2))
        self.clear_break.set(False)
        self.clear_rebirth.set(False)
        self.write_raw()

    def write_raw(self):
        self.put(self.raw, json.dumps(self.staged, indent=2, ensure_ascii=False))

    def gather(self):
        if self.profile is None:
            raise ValueError("Load a profile first.")
        data = copy.deepcopy(self.staged)
        for path, (var, kind) in self.fields.items():
            section, key = path.split(".")
            value = (None if var.get() == "Automatic / unset" else int(var.get().split(":")[0])) if kind == "realm" else int(var.get())
            old = self.staged.get(section, {}).get(key, None if kind == "realm" else 0)
            if value != old:
                defaults = {"pavilion": {"items": {}, "spent": 0, "earned": 0, "bonus": 0, "history": []}, "duel_reputation": {"points": 0, "history": []}}
                data.setdefault(section, copy.deepcopy(defaults.get(section, {})))[key] = value
        new_realm = data.get("realm_state", {}).get("realm_index")
        if "offline" in data and new_realm is not None and new_realm != self.staged.get("realm_state", {}).get("realm_index"):
            character = data["offline"]["character"]
            character["realm_index"] = new_realm
            character["score"] = generator.realm_power_range(new_realm)[0]
            character["power_offset"] = character["score"] - generator.local_power_base(character)
        for section, key, flag in (("realm_state", "last_failed", self.clear_break), ("life", "last_roll", self.clear_rebirth)):
            if flag.get():
                data.setdefault(section, {})[key] = None
        treasures = [s.strip() for s in self.treasures.get("1.0", "end").splitlines() if s.strip()]
        if treasures != self.staged.get("inventory", {}).get("treasures", []):
            data.setdefault("inventory", {"history": []})["treasures"] = treasures
        items = storage.decode_profile_json(self.items.get("1.0", "end"))
        if items != self.staged.get("pavilion", {}).get("items", {}):
            data.setdefault("pavilion", {"spent": 0, "earned": 0, "bonus": 0, "history": []})["items"] = items
        storage.validate_profile_data(data, self.profile.steamid)
        return data

    def apply_raw(self):
        try:
            if self.profile is None:
                raise ValueError("Load a profile first.")
            data = storage.decode_profile_json(self.raw.get("1.0", "end"))
            storage.validate_profile_data(data, self.profile.steamid)
            if not messagebox.askyesno("Apply JSON", "Replace the current form values with this JSON?"):
                return
            self.staged = data
            self.populate()
            self.status.configure(text="JSON applied to form. Not saved yet.")
        except (ValueError, TypeError, KeyError) as exc:
            messagebox.showerror("Invalid JSON", str(exc))

    def prepare(self):
        if self.profile is None:
            raise ValueError("Load a profile first.")
        if storage.decode_profile_json(self.raw.get("1.0", "end")) != self.staged:
            raise ValueError("Apply your JSON edits to the form first, or reload to discard them.")
        return self.gather()

    def review(self):
        try:
            self.staged = self.prepare()
            self.populate()
            before = json.dumps(self.profile.data, indent=2, ensure_ascii=False).splitlines(True)
            after = json.dumps(self.staged, indent=2, ensure_ascii=False).splitlines(True)
            self.put(self.diff, "".join(difflib.unified_diff(before, after, fromfile="Saved", tofile="Staged")) or "No changes.")
            self.tabs.select(2)
        except (ValueError, TypeError, KeyError) as exc:
            messagebox.showerror("Cannot review", str(exc))

    def save(self):
        try:
            data = self.prepare()
            if data == self.profile.data:
                self.status.configure(text="No changes to save.")
                return
            backup = self.profile.save(data)
            self.staged = copy.deepcopy(data)
            self.populate()
            self.status.configure(text=f"Saved. Backup: {backup.name}")
        except (OSError, ValueError, TypeError, KeyError) as exc:
            messagebox.showerror("Cannot save", str(exc))

    def restore(self):
        if self.profile is None:
            messagebox.showerror("Restore", "Load a profile first.")
            return
        path = filedialog.askopenfilename(initialdir=self.cache / "devtools_backups", filetypes=[("World backups", "*.db"), ("Legacy backups", "*.bak")])
        if not path or not self.discard():
            return
        try:
            if Path(path).suffix == '.db':
                with contextlib.closing(storage.sqlite3.connect(Path(path))) as backup:
                    row=backup.execute('SELECT data FROM profiles WHERE id=?',(self.profile.steamid,)).fetchone()
                    if row is None: raise ValueError('This backup does not contain the selected profile.')
                    data=json.loads(row[0])
            else:
                data = storage.decode_profile_json(Path(path).read_bytes())
            storage.validate_profile_data(data, self.profile.steamid)
            self.staged = data
            self.populate()
            self.status.configure(text="Backup staged. Review and save to restore it; current save will be backed up.")
        except (OSError, ValueError, TypeError, KeyError) as exc:
            messagebox.showerror("Cannot restore", str(exc))

    def close(self):
        if self.discard():
            self.destroy()


    def destroy(self):
        owner = self._owned_root
        self._owned_root = None
        super().destroy()
        if owner is not None:
            owner.destroy()



# ============================================================================
# Game GUI — controller, views, and application
# ============================================================================

# ---------------------------------------------------------------------------
# Controller: everything the window does, without any window code
# ---------------------------------------------------------------------------
class Controller:
    """Holds the Steam key, the in-memory profile cache and which cultivator was looked up
    last (for the pavilion). Every method either returns plain data or raises logs.SteamError
    with a message that is fit to show to the user."""

    def __init__(self, key):
        self.key = key or ""
        self.profiles = {}
        self.session = {}
        self.busy = threading.Lock()
        logs.RUN_LOG.secret = key

    # -- running one command with logging --------------------------------------------------
    def _run(self, command, fn):
        if not self.busy.acquire(blocking=False):
            raise logs.SteamError("Please wait, the previous action is still running.")
        logs.RUN_LOG.begin(command)
        status = "ok"
        try:
            with contextlib.redirect_stdout(io.StringIO()):     # nothing may print into a window
                return fn()
        except logs.SteamError as e:
            status = f"error: {e}"
            raise
        except BaseException as e:
            status = f"crashed: {type(e).__name__}: {e}"
            raise
        finally:
            logs.RUN_LOG.finish(status)
            self.busy.release()

    # -- the cultivator tab ----------------------------------------------------------------
    def lookup(self, text, refresh=False):
        text = (text or "").strip()
        if text.lower().startswith("refresh "):
            refresh, text = True, text[len("refresh "):].strip()
        if not text:
            raise logs.SteamError("Type a Steam profile URL, custom name or SteamID64 first.")

        def work():
            steamid = steam_api.resolve_steamid(text, self.key, refresh)
            return self._view_data(steamid, refresh)
        return self._run(("refresh lookup of " if refresh else "lookup of ") + text, work)

    def sect(self):
        def work():
            sid = self.selected()
            if not sid:
                raise logs.SteamError("Look up a cultivator first.")
            c = generator.build_cultivator(sid, self.key, self.profiles)[3]
            return {"steamid": sid, "c": c, "sect": progress.sect_board(sid, c)}
        return self._run("sect board", work)

    def sect_mission(self, offer_id):
        def work():
            sid = self.selected()
            if not sid:
                raise logs.SteamError("Look up a cultivator first.")
            c = generator.build_cultivator(sid, self.key, self.profiles)[3]
            result = progress.perform_sect_mission(sid, c, offer_id)
            return {"result": result, "data": self._view_data(sid)}
        return self._run("sect mission", work)

    def create_random_local(self,sect_id=None):
        """Player-facing creation: no editable settings and no Steam calls."""
        if self.key:
            raise logs.SteamError("Enter offline mode to create a random local cultivator.")
        def work():
            for _ in range(30):
                settings = generator.random_local_settings(player_start=True)
                if sect_id:
                    selected=next((r for r in storage.sect_names() if r["id"]==sect_id),None)
                    if not selected:raise logs.SteamError("Choose a registered sect.")
                    settings["sect"]=selected["name"]
                settings["power_offset"] = settings["score"] - generator.local_power_base(settings)
                try:
                    data = generator.make_local_profile(settings)
                    data["offline"]["origin"] = "player_random"
                    data["activity"][-1]["summary"] = "Began a randomly generated local cultivation journey."
                    generator.create_local_profile(storage.CACHE_DIR, data)
                except FileExistsError:
                    continue
                except ValueError as exc:
                    if "name is already in use" in str(exc):
                        continue
                    raise
                return self._view_data(settings["seed"])
            raise logs.SteamError("Could not find a unique local name. Please try again.")
        return self._run("create random local cultivator", work)

    def _view_data(self, steamid, refresh=False):
        """Loads a cultivator, makes it the selected one and gathers what the card shows.
        (Called from inside _run, so it takes no lock itself.)"""
        info, friend_ids, note, c = generator.build_cultivator(steamid, self.key, self.profiles, refresh)
        self.session["latest"] = steamid
        storage.add_recent(steamid, c["name"])
        friend = steam_api.resolve_friend(c, friend_ids, self.key)
        out = {"steamid": steamid, "info": info, "c": c, "friend": friend, "note": note,
               "story": generator.generate_story(c, info, friend) if friend else None,
               "death": generator.describe_death(c, info, friend) if c["death"] else None}
        out["view"] = cultivator_view(c, info)
        return out

    # -- breakthrough ----------------------------------------------------------------------
    def breakthrough_info(self):
        """What the breakthrough dialog shows for the selected cultivator."""
        def work():
            steamid, c = progress.breakthrough_target(self.key, self.profiles, self.session)
            return breakthrough_view(c)
        return self._run("breakthrough", work)

    def breakthrough(self, use_pill=False):
        """Attempts the breakthrough. Returns {'result', 'info', 'data'}: what happened, the
        dialog data afterwards and the refreshed card data."""
        def work():
            steamid, c = progress.breakthrough_target(self.key, self.profiles, self.session)
            result = progress.attempt_breakthrough(steamid, c, use_pill)
            data = self._view_data(steamid)
            return {"result": result, "info": breakthrough_view(data["c"]), "data": data}
        return self._run("breakthrough attempt" + (" (with a pill)" if use_pill else ""), work)

    # -- adventure -------------------------------------------------------------------------
    def adventure(self):
        """Sends the selected cultivator on an adventure (a dead one gets the rebirth roll
        instead). Returns {'result': what happened, 'data': the refreshed card data}."""
        def work():
            steamid = self.selected()
            if not steamid:
                raise logs.SteamError("Look up a cultivator first.")
            info, friend_ids, _, c = generator.build_cultivator(steamid, self.key, self.profiles)
            result = progress.perform_adventure(steamid, c, info, friend_ids, self.key)
            return {"result": result, "data": self._view_data(steamid)}
        return self._run("adventure", work)

    # -- history ---------------------------------------------------------------------------
    def history(self):
        """{'name', 'entries'} for the selected cultivator; each entry has when/kind/text."""
        def work():
            steamid, c = progress.breakthrough_target(self.key, self.profiles, self.session)
            entries = [dict(e, when=e.get("when", "Before calendar synchronization")) for e in storage.history_entries(steamid, 100)]
            return {"name": c["name"], "entries": entries}
        return self._run("history", work)

    # -- the pavilion tab ------------------------------------------------------------------
    def selected(self):
        """The SteamID of the latest cultivator, or None."""
        return self.session.get("latest")

    def shop(self):
        """{'steamid', 'c', 'rows'} for the pavilion; raises SteamError if nobody is selected
        or the cultivator is dead."""
        def work():
            steamid, c = pavilion_shop.pavilion_target(self.key, self.profiles, self.session)
            return {"steamid": steamid, "c": c, "rows": shop_rows(c), "sells": pavilion_shop.sell_rows(c)}
        return self._run("pavilion", work)

    def sell(self, number):
        """Sells treasure number `number` (as listed in the 'sells' rows) for half its value.
        Returns the shop data plus 'sold' (the row sold)."""
        def work():
            steamid, c = pavilion_shop.pavilion_target(self.key, self.profiles, self.session, "sell")
            row = pavilion_shop.sell_treasure(steamid, c, number)
            return {"steamid": steamid, "c": c, "rows": shop_rows(c), "sells": pavilion_shop.sell_rows(c),
                    "sold": row}
        return self._run(f"sell {number}", work)

    def buy(self, number):
        """Buys item number `number` (as listed in shop rows). Returns the receipt dict."""
        def work():
            steamid, c = pavilion_shop.pavilion_target(self.key, self.profiles, self.session)
            item = pavilion_shop.buy_pavilion_item(steamid, c, number)
            return {"item": item, "c": c, "rows": shop_rows(c), "steamid": steamid,
                    "sells": pavilion_shop.sell_rows(c),
                    "goods": generator.describe_goods(c["pavilion"]["items"]) or "nothing yet",
                    "treasures": generator.describe_treasures(generator.treasures_of(c)) or "none"}
        return self._run(f"pavilion {number}", work)

    # -- the duel tab ----------------------------------------------------------------------
    def duel(self, text1, text2, mode="Competitive"):
        text1, text2 = (text1 or "").strip(), (text2 or "").strip()
        if not text1 or not text2:
            raise logs.SteamError("Type both profiles to make them duel.")

        def work():
            ids = [steam_api.resolve_steamid(t, self.key) for t in (text1, text2)]
            d = combat.perform_battle(ids, self.key, self.profiles,mode=mode)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                display.print_battle(d["a"], d["b"], d["info_a"], d["info_b"], d["result"],
                                d["story"], d["loot"], d["change"])
            d["ids"] = ids
            d["report"] = buf.getvalue()
            d["winner_side"] = "a" if d["result"]["winner"] is d["a"] else "b"
            return d
        return self._run(f"mocb {text1} {text2}", work)

    def recent_list(self):
        """Up to 5 recently looked-up cultivators for building teams, newest first. The one
        that is selected right now is left out."""
        current = self.selected()
        return [e for e in storage.read_recent() if e["steamid"] != current][:5]

    def team_battle(self, texts_a, texts_b):
        """A team battle between two teams of profile texts (2 vs 2 or 3 vs 3). Returns the
        battle data (see teambattle.perform_team_battle) plus 'report', the printed report."""
        texts_a = [(t or "").strip() for t in texts_a]
        texts_b = [(t or "").strip() for t in texts_b]
        if "" in texts_a + texts_b:
            raise logs.SteamError("Fill in every fighter slot of both teams first.")
        teambattle.check_teams(texts_a, texts_b)

        def work():
            ids_a = [steam_api.resolve_steamid(t, self.key) for t in texts_a]
            ids_b = [steam_api.resolve_steamid(t, self.key) for t in texts_b]
            d = teambattle.perform_team_battle(ids_a, ids_b, self.key, self.profiles)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                display.print_team_battle(d)
            d["report"] = buf.getvalue()
            return d
        return self._run(f"team battle {len(texts_a)} vs {len(texts_b)}", work)

    # -- the log tab -----------------------------------------------------------------------
    def log_text(self):
        """Today's log file, or a note if there is none yet."""
        path = os.path.join(logs.LOG_DIR, "steam_cultivator_"
                            + logs.stamp(time.time())[:10] + ".log")
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
    ranks = gamedata.REPUTATION_RANKS
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
            ("Gender", c["gender"].capitalize()),
            ("Talent", f"{t['name']} (power {t['power']:+d})"),
            ("Traits", ", ".join(display.personality_label(p) for p in c["personalities"])
             if c["personalities"] else "none (a quiet temperament)"),
            ("Personality", ", ".join(c.get("world_personalities", []))),
            ("Path", generator.path_label(c["path"])),
            ("Reputation", f"{rep['rank']} ({rep['points']:,} points)")]
    if c.get("injury"):
        rows.append(("Injury", c["injury"]["cause"]+" · power reduced 20% · recovering until "+storage.calendar_text(c["injury"]["until_day"])))
    if rep["bonuses"]:
        rows.append(("Fame boosts", ", ".join(f"{n} {a:+d}" for n, a in rep["bonuses"])))
    rows += [("Death risk", f"{c['death_chance'] * 100:g}%"),
             ("Affinity", c["element"]),
             ("Matchups", f"strong vs {', '.join(gamedata.ELEMENT_BEATS.get(c['element'], []))}; "
                          f"weak vs {', '.join(combat.element_weak_to(c['element']))}"),
             ("Signature", c["technique"]),
             ("Arsenal", generator.arsenal_text(c))]
    owned = generator.treasures_of(c)
    rows.append(("Treasures", generator.describe_treasures(owned) if owned
                 else "none (robbed of everything)"))
    events = [e for e in c.get("inventory_history", []) if e.get("type") != "start"]
    if events:
        rows.append(("Recent", storage.describe_event(events[-1])))
    if info["achievements_hidden"]:
        rows.append(("Missions", "0 (Steam is hiding your achievements)"))
    else:
        n = c["missions"]
        rows.append(("Missions", f"{n:,} sect mission{'' if n == 1 else 's'} completed"))
        new = info.get("achievements_new")
        if new and new > 0:
            rows.append(("Since last", f"+{new:,} new mission{'' if new == 1 else 's'} "
                                       f"(+{new * gamedata.SECT_POINTS_PER_MISSION:,} sect points) "
                                       f"since your last visit"))
    rows.append(("Sect points", generator.sect_points_text(c)))
    rows.append(("Spirit Stones", f"{c.get('spirit_stones', 0):,}"))
    if c.get("incarnation"):
        rows.append(("Rebirth", f"Reborn into a new body (incarnation {c['incarnation']})"))
    goods = generator.describe_goods(c.get("pavilion", {}).get("items", {}))
    if goods:
        rows.append(("Pavilion", goods))
    lost = c.get("lifespan_lost", 0)
    rows.append(("Lifespan", f"{c['lifespan']:,} years" + (" (cut short)" if c["death"] else "")
                 + (f" ({lost:,} lost to injuries or failed breakthroughs)" if lost else "")))
    rows.append(("Born", (storage.calendar_text(c['birth_day']) if 'birth_day' in c else f"Year {c['birth_year']}") + " of the Heavenly Calendar"))
    if c.get("age") is not None:
        yrs = c.get("account_years")
        rows.append(("Age", f"{c['age']:,} years" + (" at death" if c["death"] else "")
                     + (f" ({yrs:.0f}-year-old account)" if yrs is not None else "")))
    if c["death"]:
        rows.append(("Died", ("Before calendar synchronization" if c['death'].get('legacy') else
                              storage.calendar_text(c['death']['world_day']) if 'world_day' in c['death'] else
                              f"Year {c['death']['year']} of the Heavenly Calendar") + f" (aged {c['death']['age']:,})"))
    else:
        rows.append(("Status", "Alive and cultivating"))
    if c["lightning"]:
        rows.append(("Tribulations", f"survived {c['lightning']} heavenly lightning strikes"))

    source = []
    if info.get("account_created") and c.get("account_years") is not None:
        year = datetime.datetime.fromtimestamp(info["account_created"], datetime.timezone.utc).year
        source.append(("Account age", f"{c['account_years']:.1f} years (created {year})"))
    source.append(("Training level" if info.get("offline") else "Steam level", str(info["level"])))
    source.append(("Synthetic library" if info.get("offline") else "Paid games", f"{info['game_count']:,}"))
    source.append(("Generated missions" if info.get("offline") else "Achievements", f"{info['achievements']:,}"))
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
        "power_fraction": (c["realm_index"] + 1) / len(gamedata.REALMS),
        "power_caption": f"realm {c['realm_index'] + 1}/{len(gamedata.REALMS)}, score {c['score']:,.0f}",
        "rep_fraction": rep_frac, "rep_caption": rep_caption, "rep_rank": rep["rank"],
        "rows": rows, "source": source, "backstory": c["backstory"],
        "breakthrough_ready": progress.breakthrough_status(c)["can"],
    }


HISTORY_KINDS = {"duel_win": ("Victory", "#6fcf97"), "duel_loss": ("Defeat", "#eb6b6b"),
                 "bought": ("Bought", "#c8a24a"), "treasure": ("Treasure", "#c667d8"),
                 "talisman": ("Talisman", "#5fb3ff"), "breakthrough_ok": ("Breakthrough", "#6fcf97"),
                 "breakthrough_fail": ("Failed", "#eb6b6b"), "start": ("Start", "#9aa3b5"),
                 "sold": ("Sold", "#c8a24a"), "adventure": ("Adventure", "#5fb3ff"),
                 "reborn": ("Reborn", "#a98bff"),
                 "team_win": ("Team win", "#6fcf97"), "team_loss": ("Team loss", "#eb6b6b")}


def breakthrough_view(c):
    """What the breakthrough dialog needs: whether it can be tried, why not, the realms, the
    chance with its parts (without and with a pill) and the pills owned."""
    st = progress.breakthrough_status(c)
    out = {"name": c["name"], "can": st["can"], "reason": st["reason"], "current": st["current"],
           "next": st["next"], "pills": st["pills"], "cooldown_left": st["cooldown_left"],
           "pill_bonus": progress.BREAKTHROUGH_PILL_BONUS, "plain": None, "with_pill": None,
           "risk": "", "fatal": False, "penalty": st["penalty"]}
    if st["chance"]:
        out["risk"], out["fatal"] = progress.breakthrough_risk_text(st), st["fatal"]
    if st["chance"]:
        out["plain"] = {"lines": progress.breakthrough_lines(st["chance"]), "total": st["chance"]["total"]}
        out["with_pill"] = {"lines": progress.breakthrough_lines(st["chance_pill"]),
                            "total": st["chance_pill"]["total"]}
    return out


def shop_rows(c):
    """One dict per pavilion item for the shop list. 'number' is what buy() takes."""
    rows = []
    for n, item in enumerate(gamedata.PAVILION_ITEMS, 1):
        item = pavilion_shop.discounted_item(c, item)
        owned = c["pavilion"]["items"].get(item["id"], 0)
        weapon_owned = item["kind"] == "Weapon" and owned > 0
        affordable = item["price"] <= c["sect_points"]
        rows.append({"number": n, "id": item["id"], "kind": item["kind"], "name": item["name"],
                     "price": item["price"], "blurb": item["blurb"], "owned": owned,
                     "can_buy": affordable and not weapon_owned,
                     "status": pavilion_shop.pavilion_status(c, item)})
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

    def __init__(self, ctk, key=None, offline=False):
        import tkinter
        self.tk = tkinter
        self.ctk = ctk
        self.affinity_images = {}
        self.bodies = {}
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("dark-blue")
        if sys.platform == "win32":
            try:
                import ctypes
                ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("SteamCultivator.Desktop")
            except (AttributeError, OSError):
                pass
        self.root = ctk.CTk()
        set_game_window_icon(self.root)
        # CustomTkinter installs its own Windows icon after 200 ms; reapply ours.
        self.root.after(350, lambda: set_game_window_icon(self.root))
        self.root.title(f"Steam Cultivator {gamedata.VERSION}")
        self.root.geometry("1040x780")
        self.root.minsize(860, 600)
        self.root.configure(fg_color=BG)
        self.controller = None
        self.events = queue.Queue()
        self.working = False
        self.checking_key = False
        self.remember_key_consent = False
        self.pending_remember_key = False
        self.selected = False            # has a cultivator been looked up yet?
        self.bt_dialog = None
        self.team_dialog = None
        self.team_size = 2
        self.team_entries = {"a": [], "b": []}
        self.adv_button = None
        self.adv_dialog = None
        self.title_font = ctk.CTkFont(size=24, weight="bold")
        self.head_font = ctk.CTkFont(size=15, weight="bold")
        self.body_font = ctk.CTkFont(size=13)
        self.small_font = ctk.CTkFont(size=12)
        self.mono_font = ctk.CTkFont(family="Courier New", size=12)
        # the program version, always visible at the very top left
        self.version_label = ctk.CTkLabel(self.root, text=gamedata.VERSION, font=self.small_font,
                                          text_color=MUTED, anchor="w")
        self.version_label.pack(side="top", anchor="w", padx=16, pady=(8, 0))
        achievements.PROGRESS_HOOK = lambda done, total: self.events.put(("progress", done, total))
        self.root.after(80, self.poll)
        saved_key = "" if offline else storage.load_saved_api_key()
        if key or offline or saved_key:
            self.start(key or saved_key)
        else:
            self.build_key_screen()

    # -- starting up -----------------------------------------------------------------------
    def build_key_screen(self):
        ctk = self.ctk
        self.key_frame = ctk.CTkFrame(self.root, fg_color=PANEL, corner_radius=14)
        self.key_frame.place(relx=0.5, rely=0.45, anchor="center")
        ctk.CTkLabel(self.key_frame, text="Steam Cultivator", font=self.title_font,
                     text_color=ACCENT).pack(padx=48, pady=(32, 4))
        ctk.CTkLabel(self.key_frame, text="Enter a Steam API key, or continue offline.",
                     font=self.body_font, text_color=MUTED).pack(padx=48)
        ctk.CTkLabel(self.key_frame, text="Get one at steamcommunity.com/dev/apikey. It is "
                     "kept in memory unless you explicitly choose to remember it.", font=self.small_font,
                     text_color=MUTED, wraplength=380).pack(padx=48, pady=(2, 14))
        self.key_entry = ctk.CTkEntry(self.key_frame, width=380, show="*",
                                      placeholder_text="Steam API key")
        self.key_entry.pack(padx=48)
        self.key_entry.bind("<Return>", lambda e: self.submit_key())
        self.key_error = ctk.CTkLabel(self.key_frame, text="", text_color=BAD, font=self.small_font)
        self.key_error.pack(pady=(6, 0))
        self.key_button = ctk.CTkButton(self.key_frame, text="Enter the Dao", command=self.submit_key,
                                        fg_color=ACCENT, hover_color="#a8862f",
                                        text_color="#1a1a1a", width=180)
        self.key_button.pack(pady=(8, 32))
        ctk.CTkButton(self.key_frame, text="Continue offline (local profiles)",
                      command=self.start_offline, width=280).pack(pady=(0, 20))
        self.remember_key_var = self.tk.BooleanVar(value=False)
        self.remember_key_box = ctk.CTkCheckBox(self.root, text="Remember Steam API key (not recommended)",
                                              variable=self.remember_key_var, command=self.confirm_remember_key,
                                              font=self.small_font, fg_color=ACCENT,
                                              hover_color="#a8862f")
        self.remember_key_box.place(relx=1, rely=1, x=-20, y=-20, anchor="se")
        self.key_entry.focus()

    def confirm_remember_key(self):
        from tkinter import messagebox
        self.remember_key_consent = False
        if self.remember_key_var.get():
            accepted = messagebox.askyesno("WARNING: Save your Steam API key?",
                "NOT RECOMMENDED unless you understand the risk.\n\n"
                "This writes your Steam Web API key in readable, unencrypted text to:\n"
                + str(storage.API_KEY_SETTINGS_PATH) + "\n\n"
                "Anyone who can read that file can copy and use your API key. "
                "NEVER share this file, include it in a ZIP, upload it, or commit it to source control.\n\n"
                "The key will NOT be written to game logs or profile saves. "
                "Without this option, it stays in memory only.\n\n"
                "Do you explicitly agree to save the key after Steam validates it?",
                icon="warning", default="no", parent=self.root)
            self.remember_key_consent = bool(accepted)
            if not accepted:
                self.remember_key_var.set(False)

    def close_key_screen(self):
        self.key_frame.destroy()
        self.remember_key_box.destroy()

    def start_offline(self):
        if self.checking_key:
            return
        self.close_key_screen()
        self.start("")

    def submit_key(self):
        """Checks the key with Steam first (on a worker thread); only a working key gets in."""
        key = self.key_entry.get().strip()
        if not key:
            self.key_error.configure(text="An API key is required.", text_color=BAD)
            return
        if self.checking_key:
            return
        self.checking_key = True
        self.pending_remember_key = bool(self.remember_key_var.get() and self.remember_key_consent)
        self.remember_key_box.configure(state="disabled")
        self.key_error.configure(text="Checking the key with Steam...", text_color=MUTED)
        self.key_button.configure(state="disabled")

        def worker():
            try:
                steam_api.check_key(key)
                self.events.put(("key", key, None))
            except logs.SteamError as e:
                self.events.put(("key", key, str(e)))
            except BaseException as e:
                self.events.put(("key", key, f"Something unexpected went wrong: "
                                             f"{type(e).__name__}: {e}"))
        threading.Thread(target=worker, daemon=True).start()

    def key_checked(self, key, error):
        self.checking_key = False
        if not self.widget_alive(self.key_frame):
            return
        if error:
            self.remember_key_box.configure(state="normal")
            self.key_error.configure(text=error, text_color=BAD)
            self.key_button.configure(state="normal")
            self.key_entry.focus()
            return
        if self.pending_remember_key:
            try:
                storage.save_api_key(key, consent=True)
            except (OSError, ValueError):
                from tkinter import messagebox
                messagebox.showwarning("Key was not saved", "The key could not be saved. You can still use it for this session.", parent=self.root)
        self.close_key_screen()
        self.start(key)

    def start(self, key):
        self.controller = Controller(key)
        self.build_main()
        self.root.protocol("WM_DELETE_WINDOW",self.close_world)
        self.root.after(100,self.begin_world)

    # -- the main layout -------------------------------------------------------------------
    def build_main(self):
        ctk = self.ctk
        self.tabs = ctk.CTkTabview(self.root, fg_color=PANEL, command=self.on_tab,
                                   segmented_button_selected_color=ACCENT,
                                   segmented_button_selected_hover_color="#a8862f")
        self.tabs.pack(fill="both", expand=True, padx=14, pady=(14, 6))
        for name in ("Cultivator", "Sect", "Pavilion", "Battles", "History", "World", "World History", "Log"):
            self.tabs.add(name)
        self.build_cultivator_tab(self.tabs.tab("Cultivator"))
        self.sect_panel = ctk.CTkScrollableFrame(self.tabs.tab("Sect"), fg_color=PANEL)
        self.sect_panel.pack(fill="both", expand=True)
        self.say(self.sect_panel, "Look up a cultivator to visit their sect.")
        self.build_pavilion_tab(self.tabs.tab("Pavilion"))
        self.build_duel_tab(self.tabs.tab("Battles"))
        self.build_history_tab(self.tabs.tab("History"))
        self.build_log_tab(self.tabs.tab("Log"))
        self.build_world_tabs()
        bar = ctk.CTkFrame(self.root, fg_color="transparent")
        bar.pack(fill="x", padx=18, pady=(0, 10))
        self.status = ctk.CTkLabel(bar, text="Ready.", font=self.small_font, text_color=MUTED,
                                   anchor="w")
        self.status.pack(side="left")
        ctk.CTkButton(bar, text="Developer tools", width=130,
                      command=self.open_developer_tools).pack(side="right", padx=8)
        if storage.load_saved_api_key():
            ctk.CTkButton(bar, text="Forget saved API key", width=160,
                          command=self.forget_saved_key).pack(side="right", padx=8)
        self.progress = ctk.CTkProgressBar(bar, width=220, progress_color=ACCENT)
        self.progress.set(0)

    def forget_saved_key(self):
        from tkinter import messagebox
        try:
            storage.forget_api_key()
        except OSError:
            messagebox.showerror("Could not forget key", "The saved key file could not be deleted. Remove steam_api_settings.json manually.", parent=self.root)
            return
        messagebox.showinfo("Saved key removed", "The saved key file was deleted. This session keeps its key in memory until you close the game. An existing STEAM_API_KEY environment variable, if set, still applies on future launches.", parent=self.root)

    def open_developer_tools(self):
        if self.working or self.controller.busy.locked():
            messagebox.showinfo("Action running", "Wait for the current game action to finish before editing saves.", parent=self.root)
            return
        window = getattr(self, "developer_window", None)
        if window is not None and window.winfo_exists():
            window.lift()
            window.focus_set()
        else:
            self.developer_window = DeveloperEditor(Path(storage.CACHE_DIR), master=self.root)
            self.developer_window.transient(self.root)
            self.developer_window.grab_set()
            self.developer_window.bind("<Destroy>", lambda event: self.refresh_cached_profiles()
                                       if event.widget is self.developer_window else None, add="+")

    def on_tab(self):
        name = self.tabs.get()
        if name == "Sect":
            self.refresh_sect()
        elif name == "World":
            self.social_tab_changed()
        elif name == "World History":
            self.refresh_chronicle()
        elif name == "Pavilion":
            self.refresh_pavilion()
        elif name == "History":
            self.refresh_history()
        elif name == "Log":
            self.refresh_log()

    def open_sect_picker(self,new=False,repair=False):
        sid=None if new else self.controller.selected()
        if not new and not sid:return
        def read():
            data=storage.sect_catalog()
            state=None if new else progress.sect_management(sid)
            return data,state
        def show(result):
            rows,state=result
            window=getattr(self,'sect_picker',None)
            if window and self.widget_alive(window):window.destroy()
            dlg=self.ctk.CTkToplevel(self.root);self.sect_picker=dlg;dlg.title('Choose a sect');dlg.geometry('680x390');dlg.transient(self.root)
            correction=bool(state and state['needs_choice'])
            self.ctk.CTkLabel(dlg,text='Choose your starting sect' if new else 'Correct an unlisted membership' if correction else 'Join another sect',font=self.head_font).pack(pady=16)
            choices={r['name']:r for r in rows}
            preview=self.ctk.CTkLabel(dlg,text='',wraplength=620,justify='left');preview.pack(pady=12)
            def update(name):
                r=choices[name];preview.configure(text=f"{name}\nMembers: {r['members']} · Master: {r['master']}{' (acting)' if r['acting'] else ''} · Elders: {r['elders']}")
            menu=self.ctk.CTkOptionMenu(dlg,values=list(choices),width=480,command=update);menu.pack(pady=8);update(menu.get())
            explanation='Your character will start at this sect headquarters.' if new else 'This one-time correction transfers existing sect reputation and preserves your currencies and history.' if correction else 'Joining requires being at the new headquarters. Leaving relinquishes office and mentorship, damages former members’ trust/respect, and starts a two-hour active-play cooldown.'
            self.ctk.CTkLabel(dlg,text=explanation,wraplength=620,justify='left').pack(padx=20,pady=15)
            def choose():
                choice=choices[menu.get()]
                if not new and sid!=self.controller.selected():return
                def work():
                    if new:return self.controller.create_random_local(choice['id'])
                    def act():
                        progress.change_sect(sid,choice['id'],repair=correction)
                        return self.controller._view_data(sid)
                    return self.controller._run('join sect',act)
                def done(data):
                    if self.widget_alive(dlg):dlg.destroy()
                    self.look_entry.delete(0,'end');self.look_entry.insert(0,data['steamid']);self.show_cultivator(data)
                self.run_async('Updating sect membership…',work,done)
            self.ctk.CTkButton(dlg,text='Create character' if new else 'Join selected sect',command=choose).pack(pady=8)
            if not new and not correction:
                def travel():
                    choice=choices[menu.get()]
                    if self.widget_alive(dlg):dlg.destroy()
                    self.tabs.set('World');self.world_views.set('Map');self.map_destination=choice['location'];self.refresh_region()
                self.ctk.CTkButton(dlg,text='Preview route to selected headquarters',command=travel).pack(pady=4)
        self.run_async('Reading the twenty sects…',read,show)

    def open_sect_management(self):
        sid=self.controller.selected()
        if not sid:return
        def work():
            def read():
                generator.build_cultivator(sid,self.controller.key,self.controller.profiles)
                return progress.sect_management(sid)
            return self.controller._run('sect management',read)
        self.run_async('Reading sect affairs…',work,self.show_sect_management)

    def show_sect_management(self,data):
        a=data['actor'];sid=a['actor']
        dlg=getattr(self,'sect_management_window',None)
        if not dlg or not self.widget_alive(dlg):
            dlg=self.ctk.CTkToplevel(self.root);self.sect_management_window=dlg;dlg.title('Sect membership and politics');dlg.geometry('930x800');dlg.transient(self.root)
            self.sect_management_panel=self.ctk.CTkScrollableFrame(dlg);self.sect_management_panel.pack(fill='both',expand=True,padx=10,pady=10)
        body=self.fresh(self.sect_management_panel)
        self.section(body,a['name']+' · '+data['role'])
        self.paragraph(body,f"Standing: {a['standing']} · Spirit Stones: {data['spirit_stones']:,} · Salary: {data['salary']} every 30 active minutes (highest role only).")
        self.paragraph(body,f"Next salary: {int(data['salary_seconds'])//60}m; voluntary membership-change wait: {int(data['change_seconds'])//60}m.")
        def act(label,fn,confirm=None):
            if sid!=self.controller.selected():return
            if confirm and not messagebox.askyesno(label,confirm,parent=dlg):return
            def work():
                def perform():
                    message=fn()
                    card=self.controller._view_data(sid)
                    return message,card,progress.sect_management(sid)
                return self.controller._run(label,perform)
            def done(result):
                message,card,affairs=result
                self.show_cultivator(card)
                if self.tabs.get()=='Sect':
                    self.show_sect(dict(steamid=sid,c=card['c'],sect=card['c']['sect_status']))
                self.status.configure(text=message)
                self.show_sect_management(affairs)
            self.run_async(label+'…',work,done)
        self.ctk.CTkButton(body,text='Choose / change sect',command=lambda:self.open_sect_picker()).pack(pady=4)
        if a['sect_id']:
            self.ctk.CTkButton(body,text='Leave sect and relinquish position',command=lambda:act('Leave sect',lambda:progress.change_sect(sid,None), 'Leave this sect? You lose your office/mentor, former members lose trust and respect, and the two-hour active-play cooldown begins.')).pack(pady=4)
        self.section(body,'Mentorship and council appointments')
        council={v['office']+' · '+v['name']:v for v in data['council'] if v['actor']!=sid}
        if council:
            detail=self.ctk.CTkLabel(body,text='',wraplength=800,justify='left');detail.pack(pady=6)
            def preview(name):
                v=council[name];detail.configure(text=f"{v['name']} · {v['location']['name']} · Direct disciples {v['disciples']}/{v['capacity']} · Base support chance {v['support_chance']:.0%}. Meet them at the same location to apply or ask for backing.")
            contact=self.ctk.CTkOptionMenu(body,values=list(council),width=600,command=preview);contact.pack(pady=4);preview(contact.get())
            self.ctk.CTkButton(body,text='View selected council member',command=lambda:self.inspect_world_actor(council[contact.get()]['actor'])).pack(pady=3)
            def apply_disciple():
                mentor = council[contact.get()]['actor']
                act('Direct disciple application',lambda:progress.apply_direct_disciple(sid,mentor))
            self.ctk.CTkButton(body,text='Apply as their direct disciple',command=apply_disciple).pack(pady=3)
            purpose=self.ctk.CTkOptionMenu(body,values=['elder','master']);purpose.pack(pady=3)
            amount=self.ctk.CTkEntry(body,placeholder_text='Spirit Stone bribe (0 = ordinary request)');amount.insert(0,'0');amount.pack(pady=3)
            def request_vote():
                try:stones=int(amount.get())
                except ValueError:messagebox.showerror('Invalid amount','Enter a whole number of Spirit Stones.',parent=dlg);return
                voter=council[contact.get()]['actor'];campaign=purpose.get()
                act('Seek council support',lambda:progress.seek_support(sid,voter,campaign,stones),'An offer can be refused or exposed. Accepted bribes transfer your Spirit Stones; exposure can damage standing.' if stones else None)
            self.ctk.CTkButton(body,text='Request council support',command=request_vote).pack(pady=4)
        self.paragraph(body,'Elder: 1,200 standing, suitable strength, an open seat and council backing. Master: eligible elder/guardian, backing and a vacant or acting leadership. A supported candidacy can request an earlier council decision.')
        for office in ('Elder','Sect Master'):
            self.ctk.CTkButton(body,text='Apply for '+office,command=lambda role=office:act('Office application',lambda:progress.apply_office(sid,role))).pack(pady=3)
        if a['mentor']:
            self.ctk.CTkButton(body,text='Train with mentor (10 active-minute cooldown)',command=lambda:act('Mentor training',lambda:progress.mentor_training(sid))).pack(pady=3)
            self.ctk.CTkButton(body,text='Claim achievement reward from mentor',command=lambda:act('Mentor reward',lambda:progress.claim_mentor_reward(sid))).pack(pady=3)
        self.section(body,'Political warning signs')
        plot=data['plot']
        if not plot:self.paragraph(body,'No plot is currently known to you. Private NPC plans are not revealed here.')
        else:
            self.paragraph(body,f"Stage: {plot['stage']} · Organizer: {plot['organizer']} · Evidence: {plot['evidence']}/3 · Confrontations: {plot['round']}/3")
            self.paragraph(body,'Interventions require headquarters attendance and have a two-minute active-play cooldown. Failed investigations increase the organizer’s hostility. Unsupported warnings cost 10 standing; accusations cost 50. Backing betrayal is unavailable to Loyal characters.')
            for action,chance in plot['choices'].items():
                self.ctk.CTkButton(body,text=f'{action} · {chance:.0%} chance',command=lambda value=action:act(value,lambda:progress.intervene(sid,value))).pack(pady=3)
            if plot['stage']=='conflict':
                for side in ('Defenders','Challengers'):
                    self.ctk.CTkButton(body,text='Fight for '+side,command=lambda value=side:act('Lethal sect confrontation',lambda:progress.fight_for_sect(sid,value,self.controller.key,self.controller.profiles),'Enter lethal combat? The loser has a 15% chance of death. You can instead negotiate, withdraw, or remain out of the fighting.')).pack(pady=3)
        for event in data['reports']:
            self.paragraph(body,storage.calendar_text(event['day'])+' · '+event['title']+'\n'+event['summary'])
        self.ctk.CTkButton(body,text='Refresh sect affairs',command=self.open_sect_management).pack(pady=12)

    def refresh_sect(self):
        if self.working:
            self.root.after(1000, lambda: self.refresh_sect() if self.tabs.get() == "Sect" else None)
            return
        if not self.selected:
            self.say(self.sect_panel, "Look up a cultivator to visit their sect.")
            return
        self.run_async("Visiting the sect…", self.controller.sect, self.show_sect)

    def show_sect(self, data, show_offers=False):
        job = getattr(self, "_sect_refresh_job", None)
        if job:
            self.root.after_cancel(job)
            self._sect_refresh_job = None
        body = self.fresh(self.sect_panel)
        c, sect = data["c"], data["sect"]
        self.section(body, sect["identity"]["name"])
        self.ctk.CTkButton(body,text="Membership, mentorship and sect politics",command=self.open_sect_management).pack(pady=8)
        if c["sect"]=="Wanderer":
            self.paragraph(body,"You are a wanderer. Choose a sect above and travel to its headquarters to join; sect missions require membership.")
            return
        self.table(body, [("Cultivator", c["name"]), ("Current title", c["title"]),
                          ("Sect reputation rank", sect["rank"]), ("Sect reputation points", f"{sect['points']:,}"),
                          ("Sect points", f"{c['sect_points']:,}"), ("Spirit Stones", f"{c['spirit_stones']:,}")], label_width=190)
        discounts = gamedata.SECT_DISCOUNTS[sect["rank_index"]]
        self.paragraph(body, "Pavilion discounts: " + ", ".join(f"{v}%" for v in discounts) + " for prices <500 / <2,000 / <5,000 / 5,000+.")
        self.paragraph(body, "Easy: guaranteed success, 5-minute cooldown. Hard: success/failure 10 minutes; injury 15 minutes. Failure, injury and death give no rewards.")
        risk = progress.mission_risks(c)
        self.paragraph(body, f"Hard mission risks: failure {risk['failure']*100:g}%, injury {risk['injury']*100:g}%, death {risk['death']*100:g}%. Injury costs {10*(c['realm_index']+1)} lifespan years and can be fatal.")
        if sect["history"]:
            self.paragraph(body, sect["history"][-1]["summary"])
        remaining = max(0, int(sect["ready_at"] - time.time() + .999))
        if c["death"]:
            self.paragraph(body, "This cultivator is dead. Use Adventure to seek rebirth.")
        elif remaining:
            countdown = self.ctk.CTkLabel(body, text="", anchor="w", justify="left",
                                         wraplength=WIDE, font=self.body_font)
            countdown.pack(fill="x", padx=12, pady=3)
            sid = data["steamid"]
            def tick():
                self._sect_refresh_job = None
                if not self.widget_alive(countdown) or self.tabs.get() != "Sect" or self.controller.selected() != sid:
                    return
                left = max(0, int(sect["ready_at"] - time.time() + .999))
                if not left:
                    self.refresh_sect()
                    return
                countdown.configure(text=f"Next sect mission in {left//60}m {left%60:02d}s. New offers unlock when the cooldown ends.")
                self._sect_refresh_job = self.root.after(1000, tick)
            tick()
        else:
            self.ctk.CTkButton(body, text="Go out on a sect mission", command=lambda: self.show_sect(data, True)).pack(pady=10)
            if show_offers:
                for offer in sect["offers"]:
                    card = self.ctk.CTkFrame(body, fg_color=PANEL_2)
                    card.pack(fill="x", padx=10, pady=5)
                    self.paragraph(card, ("Hard: " if offer["hard"] else "Easy: ") + offer["text"])
                    self.paragraph(card, f"Rewards: {offer['sect_points']} sect points · {offer['stones']} Spirit Stones · {offer['reputation']} sect reputation")
                    self.ctk.CTkButton(card, text="Choose this mission", command=lambda oid=offer["id"]: self.choose_sect_mission(oid)).pack(pady=8)

    def choose_sect_mission(self, offer_id):
        if self.working:
            return
        def done(result):
            self.show_cultivator(result["data"])
            self.refresh_sect()
        self.run_async("On a sect mission…", lambda: self.controller.sect_mission(offer_id), done)

    # -- living world and shared chronicle -------------------------------------
    def build_world_tabs(self):
        ctk = self.ctk
        self.world_views = ctk.CTkTabview(self.tabs.tab('World'),command=self.social_tab_changed)
        self.encounter_notice=ctk.CTkButton(self.tabs.tab('World'),text='Travel encounters: none pending',state='disabled',command=lambda:self.show_encounter(getattr(self,'_encounter',None)))
        self.encounter_notice.pack(fill='x',padx=12,pady=4)
        self.world_views.pack(fill='both',expand=True)
        for label in ('People here','Population','Map','Leadership','Relationships'): self.world_views.add(label)
        self.build_region_tabs()
        tab = self.world_views.tab('Population')
        self.world_page = 0
        self.world_header = ctk.CTkLabel(tab,text='Preparing the living world…',font=self.head_font,text_color=ACCENT)
        self.world_header.pack(fill='x',padx=12,pady=8)
        controls = ctk.CTkFrame(tab,fg_color='transparent');controls.pack(fill='x',padx=12)
        self.world_search = ctk.CTkEntry(controls,placeholder_text='Search cultivator name or ID',width=280)
        self.world_search.pack(side='left',padx=(0,8))
        self.world_search.bind('<Return>',lambda e:self.refresh_world(reset=True))
        ctk.CTkButton(controls,text='Search',width=90,command=lambda:self.refresh_world(reset=True)).pack(side='left')
        ctk.CTkButton(controls,text='Previous',width=90,command=lambda:self.change_world_page(-1)).pack(side='right',padx=4)
        ctk.CTkButton(controls,text='Next',width=90,command=lambda:self.change_world_page(1)).pack(side='right',padx=4)
        self.world_count = ctk.CTkLabel(tab,text='',font=self.small_font);self.world_count.pack()
        self.world_panel = ctk.CTkScrollableFrame(tab,fg_color=PANEL);self.world_panel.pack(fill='both',expand=True)
        tab = self.tabs.tab('World History')
        self.chronicle_page = 0
        controls = ctk.CTkFrame(tab,fg_color='transparent');controls.pack(fill='x',padx=12,pady=8)
        self.chronicle_search = ctk.CTkEntry(controls,placeholder_text='Search event, location or sect',width=280)
        self.chronicle_search.pack(side='left',padx=(0,8))
        self.chronicle_kind = ctk.CTkOptionMenu(controls,values=['All','calendar','world','breakthrough','death','war','inheritance'],width=140)
        self.chronicle_kind.pack(side='left',padx=8)
        ctk.CTkButton(controls,text='Search',width=80,command=lambda:self.refresh_chronicle(reset=True)).pack(side='left')
        ctk.CTkButton(controls,text='Next',width=70,command=lambda:self.change_chronicle_page(1)).pack(side='right',padx=4)
        ctk.CTkButton(controls,text='Previous',width=80,command=lambda:self.change_chronicle_page(-1)).pack(side='right',padx=4)
        self.chronicle_count = ctk.CTkLabel(tab,text='Major public events and rumors; hidden discoveries remain secret.',font=self.small_font)
        self.chronicle_count.pack()
        self.chronicle_panel = ctk.CTkScrollableFrame(tab,fg_color=PANEL);self.chronicle_panel.pack(fill='both',expand=True)

    def begin_world(self):
        if self.working:
            self.root.after(200,self.begin_world);return
        def work():
            def initialize():
                result = progress.initialize_world()
                self.controller.world_clock = storage.WorldClock()
                return result
            return self.controller._run('prepare world',initialize)
        def done(world):
            self.show_world_clock(world)
            self.root.after(1000,self.world_tick)
            if self.tabs.get() == 'World': self.refresh_world()
        self.run_async('Preparing the living world…',work,done,
                       lambda message:self.world_header.configure(text='World could not start: '+message))

    def show_world_clock(self,world):
        self._displayed_world_day = int(world['day'])
        caption = storage.calendar_text(world['day']) + ' · 1 day / 5 minutes · time pauses when closed'
        self.world_header.configure(text=caption)
        self.version_label.configure(text=gamedata.VERSION+'   ·   '+storage.calendar_text(world['day']))

    def world_tick(self):
        if getattr(self,'_closing',False): return
        if getattr(self,'_world_tick_running',False): return
        if self.working or not hasattr(self.controller,'world_clock'):
            self.root.after(1000,self.world_tick);return
        self._world_tick_running = True
        nearby_revision=getattr(self,'_people_request_revision',0)
        nearby_request=(self.controller.selected(),self.nearby_search.get(),self.nearby_page) if hasattr(self,'world_views') and self.tabs.get()=='World' and self.world_views.get()=='People here' else None
        def worker():
            try:
                result=self.controller.world_clock.tick()
                if nearby_request and nearby_request[0]:
                    result['nearby']=(nearby_request,storage.people_here(*nearby_request))
                    result['nearby_revision']=nearby_revision
                self.events.put(('world_clock',result,None))
            except Exception as exc:
                self.events.put(('world_clock',None,str(exc)))
        threading.Thread(target=worker,daemon=True).start()

    def finish_world_tick(self,world,error):
        self._world_tick_running = False
        if error:
            self.world_header.configure(text='World paused: '+error)
        elif int(world['day']) != getattr(self,'_displayed_world_day',None):
            self.show_world_clock(world)
        if not error:
            if world.get('nearby') and self.tabs.get()=='World' and self.world_views.get()=='People here':
                request,data=world['nearby']
                if request==(self.controller.selected(),self.nearby_search.get(),self.nearby_page) and world.get('nearby_revision',0)==getattr(self,'_people_request_revision',0):self.show_people(data)
            encounter=world.get('encounter')
            self._encounter=encounter
            if hasattr(self,'encounter_notice'):
                text=('World paused: '+encounter['name']+' has a travel encounter — open choices') if encounter else 'Travel encounters: none pending'
                state='normal' if encounter else 'disabled'
                if self.encounter_notice.cget('text')!=text or self.encounter_notice.cget('state')!=state:
                    self.encounter_notice.configure(text=text,state=state)
            if encounter and not getattr(self,'_shown_encounter',None)==encounter['id']:
                self._shown_encounter=encounter['id'];self.show_encounter(encounter)
        if not error and getattr(self,'_map_view',None):
            self._map_view['day'] = world['day']
            if self.tabs.get()=='World' and self.world_views.get()=='Map': self.draw_region()
        if not getattr(self,'_closing',False):
            self.root.after(5000 if error else 10 if world.get('pending_seconds',0)>1e-6 else 1000,self.world_tick)

    def close_world(self):
        self._closing = True
        if self.working or getattr(self,'_world_tick_running',False):
            self.root.after(100,self.close_world);return
        clock = getattr(getattr(self,'controller',None),'world_clock',None)
        if clock:
            def failed(message):
                self._closing = False
                self.status.configure(text='Could not finish saving: '+message,text_color=BAD)
                self.root.after(1000,self.world_tick)
            def finish():
                result=clock.tick()
                clock.close()
                return result
            self.run_async('Saving the world…',lambda:self.controller._run('close world',finish),
                           lambda result:self.destroy_app(),failed)
        else:
            self.destroy_app()

    def destroy_app(self):
        for job in self.root.tk.splitlist(self.root.tk.call('after','info')):
            try:self.root.tk.call('after','cancel',job)
            except self.tk.TclError:pass
        self.root.destroy()

    def build_region_tabs(self):
        tab=self.world_views.tab('People here')
        self.nearby_page=0
        self.nearby_header=self.ctk.CTkLabel(tab,text='Select your cultivator to see people at your location.')
        self.nearby_header.pack(fill='x',padx=12,pady=8)
        bar=self.ctk.CTkFrame(tab);bar.pack(fill='x')
        self.nearby_search=self.ctk.CTkEntry(bar,placeholder_text='Filter nearby names')
        self.nearby_search.pack(side='left',fill='x',expand=True,padx=6)
        self.nearby_search.bind('<Return>',lambda e:self.refresh_people(reset=True))
        self.ctk.CTkButton(bar,text='Refresh',width=90,command=lambda:self.refresh_people(reset=True)).pack(side='left',padx=4)
        for label,delta in (('Previous',-1),('Next',1)):
            self.ctk.CTkButton(bar,text=label,width=85,command=lambda d=delta:self.page_people(d)).pack(side='left',padx=4)
        self.people_panel=self.ctk.CTkScrollableFrame(tab);self.people_panel.pack(fill='both',expand=True)
        self.people_panel.grid_columnconfigure(0,weight=1)
        self._people_rows={}
        self._people_order=[]
        self._people_pointer_down=False
        self._people_layout_revision=0
        self.people_message=self.ctk.CTkLabel(self.people_panel,text='',wraplength=700,justify='left')
        self.root.bind('<ButtonPress-1>',self.people_pointer_press,add='+')
        self.root.bind('<ButtonRelease-1>',self.people_pointer_release,add='+')
        self.root.bind('<MouseWheel>',lambda event:setattr(self,'_people_layout_revision',self._people_layout_revision+1),add='+')
        tab=self.world_views.tab('Map')
        self.map_notice=self.ctk.CTkLabel(tab,text='Select a cultivator, then choose a destination.',wraplength=900)
        self.map_notice.pack(fill='x',padx=10,pady=4)
        self.map_canvas=self.tk.Canvas(tab,bg='#1d252c',highlightthickness=0)
        self.map_canvas.pack(fill='both',expand=True,padx=8,pady=4)
        self.map_canvas.bind('<Configure>',lambda e:self.draw_region())
        bar=self.ctk.CTkFrame(tab);bar.pack(fill='x')
        self.map_go=self.ctk.CTkButton(bar,text='Travel to destination',state='disabled',command=self.start_map_travel)
        self.map_go.pack(side='right',padx=8,pady=6)
        self.ctk.CTkButton(bar,text='Refresh map',command=self.refresh_region).pack(side='left',padx=8)
        self.route_policy=self.ctk.CTkOptionMenu(bar,values=['Fastest','Safer'],command=lambda value:self.draw_region())
        self.route_policy.pack(side='left',padx=8)
        self.map_destination=None
        tab=self.world_views.tab('Leadership')
        self.sect_selector=self.ctk.CTkOptionMenu(tab,values=['Preparing sects…'],command=lambda value:self.refresh_leadership(reset=True))
        self.sect_selector.pack(fill='x',padx=12,pady=8)
        self.roster_page=0
        bar=self.ctk.CTkFrame(tab);bar.pack(fill='x')
        for text,delta in (('Previous',-1),('Next',1)):
            self.ctk.CTkButton(bar,text=text,width=90,command=lambda d=delta:self.change_roster_page(d)).pack(side='left',padx=4)
        self.leader_panel=self.ctk.CTkScrollableFrame(tab);self.leader_panel.pack(fill='both',expand=True)
        tab=self.world_views.tab('Relationships')
        self.relationship_page=0
        bar=self.ctk.CTkFrame(tab);bar.pack(fill='x')
        for text,delta in (('Previous',-1),('Next',1)):
            self.ctk.CTkButton(bar,text=text,width=90,command=lambda d=delta:self.change_relationship_page(d)).pack(side='left',padx=4,pady=6)
        self.relationship_panel=self.ctk.CTkScrollableFrame(tab);self.relationship_panel.pack(fill='both',expand=True)

    def defer_world_refresh(self, view):
        if self.working:
            self._pending_world_refresh=view
            return True
        self._pending_world_refresh=None
        return False

    def retry_world_refresh(self):
        if self.working or getattr(self,'_closing',False):return
        view=getattr(self,'_pending_world_refresh',None)
        self._pending_world_refresh=None
        if view and self.tabs.get()=='World' and self.world_views.get()==view:
            # Re-read current selection, filters and page on the UI thread.
            self.social_tab_changed()

    def social_tab_changed(self):
        view=self.world_views.get()
        if view=='People here':self.refresh_people()
        elif view=='Population':self.refresh_world()
        elif view=='Relationships':self.refresh_relationships()
        else:self.refresh_region()

    def refresh_region(self):
        if self.defer_world_refresh(self.world_views.get()):return
        sid=self.controller.selected()
        def done(view):
            if sid==self.controller.selected():self.show_region(view)
        self.run_async('Reading region…',lambda:progress.region_view(sid),done)

    def show_region(self,view):
        self._map_view=view
        names={r['name']:r['sect_id'] for r in view['locations'] if r['sect_id']}
        self._region_sects=names
        if names:
            old=self.sect_selector.get()
            self.sect_selector.configure(values=sorted(names))
            self.sect_selector.set(old if old in names else sorted(names)[0])
        self.draw_region()
        if self.world_views.get()=='Leadership':self.refresh_leadership()

    def draw_region(self):
        import json
        view=getattr(self,'_map_view',None)
        if not view:return
        canvas=self.map_canvas;canvas.delete('all')
        sx=max(1,canvas.winfo_width())/1050;sy=max(1,canvas.winfo_height())/760
        places={r['id']:r for r in view['locations']}
        def point(sid):
            r=places[sid];return r['x']*sx,r['y']*sy
        for i,(name,color,_) in enumerate(gamedata.REGION_DISTRICTS):
            group=[r for r in places.values() if r['district']==i]
            x1=min(r['x'] for r in group)-35;y1=min(r['y'] for r in group)-30
            x2=max(r['x'] for r in group)+35;y2=max(r['y'] for r in group)+35
            canvas.create_rectangle(x1*sx,y1*sy,x2*sx,y2*sy,fill=color,outline='')
            canvas.create_text((x1+10)*sx,(y1+8)*sy,text=name,anchor='w',fill='#d4dfd5',font=('Arial',9,'bold'))
        for road in view['routes']:
            canvas.create_line(*point(road['a']),*point(road['b']),fill='#c18a67' if road['danger']>=2 else '#728798',width=2,dash=(4,3) if road['danger']>=2 else ())
        for sid,r in places.items():
            x,y=point(sid);tag='place:'+sid
            canvas.create_oval(x-6,y-6,x+6,y+6,fill='#e3be71' if r['sect_id'] else '#b0d6d1',outline='#ffffff' if sid==self.map_destination else '',tags=tag)
            label=r['name'] if len(r['name'])<24 else r['name'][:21]+'…'
            canvas.create_text(x,y+13,text=label,fill='#f0f1ec',font=('Arial',8),tags=tag)
            canvas.tag_bind(tag,'<Button-1>',lambda e,d=sid:self.select_destination(d))
        location=view['location'];journey=view['journey']
        travelling=journey and view['day']<journey['arrival']
        if journey:
            path=json.loads(journey['path'])
            if not travelling:location=path[-1]
            else:
                elapsed=max(0,(view['day']-journey['departure'])*view['seconds_per_day'])
                edges={frozenset((r['a'],r['b'])):r['seconds'] for r in view['routes']}
                road_total=sum(edges[frozenset((a,b))] for a,b in zip(path,path[1:]))
                journey_total=(journey['arrival']-journey['departure'])*view['seconds_per_day']
                for a,b in zip(path,path[1:]):
                    duration=edges[frozenset((a,b))]*journey_total/road_total
                    if elapsed<=duration:
                        ax,ay=point(a);bx,by=point(b);ratio=elapsed/duration
                        canvas.create_oval(ax+(bx-ax)*ratio-7,ay+(by-ay)*ratio-7,ax+(bx-ax)*ratio+7,ay+(by-ay)*ratio+7,fill='#ffffff',outline='#54dbe2',width=3)
                        break
                    elapsed-=duration
        if location and not travelling:
            x,y=point(location);canvas.create_oval(x-10,y-10,x+10,y+10,outline='#54dbe2',width=3)
        if travelling:
            seconds=max(0,int((journey['arrival']-view['day'])*view['seconds_per_day'])+1)
            self.map_notice.configure(text=f'Travelling to {places[json.loads(journey["path"])[-1]]["name"]} · {seconds}s remaining · progress saves and pauses when closed')
            self.map_go.configure(state='disabled')
        elif self.map_destination and location:
            preview=dict(view,location=location)
            plan=progress.route_plan(preview,self.map_destination,safe=self.route_policy.get()=='Safer')
            self.map_notice.configure(text=f'{places[self.map_destination]["name"]} · {plan["seconds"]} seconds total · {len(plan["path"])-1} road segments · route danger {plan["danger"]}/3 · possible road encounter; choices pause the world')
            self.map_go.configure(state='normal' if plan['seconds'] else 'disabled')
        else:
            self.map_notice.configure(text='Click a location to preview its route. Gold: sect headquarters · Teal: landmarks · White: your cultivator')
            self.map_go.configure(state='disabled')

    def select_destination(self,destination):
        self.map_destination=destination;self.draw_region()

    def start_map_travel(self):
        sid=self.controller.selected();destination=self.map_destination;safe=self.route_policy.get()=='Safer'
        if not sid or not destination:return
        def act():
            generator.build_cultivator(sid,self.controller.key,self.controller.profiles)
            return progress.begin_journey(sid,destination,safe=safe)
        self.run_async('Starting journey…',lambda:self.controller._run('travel',act),self.show_region)

    def change_roster_page(self,delta):
        self.roster_page=max(0,self.roster_page+delta);self.refresh_leadership()

    def refresh_leadership(self,reset=False):
        if reset:self.roster_page=0
        if self.defer_world_refresh('Leadership'):return
        sect=getattr(self,'_region_sects',{}).get(self.sect_selector.get())
        if not sect:return
        page=self.roster_page
        def done(data):
            if page==self.roster_page and sect==getattr(self,'_region_sects',{}).get(self.sect_selector.get()):self.show_leadership(data)
        self.run_async('Reading sect leadership…',lambda:storage.sect_roster(sect,page),done)

    def show_leadership(self,data):
        body=self.fresh(self.leader_panel)
        self.section(body,f'{self.sect_selector.get()} · {data["total"]} members')
        self.paragraph(body,'Offices are separate from reputation ranks. Use the Sect tab for applications, mentorship and political intervention.')
        for row in data['leaders']:
            self.ctk.CTkButton(body,text=row['office']+' · '+row['name']+(' · Deceased (office vacant)' if row['dead'] else ''),command=lambda sid=row['actor']:self.inspect_world_actor(sid)).pack(fill='x',padx=12,pady=3)
        self.section(body,f'Membership · Page {self.roster_page+1}')
        for row in data['members']:
            text=row['name']+' · '+row['office']+(' · Deceased' if row['dead'] else '')
            if row['mentor_name']:text+=' · Direct disciple of '+row['mentor_name']
            self.ctk.CTkButton(body,text=text,command=lambda sid=row['actor']:self.inspect_world_actor(sid)).pack(fill='x',padx=12,pady=2)

    def change_relationship_page(self,delta):
        self.relationship_page=max(0,self.relationship_page+delta);self.refresh_relationships()

    def refresh_relationships(self):
        if self.defer_world_refresh('Relationships'):return
        sid=self.controller.selected()
        page=self.relationship_page
        def done(data):
            if sid==self.controller.selected() and page==self.relationship_page:self.show_relationships(data)
        self.run_async('Reading relationships…',lambda:storage.relationship_list(sid,page),done)

    def show_relationships(self,result):
        rows,total=result;body=self.fresh(self.relationship_panel)
        self.section(body,f'{total} acquaintances · Page {self.relationship_page+1}')
        self.paragraph(body,'Trust grows through greetings once per world day. Respect, fear and hostility reflect known events. Locations are last known, not live tracking.')
        for row in rows:
            self.ctk.CTkButton(body,text=row['name'],command=lambda sid=row['npc']:self.inspect_world_actor(sid)).pack(fill='x',padx=12,pady=(10,2))
            self.paragraph(body,f'Trust {row["trust"]} · Respect {row["respect"]} · Fear {row["fear"]} · Hostility {row["hostility"]} · Last known: {row["known_location"] or "Unknown"}')
            if row.get('memory'):self.paragraph(body,'Known deed: '+row['memory'])
        if not rows:self.paragraph(body,'Speak to a cultivator in People here to begin a relationship.')

    def refresh_people(self,reset=False):
        self._people_request_revision=getattr(self,'_people_request_revision',0)+1
        revision=self._people_request_revision
        if reset:self.nearby_page=0
        if self.defer_world_refresh('People here'):return
        sid=self.controller.selected();query=self.nearby_search.get();page=self.nearby_page
        if not sid:
            self.show_people(dict(people=[],total=0,where='Select a cultivator',state='unmapped'));return
        context=(sid,query,page)
        def done(data):
            if revision==self._people_request_revision and context==self.people_context() and self.tabs.get()=='World' and self.world_views.get()=='People here':self.show_people(data)
        self.run_async('Reading nearby cultivators…',lambda:storage.people_here(sid,query,page),done)

    def page_people(self,delta):
        self.nearby_page=max(0,self.nearby_page+delta);self.refresh_people()

    def people_context(self):
        return (self.controller.selected(),self.nearby_search.get(),self.nearby_page)

    def people_pointer_press(self,event):
        # A row must not disappear or move between pressing and releasing its button.
        widget=event.widget
        while widget is not None:
            if widget in (self.people_panel,self.people_panel._parent_frame):
                self._people_pointer_down=True;return
            widget=getattr(widget,'master',None)

    def people_pointer_release(self,event):
        self._people_pointer_down=False
        pending=getattr(self,'_pending_people',None)
        self._pending_people=None
        if pending:
            context,data=pending
            def apply():
                if (not self.working and self.tabs.get()=='World' and
                    self.world_views.get()=='People here' and context==self.people_context()):
                    self.show_people(data)
            self.root.after_idle(apply)

    def show_people(self,data):
        # Only called by main-thread event handlers. Workers return plain snapshots.
        context=self.people_context()
        if self._people_pointer_down:
            self._pending_people=(context,data);return
        self._pending_people=None
        header=f'{data["where"]} · {data["total"]} available cultivators · Page {self.nearby_page+1}'
        if self.nearby_header.cget('text')!=header:self.nearby_header.configure(text=header)
        message=''
        if data['state']=='deceased':message='Seek rebirth through Adventure before meeting people again.'
        elif data['state']!='present':message='You can browse profiles, history and relationships while travelling. Conversations and physical activities become available after arrival.'
        elif not data['people']:message='No living NPCs are available here on this page. Try another location or clear the filter.'
        if self.people_message.cget('text')!=message:
            self.people_message.configure(text=message)
            if message:self.people_message.grid(row=0,column=0,sticky='ew',padx=12,pady=12)
            else:self.people_message.grid_remove()
        order=[p['id'] for p in data['people']]
        structural=order!=self._people_order
        layout_changed=structural or any(p['id'] in self._people_rows and self._people_rows[p['id']]['text']!=p['name']+' · '+(p['sect'] or 'Wanderer')+' · '+p['activity'] for p in data['people'])
        canvas=self.people_panel._parent_canvas
        anchor=None
        if layout_changed and getattr(self,'_people_context',None)==context:
            top=canvas.canvasy(0)
            for sid in self._people_order:
                card=self._people_rows[sid]['card']
                if sid in order and card.winfo_y()+card.winfo_height()>top:
                    anchor=(sid,card.winfo_y()-top);break
        for sid in set(self._people_rows)-set(order):
            self._people_rows.pop(sid)['card'].destroy()
        for index,person in enumerate(data['people']):
            sid=person['id']
            text=person['name']+' · '+(person['sect'] or 'Wanderer')+' · '+person['activity']
            row=self._people_rows.get(sid)
            if row is None:
                card=self.ctk.CTkFrame(self.people_panel)
                button=self.ctk.CTkButton(card,text='View / Talk',width=110,command=lambda actor=sid:self.inspect_world_actor(actor))
                button.pack(side='right',padx=8,pady=8)
                label=self.ctk.CTkLabel(card,text=text,wraplength=650,anchor='w')
                label.pack(fill='x',padx=10,pady=8)
                row=dict(card=card,label=label,button=button,text=text,index=None)
                self._people_rows[sid]=row
            elif row['text']!=text:
                row['label'].configure(text=text);row['text']=text
            if row['index']!=index:
                row['card'].grid(row=index+1,column=0,sticky='ew',padx=8,pady=4)
                row['index']=index
        self._people_order=order
        self._people_context=context
        if layout_changed:
            self._people_layout_revision+=1
            revision=self._people_layout_revision
            if anchor:
                sid,offset=anchor
                def restore_anchor():
                    if (revision!=self._people_layout_revision or context!=self.people_context() or
                        self._people_pointer_down or not self.widget_alive(canvas)):return
                    # Flush geometry-only idle work; never run a nested input event loop.
                    canvas.update_idletasks()
                    if revision!=self._people_layout_revision or not self.widget_alive(canvas):return
                    row=self._people_rows.get(sid);bounds=canvas.bbox('all')
                    if row and bounds and bounds[3]>bounds[1]:
                        canvas.yview_moveto((row['card'].winfo_y()-offset-bounds[1])/(bounds[3]-bounds[1]))
                self.root.after_idle(restore_anchor)

    def prepare_nearby_duel(self,player,npc):
        for entry,sid in zip(self.duel_entries,(player,npc)):
            entry.delete(0,'end');entry.insert(0,'local:'+sid if len(sid)!=17 else sid)
        self.duel_kind.set('Sparring');self.tabs.set('Battles')

    def show_encounter(self,encounter):
        if not encounter:return
        window=getattr(self,'encounter_window',None)
        if window and self.widget_alive(window):window.lift();return
        dlg=self.ctk.CTkToplevel(self.root);self.encounter_window=dlg
        dlg.title('Travel encounter — world paused');dlg.geometry('620x380');dlg.transient(self.root)
        odds=encounter['data']
        self.ctk.CTkLabel(dlg,text=encounter['name']+' encountered '+odds['enemy'],wraplength=570,font=self.head_font).pack(padx=20,pady=20)
        self.ctk.CTkLabel(dlg,text=f'World time and all journeys are paused.\nRetreat: return safely to departure.\nEscape: {odds["escape"]:.0%} success; failure causes injury and return.\nFight: {odds["win"]:.0%} victory; a loss has a 5% death chance.\nA victory earns 25 Spirit Stones.',wraplength=570,justify='left').pack(padx=20,pady=10)
        def choose(choice):
            def work():
                result=progress.resolve_encounter(encounter['id'],choice,self.controller.key,self.controller.profiles)
                clock=getattr(self.controller,'world_clock',None)
                if clock:clock.last=storage.active_play_time()
                return result
            def done(result):
                if self.widget_alive(dlg):dlg.destroy()
                self._encounter=None;self._shown_encounter=None
                self.status.configure(text=result['text'])
                self.refresh_region()
            self.run_async('Resolving encounter…',lambda:self.controller._run('encounter',work),done)
        for choice in ('Retreat','Escape','Fight'):
            self.ctk.CTkButton(dlg,text=choice,command=lambda value=choice:choose(value)).pack(pady=5)

    def refresh_world(self,reset=False):
        if reset:self.world_page=0
        if self.defer_world_refresh('Population'):return
        query,page = self.world_search.get().strip(),self.world_page
        def done(data):
            if query==self.world_search.get().strip() and page==self.world_page:self.show_world(data)
        self.run_async('Reading the world…',lambda:self.controller._run('world browser',lambda:storage.world_population(query,page)),done)

    def change_world_page(self,delta):
        self.world_page=max(0,self.world_page+delta);self.refresh_world()

    def show_world(self,result):
        rows,total=result
        self.world_count.configure(text=f'{total:,} cultivators · Page {self.world_page+1} of {max(1,(total+49)//50)} · 50 per page')
        body=self.fresh(self.world_panel)
        for actor in rows:
            card=self.ctk.CTkFrame(body,fg_color=PANEL_2);card.pack(fill='x',padx=8,pady=4)
            self.ctk.CTkButton(card,text='View / Talk',width=110,command=lambda sid=actor['id']:self.inspect_world_actor(sid)).pack(side='right',padx=10,pady=8)
            self.ctk.CTkLabel(card,text=actor['name']+' · '+actor['realm'],anchor='w',font=self.body_font).pack(fill='x',padx=12,pady=(6,0))
            self.ctk.CTkLabel(card,text=actor['sect']+' · '+actor['activity']+' · '+actor['location'],anchor='w',font=self.small_font,text_color=MUTED,wraplength=600).pack(fill='x',padx=12,pady=(0,6))
        if not rows:self.paragraph(body,'No cultivators on this page. Try a different search or the previous page.')

    def inspect_world_actor(self,sid):
        def work():
            def inspect():
                info,_,_,c=generator.build_cultivator(sid,self.controller.key,self.controller.profiles)
                player=self.controller.selected()
                c['talk_reason']='Select your own cultivator first.'
                if player:
                    try:
                        storage.require_physical(player,others=(sid,))
                        c['talk_reason']=''
                    except logs.SteamError as exc:c['talk_reason']=str(exc)
                c['presence']=storage.presence(sid)
                return sid,c,info
            return self.controller._run('world profile',inspect)
        self.run_async('Reading cultivator…',work,self.show_world_actor)

    def show_world_actor(self,result):
        sid,c,info=result
        dlg=self.ctk.CTkToplevel(self.root);dlg.title(c['name']);dlg.geometry('820x760');dlg.transient(self.root)
        body=self.ctk.CTkScrollableFrame(dlg,fg_color=PANEL);body.pack(fill='both',expand=True,padx=12,pady=12)
        self.section(body,c['name']+' · '+c['realm'])
        self.paragraph(body,'Profile ID: '+sid)
        self.table(body,cultivator_view(c,info)['rows'],content_width=700)
        self.paragraph(body,c['backstory'],width=700)
        self.paragraph(body,'Current location: '+c.get('presence',{}).get('name','Unknown'))
        if c.get('injury'):self.paragraph(body,'Recovering from '+c['injury']['cause']+' until '+storage.calendar_text(c['injury']['until_day'])+' · effective power reduced 20%.')
        self.section(body,'Conversation')
        if c.get('talk_reason'):self.paragraph(body,c['talk_reason'])
        self.paragraph(body,'Talk as your selected player cultivator. NPC profiles here do not change your selection.',width=700)
        reply=self.ctk.CTkLabel(body,text='',justify='left',wraplength=700,font=self.body_font)
        reply.pack(fill='x',padx=12,pady=8)
        player_id=self.controller.selected()
        def show_reply(data):
            if self.widget_alive(reply):
                reply.configure(text=f"{data['when']} · Trust {data['trust']}\n{data['name']}: {data['reply']}")
        def talk(topic):
            if not player_id:
                reply.configure(text='Select or create your own cultivator in the Cultivator tab first.');return
            def work():
                def act():
                    generator.build_cultivator(player_id,self.controller.key,self.controller.profiles)
                    return progress.talk_to_cultivator(player_id,sid,topic)
                return self.controller._run('conversation',act)
            self.run_async('Talking…',work,show_reply)
        for topic in ('Greeting','Your life','Your sect','Your activity','World news'):
            self.ctk.CTkButton(body,text=topic,state='disabled' if c['death'] or c.get('talk_reason') else 'normal',command=lambda t=topic:talk(t)).pack(pady=3)
        if player_id and player_id!=sid and not c['death']:
            self.ctk.CTkButton(body,text='Set up a duel',command=lambda:self.prepare_nearby_duel(player_id,sid)).pack(pady=8)
        def show_memory(rows):
            if self.widget_alive(reply):
                reply.configure(text='\n\n'.join(storage.calendar_text(r['day'])+' · '+r['topic']+'\n'+r['reply'] for r in rows[:8]) or 'No conversations yet.')
        self.ctk.CTkButton(body,text='Remembered conversations',command=lambda:self.run_async('Reading memories…',lambda:progress.conversation_history(player_id,sid),show_memory)).pack(pady=8)

    def refresh_chronicle(self,reset=False):
        if reset:self.chronicle_page=0
        query,kind,page=self.chronicle_search.get().strip(),self.chronicle_kind.get(),self.chronicle_page
        self.run_async('Reading World History…',lambda:self.controller._run('world history',lambda:storage.world_history(query,kind,page)),self.show_chronicle)

    def change_chronicle_page(self,delta):
        self.chronicle_page=max(0,self.chronicle_page+delta);self.refresh_chronicle()

    def show_chronicle(self,result):
        rows,total=result
        self.chronicle_count.configure(text=f'{total:,} major public events · Page {self.chronicle_page+1} of {max(1,(total+29)//30)}')
        body=self.fresh(self.chronicle_panel)
        for event in rows:
            card=self.ctk.CTkFrame(body,fg_color=PANEL_2);card.pack(fill='x',padx=8,pady=6)
            self.section(card,('Rumor: ' if event['visibility']=='rumor' else '')+event['title'])
            self.paragraph(card,event['when']+' · '+event['location'],muted=True)
            self.paragraph(card,event['summary'])
            for sid in event['actors']:
                self.ctk.CTkButton(card,text='View involved cultivator',command=lambda value=sid:self.inspect_world_actor(value)).pack(padx=12,pady=4,anchor='w')
        if not rows:self.paragraph(body,'No major public events match this search. Hidden events do not appear here.')


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
            except logs.SteamError as e:
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
                if event[0] == "world_clock":
                    self.finish_world_tick(event[1],event[2])
                elif event[0] == "cached_profiles":
                    self._cache_scan_running = False
                    if event[2] is None:
                        self.cached_profile_ids = dict(event[1])
                        self.filter_cached_profiles()
                    else:
                        self.cached_count.configure(text="Cache scan failed")
                    if getattr(self, "_cache_scan_again", False):
                        self._cache_scan_again = False
                        self.refresh_cached_profiles()
                elif event[0] == "key":
                    self.key_checked(event[1], event[2])
                elif event[0] == "progress":
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
        if self.widget_alive(self.root):
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

        if getattr(self,'_pending_world_refresh',None):
            self.root.after_idle(self.retry_world_refresh)

    def set_buttons(self, state):
        random_button = getattr(self, "random_local_button", None)
        if random_button is not None:
            random_button.configure(state=state)
        for b in (self.look_button, self.fight_button, self.log_button):
            b.configure(state=state)
        self.bt_button.configure(state=state if self.selected else "disabled")
        adv = getattr(self, "adv_button", None)
        if adv is not None and self.widget_alive(adv):
            try:
                adv.configure(state=state)
            except Exception:
                pass
        for b in self.buy_buttons:
            b.configure(state=state if state == "disabled" else b.intended_state)
        for b in (getattr(self, "team_start", None), getattr(self, "team_button", None)):
            if b is not None and self.widget_alive(b):
                try:
                    b.configure(state=state)
                except Exception:
                    pass

    # -- tab: cultivator -------------------------------------------------------------------
    def build_cultivator_tab(self, tab):
        ctk = self.ctk
        top = ctk.CTkFrame(tab, fg_color="transparent")
        top.pack(fill="x", pady=(4, 8))
        self.look_entry = ctk.CTkEntry(top, placeholder_text="Local cultivator name / ID, or Steam profile", height=36)
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
        self.bt_button = ctk.CTkButton(top, text="Breakthrough", command=self.do_breakthrough,
                                       height=36, fg_color="#7b5fd1", hover_color="#5f47a8",
                                       width=130, state="disabled")
        self.bt_button.pack(side="left", padx=(8, 0))
        if not self.controller.key:
            self.random_local_button = ctk.CTkButton(tab, text="Create random local cultivator",
                                                     command=self.create_random_local_character,
                                                     fg_color=ACCENT, text_color="#1a1a1a")
            self.random_local_button.pack(anchor="w", pady=(0, 8))
        cached = ctk.CTkFrame(tab, fg_color="transparent")
        cached.pack(fill="x", pady=(0, 8))
        ctk.CTkLabel(cached, text="Cached cultivators", font=self.small_font,
                     text_color=MUTED).pack(side="left", padx=(0, 10))
        self.cached_profiles_menu = ctk.CTkOptionMenu(cached, values=["No cached profiles"],
                                                     command=self.load_cached_profile, width=340)
        self.cached_profiles_menu.pack(side="left", fill="x", expand=True)
        ctk.CTkButton(cached, text="Refresh list", width=110,
                      command=self.refresh_cached_profiles).pack(side="left", padx=(8, 0))
        tools = ctk.CTkFrame(tab, fg_color="transparent")
        tools.pack(fill="x", pady=(0, 8))
        self.cached_filter = ctk.CTkEntry(tools, placeholder_text="Filter cached cultivators by name")
        self.cached_filter.pack(side="left", fill="x", expand=True)
        self.cached_filter.bind("<KeyRelease>", lambda event: self.filter_cached_profiles())
        ctk.CTkButton(tools, text="Previous", width=80, command=lambda: self.page_cached_profiles(-1)).pack(side="left", padx=6)
        self.cached_count = ctk.CTkLabel(tools, text="", width=125, font=self.small_font)
        self.cached_count.pack(side="left")
        ctk.CTkButton(tools, text="Next", width=65, command=lambda: self.page_cached_profiles(1)).pack(side="left", padx=6)
        self.cached_page = 0
        self.refresh_cached_profiles()
        self.card = ctk.CTkScrollableFrame(tab, fg_color=PANEL, corner_radius=10)
        self.card.pack(fill="both", expand=True)
        self.say(self.card, "Enter a local cultivator's name or ID, or look up a Steam profile.")

    def refresh_cached_profiles(self):
        if getattr(self, "_cache_scan_running", False):
            self._cache_scan_again = True
            return
        if not hasattr(self, "cached_profile_ids"):
            self.cached_profile_ids = {}
            self.filtered_cached_names = []
            self.cached_profiles_menu.configure(state="disabled")
            self.cached_profiles_menu.set("Scanning cached profiles…")
        self._cache_scan_running = True
        self.cached_count.configure(text="Scanning…")
        def scan():
            try:
                self.events.put(("cached_profiles", storage.cached_profile_choices(), None))
            except Exception:
                self.events.put(("cached_profiles", [], "Could not scan cache"))
        threading.Thread(target=scan, daemon=True).start()

    def filter_cached_profiles(self):
        query = self.cached_filter.get().strip().casefold()
        self.filtered_cached_names = [name for name in self.cached_profile_ids if query in name.casefold()]
        self.cached_page = 0
        self.page_cached_profiles(0)

    def page_cached_profiles(self, step):
        names = self.filtered_cached_names
        pages = max(1, (len(names) + 49) // 50)
        self.cached_page = min(pages - 1, max(0, self.cached_page + step))
        labels = names[self.cached_page * 50:(self.cached_page + 1) * 50]
        self.cached_count.configure(text=f"Page {self.cached_page + 1}/{pages} · {len(names)} profiles")
        current = self.cached_profiles_menu.get()
        self.cached_profiles_menu.configure(values=labels or ["No cached profiles"],
                                             state="normal" if labels else "disabled")
        self.cached_profiles_menu.set(current if current in self.cached_profile_ids else
                                       "Select a cached cultivator…" if labels else "No cached profiles")

    def load_cached_profile(self, name):
        if self.working:
            return
        sid = self.cached_profile_ids.get(name)
        if sid:
            self.look_entry.delete(0, "end")
            self.look_entry.insert(0, sid)
            self.do_lookup()

    def create_random_local_character(self):
        self.open_sect_picker(new=True)

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
        self.refresh_cached_profiles()
        ctk, v = self.ctk, data["view"]
        if data.get("c",{}).get("sect_choice_needed") and getattr(self,"_sect_prompted",None)!=data["steamid"]:
            self._sect_prompted=data["steamid"]
            self.root.after_idle(lambda:self.open_sect_picker(repair=True))
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
        # the Adventure button: top right of this box, under the Look up button
        self.adv_button = ctk.CTkButton(head, text="Seek rebirth" if v["dead"] else "Adventure",
                                        command=self.do_adventure, width=110, height=36,
                                        fg_color="#a98bff" if v["dead"] else "#3f9f7a",
                                        hover_color="#7d62cc" if v["dead"] else "#2f7a5d",
                                        text_color="#101010")
        self.adv_button.place(relx=1.0, x=-16, y=12, anchor="ne")
        if v["breakthrough_ready"]:
            self.chip(chips, "Ready to break through", "#a98bff")
        self.selected = True
        self.bt_button.configure(state="normal")

        bars = ctk.CTkFrame(body, fg_color="transparent")
        bars.pack(fill="x", padx=6)
        self.bar(bars, "Power", v["power_fraction"], v["power_caption"], v["realm_color"])
        self.bar(bars, v["rep_rank"], v["rep_fraction"], v["rep_caption"], ACCENT)

        self.section(body, "Cultivator")
        self.table(body, v["rows"])
        self.section(body, "Locally generated stats" if data["info"].get("offline") else "Source stats from Steam")
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
            self.paragraph(body, ("Cause: " if data["c"]["death"]["killer"] == "lifespan"
                                  else "Slain by: ") + label)
            self.paragraph(body, text)
        self.status.configure(text=f"Loaded {v['name']}.", text_color=GOOD)
        self.refresh_team_recent()

    def do_adventure(self):
        self.run_async("Out on an adventure...", self.controller.adventure,
                       self.show_adventure, self.show_adventure_error)

    def show_adventure_error(self, message):
        self.status.configure(text=message, text_color=BAD)

    def show_adventure(self, res):
        r = res["result"]
        self.show_cultivator(res["data"])
        ctk = self.ctk
        if getattr(self, "adv_dialog", None) is not None and self.widget_alive(self.adv_dialog):
            self.adv_dialog.destroy()
        dlg = ctk.CTkToplevel(self.root)
        self.adv_dialog = dlg
        dlg.title(r["title"])
        dlg.geometry("560x340")
        dlg.configure(fg_color=PANEL)
        try:
            dlg.transient(self.root)
        except Exception:
            pass
        good = r["kind"] in ("treasure", "friend", "gain", "reborn")
        color = {"loss": BAD, "rebirth_fail": BAD}.get(r["kind"], ACCENT if good else MUTED)
        ctk.CTkLabel(dlg, text=r["title"], font=self.title_font, text_color=color
                     ).pack(padx=24, pady=(22, 8))
        ctk.CTkLabel(dlg, text=r["text"], font=self.body_font, wraplength=490, justify="left"
                     ).pack(padx=30, pady=8)
        ctk.CTkButton(dlg, text="Close", command=dlg.destroy, width=140).pack(pady=20)
        self.focus_dialog(dlg)

    def centered_chip(self, parent, text, color):
        """A chip in the middle of a box (chip() itself packs to the left)."""
        holder = self.ctk.CTkFrame(parent, fg_color="transparent")
        holder.pack()
        self.chip(holder, text, color)

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

    def affinity_image(self, element):
        """Cache theme-aware icons; keep affinity text usable when assets are unavailable."""
        if element not in gamedata.ELEMENTS and element != "Death risk":
            return None
        if element not in self.affinity_images:
            import io
            import base64
            image = None
            path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "assets", "icons", "affinities", element.lower() + ".png")
            if element == "Death risk":
                path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "icons", "status", "skull.png")
            payload = None
            try:
                with open(path, "rb") as stream:
                    payload = stream.read()
            except OSError:
                pass
            # Try bundled originals too if a loose file is missing or damaged.
            def sources():
                if payload:
                    yield payload
            for payload in sources():
                try:
                    from PIL import Image
                    with Image.open(io.BytesIO(payload)) as source:
                        pixels = source.convert("RGBA")
                    image = self.ctk.CTkImage(light_image=pixels, dark_image=pixels, size=(28, 28))
                    break
                except (ImportError, OSError, ValueError, AttributeError):
                    try:
                        import tkinter
                        native = tkinter.PhotoImage(master=self.root, data=base64.b64encode(payload).decode("ascii"))
                        image = native.subsample(max(1, round(max(native.width(), native.height()) / 28)))
                        break
                    except (ImportError, tkinter.TclError, AttributeError):
                        pass
            if image is not None:
                self.affinity_images[element] = image
            else:
                logs.RUN_LOG.note(f"Could not load {element} affinity icon; expected file: {path}")
            return image
        return self.affinity_images[element]

    def affinity_label(self, parent, element, text=None, **kwargs):
        image = self.affinity_image(element)
        import tkinter
        if isinstance(image, tkinter.PhotoImage):
            # Native Tk images belong on native Tk widgets. Passing them to CTkLabel
            # produces a DPI warning even though the image renders correctly.
            frame = self.ctk.CTkFrame(parent, fg_color="transparent")
            background = frame._apply_appearance_mode(frame.cget("bg_color"))
            icon = tkinter.Label(frame, image=image, background=background,
                                 borderwidth=0, highlightthickness=0)
            icon.pack(side="left", padx=(0, 6))
            caption = self.ctk.CTkLabel(frame, text=element if text is None else text, **kwargs)
            caption.pack(side="left", fill="x", expand=True)
            frame.affinity_image = image
            return frame
        if image is not None:
            kwargs.update(image=image, compound="left", padx=6)
        caption = element if text is None else text
        if image is None and element in gamedata.ELEMENTS:
            caption += " (icon unavailable)"
        label = self.ctk.CTkLabel(parent, text=caption, **kwargs)
        label.affinity_image = image  # retain a reference for the lifetime of the widget
        return label

    def table(self, parent, rows, label_width=110, content_width=WIDE):
        ctk = self.ctk
        grid = ctk.CTkFrame(parent, fg_color=PANEL_2, corner_radius=8)
        grid.pack(fill="x", padx=6)
        for label, value in rows:
            row = ctk.CTkFrame(grid, fg_color="transparent")
            row.pack(fill="x", padx=10, pady=2)
            ctk.CTkLabel(row, text=label, width=label_width, anchor="nw", text_color=MUTED,
                         font=self.body_font).pack(side="left", anchor="n", padx=(0, 18))
            if label == "Affinity":
                value_label = self.affinity_label(row, value, anchor="w", font=self.body_font)
            elif label == "Death risk":
                value_label = self.affinity_label(row, "Death risk", text=value, anchor="w", font=self.body_font)
            else:
                value_label = ctk.CTkLabel(row, text=value, anchor="w", justify="left",
                                           wraplength=content_width - label_width - 38, font=self.body_font)
            value_label.pack(side="left", fill="x", expand=True)

    def paragraph(self, parent, text, muted=False, width=WIDE):
        self.ctk.CTkLabel(parent, text=text, anchor="w", justify="left", wraplength=width,
                          font=self.body_font, text_color=MUTED if muted else TEXT
                          ).pack(fill="x", padx=12, pady=3)

    # -- breakthrough dialog ---------------------------------------------------------------
    def do_breakthrough(self):
        self.run_async("Checking the realm...", self.controller.breakthrough_info,
                       self.show_breakthrough_dialog)

    @staticmethod
    def widget_alive(w):
        try:
            return bool(w.winfo_exists())
        except Exception:
            return False

    def show_breakthrough_dialog(self, info):
        ctk = self.ctk
        if self.bt_dialog is not None and self.widget_alive(self.bt_dialog):
            self.bt_dialog.destroy()
        dlg = ctk.CTkToplevel(self.root)
        self.bt_dialog = dlg
        dlg.title("Breakthrough")
        dlg.geometry("560x640")
        dlg.configure(fg_color=PANEL)
        try:
            dlg.transient(self.root)
        except Exception:
            pass
        ctk.CTkLabel(dlg, text=f"Breakthrough - {info['name']}", font=self.title_font,
                     text_color=ACCENT).pack(padx=24, pady=(22, 4))
        ctk.CTkLabel(dlg, text=f"{info['current']}   ->   {info['next'] or '-'}",
                     font=self.head_font).pack(padx=24)
        if not info["can"]:
            ctk.CTkLabel(dlg, text=info["reason"], font=self.body_font, text_color=BAD,
                         wraplength=480, justify="left").pack(padx=30, pady=24)
            ctk.CTkButton(dlg, text="Close", command=dlg.destroy, width=140).pack(pady=(0, 24))
            self.focus_dialog(dlg)
            return
        state = {"pill": False}
        chance = ctk.CTkLabel(dlg, text="", font=ctk.CTkFont(size=40, weight="bold"),
                              text_color=ACCENT)
        chance.pack(pady=(14, 0))
        bar = ctk.CTkProgressBar(dlg, width=420, progress_color="#7b5fd1")
        bar.pack(pady=(4, 10))
        box = ctk.CTkFrame(dlg, fg_color=PANEL_2, corner_radius=8)
        box.pack(fill="x", padx=30)
        lines = ctk.CTkLabel(box, text="", font=self.body_font, justify="left", anchor="w")
        lines.pack(fill="x", padx=14, pady=10)

        def show():
            part = info["with_pill"] if state["pill"] else info["plain"]
            chance.configure(text=f"{part['total'] * 100:g}%")
            bar.set(part["total"])
            lines.configure(text="\n".join(part["lines"]))
        show()
        pill_var = self.tk.BooleanVar(value=False)
        if info["pills"]:
            def toggle():
                state["pill"] = bool(pill_var.get())
                show()
            ctk.CTkCheckBox(dlg, text=f"Swallow a Heaven-Defying Breakthrough Pill "
                                      f"(+{info['pill_bonus'] * 100:g}%, you own {info['pills']})",
                            variable=pill_var, command=toggle, font=self.body_font,
                            fg_color=ACCENT, hover_color="#a8862f").pack(pady=(12, 0))
        else:
            ctk.CTkLabel(dlg, text="A Heaven-Defying Breakthrough Pill (+30%) can be bought in the "
                         "Pavilion for 5,000 sect points.", font=self.small_font, text_color=MUTED,
                         wraplength=470).pack(pady=(12, 0))
        ctk.CTkLabel(dlg, text=info["risk"], font=self.body_font, wraplength=480, justify="left",
                     text_color=BAD if info["fatal"] else MUTED).pack(padx=30, pady=(12, 0))
        result = ctk.CTkLabel(dlg, text="", font=self.body_font, wraplength=480, justify="left")
        result.pack(padx=30, pady=(8, 0))
        row = ctk.CTkFrame(dlg, fg_color="transparent")
        row.pack(pady=18)
        attempt = ctk.CTkButton(row, text="Attempt breakthrough", fg_color="#7b5fd1",
                                hover_color="#5f47a8", width=200)
        close = ctk.CTkButton(row, text="Cancel", command=dlg.destroy, fg_color=PANEL_2, width=120)

        def go():
            attempt.configure(state="disabled")
            use = state["pill"]

            def done(res):
                if not self.widget_alive(dlg):
                    return
                r = res["result"]
                result.configure(text=progress.breakthrough_result_text(info["name"], r),
                                 text_color=GOOD if r["success"] else BAD)
                close.configure(text="Close")
                self.show_cultivator(res["data"])

            def failed(message):
                if self.widget_alive(dlg):
                    result.configure(text=message, text_color=BAD)
                    close.configure(text="Close")
            self.run_async("The breakthrough begins...", lambda: self.controller.breakthrough(use),
                           done, failed)
        attempt.configure(command=go)
        attempt.pack(side="left", padx=8)
        close.pack(side="left", padx=8)
        self.focus_dialog(dlg)

    @staticmethod
    def focus_dialog(dlg):
        try:
            dlg.lift()
            dlg.focus()
            dlg.grab_set()           # the main window waits until the dialog is closed
        except Exception:
            pass

    # -- tab: history ----------------------------------------------------------------------
    def build_history_tab(self, tab):
        ctk = self.ctk
        self.hist_head = ctk.CTkLabel(tab, text="History", font=self.head_font, anchor="w",
                                      text_color=ACCENT)
        self.hist_head.pack(fill="x", padx=6, pady=(4, 6))
        self.hist_list = ctk.CTkScrollableFrame(tab, fg_color=PANEL, corner_radius=10)
        self.hist_list.pack(fill="both", expand=True)
        self.say(self.hist_list, "Look up a cultivator to see what they did recently.")

    def refresh_history(self):
        if self.working or self.controller is None:
            return
        self.run_async("Reading the history...", self.controller.history, self.show_history,
                       lambda m: self.say(self.hist_list, m, BAD, 30))

    def show_history(self, data):
        ctk = self.ctk
        self.hist_head.configure(text=f"Recent history of {data['name']}")
        if not data["entries"]:
            self.say(self.hist_list, "Nothing yet: no duels, purchases or breakthroughs.")
            return
        body = self.fresh(self.hist_list)
        for e in data["entries"]:
            label, color = HISTORY_KINDS.get(e["kind"], (e["kind"], MUTED))
            row = ctk.CTkFrame(body, fg_color=PANEL_2, corner_radius=8)
            row.pack(fill="x", padx=6, pady=3)
            ctk.CTkLabel(row, text=f"  {label}  ", fg_color=color, text_color="#101010",
                         corner_radius=10, font=self.small_font, width=110).pack(side="left", padx=10, pady=8)
            text = ctk.CTkFrame(row, fg_color="transparent")
            text.pack(side="left", fill="x", expand=True)
            ctk.CTkLabel(text, text=e["text"], font=self.body_font, anchor="w", justify="left",
                         wraplength=WIDE - 190).pack(fill="x")
            ctk.CTkLabel(text, text=e["when"], font=self.small_font, text_color=MUTED,
                         anchor="w").pack(fill="x")

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
        sold = data.get("sold")
        ctk, c = self.ctk, data["c"]
        body = self.fresh(self.pav_list)
        self.buy_buttons = []
        self.pav_head.configure(text=f"Sect Martial Pavilion - {c['name']} of the {c['sect']}"
                                     f"     Sect points: {c['sect_points']:,}")
        if sold:
            self.pav_msg.configure(
                text=f"{c['name']} sold {sold['name']} for {sold['price']:,} sect points "
                     f"(half of its {sold['value']:,} value).", text_color=GOOD)
        elif receipt:
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
        self.section(body, "Sell treasures (the pavilion pays half the value)")
        if not data.get("sells"):
            self.paragraph(body, "No treasures to sell.", muted=True)
        for r in data.get("sells", []):
            row = ctk.CTkFrame(body, fg_color=PANEL_2, corner_radius=8)
            row.pack(fill="x", padx=6, pady=3)
            ctk.CTkLabel(row, text=f"{r['name']}   -   pays {r['price']:,}  (worth {r['value']:,})",
                         font=self.body_font, anchor="w", justify="left", wraplength=WIDE - 160
                         ).pack(side="left", fill="x", expand=True, padx=10, pady=8)
            b = ctk.CTkButton(row, text="Sell", width=110, fg_color="#c667d8",
                              hover_color="#9d4fad", text_color="#101010",
                              command=lambda n=r["number"]: self.do_sell(n))
            b.intended_state = "normal"
            b.pack(side="right", padx=10)
            self.buy_buttons.append(b)

    def do_sell(self, number):
        self.run_async("Selling...", lambda: self.controller.sell(number),
                       self.show_shop, self.show_buy_error)

    def do_buy(self, number):
        self.run_async("Buying...", lambda: self.controller.buy(number),
                       lambda rec: self.show_shop(rec, rec), self.show_buy_error)

    def show_buy_error(self, message):
        self.pav_msg.configure(text=message, text_color=BAD)

    # -- tab: duel -------------------------------------------------------------------------
    def build_duel_tab(self, tab):
        """The Battles tab: three buttons (Duel, Team Battle, Sect War), and the duel below."""
        ctk = self.ctk
        modes = ctk.CTkFrame(tab, fg_color="transparent")
        modes.pack(fill="x", pady=(4, 6))
        self.duel_mode_button = ctk.CTkButton(modes, text="Duel", width=150, height=36,
                                              fg_color=BAD, hover_color="#b84848",
                                              command=self.focus_duel)
        self.duel_mode_button.pack(side="left", padx=(0, 8))
        self.team_button = ctk.CTkButton(modes, text="Team Battle", width=150, height=36,
                                         fg_color="#3f7fd1", hover_color="#2f62a3",
                                         command=self.open_team_window)
        self.team_button.pack(side="left", padx=8)
        self.sect_war_button = ctk.CTkButton(modes, text="Sect War", width=150, height=36,
                                             state="disabled", fg_color="#3a3f4d",
                                             text_color_disabled="#7d8497")
        self.sect_war_button.pack(side="left", padx=8)           # not available yet
        top = ctk.CTkFrame(tab, fg_color="transparent")
        top.pack(fill="x", pady=(4, 8))
        self.duel_kind=ctk.CTkOptionMenu(modes,values=list(gamedata.DUEL_MODES))
        self.duel_kind.set('Sparring');self.duel_kind.pack(side='right',padx=8)
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
        self.say(self.duel_area, "Enter two profiles and let their cultivators duel, or press "
                                 "Team Battle for 2 vs 2 and 3 vs 3. Both fighters must be present at the same location. Sparring is harmless; competitive fights have a 5% injury chance; lethal duels risk death.")

    def focus_duel(self):
        try:
            self.duel_entries[0].focus()
        except Exception:
            pass

    # -- the team battle window --------------------------------------------------------------
    def open_team_window(self):
        if self.controller is None:
            return
        ctk = self.ctk
        if self.team_dialog is not None and self.widget_alive(self.team_dialog):
            try:
                self.team_dialog.lift()
                self.team_dialog.focus()
            except Exception:
                pass
            return
        dlg = ctk.CTkToplevel(self.root)
        self.team_dialog = dlg
        dlg.title("Team Battle")
        dlg.geometry("1020x860")
        dlg.configure(fg_color=PANEL)
        try:
            dlg.transient(self.root)
        except Exception:
            pass
        ctk.CTkLabel(dlg, text="Team Battle", font=self.title_font, text_color=ACCENT
                     ).pack(pady=(14, 0))
        ctk.CTkLabel(dlg, text="Type a profile for every slot, or pick from the recently looked-up "
                     "cultivators below. Team One fights on the left, Team Two on the right.",
                     font=self.small_font, text_color=MUTED, wraplength=900).pack(pady=(0, 6))
        sizes = ctk.CTkFrame(dlg, fg_color="transparent")
        sizes.pack(pady=4)
        self.team_size_buttons = {}
        for n in (2, 3):
            b = ctk.CTkButton(sizes, text=f"{n} vs {n}", width=110,
                              command=lambda n=n: self.set_team_size(n))
            b.pack(side="left", padx=4)
            self.team_size_buttons[n] = b
        cols = ctk.CTkFrame(dlg, fg_color="transparent")
        cols.pack(fill="x", padx=16, pady=4)
        cols.grid_columnconfigure((0, 1), weight=1)
        self.team_entries = {"a": [], "b": []}
        for col, (side, title, color) in enumerate((("a", "Team One", "#5fb3ff"),
                                                    ("b", "Team Two", "#e0a85f"))):
            box = ctk.CTkFrame(cols, fg_color=PANEL_2, corner_radius=10)
            box.grid(row=0, column=col, sticky="nsew", padx=6)
            ctk.CTkLabel(box, text=title, font=self.head_font, text_color=color).pack(pady=(10, 4))
            for n in range(3):
                e = ctk.CTkEntry(box, placeholder_text=f"Fighter {n + 1}: URL, name or SteamID64",
                                 height=34)
                e.pack(fill="x", padx=12, pady=3)
                self.team_entries[side].append(e)
            ctk.CTkButton(box, text="Clear", width=80, fg_color=PANEL,
                          command=lambda sd=side: self.clear_team(sd)).pack(pady=(4, 10))
        self.team_recent_box = ctk.CTkFrame(dlg, fg_color=PANEL_2, corner_radius=10)
        self.team_recent_box.pack(fill="x", padx=22, pady=8)
        row = ctk.CTkFrame(dlg, fg_color="transparent")
        row.pack(pady=(2, 0))
        self.team_start = ctk.CTkButton(row, text="Start team battle", width=200, height=38,
                                        fg_color=BAD, hover_color="#b84848",
                                        command=self.do_team_battle)
        self.team_start.pack(side="left", padx=6)
        ctk.CTkButton(row, text="Close", width=110, height=38, fg_color=PANEL_2,
                      command=dlg.destroy).pack(side="left", padx=6)
        self.team_msg = ctk.CTkLabel(dlg, text="", font=self.body_font, text_color=MUTED,
                                     wraplength=900, justify="left")
        self.team_msg.pack(pady=(4, 2))
        self.team_result = ctk.CTkScrollableFrame(dlg, fg_color=PANEL, corner_radius=10)
        self.team_result.pack(fill="both", expand=True, padx=16, pady=(0, 14))
        self.set_team_size(2)
        self.refresh_team_recent()

    def set_team_size(self, n):
        self.team_size = n
        for size, b in self.team_size_buttons.items():
            b.configure(fg_color=ACCENT if size == n else PANEL_2,
                        text_color="#1a1a1a" if size == n else TEXT)
        for side in ("a", "b"):
            third = self.team_entries[side][2]
            if n == 2:
                third.delete(0, "end")
                third.configure(state="disabled")
            else:
                third.configure(state="normal")

    def clear_team(self, side):
        for e in self.team_entries[side]:
            if str(e.cget("state") or "normal") != "disabled":
                e.delete(0, "end")

    def refresh_team_recent(self):
        """Redraws the 'recently looked up' list (never shows the selected cultivator)."""
        if self.team_dialog is None or not self.widget_alive(self.team_dialog) or self.controller is None:
            return
        ctk = self.ctk
        body = self.fresh(self.team_recent_box)
        ctk.CTkLabel(body, text="Recently looked up (the selected cultivator is not listed)",
                     font=self.head_font, text_color=ACCENT, anchor="w").pack(fill="x", padx=12, pady=(8, 2))
        recent = self.controller.recent_list()
        if not recent:
            ctk.CTkLabel(body, text="Nobody yet: look up some profiles in the Cultivator tab.",
                         font=self.small_font, text_color=MUTED, anchor="w").pack(fill="x", padx=12, pady=(0, 8))
            return
        for e in recent:
            row = ctk.CTkFrame(body, fg_color="transparent")
            row.pack(fill="x", padx=10, pady=1)
            ctk.CTkLabel(row, text=f"{e['name']}    ({e['steamid']})", font=self.body_font,
                         anchor="w").pack(side="left", fill="x", expand=True)
            ctk.CTkButton(row, text="Team Two", width=90, height=26, fg_color="#e0a85f",
                          text_color="#1a1a1a", hover_color="#b88840",
                          command=lambda sid=e["steamid"]: self.add_to_team("b", sid)
                          ).pack(side="right", padx=3)
            ctk.CTkButton(row, text="Team One", width=90, height=26, fg_color="#5fb3ff",
                          text_color="#1a1a1a", hover_color="#4a8fcc",
                          command=lambda sid=e["steamid"]: self.add_to_team("a", sid)
                          ).pack(side="right", padx=3)
        ctk.CTkLabel(body, text="", height=4).pack()

    def add_to_team(self, side, steamid):
        """Puts a recent cultivator in the first free slot of a team."""
        used = [e.get().strip() for sd in ("a", "b") for e in self.team_entries[sd][:self.team_size]]
        name = "Team One" if side == "a" else "Team Two"
        if steamid in used:
            self.team_msg.configure(text="That cultivator is already on a team.", text_color=BAD)
            return
        for e in self.team_entries[side][:self.team_size]:
            if not e.get().strip():
                e.insert(0, steamid)
                self.team_msg.configure(text="", text_color=MUTED)
                return
        self.team_msg.configure(text=f"{name} is full ({self.team_size} fighters).", text_color=BAD)

    def do_team_battle(self):
        a = [e.get() for e in self.team_entries["a"][:self.team_size]]
        b = [e.get() for e in self.team_entries["b"][:self.team_size]]
        self.team_msg.configure(text="", text_color=MUTED)
        self.run_async("The teams clash...", lambda: self.controller.team_battle(a, b),
                       self.show_team_result, self.show_team_error)

    def show_team_error(self, message):
        if self.team_dialog is not None and self.widget_alive(self.team_dialog):
            self.team_msg.configure(text=message, text_color=BAD)

    def show_team_result(self, d):
        if self.team_dialog is None or not self.widget_alive(self.team_dialog):
            return
        ctk, result = self.ctk, d["result"]
        body = self.fresh(self.team_result)
        sides = ctk.CTkFrame(body, fg_color="transparent")
        sides.pack(fill="x", padx=6, pady=(6, 10))
        sides.grid_columnconfigure((0, 1), weight=1)
        for col, (side, title) in enumerate((("a", "Team One"), ("b", "Team Two"))):
            team, p = d["team_" + side], result["p_" + side]
            won = result["winner_side"] == side
            box = ctk.CTkFrame(sides, fg_color=PANEL_2, corner_radius=10,
                               border_width=2 if won else 0, border_color=GOOD)
            box.grid(row=0, column=col, sticky="nsew", padx=6)
            ctk.CTkLabel(box, text=("WINNER  " if won else "") + title, font=self.head_font,
                         text_color=GOOD if won else TEXT).pack(padx=12, pady=(10, 0))
            ctk.CTkLabel(box, text=f"{teambattle.team_type(team)} team", font=self.small_font,
                         text_color=MUTED).pack()
            for c in team:
                ctk.CTkLabel(box, text=c["name"], font=self.head_font).pack(pady=(8, 0))
                self.centered_chip(box, c["path"]["name"], PATH_COLORS.get(c["path"]["name"], "#999999"))
                for line in (f"{c['realm']}   -   power {c['score']:,.0f}", f"{c['element']}, {c['talent']['name']}"):
                    ctk.CTkLabel(box, text=line, font=self.small_font, text_color=MUTED).pack()
            pb = ctk.CTkProgressBar(box, progress_color=GOOD if won else BAD, width=220)
            pb.set(p)
            pb.pack(pady=(10, 2))
            ctk.CTkLabel(box, text=f"Win chance {p * 100:.1f}%", font=self.small_font,
                         text_color=MUTED).pack(pady=(0, 10))
        self.section(body, "The battle")
        self.paragraph(body, d["story"])
        self.section(body, "Report")
        box = ctk.CTkTextbox(body, height=420, font=self.mono_font, wrap="none", fg_color=PANEL_2)
        box.pack(fill="x", padx=8, pady=(0, 10))
        box.insert("end", d["report"])
        box.configure(state="disabled")
        winners = d["team_a"] if result["winner_side"] == "a" else d["team_b"]
        self.status.configure(text=f"{teambattle.names_text(winners)} win the team battle.",
                              text_color=GOOD)

    def do_duel(self):
        a, b = (e.get() for e in self.duel_entries)
        mode=self.duel_kind.get()
        if mode=="Lethal" and not messagebox.askyesno("Lethal duel", "The loser has a 15% chance of death; survivors are injured. Proceed?",parent=self.root):return
        self.run_async("The duel begins...", lambda: self.controller.duel(a, b,mode=mode),
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
            self.centered_chip(box, c["path"]["name"], PATH_COLORS.get(c["path"]["name"], "#999999"))
            for line in (c["realm"], f"Power {c['score']:,.0f}", f"{c['talent']['name']}"):
                ctk.CTkLabel(box, text=line, font=self.small_font).pack()
            self.affinity_label(box, c["element"], text=f"Affinity: {c['element']}",
                                font=self.small_font).pack()
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
    if "--devtools" in sys.argv[1:]:
        import argparse
        parser = argparse.ArgumentParser(description="Steam Cultivator developer tools")
        parser.add_argument("--devtools", action="store_true")
        parser.add_argument("--cache", type=Path, default=Path(storage.CACHE_DIR))
        args = parser.parse_args()
        DeveloperEditor(args.cache).mainloop()
        return
    try:
        import customtkinter as ctk
    except ImportError:
        sys.exit("The window version needs CustomTkinter. Install it with:\n"
                 "    pip install customtkinter\n"
                 "(the terminal version, steam_cultivator.py, works without it).")
    offline = "--offline" in sys.argv[1:]
    App(ctk, "" if offline else os.environ.get("STEAM_API_KEY"), offline=offline).run()


if __name__ == "__main__":
    main()

