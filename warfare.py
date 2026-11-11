"""Persistent inter-sect relations, field armies, garrisons and campaign objectives."""
import datetime
import random
import sqlite3
import time

import logs
import storage

MASTER = ('Sect Master','Acting Master')
OBJECTIVES = ('Mine','Pass','Reparations','Headquarters')
FIELD_ORDERS = ('Hold position','Press attack','Cover retreat')
SCHEMA = (
    """CREATE TABLE campaign_sites(site TEXT PRIMARY KEY REFERENCES locations(id),owner TEXT REFERENCES sect_charters(sect_id),
       founding_owner TEXT REFERENCES sect_charters(sect_id),kind TEXT NOT NULL)""",
    """CREATE TABLE foreign_policy(sect TEXT PRIMARY KEY REFERENCES sect_charters(sect_id),review REAL NOT NULL)""",
    """CREATE TABLE foreign_relations(a TEXT REFERENCES sect_charters(sect_id),b TEXT REFERENCES sect_charters(sect_id),
       regard INTEGER NOT NULL DEFAULT 0,treaty TEXT NOT NULL DEFAULT 'Open',until_day REAL NOT NULL DEFAULT 0,
       PRIMARY KEY(a,b),CHECK(a<b))""",
    """CREATE TABLE campaigns(id INTEGER PRIMARY KEY,attacker TEXT NOT NULL REFERENCES sect_charters(sect_id),
       defender TEXT REFERENCES sect_charters(sect_id),site TEXT NOT NULL REFERENCES locations(id),objective TEXT NOT NULL,
       phase TEXT NOT NULL,deadline REAL NOT NULL,next_turn REAL NOT NULL,rounds INTEGER NOT NULL DEFAULT 0,
       control INTEGER NOT NULL DEFAULT 0,loss_a INTEGER NOT NULL DEFAULT 0,loss_d INTEGER NOT NULL DEFAULT 0,
       proposed_by TEXT REFERENCES sect_charters(sect_id),proposed_victory INTEGER CHECK(proposed_victory IN (0,1)),
       result TEXT,commander TEXT REFERENCES profiles(id),defending_commander TEXT REFERENCES profiles(id))""",
    """CREATE TABLE alliance_offers(sender TEXT REFERENCES sect_charters(sect_id),recipient TEXT REFERENCES sect_charters(sect_id),
       expires REAL NOT NULL,PRIMARY KEY(sender,recipient))""",
    "CREATE INDEX active_campaign_attacker ON campaigns(attacker,next_turn) WHERE result IS NULL",
    "CREATE INDEX active_campaign_defender ON campaigns(defender) WHERE result IS NULL",
    "CREATE UNIQUE INDEX contested_site ON campaigns(site) WHERE result IS NULL",
    """CREATE TABLE campaign_forces(actor TEXT PRIMARY KEY REFERENCES profiles(id),campaign INTEGER NOT NULL REFERENCES campaigns(id),
       side TEXT NOT NULL,origin TEXT REFERENCES sect_charters(sect_id),muster TEXT NOT NULL REFERENCES locations(id),
       assembled INTEGER NOT NULL DEFAULT 0,orders TEXT NOT NULL DEFAULT 'Hold position',
       detachment TEXT REFERENCES profiles(id),ready REAL NOT NULL DEFAULT 0)""",
    """CREATE TRIGGER leave_field_on_transfer AFTER UPDATE OF sect_id ON affiliations WHEN OLD.sect_id IS NOT NEW.sect_id
       BEGIN DELETE FROM campaign_forces WHERE actor=NEW.actor;
       DELETE FROM garrison_orders WHERE actor=NEW.actor; END""",
    "CREATE INDEX army_by_campaign ON campaign_forces(campaign,side)",
    """CREATE TABLE garrison_orders(actor TEXT PRIMARY KEY REFERENCES profiles(id),site TEXT NOT NULL REFERENCES locations(id),
       sect TEXT NOT NULL REFERENCES sect_charters(sect_id))""",
)

