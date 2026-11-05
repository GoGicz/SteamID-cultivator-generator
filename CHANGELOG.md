# Steam Cultivator v0.6.5-DEV — Performance, UI & Living World Improvements

This release focuses on making the Living World faster, more storage-efficient, and easier to explore. From major SQLite optimizations to a redesigned interface with illustrated sect hierarchies, v0.6.5 brings substantial improvements to the existing 2,500-cultivator simulation.

**This is still an early development release.** Inter-sect warfare, diplomacy, territory conquest, and major inheritance expeditions remain planned for Living World Part 4.

## ✨ Highlights

- **Massively improved GUI performance:** Population, Relationships, World History, and other major views now avoid unnecessary widget rebuilding.
- **New illustrated sect hierarchy:** Explore your sect's leadership, elders, and direct disciples through clickable character portraits.
- **Reduced database growth:** New retention policies limit unnecessary historical storage while preserving important events and relationships.
- **Improved political history:** Sect takeovers and successions now provide clearer historical context.
- **Smarter relationship display:** Only cultivators you've actually spoken with appear in your Relationships tab.
- **Better character information:** Power, sect standing, and actual political authority are now presented more clearly.
- **Save compatibility:** Existing worlds can be carried forward without starting over.

## 🚀 GUI Performance & Scrolling Overhaul

The interface has received extensive optimization to reduce stuttering, visible rebuilding, and scrolling artifacts.

### Population, Relationships & World History

These views now use retained, scrollable cards instead of repeatedly destroying and recreating hundreds of Tk widgets.

- Unchanged rows no longer require unnecessary updates.
- Individual NPC changes update only the affected information.
- Pagination updates existing cards instead of rebuilding the entire interface.
- Scroll positions are preserved when returning to the same page.
- Keyboard navigation is supported for profile links.
- Rapid scrollbar dragging and mouse-wheel scrolling no longer trigger card reconstruction.

### Population Rendering Benchmarks

Measured on a mature 2,500-NPC world:

| Operation | Previous renderer | New renderer |
|---|---:|---:|
| Refresh unchanged page | 1,855 ms | **0.15 ms** |
| Update one NPC | 1,674 ms | **1.85 ms** |
| Display 50 different NPCs | 1,860 ms | **31.62 ms** |

These figures measure GUI rendering operations, not complete database-fetch times.

### Improvements Across Other Tabs

- **People here:** Uses the optimized renderer and handles NPC arrivals and departures without disrupting browsing.
- **Leadership:** Uses retained rendering for the hierarchy and member roster.
- **Cultivator:** Keeps Adventure controls and progress bars stable while details update.
- **Sect:** Mission board and character information update in place.
- **Pavilion:** Shop cards update without unnecessary rebuilding; purchases verify the displayed item, price, and character.
- **History & Battles:** Existing content updates more efficiently, with a new **Copy report** action for duel reports.
- **Log:** Preserves your reading position as new output arrives.

## 👑 Illustrated Sect Leadership Hierarchy

**World → Leadership** now opens a visual council hierarchy featuring illustrated character portraits.

- Gold highlights the Sect Master or Acting Master.
- Silver identifies elders.
- Jade connections show direct disciples and their actual mentors.
- The Sect Master's disciples appear on a separate branch.
- Click a portrait to open the cultivator's profile.
- Navigate using arrow keys and Enter.
- Use horizontal scrolling to explore larger hierarchies.
- Switch to **Member roster** for the complete paginated sect membership list.

The hierarchy uses a shared collection of **16 illustrated portraits**, consistently assigned to characters across promotions and restarts.

All offices and mentorship connections come from existing save data. Portraits do not increase the world database size.

## 📜 Improved Political History

World History now provides clearer information about political events.

- Succession and takeover reports identify the sect involved.
- New political events preserve the challenger's position at the time of the event.
- Historical reports no longer incorrectly describe a successful challenger using their newly acquired office.
- Older events display their recorded sect when available.
- Added political-event filtering and searching by sect name.
- Existing historical descriptions are preserved.

These improvements make it easier to follow leadership changes, political struggles, and major developments across the Living World.

## 🤝 Relationships & Character Information

### More Meaningful Relationships

