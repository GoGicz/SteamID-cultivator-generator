# SteamID-cultivator-generator

Turn your Steam profile into a cultivator from a xianxia novel.

Features
- Steam-powered cultivation realms
- Heavenly talents and elemental affinities
- Sects, techniques, and treasures
- Life, death, and heavenly fate
- Encounters with Steam friends
- Achievements as sect missions
- Personality and Reputation system based on your steam Stats
- Mock Battle system which allow two different SteamID's to have dynamic battles between them
- full profile caching for better load time
- Inventory and theft system based on your cached cultivator profile
- Sect martial pavilion let's you buy treasures and talismans for protection

  **example:**
  <img width="1920" height="861" alt="obrazek" src="https://github.com/user-attachments/assets/5fb88fe7-cdac-43ec-bb5f-cd032eeab14e" />

  <img width="1918" height="831" alt="obrazek" src="https://github.com/user-attachments/assets/526bd267-0b05-4fde-89aa-2cf8b5d59f83" />

  **example of the mock battle in GUI mode:**
  <img width="1041" height="811" alt="obrazek" src="https://github.com/user-attachments/assets/704a823d-9e65-413a-9e6a-8ffca190ef0a" />


  **example of the mock battle in terminal mode:**
  
  <img width="751" height="517" alt="obrazek" src="https://github.com/user-attachments/assets/72dee07a-2aa0-4dd9-bb95-c55c7598df4c" />

  <img width="978" height="513" alt="obrazek" src="https://github.com/user-attachments/assets/19e65829-2f65-4513-abdd-812e07924d97" />
  
**Setup for GUI+Terminal:**  
    **pip install customtkinter**  
    **pip install requests**  
    
  **Run: python steam_cultivator_gui.py (steam_cultivator.py must be next to it):**

    Windows (cmd):   set STEAM_API_KEY=yourkey
    Linux / macOS:   export STEAM_API_KEY=yourkey
    or just paste it when the program asks.

**Setup for Terminal only:
    pip install requests**
    
  **Get a free API key: https://steamcommunity.com/dev/apikey
    Set it as an environment variable (recommended):**
    
    Windows (cmd):   set STEAM_API_KEY=yourkey
    Linux / macOS:   export STEAM_API_KEY=yourkey
    or just paste it when the program asks.

**Run:
    python steam_cultivator.py**

*Your Steam profile's "Game details" must be set to Public,
otherwise Steam will not give out the data.
The friend story needs a public "Friends List" too; if it is private (or you
have no friends) the story is simply skipped.*





**This project was also Helped with AI, therefore this project also will always stay under the MIT license so anyone can use this, this project is merely a fun project meant to share as jokes between my friend group so take it or leave it or modify it and add more names, sect names etc easily using the template system implemented.**

# Disclaimer

Steam Cultivator Generator is an unofficial, fan-made project and is not affiliated with, endorsed by, or sponsored by Valve Corporation or Steam.

Steam profile information is retrieved using the Steam Web API. All cultivation characters, ranks, talents, and fictional events are generated for entertainment purposes.

Steam and related trademarks belong to their respective owners.
