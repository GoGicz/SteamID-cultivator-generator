"""Every story template: friend stories, deaths, backstories, adventure events and the pieces a
duel is told from."""


# ---------------------------------------------------------------------------
# Friend stories. Placeholders: {me} {friend} {friend_steam} {game} {sect}
# {realm} {treasure}. Add as many templates as you like.
# ---------------------------------------------------------------------------
STORIES_COMMON = [
    "While wandering the mountains, {me} met a fellow cultivator named {friend} "
    "(known in the mortal realm as '{friend_steam}'). They shared a pot of spirit tea and "
    "swore to become sworn siblings on the spot. By the next morning both had forgotten the oath.",

    "{me} and {friend} found a secret realm hidden behind a waterfall. Inside waited an ancient "
    "inheritance, and after three days of arguing about whose {game} technique was superior, "
    "they opened the final chamber. It contained one note: 'Go touch grass.' Both were "
    "enlightened at once.",

    "A rival sect challenged {me} to a duel, and {friend} showed up uninvited with a bag of "
    "snacks to watch from the sidelines. The whole mountain heard the cheering. {me} won, "
    "mostly out of embarrassment.",

    "{friend} once asked {me} for a pill recipe. {me} confidently provided one, and the furnace "
    "explosion was seen from three provinces away. The {sect} still sends {friend} the bill.",

    "{me} and {friend} bet a month of spirit stones on who could meditate longer. Three days "
    "in, both were still sitting perfectly still, glaring at each other. A passing sect elder "
    "declared it a draw and quietly took the whole pot.",

    "{friend} dragged {me} into a market haggling contest over {treasure}. After an hour of "
    "dramatic gasps and walking away twice, the merchant paid {me} to leave. Nobody can "
    "explain how that works.",

    "In a thunderstorm, {me} and {friend} sheltered inside a cave that turned out to be the "
    "den of a sleeping dragon. They tiptoed out together, whispering about {game}, and "
    "agreed never to mention the dragon's snoring to anyone.",

    "{friend} invited {me} to a banquet 'with only a few guests'. It was the entire "
    "{sect}, two rival sects, and a goose of unclear origin. {me} still insists the goose "
    "started the fight.",

    "On a lonely road, {me} and {friend} found a map to a legendary treasure. They followed "
    "it for a week, argued at every crossroads, and finally dug up a chest holding a single "
    "spirit stone and a note: 'Friendship was the real treasure.' They split the stone anyway.",

    "{me} taught {friend} the secret of a {game}-inspired sword form. {friend} practiced it "
    "so loudly that the neighbors filed a complaint with the {sect}. The form is now banned "
    "after sunset.",

    "{friend} once swore to {me} that a certain mushroom was perfectly safe. For three days "
    "both of them saw the future, though sadly only the part where they ate more mushrooms. "
    "They have not looked at a mushroom since.",

    "Lost in a mountain fog, {me} and {friend} walked in circles for a whole day before "
    "realizing they had been following each other. They laughed until the fog lifted, and the "
    "path home turned out to be right behind them.",
]

STORIES_WEAK = [
    "{me}, whose cultivation had only reached {realm}, was cornered by a demonic beast until "
    "{friend} burst in wielding nothing but a cooking pot. The beast fled in confusion. "
    "Neither of them speaks of it.",

    "Both {me} and {friend} were too poor to afford a single spirit stone, so they pooled their "
    "savings for one steamed bun and shared it under a tree, swearing that one day they would "
    "rule the heavens. The bun was delicious.",

    "Still only at {realm}, {me} could not make a flying sword rise higher than a stool. "
    "{friend} stood on the stool to cheer anyway, and the sword wobbled into the air for one "
    "glorious second before dropping them both into a pond.",

    "{me} and {friend} were hired as guards for a merchant caravan, and managed to lose the "
    "caravan, the merchant and one very patient donkey. They were paid in a sack of turnips, "
    "which they ate with great dignity.",
]

STORIES_STRONG = [
    "{me}, whose cultivation had reached {realm}, crossed nine provinces in a single breath "
    "just to rescue {friend} from a terrible blind date arranged by the {sect}.",

    "At the Great Ascension Banquet, every elder bowed to {me}. Only {friend} dared to say, "
    "'You still owe me a spirit stone.' {me} paid up immediately.",

    "When {me}, a master of {realm}, finally walked through the gates of the {sect}, ten "
    "thousand disciples knelt. {friend} waved from the back and shouted, 'Nice robe!' It was "
    "the only compliment {me} remembered.",

    "{me} once split a mountain in two to settle a dispute. {friend} asked politely whether "
    "{me} could put it back, since the mountain had a very good view. {me} spent the rest of "
    "the week gluing a mountain together.",

    "Heaven's tribulation lightning rained on {me} for nine hours. {friend} sat beside the "
    "crater with a parasol and a flask of tea, remarking that {me} looked 'a little "
    "crispy'. They shared the tea after.",
]

# ---------------------------------------------------------------------------
# Death scenes. Placeholders: {me} {sect} {technique} {treasure} {realm} {game}
# plus {rogue} / {bandits} (killer descriptions) or {friend} / {friend_steam}.
# ---------------------------------------------------------------------------
DEATH_ROGUE = [
    "{me} was ambushed at a mountain pass by {rogue} who coveted {treasure}. The duel lasted "
    "three breaths. {me}'s last words were reportedly: 'Tell the {sect} I was winning.'",

    "At the exact moment of a breakthrough attempt, {rogue} who had been stalking {me} for nine "
    "days finally struck. {technique} was unleashed too late, and the mountain fell silent.",

    "{me} accepted a duel with {rogue} and underestimated the stranger. The Heavens did not "
    "even bother to send thunder.",
]

