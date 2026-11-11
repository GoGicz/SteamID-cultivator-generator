# Steam Cultivator — Changelog

All notable changes from **v0.6.6 through v0.9.14-DEV**.

## v0.9.14-DEV — Retention Maintenance Improvements

### Improved
- Optimized background retention maintenance so completed cleanup jobs no longer waste processing slots.
- Added indexed, bounded cleanup of secondhand NPC news reports.
- Preserved recent news, in-progress rumor propagation, significant memories, and meaningful relationships.
- Added detailed retention diagnostics to `Logs/performance.log`, including cleanup activity, news deliveries, processing time, and maintenance backlog age.

### Technical
- Retention maintenance continues during simulation catch-up.
- No changes to NPC autonomy, news distribution rules, SQLite durability, or WAL checkpoint policy.
- Existing cleanup debt can still be processed with the offline database optimization tool.

## v0.9.13-DEV — Sect Politics Dashboard

### Added
- Redesigned **Sect Membership & Politics** into a cleaner, organized dashboard.
- Dedicated panels for membership, sect treasury, council confidence, mentorship, political support, career advancement, and political warnings.
- Responsive two-column layout that adapts to narrower windows.
- Clearer promotion eligibility explanations and labeled political controls.
- Persistent feedback and refresh controls.

### Improved
- Preserved selected council members, requested positions, payment inputs, and scroll positions during refreshes.
- Improved window lifecycle handling to prevent delayed callbacks from reopening closed dialogs.
- Corrected the display of living disciple capacity and clarified mentorship eligibility.
- Newly created offline players now begin with zero completed sect missions.
- Preserved existing player progression and developer customization.

## v0.9.12-DEV — NPC Memory & Rumor Optimization

### Improved
- Introduced bounded retention for routine NPC activity and secondhand news.
- NPCs retain 25 routine activity entries and a target of 170 secondhand Local reports.
- Protected recent rumors, ongoing news propagation, direct memories, major achievements, and significant world events.
- Fixed maintenance starvation by allowing cleanup to continue during simulation catch-up.

### World Simulation
- Ordinary notable news now spreads regionally and through relevant sect headquarters.
- Major events and exceptional victories can still become worldwide news.
- News delivery uses bounded batches while preserving unfinished deliveries.
- Prevented repeated relationship effects from duplicate news delivery.
- Preserved NPC autonomy, meaningful relationships, travel, politics, warfare, and economic systems.

### Save Compatibility
- Added backed-up, resumable retention cleanup for existing worlds.
- Updated offline database optimization to apply the new retention limits without modifying the original save.

## v0.9.11-DEV — Simulation Efficiency & Diagnostics

### Improved
- Reduced redundant NPC profile decoding and database reads.
- Introduced transaction-scoped caches with proper invalidation after database changes.
- Improved sect mission travel behavior so NPCs can retain valid mission intentions until arrival.
- Preserved existing military scheduling and NPC decision frequencies.

### Diagnostics
- Expanded performance logging across World Map, Population, Campaigns, Leadership, Relationships, World History, and profile loading.
- Added detailed measurements for background work, GUI delivery, rendering callbacks, and simulation batches.
- Improved SQLite transaction and checkpoint diagnostics.
- Added bounded, rotating performance logs to avoid excessive diagnostic overhead.

## v0.9.10-DEV — SQLite WAL Management

### Improved
- Added SQLite WAL disk-space reclamation through the background checkpoint worker.
- Introduced a 64 MiB reclamation threshold with deferral when database locks prevent safe recovery.
- Added WAL reclaim and checkpoint diagnostics.
- Preserved existing database durability and simulation data.

## v0.9.9-DEV — Cultivation & World Responsiveness

### Added
- **Cultivate (+1 day)** allows players to gain power while advancing the entire world by one Heavenly day.
- Five-minute active-play recovery shared across player profiles.
- Power gains from competitive or lethal duels against equally strong or stronger opponents.
- Visible simulation catch-up progress following cultivation.

### World Map
- Added visible attacking and defending army markers.
- Army markers show troop counts, sect information, and locations.
- Players can inspect armies and select destinations using map markers or **Find an army**.

### Improved
- Optimized database path handling and background simulation catch-up.
- Improved responsiveness while queued world simulation work is processed.
- Preserved all pending NPC actions, travel, payroll, and military activity.

## v0.9.2–v0.9.8 — World Performance, Warfare & Ascension

### World Performance
- Added **Pause simulation** to the World interface.
- Improved World History responsiveness through independent background reads.
- Introduced SQLite WAL mode on supported local Windows drives.
- Added diagnostic logging for slow database operations and delayed GUI activity.
- Improved sect council scheduling and simulation catch-up handling.

