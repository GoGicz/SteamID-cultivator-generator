**changed:** split the modules for easier understanding of the code

**How to use it:**

*Put all the .py files in one folder, replacing the old steam_cultivator.py and steam_cultivator_gui.py. The zip has the same 14 files if you’d rather download one thing.
Run python steam_cultivator.py or python steam_cultivator_gui.py as before.
The top of steam_cultivator.py now lists what each file is for.*


**The modules:**

*steam_cultivator.py is the command line, with the command routing and prompts.*

*steam_cultivator_gui.py is the window.*

*logs.py, steam_api.py, storage.py, achievements.py and steam_profile.py cover logging, Steam requests, saved profiles, achievement counting and assembling a profile.*

*gamedata.py and gametext.py hold the static content: realms, talents, treasures, and all the story and battle templates.*

*generator.py builds the cultivator.*

*combat.py covers duels, theft and duel reputation.*

*pavilion_shop.py covers buying and selling.*

*progress.py covers breakthrough, adventure and rebirth.*

*display.py handles terminal printing.*