# Died because a failed breakthrough used up the last of the lifespan. Placeholders: {me} {sect} {realm}
DEATH_LIFESPAN = [
    "The failed breakthrough had taken the last of {me}'s years. At dawn the {sect} found "
    "{me} sitting upright in the meditation hall, as peaceful as stone, and the lamp beside "
    "{me} had burned out at the very same moment.",
    "{me} had been warned that another failure would cost more than the {sect} could pay. "
    "The Qi turned back, the years drained away like water from a cracked bowl, and the "
    "{realm} cultivator whispered one last word: 'Almost.'",
    "Nobody doubted {me}'s courage, only the arithmetic. The backlash of the failed "
    "breakthrough consumed what little lifespan remained, and the {sect} rang its bells "
    "for three days.",
    "The heavens do not forgive a breakthrough that fails at the end of a life. {me}'s hair "
    "turned white in a single breath, and the {realm} cultivator was dust before sunset.",
]
DEATH_BANDITS = [
    "While travelling a lonely mountain road, {me} was surrounded by {bandits}. {technique} "
    "felled many of them, but in the end numbers won.",

    "{me} held the road against {bandits} so that a small village could escape. The villagers "
    "still burn incense at a roadside shrine, though nobody remembers the {sect}.",

    "{me} was poisoned with a cup of cheap wine at a roadside inn, then finished off by "
    "{bandits}. They sold {treasure} the next day for three copper coins.",
]

DEATH_FRIEND = [
    "{me} was betrayed by an old friend, {friend} (known in the mortal realm as '{friend_steam}'), "
    "who offered a cup of spirit tea laced with poison and then struck the final blow. "
    "{me}'s last words: 'I trusted you.'",

    "{friend} ('{friend_steam}'), a friend of many years, stabbed {me} in the back during a "
    "secret realm expedition and left with {treasure}. The {sect} still whispers about it.",

    "{me} and {friend} ('{friend_steam}') entered an ancient ruin together. Only {friend} came "
    "out, carrying {treasure} and a very unconvincing explanation.",
]

# ---------------------------------------------------------------------------
# Backstory building blocks. Every cultivator gets one template and one variant
# from each tier list, all picked from their SteamID, so it never changes.
#   Tier lists are (upper limit, [variants]); the first limit the value stays under wins.
#   meditation / treasury / missions are past-tense phrases ("spent 80 hours ...") and
#   work after any subject; dao is a complete sentence without the final period.
# ---------------------------------------------------------------------------
INF = float("inf")

MEDITATION_TIERS = [   # by hours in the most-played game: {hrs} {game}
    (5,    ["barely began to meditate in the cave of {game}",
            "dipped a toe into cultivation inside the cave of {game}, then wandered off for snacks"]),
    (200,  ["spent {hrs} hours in closed-door cultivation inside the cave of {game}",
            "sat cross-legged for {hrs} hours in the cave of {game}, slowly refining their Qi"]),
    (1500, ["endured {hrs} hours of seclusion in {game}, emerging with unshakable resolve",
            "vanished into {game} for {hrs} hours and returned with a sharper Dao heart"]),
    (INF,  ["sat in seclusion for an absurd {hrs} hours within {game}, long enough for mountains "
            "to turn to dust",
            "lost count of the seasons during {hrs} hours of seclusion in {game}, and the sect's "
            "cats grew old waiting"]),
]

TREASURY_TIERS = [     # by paid games owned: {gc}
    (1,    ["owned no treasures worth mentioning, a truly poor cultivator",
            "kept an empty storage ring and a head full of big dreams"]),
    (20,   ["kept {gc} humble treasures in their storage ring",
            "carried {gc} modest treasures wrapped in an old cloth"]),
    (200,  ["gathered {gc} treasures from across the realms",
            "collected {gc} treasures, each with its own story or curse"]),
    (INF,  ["amassed a vault of {gc} treasures that made whole sects weep with envy",
            "ruled over a treasure vault of {gc} items, guarded by three formations and one "
            "grumpy elder"]),
]

DAO_TIERS = [          # by Steam level: {lvl}
    (5,    ["A shallow Dao foundation had yet to be forged",
            "Their Dao foundation was only a tender sapling"]),
    (30,   ["Their Dao foundation stood at level {lvl}, steady but unspectacular",
            "At level {lvl}, their Dao foundation was solid if not dazzling"]),
    (100,  ["Their Dao foundation, tempered to level {lvl}, was respected throughout the region",
            "Tempered to level {lvl}, their Dao foundation earned quiet respect across the region"]),
    (INF,  ["Their Dao foundation reached level {lvl}, a height few have ever seen",
            "A Dao foundation at level {lvl} drew awe from rivals across nine provinces"]),
]

MISSION_TIERS = [      # by sect missions (= achievements): {n}
    (1,    ["never completed a single sect mission",
            "dodged every sect mission posted on the board"]),
    (2,    ["completed exactly one sect mission, and brought it up at every banquet",
            "finished one sect mission and took a three-year rest afterwards"]),
    (50,   ["completed {n} sect missions, just enough to avoid being thrown out",
            "took on {n} sect missions, mostly the ones nobody else wanted"]),
    (300,  ["completed {n} sect missions without complaint",
            "answered the mission board {n} times"]),
    (1000, ["completed {n} sect missions, and the mission hall elders learned their face by heart",
            "cleared {n} sect missions and earned a reserved seat at the mission hall"]),
    (INF,  ["completed an astonishing {n} sect missions, and the mission hall clerks ran out of ink",
            "cleared {n} sect missions, a record the {sect} carved onto a stone tablet"]),
]

