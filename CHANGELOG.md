# Steam Cultivator v0.6.1 — The Living World Update

## Overview

The Living World Update is one of the largest expansions to Steam Cultivator so far, transforming the game from a primarily character-focused cultivation experience into a persistent, autonomous simulation.

The world now contains thousands of individual cultivators who travel, train, undertake missions, fight, develop relationships, remember events, and participate in sect politics independently of the player.

This update combines the Living World foundation, world expansion, sect politics, and the v0.6.1 performance improvements.

---

## 1. Living World & Autonomous NPC Simulation

- Introduced a persistent population of **2,500 NPC cultivators**, including sect members and independent wanderers.
- Established **20 persistent sects** with individual membership rosters and leadership.
- NPCs autonomously cultivate, travel, undertake missions and adventures, socialize, and challenge other cultivators.
- NPC personalities, relationships, injuries, resources, and nearby opportunities influence their decisions.
- Cultivators can progress through cultivation realms, suffer injuries, and die.
- Introduced the **Heavenly Calendar**, with one in-game day passing every five minutes of active play.
- World progression pauses when the game is closed or when a player road encounter awaits a decision.
- NPC identities, locations, schedules, relationships, and world changes persist through SQLite.

## 2. World Exploration & Physical Travel

- Introduced an interactive world map with **40 locations across five districts**.
- Added fixed sect headquarters and a connected road network.
- Players and NPCs travel using persistent, timed journeys.
- Added route previews, travel progress, and Fastest/Safer route selection.
- Travel danger affects the probability of encountering threats.
- Characters must be physically present for conversations and many activities.
- Missions use actual world locations, requiring travel to complete certain objectives.
- Introduced the **People here** interface for browsing cultivators at the player's current location.
- Added name filtering, pagination, nearby NPC profiles, and automatic list updates.

## 3. Sect Membership, Mentorship & Politics

- Players can choose their starting sect during character creation.
- Added sect membership changes, headquarters-based joining, departure consequences, and preserved former membership records.
- NPCs can voluntarily leave sects or seek membership according to their personalities and circumstances.
- Introduced direct discipleship under elders and sect masters.
- Mentors provide training and achievement-based rewards.
- Added persistent sect offices, including elders, sect masters, and acting masters.
- Introduced leadership salaries and council-based appointment requirements.
- Players can seek promotion to elder or compete for sect leadership.
- Added council support, political influence, and bribery using actual Spirit Stones.
- Introduced autonomous political conspiracies, evidence gathering, and takeover attempts.
- Sect leadership can change through legitimate succession, political challenges, or armed internal conflict.
- Players can investigate plots, warn leadership, negotiate, support challengers, or defend the existing leadership.
- NPCs can independently resist political threats and participate in factional conflicts.
- Significant leadership changes and political crises become part of World History.

## 4. Relationships, Memories & World History

- Introduced persistent NPC relationships involving trust, respect, fear, hostility, and remembered encounters.
- Added distinct NPC personalities that influence behavior and social interactions.
- NPCs can recognize notable deeds, reputation, sect positions, and important achievements.
- Introduced event witnesses and geographically spreading news.
- Conversations reflect information that an NPC has actually learned.
- Significant actions can affect relationships and public reputation.
- Added **World History**, a persistent chronicle of major breakthroughs, deaths, notable combat achievements, and political events.
- Ordinary activities are distinguished from significant historical events.
- Event consequences are tracked to prevent duplicate rewards or repeated relationship effects.
- Added persistent conversation histories and contextual NPC dialogue.

## 5. Combat, Injuries & Road Encounters

- Expanded dueling into three modes: **Sparring, Competitive, and Lethal**.
- Added different risks and consequences for each duel type.
- Introduced temporary injuries that reduce combat effectiveness and restrict dangerous activities.
- Added rematch cooldowns and notable victories against stronger opponents.
- NPCs autonomously challenge other NPCs according to their behavior and circumstances.
- Added interactive road encounters with retreat, escape, and fight choices.
- Encounter outcomes can include injuries, rewards, interrupted travel, or death.
- Player encounters require explicit decisions and never silently initiate lethal combat.
- Existing team battles remain supported with additional location and injury checks.

