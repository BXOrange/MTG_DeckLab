"""Subtype ownership for characteristic changes (RULE 205.3g-i, k-m)."""
from .creature_types import CREATURE_SUBTYPES

ARTIFACT_SUBTYPES = frozenset('attraction blood bobblehead book clue contraption equipment food fortification gold incubator infinity junk lander map mutagen powerstone spacecraft stone treasure vehicle vibranium'.split())
ENCHANTMENT_SUBTYPES = frozenset('aura background cartouche case class curse plan role room rune saga shard shrine'.split())
LAND_SUBTYPES = frozenset("cave desert forest gate island lair locus mine mountain plains planet power-plant sphere swamp tower town urza's urza’s".split())
SPELL_SUBTYPES = frozenset('adventure arcane lesson omen trap'.split())
SUBTYPES_BY_CARD_TYPE = {
    'artifact': ARTIFACT_SUBTYPES, 'enchantment': ENCHANTMENT_SUBTYPES, 'land': LAND_SUBTYPES,
    'creature': CREATURE_SUBTYPES, 'kindred': CREATURE_SUBTYPES, 'tribal': CREATURE_SUBTYPES,
    'instant': SPELL_SUBTYPES, 'sorcery': SPELL_SUBTYPES, 'battle': frozenset({'siege'}),
}