REPUTATION_TIERS = [   # by reputation rank number (0 = lowest): {sect} {rank}
    (2,    ["Hardly anyone in the {sect} could have named them, and the world's verdict was "
            "simply '{rank}'",
            "Their name drew only shrugs, and the gossips filed them under '{rank}'"]),
    (4,    ["A few disciples of the {sect} knew their name, and rumor called them '{rank}'",
            "Their name had started to travel between the dining hall and the mission board, "
            "earning the title '{rank}'"]),
    (6,    ["Their name was spoken in tea houses across the region, where they were called "
            "'{rank}'",
            "Travelling merchants carried tales of them across the provinces, and the title "
            "'{rank}' followed"]),
    (8,    ["Whole sects bowed their heads at the mention of their name, and the world hailed "
            "them as '{rank}'",
            "Their name was carved into the tournament stones of three continents, and they "
            "became known as '{rank}'"]),
    (INF,  ["Every living cultivator knew their name, and even the heavens called them "
            "'{rank}'",
            "Their legend outlived kingdoms and sects alike, and the ages remembered them as "
            "'{rank}'"]),
]

# Placeholders: {steam} {name} {sect} {a_title} {talent} {dao} {meditation} {treasury}
# {missions} {personality} {reputation} {treasure} {element} {technique} {game} {realm}.
# {personality} is a past-tense phrase ("{name} made friends wherever they went");
# {reputation} is a full sentence without the final period. Add your own!
BACKSTORIES = [
    "Once known on Steam as '{steam}', {name} joined the {sect} as {a_title}. Their talent "
    "test revealed {talent}. {dao}. They {meditation}, and {treasury}. Within the sect, they "
    "{missions}. {name} {personality}. {reputation}. Their prized possession was {treasure}.",

    "The mortal world knew {name} only as '{steam}', a stubborn wanderer who {meditation}. "
    "Eventually the {sect} accepted them as {a_title}, and the talent stone revealed {talent}. "
    "{dao}. Over the years they {missions}, and {treasury}. {name} {personality}. "
    "{reputation}. At their belt always hung {treasure}.",

    "Elders of the {sect} still argue about {name}, {a_title} who once went by '{steam}' in "
    "the mortal realm. The talent test showed {talent}. {dao}. Mission hall records say {name} "
    "{missions}, and the vault ledger says they {treasury}. {name} {meditation}. "
    "{reputation}. Some say {name} {personality}. Their prized possession was {treasure}.",

    "Some say '{steam}' was just a name {name} borrowed in the mortal realm. Whatever the truth, "
    "the {sect} took them in as {a_title}, and the elders at the talent test uncovered {talent}. "
    "{dao}. {name} {meditation}, then {missions}. Along the way they {treasury}. Disciples "
    "agreed that {name} {personality}. {reputation}. Their most precious belonging was "
    "{treasure}.",

    "{name}, formerly '{steam}' in the mortal realm, served the {sect} as {a_title}. The talent "
    "test showed {talent}. {dao}. In their time, {name} {missions}, and {treasury}. They also "
    "{meditation}. {reputation}. Friends and rivals alike agreed that {name} {personality}. "
    "Of all their belongings, {treasure} was the dearest.",

    "Nobody in the {sect} could say where {name} came from, only that the mortal records listed "
    "them as '{steam}'. They joined as {a_title}, and the talent test revealed {talent}. {dao}. "
    "Legend says {name} {meditation}, and that they {missions}. They {treasury}. {reputation}. "
    "Whenever the tale was told, it added that {name} {personality}. Their prized possession "
    "was {treasure}.",

    "{name} came to the {sect} as {a_title}, carrying nothing but the mortal name '{steam}' and "
    "an affinity for {element}. The talent test revealed {talent}. {dao}. {name} {meditation}. "
    "The {technique} became their signature art. Over time they {missions}, and {treasury}. "
    "It was said {name} {personality}. {reputation}. Their prized possession was {treasure}.",
]

