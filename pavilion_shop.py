"""The sect's Martial Pavilion: buying goods and selling treasures for half their value."""

import random
import time

import gamedata
import generator
import logs
import storage


# ---------------------------------------------------------------------------
# The Martial Pavilion: the "pavilion" command. It always serves the cultivator you looked
# up last in this run (session["latest"]); looking up another profile makes that one the
# latest. mocb does not change it.
# ---------------------------------------------------------------------------
def pavilion_status(c, item):
    """'you can afford it', 'need 120 more', 'already owned'... for one item."""
    owned = c["pavilion"]["items"].get(item["id"], 0)
    if item["kind"] == "Weapon" and owned:
        return "already owned"
    price = item["price"]
    if price > c["sect_points"]:
        return f"need {price - c['sect_points']:,} more"
    return "you can afford it" + (f" (you own {owned})" if owned else "")


def pavilion_goods_text(c):
    """What a cultivator holds from the pavilion, for the purchase receipt."""
    goods = generator.describe_goods(c["pavilion"]["items"])
    return goods or "nothing yet"


def buy_pavilion_item(steamid, c, number):
    """Buys item number `number` (1-based, as listed) for the cultivator c: the sect points
    are spent, and the item is written into their JSON file (a treasure goes into the
    treasure inventory, everything else into the pavilion goods). One write, so a purchase is
    never half done. Raises SteamError if the choice is not valid or too expensive."""
    try:
        n = int(str(number).strip().lstrip("#"))
    except ValueError:
        raise logs.SteamError(f"'{number}' is not an item number. Pick one from 1 to {len(gamedata.PAVILION_ITEMS)}.")
    if not 1 <= n <= len(gamedata.PAVILION_ITEMS):
        raise logs.SteamError(f"There is no item number {n}. Pick one from 1 to {len(gamedata.PAVILION_ITEMS)}.")
    item = gamedata.PAVILION_ITEMS[n - 1]
    pav = c["pavilion"]
    if item["kind"] == "Weapon" and pav["items"].get(item["id"], 0):
        raise logs.SteamError(f"{c['name']} already owns {item['name']}; one is enough.")
    if item["price"] > c["sect_points"]:
        raise logs.SteamError(f"Not enough sect points: {item['name']} costs {item['price']:,}, "
                              f"but {c['name']} has {c['sect_points']:,}.")
    now = time.time()
    spent = pav["spent"] + item["price"]
    items = dict(pav["items"])
    event = {"at": now, "type": "bought", "item": item["name"], "price": item["price"]}
    pc = storage.load_profile_cache(steamid)
    if item["kind"] == "Treasure":
        inv = pc.get("inventory")
        if not storage.inventory_valid(inv):
            inv = {"treasures": generator.treasures_of(c), "history": list(c.get("inventory_history", []))}
        inv["treasures"] = list(inv["treasures"]) + [item["name"]]
        inv["history"] = (inv["history"] + [{"at": now, "type": "bought", "item": item["name"],
                                              "other": None}])[-storage.INVENTORY_HISTORY_LIMIT:]
        pc["inventory"] = inv
        c["treasures"] = inv["treasures"]
        c["treasure"] = generator.prized_treasure(inv["treasures"]) or gamedata.FALLBACK_TREASURE
        c["inventory_history"] = inv["history"]
    else:
        items[item["id"]] = items.get(item["id"], 0) + 1
    history = (pav["history"] + [event])[-storage.INVENTORY_HISTORY_LIMIT:]
    pc["pavilion"] = {"items": items, "spent": spent, "earned": c["sect_points_earned"],
                      "bonus": pav.get("bonus", 0), "history": history}
    storage.save_profile_cache(pc)
    c["pavilion"] = dict(pc["pavilion"])
    c["sect_points"] = generator.points_left(c)
    logs.RUN_LOG.note(f"pavilion: {c['name']} ({steamid}) bought {item['name']} for {item['price']} "
                      f"sect points, {c['sect_points']} left")
    return item