## 6. Character Creation & Progression

- Added player-facing offline cultivator creation without requiring Steam access.
- Introduced starting-character progression limits for more balanced new characters.
- Added expanded personality traits and motivations.
- Introduced **Veteran** and **Sage** bonuses for eligible long-standing Steam accounts.
- Added optional starting treasures based on public Steam Community inventories from supported games.
- Improved cultivation power calculations and local character editing.
- Added persistent Spirit Stone balances and expanded sect-related progression.
- Introduced mentorship-based training and achievement rewards.
- Improved character profiles with additional world, personality, and progression information.

## 7. World Interface & Quality-of-Life Improvements

- Added dedicated World interfaces for population browsing, map exploration, leadership, relationships, and nearby cultivators.
- Added NPC profile inspection without changing the selected player character.
- Improved NPC conversation access and physical-presence checks.
- Improved nearby-person rendering, filtering, pagination, and scroll-position preservation.
- Improved encounter prompts and persistent encounter handling.
- Added sect membership, mentorship, and political management interfaces.
- Improved calendar display and background UI updates.
- Expanded cached-character selection and integrated developer editing.
- Improved visual presentation with character status icons and a dedicated game-window icon.

## 8. Performance, Stability & Database Improvements

**v0.6.1 includes major technical improvements designed to keep the Living World responsive as its population and history grow.**

- Optimized NPC scheduling with bounded GUI simulation work.
- Improved handling of accumulated simulation time and catch-up processing.
- Reduced unnecessary database-path resolution and repeated queries.
- Optimized NPC relationship lookups to avoid scanning the entire relationship database.
- Improved World Map queries and nearby-population rendering.
- Added automatic retrying of the latest requested World tab after busy operations.
- Introduced supporting SQLite indexes for event cleanup.
- Split expired-event cleanup into smaller transactions to prevent prolonged World-lock contention.
- Improved active-time handling on Windows to distinguish processing delays from computer suspension.
- Preserved transaction consistency while allowing simulation work to proceed incrementally.
- Improved database validation, error handling, and save migration safety.

### Performance benchmark

On a recovered mature simulation save containing millions of persistent records:

- The original expired-event cleanup required approximately **358 seconds**.
- The optimized cleanup processed the same **1,041 expired events in 1.87 seconds**.
- Cleanup was divided into **11 transactions**, with the longest taking approximately **0.21 seconds**.
- In a separate two-minute GUI test, seven World-tab requests completed in approximately **0.05–0.30 seconds** each.
- The simulation backlog decreased while new playtime continued accumulating.

These are measured test results, not guaranteed performance figures for every computer or save.

## 9. Persistent World & Save System

- Consolidated world progression into a persistent SQLite database.
- Added persistent NPC identities, sect memberships, locations, schedules, events, relationships, and political records.
- Introduced database-backed world time and session ownership.
- Added backed-up migrations for major save-format changes.
- Improved transaction safety for gameplay actions affecting multiple records.
- Expanded developer tools for inspecting, editing, backing up, and restoring character data.
- Preserved important world state across restarts and supported migrations.

## 10. Future Development

The Living World is still expanding.

Planned future systems include:

- Inter-sect warfare and diplomacy.
- Territorial control and conquest.
- Sect resource production and economies.
- Major inheritance expeditions.
- Additional long-term world simulation systems.

These features are **not included in v0.6.1**.

---

## Alpha Compatibility Notice

Steam Cultivator remains under active Alpha development. Major updates may change the world database format, and full backward compatibility is not guaranteed.

Before upgrading, close the game and developer tools, preserve a backup of the existing installation, and copy the complete `cache` folder into the new installation.

Do not run multiple game instances against the same world database.

---

**The Living World Update lays the foundation for a cultivation world that continues evolving through the actions of its inhabitants, not just the player.**