# Placeholders in all of these: {me} {sect}; finds also {item}; reputation also {amount}
ADVENTURE_NOTHING = [
    "{me} went on a walk through the mountains, but nothing happened on the walk.",
    "{me} wandered the market of a nearby town all afternoon. Nothing happened, and nobody "
    "tried to sell a single fake pill.",
    "{me} sat by a stream for hours, waiting for an adventure. The stream kept flowing, the "
    "adventure never came.",
    "{me} climbed a tall peak for a view of the whole region. The view was lovely. Nothing "
    "else happened.",
    "A quiet day: {me} walked a long road, nodded at a few farmers, and walked back. The "
    "Heavens had nothing to say.",
    "{me} searched an old cave for a secret inheritance and found only bats and an echo.",
    "{me} meditated under a pine tree until sunset. The pine tree was unimpressed, and "
    "nothing happened.",
    "{me} followed a strange glimmer into the forest. It was a puddle. {me} came home "
    "slightly wetter and no wiser.",
    "A rumor of a hidden realm led {me} to an empty valley. There was no realm, only wind.",
    "{me} fed some wild cranes, practiced a few forms in a meadow and returned to the {sect} "
    "before dinner. Absolutely nothing happened.",
    "{me} took the long way around the lake. The long way turned out to be just as eventless "
    "as the short one.",
    "{me} spent the day looking for a rare herb. It turned out to be a weed, a perfectly "
    "ordinary weed.",
    "{me} stood in a thunderstorm hoping for a heavenly sign. It was only a storm.",
    "A hawk circled over {me} for an hour, as if it knew something. It did not.",
    "{me} walked the border of the {sect}'s lands twice, waved at the gate guards, and went "
    "home. The day will not be remembered.",
    "{me} watched the clouds for a whole afternoon. They drifted, they parted, they were "
    "only clouds.",
    "{me} visited a roadside shrine, burned a stick of incense, and heard no divine answer. "
    "A peaceful day, if an uneventful one.",
    "Nothing of note occurred. {me} left at dawn, returned at dusk, and could not have told "
    "anyone where the day had gone.",
]
ADVENTURE_FIND = [
    "On a forgotten trail, {me} noticed something shining in the roots of an old tree: "
    "{item}. A lucky day indeed.",
    "{me} helped an old hermit fix his roof, and he insisted on giving a reward: {item}.",
    "Beneath a collapsed shrine, {me} dug up {item}, which had waited there for a very long "
    "time.",
    "A wandering merchant lost a bundle on the road. {me} chased him for an hour, but he "
    "only waved back and shouted that {item} was a gift for the kind soul who picked it up.",
    "While resting in a cave, {me} pulled a loose stone from the wall and found {item} "
    "hidden behind it.",
    "A river had washed away a bank near the {sect}, and in the mud lay {item}. {me} was "
    "the first to find it.",
    "{me} won a game of chess against a grumpy old stranger, who paid the wager with {item} "
    "and left without a word.",
    "A spirit beast led {me} to its den, and in the nest, among the bones, lay {item}.",
]
ADVENTURE_REP_GAIN_TEXT = [
    "{me} drove a pack of wolves away from a village at the foot of the mountain. The "
    "villagers spread the story far and wide, and the name of the {sect} rose by {amount} "
    "reputation.",
    "{me} settled a bitter quarrel between two rival clans with patience and tea. Word of "
    "the wise peacemaker earned {amount} reputation.",
    "A caravan was saved from bandits when {me} happened to pass by. The merchants praised "
    "the cultivator in every city they visited: +{amount} reputation.",
    "{me} healed a sick child in a poor village without asking for payment. Gratitude "
    "traveled faster than any messenger bird: +{amount} reputation.",
    "{me} cleared an old demon's den that had troubled travelers for years. The {sect} "
    "recorded the deed, and the reputation rose by {amount}.",
    "At a small tournament, {me} took the winning bow and gave the prize to the runner-up. "
    "The crowd loved it: +{amount} reputation.",
]
ADVENTURE_REP_LOSS_TEXT = [
    "{me} lost a temper at a market and smashed a stall of spirit herbs. The whole street "
    "talked about it for days: -{amount} reputation.",
    "{me} promised to escort a merchant and then forgot the appointment entirely. The "
    "merchant told everyone: -{amount} reputation.",
    "{me} insulted a respected elder at a banquet, thinking nobody important was listening. "
    "Everyone important was listening: -{amount} reputation.",
    "A careless technique brought down the roof of an inn. The innkeeper sent the bill, and "
    "the gossip, to the {sect}: -{amount} reputation.",
    "{me} was caught bragging about a victory that had been won by someone else. The truth "
    "came out, as truth does: -{amount} reputation.",
    "{me} boasted of a secret technique and could not perform it when asked. The laughter "
    "lasted longer than the lesson: -{amount} reputation.",
]
ADVENTURE_TITLES = {"nothing": "A quiet adventure", "treasure": "A lucky find",
                    "friend": "A tale with a friend", "gain": "Fame", "loss": "Disgrace",
                    "reborn": "Reborn", "rebirth_fail": "The Heavens stay silent",
                    "rebirth_wait": "The Heavens are resting"}


# ---------------------------------------------------------------------------
# Duels: the "mocb" command
# ---------------------------------------------------------------------------
BATTLE_PLACES = [
    "a storm-lashed cliff above the Nine-Dragon Sea", "the ruins of an ancient sect gate",
    "a frozen mountain pass", "the arena of the Heavenly Tournament",
    "a moonlit bamboo forest", "a valley where the Qi hung thick as fog",
    "the courtyard of an abandoned temple", "a floating island high above the clouds",
]

# Openings by the two paths. In a mixed pair {x} is always the Righteous one and {y} the
# Demonic one. Placeholders: {x} {y} {x_sect} {y_sect} {place}
BATTLE_OPENINGS = {
    ("Righteous", "Righteous"): [
        "At {place}, {x} of the {x_sect} and {y} of the {y_sect}, both walkers of the "
        "Righteous Path, agreed to settle an old argument over who was the greater "
        "cultivator. Neither intended to hold back.",
        "Two upright cultivators, {x} and {y}, met at {place}. Bows were exchanged, then the "
        "Qi began to rise, because both were far too proud to yield.",
        "The elders of the {x_sect} and the {y_sect} had argued for a whole season about whose "
        "disciple was better. In the end they sent {x} and {y} to {place} to answer it.",
        "{x} had sworn to protect the weak, and {y} had sworn the very same thing. At {place} "
        "they discovered that a shared vow is no reason not to fight.",
        "A crowd of junior disciples gathered at {place} to watch {x} of the {x_sect} face {y} "
        "of the {y_sect}. Both walked the Righteous Path, and both wished to look good doing it.",
        "It began as a polite match at {place}. By the third exchange of bows, {x} and {y} had "
        "quietly decided that politeness was over.",
    ],
    ("Demonic", "Demonic"): [
        "At {place}, {x} and {y}, two walkers of the Demonic Path, reached for the same prize. "
        "Demonic cultivators do not share, and they certainly do not talk it over.",
        "{x} of the {x_sect} and {y} of the {y_sect} met at {place}, and the air turned bitter "
        "with killing intent. On the Demonic Path, only one of them was walking away.",
        "Nobody at {place} dared to breathe loudly. {x} and {y}, both Demonic, had just spotted "
        "each other across the ruins, and each one was already smiling.",
        "{y} had stolen from {x} once, and {x} had never forgotten. When they met again at "
        "{place}, no words were wasted, and the ground began to crack.",
        "The {x_sect} and the {y_sect} were rivals in everything, so when {x} and {y} met at "
        "{place}, the Demonic arts on both sides were released without a single warning.",
        "Birds fled the sky above {place}. {x} and {y}, two cultivators who trusted nobody, had "
        "agreed to a duel precisely because neither trusted the other to stay away.",
    ],
    ("Righteous", "Demonic"): [
        "At {place}, {x} of the {x_sect}, a champion of the Righteous Path, finally cornered "
        "{y} of the {y_sect}, whose Demonic arts had troubled the region for years.",
        "{y}, a Demonic cultivator, was trespassing near {place} when {x} of the Righteous Path "
        "appeared and demanded they leave. {y} laughed, and the sky darkened.",
        "Villagers near {place} had begged the {x_sect} for help, and the sect had sent {x}. "
        "{y} of the {y_sect} was waiting for them with a grin and an unfinished ritual.",
        "{x} walked into {place} with a spotless robe and a clear conscience. {y}, wrapped in "
        "the dark Qi of the Demonic Path, found both of those things very funny.",
        "'The Righteous Path ends at this valley,' {y} announced from the shadows of {place}. "
        "{x} drew a weapon and answered that it would be happy to finish the road.",
        "Rumor said {y} of the {y_sect} was hiding at {place}. {x} of the {x_sect} came alone, "
        "and rumor, for once, was correct.",
    ],
}