def migrate(db,path):
    if db.execute('PRAGMA user_version').fetchone()[0]!=7:return
    lease=db.execute('SELECT expires FROM simulation_lease WHERE id=1').fetchone()
    if lease and lease[0]>time.time():
        raise logs.SteamError('Close the other game before upgrading warfare. A crashed lease expires after 30 seconds.')
    folder=path.parent/'migration_backups'
    folder.mkdir(exist_ok=True)
    target=folder/('before_warfare_'+datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f')+'.db')
    backup=sqlite3.connect(target)
    try:
        db.backup(backup)
    finally:
        backup.close()
    db.execute('BEGIN IMMEDIATE')
    if db.execute('PRAGMA user_version').fetchone()[0]==7:
        for statement in SCHEMA:
            db.execute(statement)
        db.execute('PRAGMA user_version=8')
    db.commit()


def initialize(db,day,pace):
    if db.execute('SELECT 1 FROM foreign_policy LIMIT 1').fetchone():
        return
    homes=db.execute('SELECT * FROM locations WHERE sect_id IS NOT NULL ORDER BY id').fetchall()
    if not homes:
        return
    for h in homes:
        sect=h['sect_id']
        db.execute("INSERT INTO campaign_sites VALUES(?,?,?,'Headquarters')",(h['id'],sect,sect))
        wait=random.Random('foreign:'+sect).uniform(1800,5400)
        db.execute('INSERT INTO foreign_policy VALUES(?,?)',(sect,day+wait/pace))
    for r in db.execute('SELECT * FROM locations WHERE district>=5 ORDER BY id'):
        if r['id'].endswith('_0'):
            nearest=min(homes,key=lambda h:(h['x']-r['x'])**2+(h['y']-r['y'])**2)
            db.execute("INSERT INTO campaign_sites VALUES(?,?,?,'Pass')",(r['id'],nearest['sect_id'],nearest['sect_id']))
        elif r['id'].endswith('_2'):
            db.execute("INSERT INTO campaign_sites VALUES(?,NULL,NULL,'Mine')",(r['id'],))


class CampaignRefused(logs.SteamError):
    pass


def error(message):
    raise CampaignRefused(message)


def council(db,sect):
    return db.execute("""SELECT a.actor,a.office,p.name,p.kind FROM affiliations a JOIN profiles p ON p.id=a.actor
        WHERE a.sect_id=? AND a.office IN ('Elder','Acting Master','Sect Master')
        AND json_extract(p.data,'$.life.dead') IS NULL ORDER BY a.actor""",(sect,)).fetchall()


def home(db,sect):
    seat=storage.seat_location(db,sect)
    return seat[0] if seat else 'r0_4'


def sect_name(db,sect):
    if not sect:return 'the local wardens'
    return db.execute('SELECT name FROM sects WHERE id=?',(sect,)).fetchone()[0]


def relation(db,a,b):
    if not b:return dict(regard=0,treaty='Open',until_day=0)
    row=db.execute('SELECT * FROM foreign_relations WHERE a=? AND b=?',sorted((a,b))).fetchone()
    return dict(row) if row else dict(regard=0,treaty='Open',until_day=0)


def set_relation(db,a,b,delta,treaty,until):
    if not b:return
    first,second=sorted((a,b))
    regard=max(-100,min(100,relation(db,a,b)['regard']+delta))
    db.execute('INSERT OR REPLACE INTO foreign_relations VALUES(?,?,?,?,?)',(first,second,regard,treaty,until))


def active(db,sect):
    return db.execute('SELECT * FROM campaigns WHERE result IS NULL AND (attacker=? OR defender=?)',(sect,sect)).fetchone()


def clock():
    w=storage.world_state()
    return w['day'],w['seconds_per_day']


def treasury(db,sect):
    row=db.execute('SELECT treasury FROM sect_governance WHERE sect_id=?',(sect,)).fetchone()
    return row[0] if row else 0


# Reserve a full payroll, existing obligations and ten combat rounds before mobilizing.
MOBILIZATION = 600
FIELD_COST = 80
MAX_ROUNDS = 10
PEACE_SECONDS = 7200

def war_budget(db,sect):
    import progress
    ledger=progress.treasury_summary(db,sect)
    return ledger['wages']+ledger['arrears']+occupation_cost(db,sect)+MOBILIZATION+MAX_ROUNDS*FIELD_COST


def available_power(db,sect,site):
    # Use last observed healthy power for planning. Only the two relevant rosters
    # (or the independent objective's wardens) are read on a prospective offensive.
    roster="SELECT actor FROM affiliations WHERE sect_id=?" if sect else "SELECT actor FROM mine_wardens WHERE location=?"
    return db.execute(f"""SELECT coalesce(sum(max(1,coalesce(m.power,
            json_extract(p.data,'$.offline.character.score'),1))),0)
        FROM ({roster}) r JOIN profiles p ON p.id=r.actor
        LEFT JOIN actor_measures m ON m.actor=r.actor
        LEFT JOIN injuries i ON i.actor=r.actor AND i.until_day>?
        WHERE i.actor IS NULL AND json_extract(p.data,'$.life.dead') IS NULL
        AND NOT EXISTS(SELECT 1 FROM ascensions z WHERE z.actor=r.actor)
        AND NOT EXISTS(SELECT 1 FROM ritual_party z WHERE z.actor=r.actor)
        AND NOT EXISTS(SELECT 1 FROM campaign_forces z WHERE z.actor=r.actor)""",
        (sect or site,clock()[0])).fetchone()[0]


def traits(actor):
    settings=storage.load_profile_cache(actor).get('offline',{}).get('character',{})
    return set(storage.actor_disposition(actor)) | set(settings.get('personalities') or [])


def strength(actor):
    import progress
    return progress.political_actor(actor)['power']


def field_strengths(db,actors,day):
    """Use the same power formula as political_actor, reading just the present troops."""
    import gamedata
    import generator
    import json
    if not actors:return {}
    marks=','.join('?' for _ in actors)
    rows=db.execute(f"""SELECT p.id,json_extract(p.data,'$.offline.character') settings,
        json_extract(p.data,'$.life.incarnation.talent') talent,
        coalesce(json_extract(p.data,'$.realm_state.realm_index'),0) realm,m.power,i.factor
        FROM profiles p LEFT JOIN actor_measures m ON m.actor=p.id
        LEFT JOIN injuries i ON i.actor=p.id AND i.until_day>?
        WHERE p.id IN ({marks})""",(day,*actors))
    powers={}
    for row in rows:
        if row['settings']:
            settings=json.loads(row['settings'])
            power=generator.local_power_score(settings,talent_name=row['talent'] or settings['talent'])
        else:
            power=row['power'] if row['power'] is not None else gamedata.REALMS[row['realm']][0]
        powers[row['id']]=max(1,power*(row['factor'] or 1))
    return powers


def council_vote(db,sect,defender,site,objective):
    members=council(db,sect)
    rivals=council(db,defender) if defender else []
    own=sum(strength(r['actor']) for r in members)
    enemy=sum(strength(r['actor']) for r in rivals) or 3000
    ratio=own/max(1,enemy)
    votes=[]
    for elder in members:
        if elder['office']!='Elder':continue
        nature=traits(elder['actor'])
        rng=random.Random(f"vote:{elder['actor']}:{site}:{objective}:{int(clock()[0]//6)}")
        chance=.48+min(.24,max(-.24,(ratio-1)*.18))
        if 'Cautious' in nature and ratio<1.6:chance-=.42
        if nature.intersection(('Ambitious','Brave','Fearless')):chance+=.27
        if treasury(db,sect)<2000:chance-=.3
        votes.append((elder['actor'],rng.random()<chance))
    return votes


def sites(db,sect):
    rows=db.execute("""SELECT c.*,l.name,m.owner mine_owner,m.kind mine_kind
        FROM campaign_sites c JOIN locations l ON l.id=c.site LEFT JOIN spirit_mines m ON m.location=c.site ORDER BY l.name""")
    result=[]
    for row in rows:
        options=[]
        if row['mine_kind']:options.append(('Mine',row['mine_owner']))
        if row['kind'] in ('Pass','Headquarters'):options.append((row['kind'],row['owner']))
        if row['kind']=='Headquarters' and row['owner']:options.append(('Reparations',row['owner']))
        for kind,owner in options:
            if owner!=sect:result.append(dict(site=row['site'],name=row['name'],objective=kind,owner=owner))
    return result


def announce(db,w,title,body):
    place=db.execute('SELECT name FROM locations WHERE id=?',(w['site'],)).fetchone()[0]
    factions=[w['attacker']]+([w['defender']] if w['defender'] else [])
    text=f"{sect_name(db,w['attacker'])} against {sect_name(db,w['defender'])} at {place}. {body}"
    event=storage.world_event('war',title,text,sects=factions,location=place,importance=3)
    day,_=clock()
    for sect in factions:
        for member in council(db,sect):
            db.execute("INSERT OR IGNORE INTO event_knowledge VALUES(?,?,?,'Sect report')",(member['actor'],event,day))
    # Let actual residents hear the dispatch at the objective and the rally seats.
    for location in {w['site'],*(home(db,sect) for sect in factions)}:
        db.execute('INSERT OR IGNORE INTO news_queue VALUES(?,?,?)',(event,location,day+.5))


def recruit(db,w,sect,side,rally,rng,limit=10):
    # Bound the invitation list per levy. Loyal invitees always answer.
    rows=db.execute("""SELECT a.actor,a.office,p.kind FROM affiliations a JOIN profiles p ON p.id=a.actor
        WHERE a.sect_id=? AND p.kind='npc'
        AND NOT EXISTS(SELECT 1 FROM ascensions z WHERE z.actor=a.actor)
        AND NOT EXISTS(SELECT 1 FROM ritual_party z WHERE z.actor=a.actor)
        AND json_extract(p.data,'$.life.dead') IS NULL
        AND NOT EXISTS(SELECT 1 FROM campaign_forces f WHERE f.actor=a.actor)
        AND NOT EXISTS(SELECT 1 FROM garrison_orders g WHERE g.actor=a.actor)
        ORDER BY a.actor""",(sect,)).fetchall()
    enemy=w['defender'] if side=='A' else w['attacker']
    leaders=council(db,enemy) if enemy else []
    opposing_power=sum(strength(r['actor']) for r in leaders)/max(1,len(leaders)) if leaders else 3000
    candidates=rng.sample(list(rows),min(limit,len(rows)))
    for r in candidates:
        actor=r['actor']
        nature=traits(actor)
        chance=.62
        if 'Cautious' in nature:chance=.55 if strength(actor)>1.5*opposing_power else .12
        if nature.intersection(('Brave','Fearless','Ambitious')):chance+=.28
        if 'Loyal' not in nature and rng.random()>chance:continue
        enlist(db,w,actor,sect,side,rally)
        stance='Cover retreat' if 'Cautious' in nature else 'Press attack' if nature.intersection(('Fearless','Brave','Ambitious')) else 'Hold position'
        db.execute('UPDATE campaign_forces SET orders=? WHERE actor=?',(stance,actor))


def enlist(db,w,actor,sect,side,rally):
    db.execute('INSERT INTO campaign_forces(actor,campaign,side,origin,muster) VALUES(?,?,?,?,?)',
               (actor,w['id'],side,sect,rally))
    if storage.presence(actor)['location']==rally:
        db.execute('UPDATE campaign_forces SET assembled=1 WHERE actor=?',(actor,))
    db.execute('UPDATE npcs SET next_day=min(next_day,?) WHERE id=?',(clock()[0]+.001,actor))


def declare(db,actor,site,objective,override=False,*,debug_force=False):
    import progress
    state=progress.political_actor(actor)
    sect=state['sect_id']
    if state['dead'] or state['office'] not in (*MASTER,'Elder'):error('A living elder or master must propose a campaign.')
    if db.execute('SELECT 1 FROM ascensions WHERE actor=? UNION ALL SELECT 1 FROM ritual_party WHERE actor=?',(actor,actor)).fetchone():error('Finish the ascension assignment first.')
    if not debug_force:storage.require_physical(actor)
    if not debug_force and storage.presence(actor)['location']!=home(db,sect):error('Attend your council at its current rally seat.')
    target=next((r for r in sites(db,sect) if r['site']==site and r['objective']==objective),None)
    if not target:error('That campaign objective is no longer available.')
    defender=target['owner']
    if db.execute('SELECT 1 FROM campaign_forces WHERE actor=?',(actor,)).fetchone():error('Finish your existing military assignment.')
    if active(db,sect) or (defender and active(db,defender)) or db.execute('SELECT 1 FROM campaigns WHERE site=? AND result IS NULL',(site,)).fetchone():
        error('A sect or the objective is already committed to a campaign.')
    day,pace=clock()
    ties=relation(db,sect,defender)
    if not debug_force and (ties['treaty']=='Alliance' or ties['until_day']>day):error('A treaty currently protects this opponent.')
    if not debug_force:
        required=war_budget(db,sect)
        if treasury(db,sect)<required:error(f'Mobilization requires {required:,} Spirit Stones including wages, arrears, upkeep and field supplies.')
    votes=council_vote(db,sect,defender,site,objective)
    yes=sum(v for _,v in votes)
    approved=yes>len(votes)//2
    if not approved and not debug_force:
        if not override or state['office'] not in MASTER:error(f'Council vote {yes}/{len(votes)}. A master may explicitly override the council.')
        db.executemany("""INSERT INTO relationships(player,npc,respect) VALUES(?,?,-30)
            ON CONFLICT(player,npc) DO UPDATE SET respect=max(-100,respect-30)""",((actor,e) for e,_ in votes))
        db.execute('UPDATE sect_payroll SET incumbent=?,confidence=max(0,confidence-30) WHERE sect_id=?',(actor,sect))
    db.execute('UPDATE sect_governance SET treasury=max(0,treasury-?) WHERE sect_id=?',(MOBILIZATION,sect))
    rid=db.execute("""INSERT INTO campaigns(attacker,defender,site,objective,phase,deadline,next_turn,commander)
        VALUES(?,?,?,?,'Muster',?,?,?)""",(sect,defender,site,objective,day+160/pace,day+60/pace,actor)).lastrowid
    w=db.execute('SELECT * FROM campaigns WHERE id=?',(rid,)).fetchone()
    enlist(db,w,actor,sect,'A',home(db,sect))
    rng=random.Random(f'mobilize:{rid}:{day}')
    recruit(db,w,sect,'A',home(db,sect),rng)
    if defender:
        chiefs=council(db,defender)
        chief=next((r for r in chiefs if r['office'] in MASTER),None)
        if chief and not db.execute('SELECT 1 FROM ascensions WHERE actor=? UNION ALL SELECT 1 FROM ritual_party WHERE actor=?',(chief['actor'],chief['actor'])).fetchone():
            db.execute('UPDATE campaigns SET defending_commander=? WHERE id=?',(chief['actor'],rid))
            if chief['kind']=='npc' and not db.execute('SELECT 1 FROM campaign_forces WHERE actor=?',(chief['actor'],)).fetchone():enlist(db,w,chief['actor'],defender,'D',home(db,defender))
        recruit(db,w,defender,'D',home(db,defender),rng)
        for ally in db.execute("SELECT CASE WHEN a=? THEN b ELSE a END FROM foreign_relations WHERE (a=? OR b=?) AND treaty='Alliance'",(defender,defender,defender)):
            partner=ally[0]
            if partner==sect or active(db,partner):continue
            pact=relation(db,sect,partner)
            if pact['until_day']<=day and pact['treaty']!='Alliance':
                recruit(db,w,partner,'D',home(db,partner),rng,4)
        set_relation(db,sect,defender,-25,'War',0)
        db.execute('DELETE FROM alliance_offers WHERE (sender=? AND recipient=?) OR (sender=? AND recipient=?)',(sect,defender,defender,sect))
    assign_detachments(db,rid)
    announce(db,w,'Campaign declared',f"{state['office']} {state['name']} ordered a campaign for {objective.lower()}. Council support {yes}/{len(votes)}."+(' The master overruled the council.' if not approved else ''))
    return 'The call to muster has gone out.'


def march(actor,destination):
    import progress
    view=progress.region_view(actor)
    if view['journey'] or view['location']==destination:return False
    plan=progress.route_plan(view,destination,safe=True)
    progress.start_journey(actor,plan,view,encounters=False)
    return True


def duty(db,actor,day):
    """Called only for a living NPC physically present at the start of its turn."""
    unit=db.execute("""SELECT u.*,w.phase,w.site,a.sect_id FROM campaign_forces u JOIN campaigns w ON w.id=u.campaign
        JOIN affiliations a ON a.actor=u.actor WHERE u.actor=?""",(actor,)).fetchone()
    if unit and unit['origin']!=unit['sect_id']:
        db.execute('DELETE FROM campaign_forces WHERE actor=?',(actor,))
        unit=None
    if unit:
        site=unit['muster']
        if storage.presence(actor)['location']==site and not unit['assembled']:
            db.execute('UPDATE campaign_forces SET assembled=1 WHERE actor=?',(actor,))
            assembled=True
        else:assembled=unit['assembled']
        if assembled and unit['phase']!='Muster':site=unit['site']
        activity='On campaign'
    else:
        g=db.execute("""SELECT g.site FROM garrison_orders g JOIN affiliations a ON a.actor=g.actor
            WHERE g.actor=? AND a.sect_id=g.sect""",(actor,)).fetchone()
        if not g:return False
        site=g[0];activity='Garrison duty'
    moving=march(actor,site) if storage.presence(actor)['location']!=site else False
    db.execute('UPDATE npcs SET activity=?,next_day=?,steps=steps+1 WHERE id=?',
               ('Marching' if moving else activity,day+45/clock()[1],actor))
    return True


def participants(db,w,side):
    """Only mustered, living, uninjured actors actually at the objective can fight."""
    if side=='D':
        guards=("SELECT actor,'Hold position' FROM garrison_orders WHERE sect=? AND site=?"
                if w['defender'] else "SELECT actor,'Hold position' FROM mine_wardens WHERE location=?")
        guard_args=(w['defender'],w['site']) if w['defender'] else (w['site'],)
    else:
        guards="SELECT NULL,NULL WHERE 0"
        guard_args=()
    query=f"""WITH troops(actor,orders) AS (
        SELECT u.actor,u.orders FROM campaign_forces u JOIN affiliations a ON a.actor=u.actor
        WHERE u.campaign=? AND u.side=? AND u.assembled=1 AND a.sect_id=u.origin
        UNION ALL {guards})
        SELECT t.actor,t.orders FROM troops t JOIN positions pos ON pos.actor=t.actor
        JOIN profiles p ON p.id=t.actor LEFT JOIN journeys j ON j.actor=t.actor
        LEFT JOIN injuries i ON i.actor=t.actor AND i.until_day>?
        WHERE pos.location=? AND j.actor IS NULL AND i.actor IS NULL AND json_extract(p.data,'$.life.dead') IS NULL"""
    return dict(db.execute(query,(w['id'],side,*guard_args,clock()[0],w['site'])))


def garrison(db,actor,site,sect):
    db.execute('INSERT OR REPLACE INTO garrison_orders VALUES(?,?,?)',(actor,site,sect))
    db.execute('UPDATE npcs SET next_day=min(next_day,?) WHERE id=?',(clock()[0]+.001,actor))


def finish(db,w,victory,reason):
    if not db.execute('SELECT 1 FROM campaigns WHERE id=? AND result IS NULL',(w['id'],)).fetchone():return
    winner=w['attacker'] if victory else w['defender']
    site=w['site'];objective=w['objective']
    terms='The existing borders stand.'
    if victory:
        if objective=='Reparations':
            amount=min(3000,treasury(db,w['defender'])//2)
            db.execute('UPDATE sect_governance SET treasury=treasury-? WHERE sect_id=?',(amount,w['defender']))
            db.execute('UPDATE sect_governance SET treasury=treasury+? WHERE sect_id=?',(amount,winner))
            terms=f'The defeated council paid {amount:,} Spirit Stones.'
        else:
            if objective!='Mine' or db.execute('SELECT kind FROM campaign_sites WHERE site=?',(site,)).fetchone()[0]=='Mine':
                db.execute('UPDATE campaign_sites SET owner=? WHERE site=?',(winner,site))
            if objective=='Mine':
                db.execute('UPDATE spirit_mines SET owner=? WHERE location=?',(winner,site))
                db.execute('DELETE FROM mine_wardens WHERE location=?',(site,))
            db.execute('''DELETE FROM garrison_orders WHERE site=? AND sect IS ?
                 AND NOT EXISTS(SELECT 1 FROM campaign_sites c WHERE c.site=garrison_orders.site AND c.owner=garrison_orders.sect)
                 AND NOT EXISTS(SELECT 1 FROM spirit_mines m WHERE m.location=garrison_orders.site AND m.owner=garrison_orders.sect)''',(site,w['defender']))
            troops=participants(db,w,'A')
            posted=0
            for actor in troops:
                member=db.execute('SELECT office,sect_id FROM affiliations WHERE actor=?',(actor,)).fetchone()
                if member['sect_id']==winner and member['office']=='Member' and storage.load_profile_cache(actor).get('world_npc'):
                    garrison(db,actor,site,winner)
                    posted+=1
                    if posted==4:break
            terms=f'{sect_name(db,winner)} gained the {objective.lower()}.'
            if objective=='Headquarters':terms+=' The displaced council retains its surviving membership and rallies elsewhere.'
            # The two closest neighboring councils remember expansion.
            neighbors=db.execute("""SELECT h.sect_id FROM locations h JOIN locations target ON target.id=?
                WHERE h.sect_id IS NOT NULL AND h.sect_id<>? AND h.sect_id<>coalesce(?,'')
                ORDER BY (h.x-target.x)*(h.x-target.x)+(h.y-target.y)*(h.y-target.y),h.id LIMIT 2""",(site,winner,w['defender']))
            for neighbor, in neighbors:
                ties=relation(db,winner,neighbor)
                set_relation(db,winner,neighbor,-12,ties['treaty'],ties['until_day'])
    day,pace=clock()
    set_relation(db,w['attacker'],w['defender'],5,'Truce',day+PEACE_SECONDS/pace)
    db.execute('UPDATE foreign_policy SET review=max(review,?) WHERE sect IN (?,?)',(day+3600/pace,w['attacker'],w['defender']))
    db.execute("UPDATE campaigns SET phase='Ended',result=? WHERE id=?",(reason+' '+terms,w['id']))
    db.execute('DELETE FROM campaign_forces WHERE campaign=?',(w['id'],))
    announce(db,w,'Campaign settled',f"{reason} {terms} Field losses (routed, injured or killed): {w['loss_a']} attackers, {w['loss_d']} defenders.")


def rout(db,w,actor,side,rng):
    pc=storage.load_profile_cache(actor)
    db.execute('DELETE FROM campaign_forces WHERE actor=?',(actor,))
    db.execute('DELETE FROM garrison_orders WHERE actor=?',(actor,))
    db.execute('DELETE FROM mine_wardens WHERE actor=?',(actor,))
    if pc.get('world_npc') and rng.random()<.045:
        import generator
        c=generator.build_cultivator(actor,'',{})[3]
        ally = sect_name(db,w['attacker'] if side=='A' else w['defender'])
        enemy = sect_name(db,w['defender'] if side=='A' else w['attacker'])
        storage.mark_dead(actor,c,'sect_war',circumstances=f'fell fighting for {ally} against {enemy}')
        announce(db,w,'Battlefield death',c['name']+' fell fighting for '+sect_name(db,w['attacker'] if side=='A' else w['defender'])+'.')
    elif pc.get('world_npc') and rng.random()<.18:
        # Surrender takes a fighter out of this battle without inflicting an injury.
        origin=w['attacker'] if side=='A' else w['defender']
        opponent=w['defender'] if side=='A' else w['attacker']
        defected=False
        if origin and opponent and rng.random()<.12:
            import progress
            a=progress.political_actor(actor)
            term=progress.ensure_member_term(actor)
            if a['office']=='Member' and not a['mentor'] and 'Loyal' not in a['personalities'] and term['ready_day']<=clock()[0]:
                progress.change_sect(actor,None,npc=True)
                saved=storage.load_profile_cache(actor)
                saved['sect_application']=opponent
                storage.save_profile_cache(saved,durable=True)
                defected=True
        march(actor,home(db,opponent if defected else origin))
        storage.add_activity(actor,dict(at=time.time(),type='adventure',summary='Surrendered and sought refuge with the opposing sect.' if defected else 'Surrendered in the field and left the campaign.'))
    else:
        storage.injure(actor,'Sect campaign')
        if pc.get('world_npc'):
            dest=home(db,w['attacker'] if side=='A' else w['defender']) if w['defender'] or side=='A' else 'r0_4'
            march(actor,dest)
        storage.add_activity(actor,dict(at=time.time(),type='adventure',outcome='injured',summary='Routed and injured in a sect campaign.'))
    column='loss_a' if side=='A' else 'loss_d'
    db.execute('UPDATE campaigns SET '+column+'='+column+'+1 WHERE id=?',(w['id'],))


def field_turn(db,w,day,rng):
    pace=clock()[1]
    if treasury(db,w['attacker'])<FIELD_COST:
        finish(db,w,False,'The attacker withdrew because it could no longer supply the army.')
        return
    for side,column in (('A','commander'),('D','defending_commander')):
        # Replace commanders lost in the field, never enlist an absent successor.
        current=w[column]
        if not current or not db.execute('SELECT 1 FROM campaign_forces WHERE actor=? AND campaign=? AND side=?',(current,w['id'],side)).fetchone():
            sect=w['attacker'] if side=='A' else w['defender']
            available=db.execute('''SELECT u.actor FROM campaign_forces u JOIN affiliations a ON a.actor=u.actor
                WHERE u.campaign=? AND u.side=? AND u.origin=? ORDER BY CASE a.office WHEN 'Sect Master' THEN 0
                WHEN 'Acting Master' THEN 0 WHEN 'Elder' THEN 1 ELSE 2 END,u.assembled DESC,u.actor LIMIT 1''',(w['id'],side,sect)).fetchone()
            db.execute('UPDATE campaigns SET '+column+'=? WHERE id=?',(available[0] if available else None,w['id']))
    if w['phase']=='Muster':
        if day>=w['deadline']:
            db.execute("UPDATE campaigns SET phase='March',deadline=? WHERE id=?",(day+200/pace,w['id']))
        return
    if w['phase']=='March':
        if day>=w['deadline']:db.execute("UPDATE campaigns SET phase='Contest' WHERE id=?",(w['id'],))
        return
    left=participants(db,w,'A');right=participants(db,w,'D')
    powers=field_strengths(db,set(left)|set(right),day)
    def force(units):
        return sum(powers[a]*{'Press attack':1.2,'Hold position':1,'Cover retreat':.85}[order] for a,order in units.items())
    attack,defense=force(left),force(right)*1.12
    won=bool(left) and (not right or rng.random()<attack/(attack+defense))
    losing=right if won else left
    if left and right and losing:
        victim=rng.choices(list(losing),[.5 if o=='Cover retreat' else 1 for o in losing.values()])[0]
        rout(db,w,victim,'D' if won else 'A',rng)
    control=max(-3,min(3,w['control']+(1 if won else -1)))
    phase='Holding' if control>=2 else 'Contest'
    if phase=='Holding' and w['phase']!='Holding':
        db.execute('UPDATE campaigns SET next_turn=? WHERE id=?',(day+180/pace,w['id']))
        if w['defender']:
            recruit(db,w,w['defender'],'D',home(db,w['defender']),rng,4)
            assign_detachments(db,w['id'])
        announce(db,w,'Relief window opened','The attackers hold the objective. Defenders can still rally to retake it.')
    db.execute('UPDATE campaigns SET rounds=rounds+1,phase=?,control=? WHERE id=?',(phase,control,w['id']))
    for sect in (w['attacker'],w['defender']):
        db.execute('UPDATE sect_governance SET treasury=max(0,treasury-?) WHERE sect_id=?',(FIELD_COST,sect))
    latest=db.execute('SELECT * FROM campaigns WHERE id=?',(w['id'],)).fetchone()
    # An NPC council can sue for peace under field and financial pressure.
    impoverished=treasury(db,w['defender'])<800 if w['defender'] else False
    defender_is_npc=any(r['office'] in MASTER and r['kind']=='npc' for r in council(db,w['defender'])) if w['defender'] and control>=2 else False
    if control>=2 and w['phase']=='Holding' and defender_is_npc and (latest['loss_d']>=4 or impoverished):
        finish(db,latest,True,'The defending council accepted terms to preserve its surviving force.')
    elif control>=3:finish(db,latest,True,'The attackers held through the relief window.')
    elif control<=-3 or latest['rounds']>=MAX_ROUNDS or treasury(db,w['attacker'])<FIELD_COST:
        finish(db,latest,False,'The offensive exhausted its field strength or supplies.')


def review(db,sect,day,rng):
    row=db.execute('SELECT review FROM foreign_policy WHERE sect=?',(sect,)).fetchone()
    if not row:return
    w=db.execute('SELECT * FROM campaigns WHERE attacker=? AND result IS NULL AND next_turn<=?',(sect,day)).fetchone()
    if w:
        db.execute('UPDATE campaigns SET next_turn=? WHERE id=?',(day+55/clock()[1],w['id']))
        field_turn(db,w,day,rng)
    if day<row[0]:return
    db.execute('DELETE FROM alliance_offers WHERE sender=? AND expires<=?',(sect,day))
    pace=clock()[1]
    db.execute('UPDATE foreign_policy SET review=? WHERE sect=?',(day+rng.uniform(2700,6000)/pace,sect))
    if active(db,sect) or treasury(db,sect)<1000:return
    chief=next((r for r in council(db,sect) if r['office'] in MASTER),None)
    if not chief or chief['kind']!='npc':return
    actor=chief['actor'];here=storage.presence(actor)
    if db.execute('SELECT 1 FROM ascensions WHERE actor=? UNION ALL SELECT 1 FROM ritual_party WHERE actor=?',(actor,actor)).fetchone():return
    if here['state']!='present' or storage.injury_state(actor):return
    if here['location']!=home(db,sect):
        if not db.execute('SELECT 1 FROM campaign_forces WHERE actor=?',(actor,)).fetchone():
            march(actor,home(db,sect))
            db.execute('UPDATE foreign_policy SET review=? WHERE sect=?',(day+120/pace,sect))
        return
    if db.execute('SELECT 1 FROM campaigns WHERE result IS NULL LIMIT 1 OFFSET 1').fetchone():return
    all_targets=sites(db,sect)
    # Prefer practical, limited gains; hostile neighbors and nearby roads matter.
    distances=dict(db.execute('''SELECT l.id,(l.x-h.x)*(l.x-h.x)+(l.y-h.y)*(l.y-h.y)
        FROM locations l JOIN locations h ON h.id=?''',(home(db,sect),)))
    def priority(t):
        regard=relation(db,sect,t['owner'])['regard']
        return rng.random()*2-distances[t['site']]/600000-regard/100-(1.4 if t['objective']=='Headquarters' else 0)
    all_targets.sort(key=priority,reverse=True)
    for t in all_targets:
        rival=t['owner'];ties=relation(db,sect,rival)
        if rival and (active(db,rival) or ties['until_day']>day):continue
        if ties['treaty']=='Alliance':continue
        if not rival and db.execute('SELECT 1 FROM campaigns WHERE site=? AND result IS NULL',(t['site'],)).fetchone():continue
        try:
            attempt_policy(db,actor,t,sect,rival,ties,rng)
        except CampaignRefused:
            pass
        return


def attempt_policy(db,actor,t,sect,rival,ties,rng):
    if rival and ties['regard']>=0 and rng.random()<.45:
        diplomatic(db,actor,rival,'Alliance' if ties['regard']>=15 else 'Embassy')
    elif rng.random()<(.06 if t['objective']=='Headquarters' else .22):
        if treasury(db,sect)<war_budget(db,sect):return
        nature=traits(actor)
        margin=1.4 if 'Cautious' in nature else .95 if 'Ambitious' in nature else 1.1
        own=available_power(db,sect,t['site'])
        opposing=available_power(db,rival,t['site'])
        if own<=0 or own<max(1,opposing)*margin:return
        declare(db,actor,t['site'],t['objective'],override='Ambitious' in traits(actor) and rng.random()<.15)
    return


def diplomatic(db,actor,other,action):
    import progress
    a=progress.political_actor(actor);sect=a['sect_id']
    if a['dead'] or a['office'] not in MASTER:error('Only a living master conducts foreign policy.')
    storage.require_physical(actor)
    if not other or other==sect or not db.execute('SELECT 1 FROM foreign_policy WHERE sect=?',(other,)).fetchone():error('Choose another chartered sect.')
    ties=relation(db,sect,other);day,pace=clock()
    if storage.presence(actor)['location']!=home(db,sect):error('Attend your council seat to conduct diplomacy.')
    if ties['treaty']=='War':error('Use the campaign peace negotiation during a war.')
    if ties['until_day']>day:error('The current agreement is still binding.')
    if action=='Embassy':
        if treasury(db,sect)<200:error('An embassy costs 200 Spirit Stones.')
        db.execute('UPDATE sect_governance SET treasury=treasury-200 WHERE sect_id=?',(sect,))
        set_relation(db,sect,other,15,ties['treaty'],day+600/pace)
    elif action in ('Accept alliance','Decline alliance'):
        offer=db.execute('SELECT expires FROM alliance_offers WHERE sender=? AND recipient=?',(other,sect)).fetchone()
        if not offer or offer[0]<=day:error('This offer has expired.')
        db.execute('DELETE FROM alliance_offers WHERE sender=? AND recipient=?',(other,sect))
        if action=='Decline alliance':return 'The council declined the alliance.'
        finalize_alliance(db,sect,other,day,pace)
    elif action=='Alliance':
        if ties['regard']<15 or ties['treaty']=='Alliance':error('Build goodwill through an embassy before offering an alliance.')
        foreign_master=next((m for m in council(db,other) if m['office'] in MASTER),None)
        if not foreign_master:error('The other council has no master to ratify this treaty.')
        if foreign_master['kind']!='npc':
            db.execute('INSERT OR REPLACE INTO alliance_offers VALUES(?,?,?)',(sect,other,day+1800/pace))
            return 'Alliance offered. The other master must ratify the treaty.'
        finalize_alliance(db,sect,other,day,pace)
    elif action=='Renounce':
        if ties['treaty']!='Alliance':error('There is no alliance to renounce.')
        set_relation(db,sect,other,-25,'Truce',day+1800/pace)
    else:error('Unknown diplomatic action.')
    return 'Foreign policy updated.'


def finalize_alliance(db,sect,other,day,pace):
    set_relation(db,sect,other,10,'Alliance',day+3600/pace)
    db.execute('DELETE FROM alliance_offers WHERE (sender=? AND recipient=?) OR (sender=? AND recipient=?)',(sect,other,other,sect))
    storage.world_event('war','Defensive alliance',f'{sect_name(db,sect)} and {sect_name(db,other)} pledged troops for mutual defense.',sects=[sect,other])


def occupation_cost(db,sect):
    seats=db.execute('SELECT count(*) FROM campaign_sites WHERE owner=? AND founding_owner IS NOT owner',(sect,)).fetchone()[0]
    mines=db.execute("""SELECT count(*) FROM spirit_mines m JOIN locations l ON l.id=m.location
        WHERE m.owner=? AND l.sect_id IS NOT m.owner""",(sect,)).fetchone()[0]
    return 100*(seats+mines)+80*seats*seats


def mobilize_player(db,w,actor):
    unit=db.execute('SELECT * FROM campaign_forces WHERE actor=? AND campaign=?',(actor,w['id'])).fetchone()
    if not unit:error('Volunteer for this campaign first.')
    here=storage.require_physical(actor,dangerous=True)['location']
    assembled=unit['assembled'] or here==unit['muster']
    if assembled:db.execute('UPDATE campaign_forces SET assembled=1 WHERE actor=?',(actor,))
    site=w['site'] if assembled and w['phase']!='Muster' else unit['muster']
    if here!=site:
        march(actor,site)
        return 'Your journey to the army destination has begun.'
    return 'You are in position.'


@storage.atomic
def command(actor,action,value,campaign_id=None,key='',profiles=None):
    import progress
    a=progress.political_actor(actor)
    sect=a['sect_id']
    if action in ('Defend ascension','Vote on ascension raid'):
        return ritual_command(actor,a,action,value)
    if a['dead'] or not sect:error('Only a living chartered sect member can act.')
    storage.require_physical(actor)
    with storage.world_transaction() as db:
        if action in ('Propose campaign','Override council'):
            site,objective=value[:2]
            if len(value)>2 and not any(t['site']==site and t['objective']==objective and t['owner']==value[2] for t in sites(db,sect)):
                error('Ownership has changed. Refresh and review the new objective.')
            return declare(db,actor,site,objective,override=action=='Override council')
        if action in ('Embassy','Alliance','Renounce','Accept alliance','Decline alliance'):
            return diplomatic(db,actor,value,action)
        if action in ('Post garrison','Release garrison'):
            if a['office'] not in MASTER:error('Only the master assigns garrisons.')
            if action=='Release garrison':
                if not db.execute('DELETE FROM garrison_orders WHERE actor=? AND sect=?',(value,sect)).rowcount:error('That assignment has ended.')
                return 'Guard relieved.'
            site=value
            owned=db.execute("""SELECT 1 FROM campaign_sites WHERE site=? AND owner=? UNION ALL
                SELECT 1 FROM spirit_mines WHERE location=? AND owner=?""",(site,sect,site,sect)).fetchone()
            if not owned:error('Your sect no longer holds that site.')
            guard=db.execute("""SELECT a.actor FROM affiliations a JOIN profiles p ON p.id=a.actor
                WHERE a.sect_id=? AND a.office='Member' AND p.kind='npc' AND json_extract(p.data,'$.life.dead') IS NULL
                AND NOT EXISTS(SELECT 1 FROM garrison_orders g WHERE g.actor=a.actor)
                AND NOT EXISTS(SELECT 1 FROM campaign_forces f WHERE f.actor=a.actor)
                AND NOT EXISTS(SELECT 1 FROM ritual_party z WHERE z.actor=a.actor)
                AND NOT EXISTS(SELECT 1 FROM ascensions z WHERE z.actor=a.actor)
                ORDER BY a.loyalty DESC,a.actor LIMIT 1""",(sect,)).fetchone()
            if not guard:error('No unassigned disciple is available.')
            garrison(db,guard[0],site,sect)
            return 'A disciple has been ordered to the garrison.'
        w=db.execute('SELECT * FROM campaigns WHERE id=? AND result IS NULL',(campaign_id,)).fetchone()
        if not w:error('That campaign has ended. Refresh the campaign board.')
        unit=db.execute('SELECT * FROM campaign_forces WHERE actor=? AND campaign=? AND origin=?',(actor,w['id'],sect)).fetchone()
        side='A' if sect==w['attacker'] else 'D' if sect==w['defender'] else None
        if not side and not unit:error('Your sect is outside this campaign.')
        if action=='Volunteer':
            if db.execute('SELECT 1 FROM ritual_party WHERE actor=?',(actor,)).fetchone():error('Finish your ascension assignment first.')
            if db.execute('SELECT 1 FROM campaign_forces WHERE actor=?',(actor,)).fetchone():error('You are already assigned to a campaign.')
            storage.require_physical(actor,dangerous=True)
            enlist(db,w,actor,sect,side,home(db,sect))
            assign_detachments(db,w['id'])
            return mobilize_player(db,w,actor)
        if action in ('Accept peace','Reject peace'):
            if a['office'] not in MASTER or not side or not w['proposed_by'] or w['proposed_by']==sect:
                error('There are no opposing terms for your council to decide.')
            if action=='Reject peace':
                db.execute('UPDATE campaigns SET proposed_by=NULL,proposed_victory=NULL WHERE id=?',(w['id'],))
                return 'The council rejected the proposed settlement.'
            finish(db,w,bool(w['proposed_victory']),'Both councils ratified a peace agreement.')
            return 'The peace agreement has taken effect.'
        if action in ('Offer peace','Concede'):
            if a['office'] not in MASTER or not side:error('Only a belligerent master can negotiate terms.')
            if action=='Offer peace':
                enemy=w['defender'] if side=='A' else w['attacker']
                losses=w['loss_d'] if side=='A' else w['loss_a']
                leverage=w['control'] if side=='A' else -w['control']
                if enemy and any(m['office'] in MASTER and m['kind']!='npc' for m in council(db,enemy)):
                    db.execute('UPDATE campaigns SET proposed_by=?,proposed_victory=? WHERE id=?',(sect,int(side=='A'),w['id']))
                    return 'The proposed settlement awaits a decision from the opposing council.'
                reserves=treasury(db,enemy) if enemy else 2000
                opposing='D' if side=='A' else 'A'
                field=len(participants(db,w,opposing))
                if w['rounds']<2 or (leverage<1 and losses<max(2,field) and reserves>1000):
                    error('The opposing force still expects to win. Improve your position or offer a concession.')
                victory=side=='A'
            else:victory=side=='D'
            finish(db,w,victory,'A negotiated agreement ended the campaign.')
            return 'Peace terms recorded in World History.'
        if not unit:error('Join the army before issuing field orders.')
        if action=='Commission commander':
            if a['office'] not in MASTER or not side:error('Only a belligerent master can commission a field commander.')
            target=db.execute('SELECT 1 FROM campaign_forces WHERE actor=? AND campaign=? AND side=? AND origin=?',(value,w['id'],side,sect)).fetchone()
            if not target:error('That officer is unavailable.')
            column='commander' if side=='A' else 'defending_commander'
            db.execute('UPDATE campaigns SET '+column+'=? WHERE id=?',(value,w['id']))
            return 'The new field commander has been commissioned.'
        if action=='Report / march':return mobilize_player(db,w,actor)
        if action=='Withdraw':
            db.execute('DELETE FROM campaign_forces WHERE actor=?',(actor,))
            if storage.presence(actor)['location']!=home(db,sect):march(actor,home(db,sect))
            return 'You have withdrawn from the field army.'
        if not unit['assembled'] and storage.presence(actor)['location']==unit['muster']:
            db.execute('UPDATE campaign_forces SET assembled=1 WHERE actor=?',(actor,))
        elif not unit['assembled']:error('Reach your muster point first.')
        if storage.presence(actor)['location'] not in (unit['muster'],w['site']):
            error('Return to muster or to the objective to give field orders.')
        if action=='Challenge':
            import combat
            storage.require_physical(actor,dangerous=True)
            if storage.presence(actor)['location']!=w['site'] or w['phase'] not in ('Contest','Holding'):error('Reach the contested battlefield first.')
            enemies=participants(db,w,'D' if unit['side']=='A' else 'A')
            foe=next((e for e in enemies if storage.load_profile_cache(e).get('world_npc') and combat.duel_ready(actor,e)),None)
            if not foe:error('There is no eligible opponent at this site.')
            result=combat.perform_battle([actor,foe],key,profiles or {},mode='Lethal')
            loser=foe if result['result']['winner'] is result['a'] else actor
            defeated='D' if (loser==foe)==(unit['side']=='A') else 'A'
            if not storage.load_profile_cache(loser).get('life',{}).get('dead'):storage.injure(loser,'Campaign challenge')
            db.execute('DELETE FROM campaign_forces WHERE actor=?',(loser,))
            column='loss_a' if defeated=='A' else 'loss_d'
            db.execute('UPDATE campaigns SET '+column+'='+column+'+1 WHERE id=?',(w['id'],))
            return result['story']
        if value not in FIELD_ORDERS:error('Choose a field order.')
        if action=='Army order':
            if actor!=w['commander' if unit['side']=='A' else 'defending_commander']:error('Only the field commander may order this army.')
            db.execute('UPDATE campaign_forces SET orders=? WHERE campaign=? AND side=?',(value,w['id'],unit['side']))
        elif action=='Detachment order':
            if a['office']!='Elder':error('Only an elder commands a detachment.')
            db.execute('UPDATE campaign_forces SET orders=? WHERE campaign=? AND side=? AND (detachment=? OR actor=?)',(value,w['id'],unit['side'],actor,actor))
        elif action=='Personal stance':
            db.execute('UPDATE campaign_forces SET orders=? WHERE actor=?',(value,actor))
        else:error('Unknown order.')
        return 'Field order issued: '+value+'.'


def dashboard(actor):
    """Read one bounded command board without advancing or resolving simulation."""
    with storage.world_snapshot() as db:
        names=dict(db.execute('SELECT id,name FROM sects'))
        places=dict(db.execute('SELECT id,name FROM locations'))
        row=db.execute("""SELECT a.sect_id,a.office,json_extract(p.data,'$.life.dead') IS NOT NULL dead
            FROM profiles p LEFT JOIN affiliations a ON a.actor=p.id WHERE p.id=?""",(actor,)).fetchone() if actor else None
        if actor and not row:error('Unknown cultivator.')
        a=dict(row) if row else {}
        sect=a.get('sect_id');office=a.get('office')
        rows=[];options={}
        def option(action,label,value,war=None):
            options.setdefault(action,{})[label]=(value,war)
        def entry(title,body):rows.append((title,body,()))
        if sect:
            entry(names[sect],f"Your role: {office} · Rally seat: {places[home(db,sect)]} · Occupation upkeep: {occupation_cost(db,sect):,} stones per payroll")
        for w in db.execute('SELECT * FROM campaigns WHERE result IS NULL ORDER BY id'):
            count=dict(db.execute('SELECT side,count(*) FROM campaign_forces WHERE campaign=? GROUP BY side',(w['id'],)))
            label=f"{places[w['site']]} · {w['objective']}"
            present=[len(participants(db,w,side)) for side in ('A','D')]
            entry(places[w['site']],f"Objective: {w['objective']}    |    Phase: {w['phase']}\nAttackers: {names[w['attacker']]}  ·  {count.get('A',0)} enlisted  ·  {present[0]} at objective  ·  {w['loss_a']} field losses\nDefenders: {names.get(w['defender'],'Local wardens')}  ·  {count.get('D',0)} enlisted  ·  {present[1]} at objective  ·  {w['loss_d']} field losses")
            if not sect or a['dead']:continue
            unit=db.execute('SELECT * FROM campaign_forces WHERE actor=? AND campaign=? AND origin=?',(actor,w['id'],sect)).fetchone()
            if sect not in (w['attacker'],w['defender']) and not unit:continue
            if unit:
                entry('Your assignment',f"Muster at {places[unit['muster']]}, then march to {places[w['site']]}. Current order: {unit['orders']}.")
                for act in ('Report / march','Withdraw','Challenge'):option(act,label,None,w['id'])
                for order in FIELD_ORDERS:
                    option('Personal stance',order,order,w['id'])
                    if office=='Elder':option('Detachment order',order,order,w['id'])
                    if actor in (w['commander'],w['defending_commander']):option('Army order',order,order,w['id'])
            else:option('Volunteer',label,None,w['id'])
            if office in MASTER and sect in (w['attacker'],w['defender']):
                if unit:
                    for member in db.execute('SELECT u.actor,p.name FROM campaign_forces u JOIN profiles p ON p.id=u.actor WHERE campaign=? AND origin=?',(w['id'],sect)):
                        option('Commission commander',f"{member['name']} · {member['actor'][-4:]}",member['actor'],w['id'])
                if w['proposed_by'] and w['proposed_by']!=sect:
                    terms='Grant the attacker its stated objective.' if w['proposed_victory'] else 'End the campaign on the existing borders.'
                    entry('Proposed peace at '+places[w['site']],terms)
                    for act in ('Accept peace','Reject peace'):option(act,label,None,w['id'])
                for act in ('Offer peace','Concede'):option(act,label,None,w['id'])
        if not rows or (len(rows)==1 and sect):entry('The field is quiet','Active campaigns and their objectives appear here when a council goes to war.')
        if sect:
            for r in db.execute('SELECT * FROM foreign_relations WHERE a=? OR b=? ORDER BY regard DESC',(sect,sect)):
                other=r['a'] if r['b']==sect else r['b']
                treaty=r['treaty'] if r['treaty']!='Truce' or r['until_day']>clock()[0] else 'Open'
                expiry=' · Peace until '+storage.calendar_text(r['until_day']) if treaty=='Truce' else ''
                entry(names[other],f"{treaty} · Diplomatic regard {r['regard']:+d}{expiry}")
            if not a['dead'] and office in (*MASTER,'Elder') and not active(db,sect):
                for t in sites(db,sect):
                    label=f"{t['objective']} · {t['name']} · {names.get(t['owner'],'Local wardens')}"
                    option('Propose campaign',label,(t['site'],t['objective'],t['owner']))
                    if office in MASTER:option('Override council',label,(t['site'],t['objective'],t['owner']))
            if not a['dead'] and office in MASTER:
                for sender, in db.execute('SELECT sender FROM alliance_offers WHERE recipient=? AND expires>?',(sect,clock()[0])):
                    entry(names[sender],'Your council has received an offer of defensive alliance.')
                    for act in ('Accept alliance','Decline alliance'):option(act,names[sender],sender)
                for other, in db.execute('SELECT sect FROM foreign_policy WHERE sect<>?',(sect,)):
                    for act in ('Embassy','Alliance','Renounce'):option(act,names[other],other)
                for site, in db.execute('SELECT site FROM campaign_sites WHERE owner=? UNION SELECT location FROM spirit_mines WHERE owner=?',(sect,sect)):
                    option('Post garrison',places[site],site)
                for r in db.execute('SELECT g.actor,g.site,p.name FROM garrison_orders g JOIN profiles p ON p.id=g.actor WHERE g.sect=?',(sect,)):
                    option('Release garrison',f"{r['name']} · {places[r['site']]} · {r['actor'][-4:]}",r['actor'])
        if sect:
            for mine,yield_stones in db.execute('SELECT l.name,m.yield_stones FROM spirit_mines m JOIN locations l ON l.id=m.location WHERE m.owner=? ORDER BY l.name',(sect,)):
                entry(mine,f'Spirit Stone mine · {yield_stones:,} stones per two active hours')
            holdings=db.execute('SELECT c.kind,l.name FROM campaign_sites c JOIN locations l ON l.id=c.site WHERE c.owner=? ORDER BY c.kind,l.name',(sect,))
            for kind,name in holdings:
                if kind!='Mine':entry(name,kind+' under sect control')
        for r in db.execute('''SELECT z.*,p.name,a.sect_id FROM ascensions z JOIN profiles p ON p.id=z.actor
                LEFT JOIN affiliations a ON a.actor=z.actor ORDER BY z.ends'''):
            label=f"{r['name']} · {places[r['site']]}"
            entry('Heavenly ascension · '+label,f"Finishes {storage.calendar_text(r['ends'])} · {max(0,r['ends']-clock()[0]):.2f} days remaining")
            if actor and actor!=r['actor'] and not a['dead']:
                option('Defend ascension',label,r['actor'])
                if sect and sect!=r['sect_id'] and office in MASTER:
                    option('Vote on ascension raid',label,r['actor'])
        return dict(rows=rows,options=options)

def assign_detachments(db,campaign):
    for side in ('A','D'):
        troops=db.execute("""SELECT u.actor,a.office FROM campaign_forces u JOIN affiliations a ON a.actor=u.actor
            WHERE campaign=? AND side=? ORDER BY u.actor""",(campaign,side)).fetchall()
        elders=[r['actor'] for r in troops if r['office']=='Elder']
        if elders:
            members=[r for r in troops if r['office']=='Member']
            db.executemany('UPDATE campaign_forces SET detachment=? WHERE actor=?',
                           ((elders[i%len(elders)],r['actor']) for i,r in enumerate(members)))


def migrate_rituals(db,path):
    if db.execute('PRAGMA user_version').fetchone()[0]!=8:return
    lease=db.execute('SELECT expires FROM simulation_lease WHERE id=1').fetchone()
    if lease and lease[0]>time.time():error('Close other game instances before upgrading this world.')
    folder=path.parent/'migration_backups'
    folder.mkdir(exist_ok=True)
    backup=sqlite3.connect(folder/('before_ascension_'+datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f')+'.db'))
    try:db.backup(backup)
    finally:backup.close()
    db.execute('BEGIN IMMEDIATE')
    if db.execute('PRAGMA user_version').fetchone()[0]==8:
        for sql in (
            'CREATE TABLE ascensions(actor TEXT PRIMARY KEY REFERENCES profiles(id),site TEXT NOT NULL REFERENCES locations(id),ends REAL NOT NULL,tick REAL NOT NULL)',
            'CREATE INDEX ascension_due ON ascensions(tick,actor)',
            """CREATE TABLE ritual_party(actor TEXT PRIMARY KEY REFERENCES profiles(id),leader TEXT NOT NULL REFERENCES profiles(id),
               site TEXT NOT NULL REFERENCES locations(id),side TEXT NOT NULL,expires REAL NOT NULL)""",
            'CREATE INDEX ritual_followers ON ritual_party(leader,side)',
            'CREATE TABLE ritual_votes(leader TEXT REFERENCES ascensions(actor) ON DELETE CASCADE,sect TEXT REFERENCES sects(id),player_decision INTEGER NOT NULL DEFAULT 0,PRIMARY KEY(leader,sect))',
        ):db.execute(sql)
        db.execute('PRAGMA user_version=9')
    db.commit()


def ritual_event(db,actor,site,title,detail):
    row=db.execute('SELECT p.name,a.sect_id FROM profiles p LEFT JOIN affiliations a ON a.actor=p.id WHERE p.id=?',(actor,)).fetchone()
    place=db.execute('SELECT name FROM locations WHERE id=?',(site,)).fetchone()[0]
    sect=row['sect_id']
    event=storage.world_event('ascension',title,f"{row['name']} ({sect_name(db,sect) if sect else 'Wanderer'}) at {place}. {detail}",
                        actors=[actor],sects=[sect] if sect else [],location=place,importance=3)
    if title=='The heavens tremble':
        db.execute("""INSERT OR IGNORE INTO event_knowledge(actor,event,learned_day,source)
            SELECT a.actor,?,?,'Witnessed' FROM affiliations a JOIN profiles p ON p.id=a.actor
            WHERE a.office IN ('Sect Master','Acting Master','Elder') AND json_extract(p.data,'$.life.dead') IS NULL""",(event,clock()[0]))


def available_escort(db,actor):
    return not db.execute("""SELECT 1 FROM campaign_forces WHERE actor=? UNION ALL SELECT 1 FROM garrison_orders WHERE actor=?
        UNION ALL SELECT 1 FROM mine_wardens WHERE actor=? UNION ALL SELECT 1 FROM ascensions WHERE actor=?
        UNION ALL SELECT 1 FROM ritual_party WHERE actor=?""",(actor,)*5).fetchone()


def assign_escort(db,actor,leader,site,side,until):
    if actor==leader or not available_escort(db,actor):return False
    db.execute('INSERT INTO ritual_party VALUES(?,?,?,?,?)',(actor,leader,site,side,until))
    db.execute('UPDATE npcs SET next_day=min(next_day,?) WHERE id=?',(clock()[0]+.001,actor))
    return True


@storage.atomic
def gather_protectors(actor,c):
    if c['realm_index']!=8 or c['death'] or not storage.read_pavilion(actor)['items'].get('dao_integration_pill'):error('A living Tribulation cultivator with the Dao Integration Pill is required.')
    here=storage.require_physical(actor,dangerous=True)
    site=here['location']
    if not site:error('Enter the living world before assembling protectors.')
    day,_=clock()
    with storage.world_transaction() as db:
        db.execute("DELETE FROM ritual_party WHERE leader=? AND site<>?",(actor,site))
        sect=db.execute('SELECT sect_id FROM affiliations WHERE actor=?',(actor,)).fetchone()
        if sect and sect[0]:
            rows=db.execute("""SELECT a.actor FROM affiliations a JOIN profiles p ON p.id=a.actor WHERE a.sect_id=?
                AND a.actor<>? AND p.kind='npc' AND json_extract(p.data,'$.life.dead') IS NULL
                ORDER BY CASE a.office WHEN 'Elder' THEN 0 WHEN 'Member' THEN 1 ELSE 2 END,a.loyalty DESC,a.actor LIMIT 12""",(sect[0],actor))
        else:
            rows=db.execute("""SELECT r.npc FROM relationships r JOIN profiles p ON p.id=r.npc
                WHERE r.player=? AND p.kind='npc' AND json_extract(p.data,'$.life.dead') IS NULL
                AND EXISTS(SELECT 1 FROM conversations c WHERE c.player=r.player AND c.npc=r.npc)
                AND r.trust+r.respect>=20 ORDER BY r.trust+r.respect DESC LIMIT 12""",(actor,))
        for row in list(rows):assign_escort(db,row[0],actor,site,'Guard',day+5)
        return db.execute("SELECT count(*) FROM ritual_party WHERE leader=? AND side='Guard'",(actor,)).fetchone()[0]


def begin_ascension(actor,c):
    import pavilion_shop
    with storage.world_transaction() as db:
        if not available_escort(db,actor):error('Finish your current military assignment first.')
        site=storage.require_physical(actor,dangerous=True)['location']
        day,_=clock()
        if not site:error('Choose a site in the living world.')
        guards=gather_protectors(actor,c)
        pavilion_shop.consume(actor,'dao_integration_pill')
        db.execute('INSERT INTO ascensions VALUES(?,?,?,?)',(actor,site,day+5,day+.02))
        db.execute('UPDATE ritual_party SET expires=? WHERE leader=?',(day+5,actor))
        ritual_event(db,actor,site,'The heavens tremble',f"Immortal ascension has begun. It finishes in five Heavenly days ({storage.calendar_text(day+5)}). {guards} protectors answered.")
        return dict(ritual='The Dao Integration Pill was consumed. Hold this site for five Heavenly days.',success=True,to='Immortal Ascension',pill_used=True)


def ritual_duty(db,actor,day):
    row=db.execute('SELECT ends FROM ascensions WHERE actor=?',(actor,)).fetchone()
    if row:
        db.execute("UPDATE npcs SET next_day=?,activity='Ascending' WHERE id=?",(row[0]+.001,actor))
        return True
    duty=db.execute('SELECT * FROM ritual_party WHERE actor=?',(actor,)).fetchone()
    if not duty:return False
    if duty['expires']<=day:
        db.execute('DELETE FROM ritual_party WHERE actor=?',(actor,))
        return False
    moving=march(actor,duty['site'])
    db.execute('UPDATE npcs SET next_day=?,activity=?,steps=steps+1 WHERE id=?',
               (day+.2,'Marching to ascension' if moving else 'Guarding ascension' if duty['side']=='Guard' else 'Assaulting ascension',actor))
    return True


def ritual_tick(db,actor,day):
    import gamedata
    r=db.execute('SELECT * FROM ascensions WHERE actor=?',(actor,)).fetchone()
    site=r['site'];pc=storage.load_profile_cache(actor)
    rng=random.Random(f"ascension:{actor}:{r['ends']}:{r['tick']}")
    def end(title,message):
        ritual_event(db,actor,site,title,message)
        db.execute('DELETE FROM ritual_party WHERE leader=?',(actor,))
        db.execute('DELETE FROM ascensions WHERE actor=?',(actor,))
    if pc.get('life',{}).get('dead') or storage.presence(actor)['location']!=site or storage.read_realm_state(actor)['realm_index']!=8:
        end('Ascension ended','The cultivator could no longer maintain the ritual.')
        return
    if day>=r['ends']:
        vitals=dict(storage.read_realm_state(actor)['vitals'] or {})
        vitals['base_lifespan']=rng.randint(*gamedata.REALM_LIFESPANS[9])
        cal=pc['calendar'];vitals.update(age=int((day-cal['birth_day'])//365),birth_year=int(cal['birth_day']//365))
        storage.write_realm_state(actor,9,None,0,vitals=vitals)
        storage.add_activity(actor,dict(type='breakthrough',at=time.time(),success=True,chance=1.0,**{'from':'Tribulation Transcendence','to':'Immortal Ascension'}))
        end('An Immortal ascends','Five Heavenly days passed. The Dao integration is complete.')
        return
    own=db.execute('SELECT sect_id FROM affiliations WHERE actor=?',(actor,)).fetchone()
    own=own[0] if own else None
    # Stagger council deliberations rather than scanning twenty councils in one transaction.
    for sect, in db.execute("""SELECT sect_id FROM sect_charters WHERE sect_id<>coalesce(?,'') AND NOT EXISTS
        (SELECT 1 FROM ritual_votes WHERE leader=? AND sect=sect_id) ORDER BY sect_id LIMIT 2""",(own,actor)).fetchall():
        chief=next((m for m in council(db,sect) if m['office'] in MASTER),None)
        db.execute('INSERT INTO ritual_votes(leader,sect) VALUES(?,?)',(actor,sect))
        if not chief or chief['kind']!='npc' or active(db,sect):continue
        ties=relation(db,sect,own)
        nature=traits(chief['actor'])
        if ties['treaty']=='Alliance' or rng.random()>(.65 if nature.intersection(('Schemer','Ambitious')) else .06):continue
        votes=council_vote(db,sect,own,site,'Prevent ascension')
        if sum(v for _,v in votes)<=len(votes)//2:continue
        dispatch_raid(db,actor,sect,site,r['ends'])
    forces={'Guard':[],'Raid':[]}
    for m in db.execute("""SELECT u.actor,u.side FROM ritual_party u JOIN positions pos ON pos.actor=u.actor JOIN profiles p ON p.id=u.actor
        LEFT JOIN journeys j ON j.actor=u.actor LEFT JOIN injuries i ON i.actor=u.actor AND i.until_day>?
        WHERE u.leader=? AND pos.location=? AND j.actor IS NULL AND i.actor IS NULL AND json_extract(p.data,'$.life.dead') IS NULL""",(day,actor,site)):
        forces[m['side']].append(m['actor'])
    if forces['Raid']:
        enemies=forces['Raid'];friends=forces['Guard']
        if friends:
            attacker,guard=rng.choice(enemies),rng.choice(friends)
            loser=guard if rng.random()<strength(attacker)/max(1,strength(attacker)+strength(guard)) else attacker
            storage.injure(loser,'Ascension battle')
            db.execute('DELETE FROM ritual_party WHERE actor=?',(loser,))
        elif rng.random()<.35:
            storage.injure(actor,'Interrupted Dao integration',1800)
            end('Ascension interrupted','An attacker broke through and struck the ascender. The pill was lost and the ascender survived with a major injury.')
            return
    db.execute('UPDATE ascensions SET tick=? WHERE actor=?',(min(r['ends'],day+.2),actor))

def debug_catalog(cache):
    with storage.world_transaction(cache) as db:
        if not storage.region_ready(db):error('Start this living world in the game before using its debug controls.')
        names=dict(db.execute('SELECT id,name FROM sects'))
        people=[dict(r) for r in db.execute("""SELECT a.actor,a.office,a.sect_id,p.name,p.kind FROM affiliations a
            JOIN profiles p ON p.id=a.actor WHERE json_extract(p.data,'$.life.dead') IS NULL ORDER BY p.name,p.id""")]
        sects={r[0]:names[r[0]] for r in db.execute('SELECT sect FROM foreign_policy')}
        return sects,people,{sect:sites(db,sect) for sect in sects}


def debug_command(cache,action,sect,choice,stage,force,subject,opinion,value,standalone=False):
    import progress
    import gamedata
    # Bind nested gameplay readers to this editor's chosen database on this worker only.
    storage._world_local.debug_cache=cache
    try:
        if standalone:
            with storage.world_transaction(cache) as db:
                lease=db.execute('SELECT expires FROM simulation_lease WHERE id=1').fetchone()
                if lease and lease[0]>time.time():error('Close the running game or open Debug from its Developer Tools.')
        backup=storage.backup_world(cache)
        with storage.world_transaction(cache) as db:
            if action=='Campaign':
                chief=next((r for r in council(db,sect) if r['office'] in MASTER),None)
                if not chief:error('This sect needs a living master.')
                site,objective,owner=choice
                if not any(t['site']==site and t['objective']==objective and t['owner']==owner for t in sites(db,sect)):error('The objective changed. Reload choices.')
                result=declare(db,chief['actor'],site,objective,debug_force=force)
                if force and stage!='Muster':
                    if stage not in ('March','Contest','Holding'):error('Unknown campaign stage.')
                    db.execute('UPDATE campaigns SET phase=?,deadline=?,control=? WHERE id=?',(stage,clock()[0]+.5,2 if stage=='Holding' else 0,active(db,sect)['id']))
            elif action=='Coup':
                a=progress.political_actor(choice)
                if a['sect_id']!=sect:error('The elder changed sects.')
                pid=progress.start_plot(choice,force=force)
                if force and stage!='gathering':
                    if stage not in ('preparing','conflict'):error('Unknown coup stage.')
                    db.execute('UPDATE sect_plots SET stage=?,due=? WHERE id=?',(stage,clock()[0]+.4,pid))
                    progress.political_event(sect,'Council unrest',a['name']+' has begun a '+stage+' takeover.',actor=choice,plot=pid)
                result='Takeover started by '+a['name']+'.'
            elif action=='Opinion':
                if choice==subject or not subject:error('Choose a distinct subject and observer.')
                if opinion not in ('respect','trust','fear','hostility'):error('Unknown opinion.')
                value=int(value)
                if not (-100 if opinion in ('respect','trust') else 0)<=value<=100:error('Opinion is outside its permitted range.')
                db.execute('INSERT OR IGNORE INTO relationships(player,npc) VALUES(?,?)',(subject,choice))
                db.execute('UPDATE relationships SET '+opinion+'=? WHERE player=? AND npc=?',(value,subject,choice))
                result=f"Observer’s {opinion} set to {value}."
            elif action=='Grant Dao Integration Pill':
                if not subject:error('Select a subject.')
                pav=storage.read_pavilion(subject);pav['items'][gamedata.DAO_PILL]=pav['items'].get(gamedata.DAO_PILL,0)+1
                storage.write_pavilion(subject,pav['items'],pav['spent'])
                result='Granted one Dao Integration Pill. Start the ritual from Breakthrough when qualified.'
            else:error('Unknown debug action.')
        return result+' Backup: '+backup.name
    finally:
        del storage._world_local.debug_cache

def dispatch_raid(db,leader,sect,site,ends):
    army=db.execute("""SELECT a.actor FROM affiliations a JOIN profiles p ON p.id=a.actor WHERE a.sect_id=?
        AND p.kind='npc' AND a.office NOT IN ('Sect Master','Acting Master') AND json_extract(p.data,'$.life.dead') IS NULL
        ORDER BY CASE a.office WHEN 'Elder' THEN 0 ELSE 1 END,a.loyalty DESC,a.actor LIMIT 7""",(sect,)).fetchall()
    sent=sum(assign_escort(db,m[0],leader,site,'Raid',ends) for m in army)
    ritual_event(db,leader,site,'Council authorizes an ascension raid',f"{sect_name(db,sect)} voted to intervene. {sent} cultivators answered the order.")
    return sent


def ritual_command(actor,state,action,leader):
    if state['dead']:error('Only living cultivators can intervene.')
    here=storage.require_physical(actor,dangerous=True)
    with storage.world_transaction() as db:
        r=db.execute('SELECT * FROM ascensions WHERE actor=?',(leader,)).fetchone()
        if not r:error('That ascension has ended.')
        own=db.execute('SELECT sect_id FROM affiliations WHERE actor=?',(leader,)).fetchone()[0]
        sect=state['sect_id']
        if action=='Defend ascension':
            if not assign_escort(db,actor,leader,r['site'],'Guard',r['ends']):error('You already have a military assignment.')
            if here['location']!=r['site']:march(actor,r['site'])
            return 'You have pledged to protect the ascender.'
        if not sect or state['office'] not in MASTER or sect==own or active(db,sect):error('An available rival sect master must call this vote.')
        if here['location']!=home(db,sect):error('Convene your elders at your council seat.')
        decided=db.execute('SELECT player_decision FROM ritual_votes WHERE leader=? AND sect=?',(leader,sect)).fetchone()
        if decided and decided[0]:error('Your council already decided.')
        votes=council_vote(db,sect,own,r['site'],'Prevent ascension')
        db.execute('INSERT OR REPLACE INTO ritual_votes(leader,sect,player_decision) VALUES(?,?,1)',(leader,sect))
        if sum(v for _,v in votes)<=len(votes)//2:return 'The council rejected intervention.'
        return f"{dispatch_raid(db,leader,sect,r['site'],r['ends'])} raiders dispatched."

def map_armies():
    """Field orders describe intent. Positions and journeys locate the troops."""
    with storage.world_snapshot() as db:
        rows=db.execute("""SELECT w.id campaign,u.side,s.name sect,u.origin,p.location,j.path,j.departure,j.arrival,
                    count(*) troops FROM campaigns w JOIN campaign_forces u ON u.campaign=w.id
                    JOIN sects s ON s.id=u.origin JOIN positions p ON p.actor=u.actor
                    LEFT JOIN journeys j ON j.actor=u.actor
                    WHERE w.result IS NULL
                    GROUP BY w.id,u.side,u.origin,p.location,j.path,j.departure,j.arrival
                    ORDER BY w.id,u.side,u.origin,p.location,j.departure""")
        return dict(day=storage.world_state()['day'],groups=[dict(row) for row in rows])