The Relationships tab now displays **cultivators you've actually spoken to**.

NPCs can still develop respect, fear, hostility, or other opinions about you through rumors, missions, and world events before meeting you.

Their existing opinions become visible in the Relationships tab after your first conversation.

### Clearer Character Profiles

- Character cards distinguish **overall power**, **sect reputation standing**, and **actual political office**.
- Special roles such as Elder, Direct Disciple, Acting Master, and Sect Master are displayed accurately.
- Injured cultivators display their currently adjusted power.
- The Cultivator tab displays your sect reputation rank, while exact reputation points remain available in the Sect tab.
- Removed the developer-facing "Locally generated stats" text from player character cards. Generation details remain available in the command log.

## 💾 Database Storage Optimization

v0.6.2 introduced new retention and maintenance systems designed to reduce long-term database growth without discarding important world state.

### What Changed

- NPC profiles retain their latest **50 routine activity entries**.
- Significant milestones, including breakthroughs, notable duels, discoveries, injuries, deaths, and mentor rewards, are preserved separately.
- Older ambiguous activity records are preserved in a legacy archive.
- NPCs retain their latest **200 eligible secondhand Local reports**, with exceptions for active news propagation and recent reports.
- Archived news cannot repeatedly award relationship effects.
- Redundant event-effect records are retired.
- Expired duel cooldowns are cleaned up in bounded batches.
- Frequently updated profile JSON uses more compact formatting.
- Retention maintenance yields while simulation catch-up is pending.

**Existing relationships, important memories, major World History events, and gameplay state are preserved.**

### Storage Benchmarks

In controlled tests using identical worlds and 23,886 NPC actions:

- **18.2% less database growth** compared with v0.6.1.
- A separate mature-world snapshot shrank from approximately **470.6 MB to 287.2 MB** after eligible retention and offline compaction — a **39% reduction**.
- Compared gameplay-state records remained consistent between versions.

Actual savings depend on world age, accumulated history, and database contents. Database growth is reduced, not eliminated.

### Optional Offline Database Optimization

To optimize a copy of an existing database, close the game and developer editor, then run:

```powershell
python storage.py --optimize-copy "cache/world.optimized.db"
```

For compaction only:

```powershell
python storage.py --compact-copy "cache/world.compact.db"
```

These commands operate on private copies and do not replace the original database automatically.

**Important:** Large mature-world optimizations can take considerable time and require additional free disk space. Keep your original save until the optimized copy has been validated and tested.

## 🛠️ Stability & Compatibility

- Retains the existing 2,500-NPC Living World simulation.
- Preserves sect politics, journeys, encounters, relationships, and mentorship systems.
- Keeps both GUI and terminal gameplay modes.
- Includes protections against stale UI refreshes and incorrect clicks after list updates.
- Existing saves remain compatible through the supported migration process.
- No new world generation is required when upgrading.

## 📦 Upgrading From v0.6.1

**Please back up your existing world before upgrading.**

1. Close Steam Cultivator and the developer editor.
2. Extract v0.6.5-DEV into a **new folder**.
3. Copy your entire existing `cache` folder into the new installation, beside the Python scripts.
4. Launch the updated game normally.
5. Keep your previous installation and backup until you've confirmed that your world loads correctly.

**Database compatibility notes:**

- v0.6.2 upgrades existing databases to **schema 6**, creating a migration backup before the upgrade.
- v0.6.3, v0.6.4, and v0.6.5 retain the same schema 6 database format.
- Older v0.6.1 installations cannot open an upgraded schema 6 database. Use the pre-upgrade backup if you need to roll back.
- Never delete your `cache` folder to troubleshoot: it contains your persistent world and character progress.
- Do not run multiple game instances against the same world database.

## 🔮 What's Next?

Living World Part 4 remains planned, with future systems including:

- Inter-sect warfare and army mobilization.
- Diplomacy and territorial conflicts.
- Territory conquest and control.
- Major inheritance expeditions.

For now, v0.6.5-DEV concentrates on strengthening the performance, presentation, and reliability of the existing Living World.

---

**Thank you for playing Steam Cultivator!**

The world keeps evolving, and this update makes it much easier to watch its cultivators, sects, and political stories unfold.