# Placeholders: {x} {y} {x_tech} {y_tech} {x_elem} {y_elem}
BATTLE_CLASHES = [
    "{x} opened with {x_tech}, and {y} met it with {y_tech}, {x_elem} colliding with "
    "{y_elem} until the ground cracked.",
    "{x_tech} tore across the sky, answered by {y_tech}; {x_elem} Qi and {y_elem} Qi spiralled "
    "together in a roaring storm.",
    "The first exchange shook the mountain: {x_tech} against {y_tech}, {x_elem} against "
    "{y_elem}, and neither dared to blink.",
]

# The middle of the fight, where the rest of the arsenal is used. The signature technique
# keeps the first clash and the deciding blow; these lines use the other four moves.
# By how likely the winner was to win. Placeholders for each side (w = winner, l = loser):
# {w_atk1} {w_atk2} (element attacks) {w_path} (path attack) {w_def} (defense), same for l.
BATTLE_EXCHANGES = {
    "close": [
        "{l} opened with {l_atk1}, and {w} answered with {w_atk1}. Neither gave way, and the "
        "ground between them cracked.",
        "{w} slipped past {l_atk2} using {w_def}, only for {l} to return the favor against "
        "{w_path}.",
        "Blow for blow, {w_atk2} met {l_atk2}, and the shockwave flattened the trees around "
        "them.",
        "{l_path} lit up the sky, but {w_def} caught most of it, and {w}'s counter with "
        "{w_atk1} left {l} gasping.",
    ],
    "clear": [
        "{l} struck with {l_atk1}, but {w_def} absorbed it, and {w_atk1} came straight back.",
        "Again and again {l_atk2} fell short, while {w_atk2} found its mark.",
        "{w} read {l}'s {l_path} perfectly, avoided it with {w_def}, and punished {l} with "
        "{w_path}.",
    ],
    "crushing": [
        "{l_atk1} broke against {w_def} without leaving a mark, and {w_atk1} sent {l} skidding "
        "backwards.",
        "{l} gathered everything into {l_path}. {w} did not even bother with {w_def}; "
        "{w_atk2} alone swatted it aside.",
        "Nothing {l} threw, not {l_atk1}, not {l_atk2}, could get through {w_def}.",
    ],
    "upset": [
        "{l_atk1} and {l_atk2} rained down on {w}, but {w_def} bent where it should have "
        "broken, and {w} waited for the single opening.",
        "{w} took {l_path} on the shoulder and answered with {w_path}, a gamble that should "
        "have failed.",
        "{l} overreached with {l_atk1}. {w} slipped away with {w_def} and struck back with "
        "{w_atk1}, as if the odds did not exist.",
    ],
}

# The turning point depends on how likely the winner was to win.
# Placeholders: {w} {l} (winner, loser) {w_tech} {l_tech} {gap} (a sentence about the realms, or empty)
BATTLE_TURNS = {
    "close": [
        "For a hundred exchanges neither gave an inch, until {w} found a single opening in "
        "{l}'s defense and drove {w_tech} straight through it.",
        "The duel hung by a thread. In the end it was {w_tech} landing a heartbeat before "
        "{l_tech} that decided everything.",
        "Both were bleeding Qi, and both were smiling. Then {l} stumbled on a loose stone, and "
        "{w} did not waste the gift.",
    ],
    "clear": [
        "Little by little the difference in cultivation showed. {w}'s Qi flowed steady while "
        "{l}'s began to falter.{gap}",
        "{w} read every move of {l}'s {l_tech} and answered each one with calm precision.{gap}",
        "{l} fought bravely, but {w_tech} grew heavier with every exchange.{gap}",
    ],
    "crushing": [
        "It was hardly a contest. A single wave of {w}'s Qi sent {l} skidding across the "
        "stone.{gap}",
        "{l} barely finished {l_tech} before {w_tech} swept it aside like autumn leaves.{gap}",
        "The ground itself bowed under {w}'s Qi, and {l} could only watch as {w_tech} "
        "descended.{gap}",
    ],
    "upset": [
        "Everyone would have bet on {l}, but fortune had other plans. A forgotten trick, a lucky "
        "misstep, and suddenly {w_tech} was past {l}'s guard.{gap}",
        "Against every prediction, {w} refused to fall. When {l} grew careless, the heavens "
        "themselves seemed to tilt, and {w_tech} struck true.{gap}",
        "The odds said {l}. The Dao said otherwise. {w} caught {l_tech} on a borrowed breath and "
        "turned it back with ruthless timing.{gap}",
    ],
}