def pavilion_target(key, profiles, session, command="pavilion"):
    """The cultivator the pavilion serves: the latest one looked up, freshly loaded so the
    current sect points are used. Returns (steamid, cultivator); raises SteamError if nobody
    has been selected yet or the cultivator is dead."""
    steamid = session.get("latest")
    if not steamid:
        raise logs.SteamError("No cultivator has been selected yet. Look up a Steam profile first, "
                              f"then type '{command}' for that cultivator.")
    info, _, _, c = generator.build_cultivator(steamid, key, profiles)
    if c["death"]:
        raise logs.SteamError(f"{c['name']} died in Year {c['death']['year']} of the Heavenly "
                              + ("Calendar. The dead have no use for the Martial Pavilion."
                                 if command == "pavilion" else "Calendar. The dead cannot sell anything."))
    return steamid, c


# ---------------------------------------------------------------------------
# Selling treasures ("sell" command, Pavilion tab in the window). Every treasure has a value in
# sect points; a treasure bought in the pavilion is worth its pavilion price, any other one a
# fixed value picked from the range of its tier (by its name, so it never changes). The
# pavilion pays SELL_RATE (50%) of it.
# ---------------------------------------------------------------------------
SELL_RATE = 0.5
TREASURE_VALUE_RANGE = [(100, 300), (600, 1600), (2500, 6000)]      # by treasure tier, low/mid/high


def treasure_value(name):
    """What a treasure is worth in sect points (before the markdown)."""
    for item in gamedata.PAVILION_ITEMS:
        if item["kind"] == "Treasure" and item["name"] == name:
            return item["price"]
    lo, hi = TREASURE_VALUE_RANGE[generator.treasure_rank(name)]
    return random.Random(f"value-{name}").randint(lo // 50, hi // 50) * 50


def sale_price(name):
    return int(treasure_value(name) * SELL_RATE)


def sell_rows(c):
    """One dict per treasure owned: number (1-based), name, value and what the pavilion pays."""
    return [{"number": n, "name": t, "value": treasure_value(t), "price": sale_price(t)}
            for n, t in enumerate(generator.treasures_of(c), 1)]


def sell_treasure(steamid, c, number):
    """Sells treasure number `number` (as listed by sell_rows) for half its value. The treasure
    leaves the inventory and the sect points are credited, in one write. Raises SteamError."""
    rows = sell_rows(c)
    if not rows:
        raise logs.SteamError(f"{c['name']} owns no treasure to sell.")
    try:
        n = int(str(number).strip().lstrip("#"))
    except ValueError:
        raise logs.SteamError(f"'{number}' is not a treasure number. Pick one from 1 to {len(rows)}.")
    if not 1 <= n <= len(rows):
        raise logs.SteamError(f"There is no treasure number {n}. Pick one from 1 to {len(rows)}.")
    row = rows[n - 1]
    now = time.time()
    pc = storage.load_profile_cache(steamid)
    inv = pc.get("inventory")
    if not storage.inventory_valid(inv):
        inv = {"treasures": generator.treasures_of(c), "history": list(c.get("inventory_history", []))}
    items = list(inv["treasures"])
    items.remove(row["name"])                                    # one copy
    inv["treasures"] = items
    inv["history"] = (inv["history"] + [{"at": now, "type": "sold", "item": row["name"],
                                          "other": None, "price": row["price"]}])[-storage.INVENTORY_HISTORY_LIMIT:]
    pc["inventory"] = inv
    pav = pc.get("pavilion") if isinstance(pc.get("pavilion"), dict) else None
    cur = storage.read_pavilion(steamid)
    cur["bonus"] += row["price"]
    cur["earned"] = max(cur["earned"], c["sect_points_earned"])
    pc["pavilion"] = {"items": cur["items"], "spent": cur["spent"], "earned": cur["earned"],
                      "bonus": cur["bonus"], "history": cur["history"]}
    storage.save_profile_cache(pc)
    c["treasures"] = items
    c["treasure"] = generator.prized_treasure(items) or gamedata.FALLBACK_TREASURE
    c["inventory_history"] = inv["history"]
    c["pavilion"] = dict(pc["pavilion"])
    c["sect_points"] = generator.points_left(c)
    logs.RUN_LOG.note(f"sell: {c['name']} ({steamid}) sold {row['name']} for {row['price']} sect points "
                      f"(worth {row['value']}), now {c['sect_points']}")
    return row