### Warfare & Diplomacy
- Added more cautious autonomous campaign planning based on treasury affordability and military strength.
- Councils account for mobilization, supplies, payroll, arrears, and occupation upkeep before launching offensives.
- Introduced post-settlement truces and delayed council policy reviews.
- Armies can withdraw when their sect can no longer afford an offensive.

### Sect Economy
- Increased small-mine production to 18,000–22,500 Spirit Stones per two active hours.
- Preserved large-mine production and existing sect financial obligations.

### Pavilion & Trading
- Added sect-point purchases at sect headquarters.
- Introduced public Spirit Stone trading locations.
- Added consumable cultivation and injury-recovery pills.
- NPCs autonomously travel to trade based on their needs, finances, and personalities.
- Added mission completion tracking and occasional Spirit Stone rewards from adventures.

### Immortal Ascension
- Added the **Dao Integration Pill** ascension ritual for qualified Tribulation cultivators.
- Ascension requires surviving five Heavenly days at the ritual site.
- Players can recruit protectors before beginning the ritual.
- Rival sects can dispatch raiders to interrupt ascension.
- Successful ascension grants immortality; interruption causes a major injury.
- Added ascension tracking through World Campaigns and World History.

### Developer Tools
- Expanded Living World Debug controls for campaigns, coups, and NPC opinions.
- Added forced campaign and coup stages for testing.
- Debug commands create database backups before modifying world state.

## v0.8.x — Inter-Sect Warfare & Diplomacy

### Added
- Autonomous inter-sect military campaigns and territorial conflicts.
- Campaign objectives including mines, passes, headquarters, and reparations.
- Physical troop mustering, marching, combat, withdrawal, and garrison deployment.
- Sect council voting and leadership overrides for military decisions.
- Defensive alliances, embassies, peace negotiations, and truces.
- Military supply costs, casualties, territorial concessions, and upkeep.

### Player Participation
- Players can volunteer for campaigns, report to muster, and join military operations.
- Elders can propose campaigns and direct detachments.
- Sect Masters can appoint commanders, manage diplomacy, negotiate peace, and assign garrisons.
- Field commanders can issue army-wide orders.

### Living World
- NPCs respond to military invitations according to personality, courage, and strength.
- Troops must physically travel to objectives and be fit for combat.
- Political and territorial outcomes are recorded in World History.
- Displaced sects can seek refuge or operate from remaining holdings.

## v0.7.x — Territory & Sect Economy

### Added
- Expanded the world map to nine districts.
- Added sect headquarters mines and four contested frontier mining regions.
- Introduced territorial ownership, passes, frontier holds, and mine wardens.
- Added shared sect treasuries and periodic mine income.
- Added recurring sect payroll, wage arrears, and partial salary payments.
- Founding sects receive an initial treasury of 10,000 Spirit Stones.

### Sect Politics
- Unpaid salaries reduce loyalty and confidence in sect leadership.
- Financial difficulties increase pressure for members to leave.
- Councils can remove leaders after sustained loss of confidence.
- Sect finances now influence long-term political stability.

## v0.6.6 — Offline Cultivators & Interface Improvements

### Offline Character Generation
- Introduced a dedicated offline character generation module.
- Local characters use their saved 20-digit IDs as generation seeds.
- Realm, power, reputation, talent, and traits are generated as cultivation attributes.
- Preserved existing local character progress, reputation, and history.
- Maintained separate Steam-based character scoring.

### Interface
- Added scrollable NPC profile windows with reusable rendering.
- Improved conversation controls and in-place response updates.
- Organized the Martial Pavilion into **Pills, Weapons, Treasures, Talismans, and Sell Treasures**.
- Improved profile browsing without replacing the currently selected player.

---

## Save Upgrade Instructions

When updating from an older release:

1. Close Steam Cultivator and the Developer Editor completely.
2. Extract the new version into a separate folder.
3. Copy your entire existing `cache` folder into the new installation.
4. Keep the previous installation and save as a backup.
5. Allow any required database migrations and backups to complete on first launch.

**Important:** Never delete `world.db-wal` or `world.db-shm` while the game is running. Do not run multiple game instances against the same world database.

## Notes

- Steam Cultivator uses a persistent SQLite world database.
- NPCs continue acting autonomously, with saved relationships, memories, travel, sect politics, and military activity.
- Simulation time pauses while the game is closed.
- Performance improvements and retention policies do not guarantee a fixed maximum database size.
- Back up your world before upgrading or using developer tools.
**Thank you for playing Steam Cultivator!**

The world keeps evolving, and this update makes it much easier to watch its cultivators, sects, and political stories unfold.