BATTLE_OPENINGS[("Righteous", "Righteous")] += [
    "A drizzle began over {place} just as {x} of the {x_sect} bowed to {y} of the {y_sect}. "
    "Neither asked to postpone it; both walked the Righteous Path, and both loved a good duel.",
    "The sect rankings had listed {x} and {y} one place apart for years. At {place} they "
    "finally agreed to settle which of them deserved the higher line.",
    "'No killing, no crippling, no sulking afterwards,' {x} said at {place}. {y} promised, "
    "and the first sword-light split the morning mist.",
    "Tea was poured, cups were raised, and then {x} and {y} walked out to {place} to see "
    "which of their masters had taught them better.",
    "Two lanterns lit {place} that night: {x}'s from the {x_sect}, {y}'s from the {y_sect}. "
    "By the time they burned low, the whole region would know who had won.",
    "A wager between two sect elders had put {x} and {y} against each other at {place}. "
    "Both disciples bore the burden of their masters' pride, and both stood straight under it.",
]
BATTLE_OPENINGS[("Demonic", "Demonic")] += [
    "At {place}, {x} and {y} each arrived hours early to set traps for the other. Both traps "
    "were found, and both cultivators were very impressed and very angry.",
    "A blood moon rose over {place}. {x} of the {x_sect} and {y} of the {y_sect} had waited "
    "years for this night, and neither planned to see another.",
    "The two Demonic cultivators met at {place} and exchanged a single word of greeting, which "
    "was a curse. After that, the fighting felt almost friendly.",
    "Rumor said the loser at {place} would be devoured by the other's sect. {x} and {y} "
    "found the rumor flattering and made no effort to deny it.",
    "{x} had a bounty on {y}'s head, and {y} had one on {x}'s. At {place} they discovered "
    "each other holding the other's wanted poster, and laughed, briefly.",
    "Ghost fire lit {place} from every side. {x} and {y}, two cultivators with a long list "
    "of enemies, had picked a battlefield where nobody would hear the screaming.",
]
BATTLE_OPENINGS[("Righteous", "Demonic")] += [
    "The bells of the {x_sect} rang three times, and {x} rode out to {place} to face {y}. "
    "{y} of the {y_sect} had been expecting company, and had brought refreshments: poison.",
    "{x} had followed the trail of burned villages to {place}. At the end of it, {y} sat "
    "calmly on a stone throne and asked whether {x} had come to talk or to die.",
    "A child had once been saved by {x}, and the child's village now begged for protection "
    "from {y}. At {place}, the Righteous Path and the Demonic Path met, and neither blinked.",
    "'You are late,' {y} said at {place}. {x} of the {x_sect} replied that justice was never "
    "late, merely thorough, and the ground trembled beneath their feet.",
    "Seven sects had sworn to bring {y} to justice, and all seven had sent {x} as their "
    "champion. At {place}, {y} bowed with exaggerated courtesy and drew a dark blade.",
    "At the crossroads of {place}, {x} and {y} stood on opposite sides of an old stone "
    "marker that read 'Turn back.' Neither of them did.",
]

# Endings by (winner's path, loser's path).
# Placeholders: {w} {l} {w_sect} {l_sect} {w_treasure} {l_treasure}
BATTLE_ENDINGS = {
    ("Righteous", "Righteous"): [
        "{w} stepped back and offered {l} a healing pill. 'You fought well,' {w} said, and "
        "neither of them ever mentioned the stakes of the duel again.",
        "{l} yielded with a bow, and {w} returned it. Word of the duel spread through the "
        "{w_sect}, and everyone agreed it had been an honorable one.",
        "Afterwards the two sat down to share a pot of spirit tea, arguing happily about who "
        "had really been the stronger.",
        "{w} helped {l} to their feet and brushed the dust off {l}'s robe. 'Again next year?' "
        "{w} asked. {l} agreed, and meant it.",
        "The elders of the {w_sect} nodded with approval. Not a single life was in danger, and "
        "{w} had shown both skill and restraint.",
        "{l} laughed through the pain and admitted that {w} had earned it. The disciples "
        "watching applauded both of them, and the argument was forgotten.",
        "'I learned more from losing than you did from winning,' {l} said with a smile. {w} "
        "was not sure that was true, but did not argue.",
    ],
    ("Righteous", "Demonic"): [
        "{w} sealed {l}'s Qi with a talisman and carried {l} off to the {w_sect} for judgment, "
        "as the Righteous Path demanded.",
        "Ignoring {l}'s pleas, {w} sealed {l}'s Qi and warned {l} never to return.",
        "{w} broke {l}'s demonic cultivation with a single palm. 'Walk a better road,' {w} "
        "said, and left.",
        "{w} bound {l} in a net of golden light and dragged them back toward the {w_sect}, "
        "while villagers who had feared {l} for years cheered along the road.",
        "'Justice has been served,' {w} said quietly, and the dark clouds above {l} finally "
        "began to part.",
        "{l} spat blood and cursed {w}'s name. {w} only sighed, left a pill beside them, and "
        "walked away, hoping {l} would think about the offer.",
        "The {w_sect} would record that {w} brought down a demonic cultivator that day. {w} "
        "would record only that {l} was tired, wounded, and, at last, quiet.",
    ],
    ("Demonic", "Righteous"): [
        "{w} smiled coldly and left {l} to crawl home with a broken pride.",
        "Showing no mercy, {w} drained the last of {l}'s Qi and strolled away, humming a "
        "cheerful tune.",
        "{l} spoke of honor and mercy. {w} laughed and vanished into the night.",
        "{w} let {l} see the sunrise, only so that {l} would remember what it cost to look at "
        "it from the ground.",
        "'Righteousness is such a heavy burden,' {w} said, pressing a heel against {l}'s "
        "back. 'Let me lighten it for you.' Then {w} was gone.",
        "By the time anyone from the {l_sect} arrived, {w} was far away, and {l}'s sword was "
        "the only thing left standing in the dust.",
        "{w} bowed mockingly to {l}, to the watching crowd, and to the sky, and walked off "
        "whistling a funeral song.",
    ],
    ("Demonic", "Demonic"): [
        "{w} finished the duel with a flick of the wrist. By morning the {l_sect} was missing "
        "one cultivator, and {w} was in a very good mood.",
        "{w} wiped a drop of blood from a thumb and left {l} as a warning to every other "
        "demonic cultivator in the region.",
        "{l} begged for mercy. {w} considered it, and let {l} live, for the moment.",
        "{w} drank the last of {l}'s spirit wine over {l}'s wounded body and called it a fair "
        "trade, then left before {l} could object.",
        "'Betray me again and I will not stop at your Qi,' {w} said. {l} nodded, already "
        "planning exactly that.",
        "Both of them knew the {l_sect} would send someone to take revenge. {w} found this "
        "delightful, and left a very clear trail to follow.",
        "{w} carved a small mark into the nearest rock to remind {l} who had won, then left "
        "{l} to explain the defeat to the {l_sect}.",
    ],
}

