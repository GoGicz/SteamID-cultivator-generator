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
def discounted_item(c, item):
    original = item.get("original_price", item["price"])
    tier = 0 if original < 500 else 1 if original < 2000 else 2 if original < 5000 else 3
    rank = c.get("sect_status", {}).get("rank_index", 0)
    discount = gamedata.SECT_DISCOUNTS[rank][tier]
    return dict(item, original_price=original, discount=discount,
                price=(original * (100 - discount) + 99) // 100)


def pavilion_status(c, item):
    """'you can afford it', 'need 120 more', 'already owned'... for one item."""
    owned = c["pavilion"]["items"].get(item["id"], 0)
    if item["kind"] == "Weapon" and owned:
        return "already owned"
    price = discounted_item(c, item)["price"]
    if price > c["sect_points"]:
        return f"need {price - c['sect_points']:,} more"
    return "you can afford it" + (f" (you own {owned})" if owned else "")


def pavilion_goods_text(c):
    """What a cultivator holds from the pavilion, for the purchase receipt."""
    goods = generator.describe_goods(c["pavilion"]["items"])
    return goods or "nothing yet"


@storage.atomic
def buy_pavilion_item(steamid, c, number):
    """Buys item number `number` (1-based, as listed) for the cultivator c: the sect points
    are spent, and the item is written into their JSON file (a treasure goes into the
    treasure inventory, everything else into the pavilion goods). One write, so a purchase is
    never half done. Raises SteamError if the choice is not valid or too expensive."""
    require_market(steamid,"sect")
    try:
        n = int(str(number).strip().lstrip("#"))
    except ValueError:
        raise logs.SteamError(f"'{number}' is not an item number. Pick one from 1 to {len(gamedata.PAVILION_ITEMS)}.")
    if not 1 <= n <= len(gamedata.PAVILION_ITEMS):
        raise logs.SteamError(f"There is no item number {n}. Pick one from 1 to {len(gamedata.PAVILION_ITEMS)}.")
    item = discounted_item(c, gamedata.PAVILION_ITEMS[n - 1])
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
    else:
        items[item["id"]] = items.get(item["id"], 0) + 1
    history = (pav["history"] + [event])[-storage.INVENTORY_HISTORY_LIMIT:]
    pc["pavilion"] = {"items": items, "spent": spent, "earned": c["sect_points_earned"],
                      "bonus": pav.get("bonus", 0), "history": history}
    if not storage.save_profile_cache(pc, durable=True):
        raise logs.SteamError("Purchase could not be saved. Check cache write permissions.")
    if item["kind"] == "Treasure":
        c["treasures"] = inv["treasures"]
        c["treasure"] = generator.prized_treasure(inv["treasures"]) or gamedata.FALLBACK_TREASURE
        c["inventory_history"] = inv["history"]
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


@storage.atomic
def sell_treasure(steamid, c, number):
    """Sells treasure number `number` (as listed by sell_rows) for half its value. The treasure
    leaves the inventory and the sect points are credited, in one write. Raises SteamError."""
    require_market(steamid,"sect")
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
    if not storage.save_profile_cache(pc, durable=True):
        raise logs.SteamError("Sale could not be saved. Check cache write permissions.")
    c["treasures"] = items
    c["treasure"] = generator.prized_treasure(items) or gamedata.FALLBACK_TREASURE
    c["inventory_history"] = inv["history"]
    c["pavilion"] = dict(pc["pavilion"])
    c["sect_points"] = generator.points_left(c)
    logs.RUN_LOG.note(f"sell: {c['name']} ({steamid}) sold {row['name']} for {row['price']} sect points "
                      f"(worth {row['value']}), now {c['sect_points']}")
    return row


def markets(actor):
    here=storage.presence(actor)
    site=here.get('location') if here['state']=='present' else None
    result=[]
    if site in gamedata.PUBLIC_SITES:result.append('public')
    with storage.world_transaction() as db:
        row=db.execute('SELECT a.sect_id FROM affiliations a JOIN sect_charters c ON c.sect_id=a.sect_id WHERE a.actor=?',(actor,)).fetchone()
        if row and site:
            seat=storage.seat_location(db,row[0])
            # Refuge can house multiple councils. Each trader uses their own stock and discount.
            if seat and seat[0]==site:result.append('sect')
    return result


def require_market(actor,market):
    storage.require_physical(actor)
    if storage.load_profile_cache(actor).get('life',{}).get('dead'):
        raise logs.SteamError('The dead cannot trade.')
    if market not in markets(actor):
        raise logs.SteamError('Visit one of the five public markets.' if market=='public' else 'Return to your own sect seat to use the Martial Pavilion.')


def consume(actor,item):
    pav=storage.read_pavilion(actor)
    if pav['items'].get(item,0)<1:raise logs.SteamError('You need one '+gamedata.PAVILION_BY_ID[item]['name']+'.')
    pav['items'][item]-=1
    storage.write_pavilion(actor,pav['items'],pav['spent'],dict(at=time.time(),type='pill used',item=gamedata.PAVILION_BY_ID[item]['name']))


@storage.atomic
def heal(actor,item):
    storage.require_physical(actor)
    if item not in ('qi_gathering_pill','meridian_cleansing_pill'):raise logs.SteamError('Choose a healing pill.')
    injury=storage.injury_state(actor)
    if not injury or storage.load_profile_cache(actor).get('life',{}).get('dead'):raise logs.SteamError('A living, injured cultivator is required.')
    day=storage.world_state()['day']
    fraction=.5 if item=='meridian_cleansing_pill' else .15
    until=day+(injury['until_day']-day)*(1-fraction)
    consume(actor,item)
    with storage.world_transaction() as db:db.execute('UPDATE injuries SET until_day=? WHERE actor=?',(until,actor))
    return until


def public_sell_price(item):
    if item in gamedata.PUBLIC_PRICES:return gamedata.PUBLIC_PRICES[item]//2
    return max(1,gamedata.PAVILION_BY_ID[item]['price']//10)


@storage.atomic
def public_trade(actor,c,action,item):
    require_market(actor,'public')
    pc=storage.load_profile_cache(actor)
    balance=storage.read_spirit_stones(actor)
    pav=storage.read_pavilion(actor)
    goods=pav['items']
    if action=='buy':
        if item not in gamedata.PUBLIC_PRICES:raise logs.SteamError('This item is unavailable.')
        price=gamedata.PUBLIC_PRICES[item]
        if balance<price:raise logs.SteamError('Not enough Spirit Stones.')
        goods[item]=goods.get(item,0)+1
        delta=-price
    elif action=='sell goods':
        if item==gamedata.DAO_PILL or item not in gamedata.PAVILION_BY_ID or goods.get(item,0)<1:raise logs.SteamError('This item cannot be sold.')
        delta=public_sell_price(item)
        goods[item]-=1
        if not goods[item]:del goods[item]
    elif action=='sell treasure':
        inv=pc.get('inventory')
        if not inv or item not in inv['treasures']:raise logs.SteamError('This treasure is no longer owned.')
        inv['treasures'].remove(item)
        delta=max(1,sale_price(item)//5)
        inv['history']=(inv['history']+[dict(at=time.time(),type='sold',item=item,other='public pavilion',price=delta)])[-storage.INVENTORY_HISTORY_LIMIT:]
    else:raise logs.SteamError('Unknown trade.')
    name=item if action=='sell treasure' else gamedata.PAVILION_BY_ID[item]['name']
    pc['pavilion']=pav
    pc.setdefault('wallet',{})['spirit_stones']=balance+delta
    storage.save_profile_cache(pc,durable=True)
    receipt=f"{'Bought' if delta<0 else 'Sold'} {name} for {abs(delta)} Spirit Stones."
    storage.add_activity(actor,dict(at=time.time(),type='adventure',summary=receipt))
    return receipt


def shop_duty(db,actor,c,nature,here,day,rng):
    import progress
    items=c['pavilion']['items']
    injury=c.get('injury')
    ready=c['eligible_realm_index']>c['realm_index']
    need=None
    if ready and c['realm_index']==1 and not items.get('foundation_pill'):need='foundation_pill'
    elif ready and c['realm_index'] in range(2,8) and 'Lazy' in nature and not items.get('breakthrough_pill'):need='breakthrough_pill'
    elif 'Lazy' in nature:return False
    elif injury and any(items.get(i) for i in ('meridian_cleansing_pill','qi_gathering_pill')):
        pc=storage.load_profile_cache(actor)
        if pc.get('last_healing_until')!=injury['until_day']:
            item='meridian_cleansing_pill' if items.get('meridian_cleansing_pill') else 'qi_gathering_pill'
            until=heal(actor,item)
            pc=storage.load_profile_cache(actor);pc['last_healing_until']=until
            storage.save_profile_cache(pc,durable=True)
            db.execute("UPDATE npcs SET steps=steps+1,activity='Taking a healing pill',next_day=? WHERE id=?",(day+.1,actor))
            return True
        return False
    elif ready and c['realm_index'] in range(2,8) and 'Ambitious' in nature and not items.get('breakthrough_pill'):need='breakthrough_pill'
    elif items.get('qi_gathering_pill',0)<(3 if 'Cautious' in nature else 1):need='qi_gathering_pill'
    elif 'Cautious' in nature and not items.get('meridian_cleansing_pill'):need='meridian_cleansing_pill'
    if not need:return False
    candidates=[]
    if need in gamedata.PUBLIC_PRICES and c['spirit_stones']>=gamedata.PUBLIC_PRICES[need]:
        candidates.extend((site,'public') for site in gamedata.PUBLIC_SITES)
    index=next((i for i,v in enumerate(gamedata.PAVILION_ITEMS,1) if v['id']==need),None)
    if index and c['sect']!='Wanderer' and discounted_item(c,gamedata.PAVILION_BY_ID[need])['price']<=c['sect_points']:
        row=db.execute('SELECT a.sect_id FROM affiliations a JOIN sect_charters s ON s.sect_id=a.sect_id WHERE a.actor=?',(actor,)).fetchone()
        seat=storage.seat_location(db,row[0]) if row else None
        if seat:candidates.append((seat[0],'sect'))
    if not candidates:return False
    local=next((market for site,market in candidates if site==here['location']),None)
    if local:
        if local=='public':public_trade(actor,c,'buy',need)
        else:buy_pavilion_item(actor,c,index)
        delay=60;activity='Buying '+gamedata.PAVILION_BY_ID[need]['name']
    else:
        view=progress.region_view(actor)
        plans=[progress.route_plan(view,site) for site,_ in candidates]
        plan=min(plans,key=lambda p:(p['seconds'],p['road_seconds']))
        progress.start_journey(actor,plan,view,encounters=True,rng=rng)
        delay=plan['seconds'];activity='Travelling to a pavilion'
    db.execute('UPDATE npcs SET steps=steps+1,activity=?,next_day=? WHERE id=?',(activity,day+delay/storage.world_state()['seconds_per_day'],actor))
    return True
