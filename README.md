# SteamID-cultivator-generator

Turn your Steam profile into a cultivator from a xianxia novel.

**Steam Cultivator Generator** is a free, open-source cultivation game that transforms your Steam profile into a fictional cultivator with unique abilities, treasures, and a personal story.

Originally created as a fun SteamID generator, the project has grown into a persistent cultivation world where thousands of NPC cultivators live their own lives, develop relationships, and shape the world independently of the player.

**Current version: v0.6.1 Alpha — The Living World Update**

## Features

- **Steam-powered cultivator generation** — Generate a unique cultivator based on your Steam profile, games, playtime, achievements, and account history, or create a character entirely offline.
- **Persistent Living World** — A simulated world with **2,500 autonomous NPC cultivators**, 20 sects, and a shared Heavenly Calendar. NPCs cultivate, travel, undertake missions, form relationships, fight, and progress independently.
- **World exploration and encounters** — Explore an interactive map with 40 locations across five districts, travel between sects, meet other cultivators, and encounter dangers along the road.
- **Sect membership and politics** — Join sects, complete missions, become a disciple or elder, compete for leadership, influence councils, and experience autonomous conspiracies, succession struggles, and internal conflicts.
- **NPC relationships and memories** — Cultivators have distinct personalities, remember encounters, spread news, and react to the actions and reputations of others.
- **Cultivation and character progression** — Cultivation realms, heavenly talents, elemental affinities, personalities, reputation, breakthroughs, lifespan, death, rebirth, and heavenly fate.
- **Dynamic combat system** — Fight other cultivators in sparring, competitive, or lethal duels, with injuries and lasting consequences. Supports **1v1, 2v2, and 3v3 battles**.
- **Treasures, inventory, and sect economy** — Collect treasures and techniques, manage inventory, steal items, earn Spirit Stones, and purchase treasures or protective talismans from the Sect Martial Pavilion.
- **Adventures and missions** — Go on adventures, encounter randomized events, and complete sect missions for rewards and progression.
- **World History and personal stories** — Significant events, notable victories, deaths, breakthroughs, and political changes become part of the world's persistent history.
- **Steam friends and achievements** — Generate encounters involving Steam friends and use Steam-related data to influence your cultivator's story and abilities.
- **GUI and Terminal modes** — Play through the graphical interface or the terminal, with SQLite-based saving and caching.

The Living World is still being expanded. Future updates are planned to introduce inter-sect warfare, territorial conquest, and additional cultivation systems.

## Examples

**Example of a generated cultivator:**

<img width="1036" height="805" alt="obrazek" src="https://github.com/user-attachments/assets/e6cc6d17-549e-4a39-9c3d-1c084bb82a83" />


<img width="1844" height="782" alt="obrazek" src="https://github.com/user-attachments/assets/cecbbe6f-322b-4279-8b3e-10a64dd801c0" />


**Example of a sect and it's politics:**

<img width="1900" height="812" alt="obrazek" src="https://github.com/user-attachments/assets/4fef3228-5fdd-40f6-92b3-48ccb1b8c944" />


**Example of the map:**

<img width="1040" height="810" alt="obrazek" src="https://github.com/user-attachments/assets/61f3f295-272e-427d-a6df-71e1dd8858ca" />

**Example of current location cultivators:**
<img width="1039" height="808" alt="obrazek" src="https://github.com/user-attachments/assets/ccd4e553-4f45-4137-8e55-ddc7bbc908d6" />


## Setup

### GUI + Terminal

Install the required dependencies:

```bash
pip install customtkinter requests
```

Run the graphical version:

```bash
python steam_cultivator_gui.py
```

### Terminal only

Install the required dependency:

```bash
pip install requests
```

Run the terminal version:

```bash
python steam_cultivator.py
```

Keep the other game modules and the supplied `assets` folder alongside the main scripts.

## Steam API Key

Get a free Steam Web API key:

https://steamcommunity.com/dev/apikey

Set it as an environment variable (recommended):

**Windows (Command Prompt):**

```cmd
set STEAM_API_KEY=yourkey
```

**Linux / macOS:**

```bash
export STEAM_API_KEY=yourkey
```

Alternatively, enter the API key when the program asks for it.

Your Steam profile's **Game details** must be set to **Public**, otherwise Steam cannot retrieve the required data.

The Steam friends story feature also requires a public Friends List. If your list is private or empty, that part of the story is skipped.

You can also create and play with local cultivators without using a Steam API key.

## Save Data & Alpha Notice

The game uses a persistent SQLite database (`cache/world.db`) to store cultivators, NPCs, relationships, world progression, and other saved information.

**Do not delete your `cache` folder when updating.** Back up your saves before installing a new version.

Steam Cultivator is still in Alpha. Features, balancing, and save formats may change as development continues, and backward compatibility is not guaranteed for every update.

## Open Source

This project was developed with the help of AI and will remain available under the **MIT License**.

It originally started as a fun project to share jokes with my friend group, and that spirit remains part of it. You're welcome to use it, modify it, or add your own names, sects, and other content through the game's template system.

## Disclaimer

Steam Cultivator Generator is an unofficial, fan-made project and is not affiliated with, endorsed by, or sponsored by Valve Corporation or Steam.

Steam profile information is retrieved using the Steam Web API. All cultivation characters, ranks, talents, and fictional events are generated for entertainment purposes.

Steam and related trademarks belong to their respective owners.