BATTLE_ENDINGS[("Righteous", "Righteous")] += [
    "{w} and {l} bowed once more. The disciples of both sects agreed that the duel had been "
    "closer than the results said, and each argued for their own favorite until dawn.",
    "'Let us not tell the elders how close that was,' {l} whispered. {w} grinned, and the "
    "secret stayed between them.",
    "{w} offered the victory to {l}'s sect with a deep bow, saying the real winner was the "
    "Righteous Path itself. {l} thought this a very elegant way to avoid gloating.",
    "{l} took the defeat without bitterness and asked {w} to teach the technique that had "
    "decided it. {w} agreed, and the two cultivators were friends from that day.",
    "That evening {w} and {l} shared one bowl of noodles at the foot of the mountain, bruises "
    "and all, while the sun set behind them.",
]
BATTLE_ENDINGS[("Righteous", "Demonic")] += [
    "{w} did not strike the final blow. 'I leave that to the Heavens,' {w} said, and walked "
    "away as {l}'s dark Qi dispersed into the wind.",
    "The villagers lit incense at {w}'s name that night. {l}, bound in golden chains, "
    "listened to them from the cart and, for the first time in years, said nothing.",
    "{w} cut the black banner in half and set {l}'s ritual circle ablaze. 'The road ends "
    "here,' {w} said, and meant it kindly.",
    "'I will return,' {l} promised. {w} nodded politely. 'Then I will be waiting, and you "
    "will have a better teacher by then.' With that, {w} bowed and walked away.",
    "A single white feather drifted down over {l}, who lay laughing in the dust. 'A good "
    "fight,' {l} wheezed, 'for a righteous bore.' {w} left without answering.",
]
BATTLE_ENDINGS[("Demonic", "Righteous")] += [
    "{w} wrote a poem about the duel on the clean stone beside {l}, mocking the Righteous "
    "Path in four elegant lines, and strolled off with the dawn.",
    "{l} swore to the Heavens that justice would find {w}. {w} thanked them for the "
    "promise and said it would look forward to the meeting.",
    "'Every hero needs a lesson in humility,' {w} said, wiping blood from a blade. 'Consider "
    "this yours.' The wind carried the laughter far into the hills.",
    "The Righteous disciples arrived too late to see anything but {w}'s shadow vanishing into "
    "the woods and {l} kneeling quietly in the ashes.",
    "{w} left {l} alive on purpose: a defeated champion walking home was worth more "
    "than a corpse, and far more embarrassing to the {l_sect}.",
]
BATTLE_ENDINGS[("Demonic", "Demonic")] += [
    "{l} fled into the darkness, swearing revenge for the next three hundred years. "
    "{w} did not bother to give chase; there would be plenty of time.",
    "{w} sat on the broken throne of {l}'s ruined hall and invited the frightened servants to "
    "bring wine. The servants did. They were not stupid.",
    "'You fought well,' {w} said, 'which is why I will not kill you today.' {l} understood "
    "perfectly: today was a loan, and the interest would be terrible.",
    "The earth around {l} was scorched black. {w} stepped over the edge of it and "
    "left without turning around. A Demonic duel never really ends; it only pauses.",
    "{w} took the sect token from {l}'s belt as a trophy, tied it to a string, and wore it "
    "like a necklace. The {l_sect} did not enjoy hearing about this.",
]

# After a duel won by a Demonic cultivator: the winner steals the loser's prized treasure,
# or finds there is nothing to steal. Placeholders: {w} {l} {stolen}
BATTLE_LOOT = [
    "{w} did not leave empty-handed: {stolen} was torn from {l}'s belt and vanished into "
    "{w}'s sleeve.",
    "Before {l} could rise, {w} had already taken {stolen}, the treasure {l} valued most.",
    "{w} claimed {stolen} as the price of victory, and {l} could only watch it go.",
    "With a cold smile, {w} pocketed {stolen}. It was, after all, what Demonic cultivators "
    "do.",
]
# A Spatial Escape Talisman saves the loser's treasure. Placeholders: {w} {l}
BATTLE_TALISMAN = [
    "{w} reached for {l}'s treasure, but a Spatial Escape Talisman flared in {l}'s sleeve. "
    "Space folded, and the treasure slipped out of reach.",
    "'Hand it over,' {w} snarled. Nothing happened. {l}'s Spatial Escape Talisman had "
    "already torn the treasure out of this place, and {w} grasped at empty air.",
    "A Spatial Escape Talisman burned to ash on {l}'s chest, and with it went every chance "
    "of {w} stealing a single thing. {w} cursed for a full minute.",
]
# A Demonic winner who could have robbed the loser but did not get the chance (STEAL_CHANCE).
# Placeholders: {w} {l} {l_treasure}
BATTLE_STEAL_MISS = [
    "{w} eyed {l}'s {l_treasure} all through the fight, but {l} guarded it too closely, "
    "and the moment to snatch it never came.",
    "Just as {w} reached for {l}'s {l_treasure}, a tremor split the ground between them. "
    "By the time the dust settled, the chance was gone.",
    "'Next time,' {w} muttered, watching {l}'s {l_treasure} glitter out of reach. Even a "
    "Demonic cultivator cannot rob everyone, every time.",
    "{l} had hidden {l_treasure} in a place {w} never thought to look. {w} searched, "
    "swore, and left with nothing but a sore pride.",
    "{w} considered taking {l}'s {l_treasure}, then heard the elders of the {l_sect} "
    "approaching and decided that today was not the day.",
    "A crowd of witnesses had gathered, and {w} could not rob {l} of {l_treasure} without "
    "being seen. For once, patience won out over greed.",
]
BATTLE_NO_LOOT = [
    "{w} searched {l} from head to toe for treasure, but {l} owned nothing worth taking. "
    "{w} left in a worse mood than before.",
    "'Where is your treasure?' {w} demanded. {l} turned out two empty pockets. There was "
    "nothing to steal, which only made {w} angrier.",
    "{w} reached for {l}'s treasure and grasped at air. {l} had nothing of value left, and "
    "even {w} felt a little embarrassed.",
]
# A lucky find for the winner (DROP_CHANCE). Placeholders: {w} {found}
BATTLE_FINDS = [
    "As {w} left the battlefield, something glittered in the rubble: {found}. Fortune "
    "favors the victor.",
    "Heaven rewarded the winner. In a crack in the ground, {w} discovered {found}.",
    "Walking away, {w} stumbled over {found}, half buried in the dust. A lucky find.",
]

