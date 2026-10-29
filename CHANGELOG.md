Added:

1.Achievements caching, now only the first time lookup takes time and any secondary lookup will use the cache file that gets created in the "cache" folder

2.When new achievements appear, the card shows a line such as “+12 new missions (+60 sect points) since your last visit”. A note under the stats says where the numbers came from, for example “1 of 37 games checked with Steam, 36 read from the cache”

3.To force a full re-check, type refresh <profile> at the prompt, or start the program with --refresh. Deleting the cache folder is always safe.

Changes:

1.the changes in the caching system and achievement system improved our testing from calling 9,492 API calls to just 366 API calls
2. fixed bug: The old code counted a failed lookup as 0 achievements. With a cache, that wrong zero would have been saved. Failed lookups are now never saved: the game keeps its last known value, or 0 if there is none, and gets retried next time. The card says how many games couldn’t be checked.

Notes:

The first lookup of a profile is as slow as before, but it saves one file per profile (cache/<SteamID>.json).
On the next run, a game is asked about again only if:
it’s new to the cache (for example a game you just started),
its playtime or “last played” time changed, since achievements come from playing, or
its saved entry is more than 30 days old.

If your achievements are private, the program stops after about three refused answers instead of asking about every game.
A damaged or old cache file is ignored and rebuilt, and an unwritable folder gives one warning and the program carries on.
If you press Ctrl+C partway through a long first scan, the games already finished are kept, so the next run only does the rest.
If you make your profile private after it’s cached, the program still shows the saved numbers.

One limitation
An achievement unlocked without touching the game (for example with an achievement tool) won’t be seen on a normal run. The 30-day re-check or refresh picks it up. You can change the 30 days with RECHECK_AFTER_DAYS at the top of the file.
