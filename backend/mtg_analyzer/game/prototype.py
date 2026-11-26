"""RULE 719: the alternate mana cost, color, power and toughness of a Prototype spell."""
from copy import copy

from ..models.cards.card_colors import with_color_override
from ..models.mana.mana_cost import ManaCost
from ..parser.oracle.catalogue.keywords import PROTOTYPE_RE


def card_for(card):
    """Project the spell's Prototype characteristics without mutating the printing."""
    match = PROTOTYPE_RE.search(card.oracle_text)
    if not match:
        return None
    mana = ManaCost.parse(match["cost"])
    prototype = copy(card)
    prototype.mana_cost_string = mana.raw
    prototype.converted_mana_cost = mana.converted_mana_cost
    prototype.power = int(match["power"])
    prototype.toughness = int(match["toughness"])
    return with_color_override(prototype, mana.color_identity)