# Placeholders: {w} {l} {w_realm} {l_realm} {l_sect}
BATTLE_REP_GAIN = [
    "News that {w}, a mere {w_realm} cultivator, had beaten a master of {l_realm} spread "
    "across the region by nightfall.",
    "Everyone who saw it would remember the day {w} of {w_realm} brought down a cultivator "
    "of {l_realm}.",
    "From that day on, the tea houses told of how {w} of {w_realm} humbled a {l_realm} "
    "expert.",
]
BATTLE_REP_LOSS_HEAVY = [
    "For {l}, a cultivator of {l_realm}, losing to someone of {w_realm} was a disgrace that "
    "no excuse could soften.",
    "The {l_sect} whispered about it for months: a {l_realm} expert, beaten by a {w_realm} "
    "cultivator.",
    "From then on {l}'s name was spoken with a sneer, for a {l_realm} cultivator had fallen "
    "to {w_realm}.",
]
BATTLE_REP_LOSS_LIGHT = [
    "Among the righteous such a defeat was forgiven quickly, though {l} still felt the sting "
    "of losing to someone of a lower realm.",
    "{l} accepted the loss with grace, and the righteous elders only shook their heads "
    "kindly.",
]

# Placeholders: {strong} {weak} {strong_power} {weak_power}
BATTLE_GAP_SETUPS = {
    "noticeable": [
        "{strong} held the edge in power, {strong_power} against {weak_power}, and made sure "
        "{weak} could see the confident smile.",
        "'Show me what you have,' said {strong}, who commanded {strong_power} power to "
        "{weak}'s {weak_power}, with the easy confidence of someone who expects to win.",
        "{strong} rolled a shoulder and smiled. {strong_power} power against {weak_power} was a "
        "lead worth being smug about.",
    ],
    "large": [
        "{weak}, with only {weak_power} power, had challenged {strong}, who held "
        "{strong_power}. {strong} laughed out loud. 'Do you even understand the gap between "
        "us?'",
        "With {strong_power} power against {weak_power}, {strong} did not bother hiding the "
        "smirk. 'Kneel now, and I might forget this insolence,' {strong} said.",
        "{strong} looked down at {weak} the way a mountain looks at a pebble: {strong_power} "
        "power against a mere {weak_power}.",
    ],
    "vast": [
        "It was the strangest challenge the region had ever seen: {weak}, with a mere "
        "{weak_power} power, daring to face {strong}, who commanded {strong_power}. {strong} "
        "yawned. 'I will grant you the first move, and the second, and the third,' {strong} "
        "said.",
        "{strong}, arrogant to the bone with {strong_power} power, did not even take a stance. "
        "'Is this a duel or a joke?' {strong} sneered at {weak}'s {weak_power}.",
        "Nobody had expected {weak}, with {weak_power} power, to challenge {strong} and "
        "{strong_power}. {strong} stood with arms folded, wearing the bored face of someone "
        "watching an ant try to move a mountain.",
    ],
}

# After the duel, for large and vast gaps: key is (tier, did the stronger fighter win?)
BATTLE_GAP_AFTERMATH = {
    ("large", True): [
        "{strong} did not even look back. 'Come again when you are worth my time,' {strong} "
        "said.",
        "Without a scratch on them, {strong} dusted off a sleeve, already bored. 'Next,' "
        "{strong} called.",
    ],
    ("large", False): [
        "{strong}'s smile was gone. The tale of how pride cost {strong} the duel against "
        "{weak} would be told in tea houses for years.",
        "{strong} stared at the sky, stunned. Arrogance, it turned out, was the one opponent "
        "{strong} had never trained against.",
    ],
    ("vast", True): [
        "'Come back in a thousand years,' {strong} said over a shoulder, and did not wait for "
        "an answer.",
        "{strong} yawned again. The whole fight had taken less effort than a morning stretch, "
        "and everyone present knew it.",
    ],
    ("vast", False): [
        "The silence was enormous. {strong}, who had boasted of {strong_power} power, had been "
        "humbled by a cultivator with only {weak_power}, and the whole region would never let "
        "{strong} forget it.",
        "{weak} bowed politely. {strong} could not speak. By the next morning, 'pride before "
        "the fall' was a saying in every tea house.",
    ],
}

# When the elements favor one fighter. Placeholders: {adv} {dis} {adv_elem} {dis_elem}
BATTLE_ELEMENT_LINES = [
    "{adv_elem} is the natural bane of {dis_elem}, and {adv} felt the Qi tilt ever so slightly "
    "in their favor.",
    "The elements leaned toward {adv}: {adv_elem} holds the upper hand over {dis_elem}.",
    "{dis} could feel {dis_elem} Qi struggle against {adv}'s {adv_elem}, like swimming against "
    "a gentle current.",
]
