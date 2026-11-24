"""Mana cost reductions for Offering (RULE 702.48 and 118.7)."""
from ..models.mana.mana_cost import COLOR, COLORLESS, GENERIC, HYBRID, MONO_HYBRID, PHYREXIAN, ManaCost


def reductions(cost: ManaCost):
    """Resolve hybrid halves in the sacrificed permanent's mana cost."""
    possibilities = {()}
    for symbol in cost.symbols:
        if symbol.kind == GENERIC:
            options = [(None, symbol.amount)]
        elif symbol.kind in (COLOR, PHYREXIAN):
            options = [(symbol.color, 1)]
        elif symbol.kind == COLORLESS:
            options = [("C", 1)]
        elif symbol.kind in (HYBRID, MONO_HYBRID):
            options = [(color, generic or 1) for color, generic, _ in symbol.payment_options()]
        else:
            continue  # RULE 107.3g: X in a permanent's mana cost is zero.
        possibilities = {(*prior, option) for prior in possibilities for option in options}
    return sorted(possibilities, key=repr)


def reduce(cost: ManaCost, reduction) -> ManaCost:
    """Reduce matching mana first, then reduce generic by the excess."""
    remaining = list(cost.symbols)
    generic = 0
    for color, amount in reduction:
        if color is None:
            generic += amount
        else:
            for _ in range(amount):
                index = next((i for i, symbol in enumerate(remaining) if
                              (symbol.kind == COLOR and symbol.color == color)
                              or (symbol.kind == COLORLESS and color == "C")), None)
                if index is None:
                    generic += 1
                else:
                    remaining.pop(index)
    return ManaCost(remaining).reduce_generic(generic)
