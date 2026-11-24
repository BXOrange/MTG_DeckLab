"""RULE 201.3: English names printed with the interchangeable-name indicator.

These are rules equivalences, not flavor names or mechanically similar cards.
The SLX printings identify the original SLD printing beneath their text box:
https://magic.wizards.com/en/news/feature/whats-new-on-the-list-for-streets-of-new-capenna
https://magic.wizards.com/en/news/announcements/whats-new-on-the-list-for-phyrexia-all-will-be-one
https://magic.wizards.com/en/news/announcements/whats-new-on-the-list-for-wilds-of-eldraine
https://magic.wizards.com/en/news/announcements/earn-d-and-d-themed-promo-cards-with-magic-presents-spring-flourishes
"""

# Keep the equivalence separate from actual characteristics: an object still
# has its own English name for display and name-changing effects (RULE 201.2).
INTERCHANGEABLE_NAME_PAIRS: tuple[tuple[str, str], ...] = (
    ('Arvinox, the Mind Flail', 'Mind Flayer, the Shadow'),
    ('Bjorna, Nightfall Alchemist', 'Lucas, the Sharpshooter'),
    ('Cecily, Haunted Mage', 'Eleven, the Mage'),
    ('Elmar, Ulvenwald Informant', 'Max, the Daredevil'),
    ('Hargilde, Kindly Runechanter', 'Dustin, Gadget Genius'),
    ('Othelm, Sigardian Outcast', 'Mike, the Dungeon Master'),
    ('Sophina, Spearsage Deserter', 'Chief Jim Hopper'),
    ("Wernog, Rider's Chaplain", 'Will the Wise'),
    ('Havengul Laboratory', 'Hawkins National Laboratory'),
    ('Havengul Mystery', 'The Upside Down'),
    ('Baldin, Century Herdmaster', 'E. Honda, Sumo Champion'),
    ('Vikya, Scorching Stalwart', 'Ryu, World Warrior'),
    ('Aisha of Sparks and Smoke', 'Ken, Burning Brawler'),
    ('The Howling Abomination', 'Blanka, Ferocious Friend'),
    ('Immard, the Stormcleaver', 'Guile, Sonic Soldier'),
    ('Maarika, Brutal Gladiator', 'Zangief, the Red Cyclone'),
    ('Tadeas, Juniper Ascendant', 'Dhalsim, Pliable Pacifist'),
    ('Zethi, Arcane Blademaster', 'Chun-Li, Countless Kicks'),
    ("Greymond, Avacyn's Stalwart", 'Rick, Steadfast Leader'),
    ("Gisa's Favorite Shovel", 'Lucille'),
    ('Enkira, Hostile Scavenger', 'Michonne, Ruthless Survivor'),
    ('Gregor, Shrewd Magistrate', 'Glenn, the Voice of Calm'),
    ('Hansk, Slayer Zealot', 'Daryl, Hunter of Walkers'),
    ('Malik, Grim Manipulator', 'Negan, the Cold-Blooded'),
    ('Rashel, Fist of Torm', 'Xenk, Paladin Unbroken'),
    ('Mathise, Surge Channeler', 'Simon, Wild Magic Sorcerer'),
    ('Evin, Waterdeep Opportunist', 'Forge, Neverwinter Charlatan'),
    ('Jurin, Leading the Charge', 'Holga, Relentless Rager'),
    ('Casal, Lurkwood Pathfinder', "Doric, Nature's Warden"),
    ('Casal, Pathbreaker Owlbear', 'Doric, Owlbear Avenger'),
    ('Bohn, Beguiling Balladeer', 'Edgin, Larcenous Lutenist'),
)

_NAME_KEYS = {name: pair[0] for pair in INTERCHANGEABLE_NAME_PAIRS for name in pair}


def matching_name_keys(names: tuple[str, ...]) -> tuple[str, ...]:
    """Comparison identities of actual names; nameless objects stay nameless."""
    return tuple(_NAME_KEYS.get(name, name) for name in names if name)
