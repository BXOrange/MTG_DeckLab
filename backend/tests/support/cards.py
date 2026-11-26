"""Shared synthetic-card factories for service tests."""

from mtg_analyzer.models.cards.card import Card


def forest(name: str = "Forest") -> Card:
    return Card(id=name, name=name, type_line="Basic Land — Forest", is_land=True)


def commander() -> Card:
    return Card(
        id="Test Commander",
        name="Test Commander",
        type_line="Legendary Creature — Elf",
        mana_cost_string="{1}{G}",
        converted_mana_cost=2,
        is_creature=True,
        power=1,
        toughness=1,
        color_identity={"G"},
    )


def cheap_creature(name: str = "Test Spell") -> Card:
    return Card(
        id=name,
        name=name,
        type_line="Creature — Elf",
        mana_cost_string="{G}",
        converted_mana_cost=1,
        is_creature=True,
        power=1,
        toughness=1,
        color_identity={"G"},
    )


def without_keywords(card: Card, *displays: str, drop_text: tuple[str, ...] = ()) -> Card:
    """``card`` minus the keyword lines of ``displays`` ("Rebound", "Cipher", ...), for a real card whose other text is under test.
    ``drop_text`` removes those substrings from the text too.

    A keyword the engine has no behaviour for (`KEYWORDS_WITHOUT_BEHAVIOUR`, BUG-75) leaves the printed card UNMODELED, so its
    other abilities are never bound; the rest of the card is the same text, line for line.
    """
    import copy
    import re

    wanted = {d.lower() for d in displays}
    out = copy.copy(card)
    kept = [
        line for line in str(card.oracle_text or "").split("\n")
        if not any(re.match(rf"{re.escape(d)}\b", line.strip(), re.I) for d in wanted)
    ]
    out.oracle_text = "\n".join(kept)
    for fragment in drop_text:  # a refused keyword inside a sentence ("... token with decayed"), not on a line of its own
        out.oracle_text = out.oracle_text.replace(fragment, "")
    out.keywords = [k for k in (card.keywords or []) if str(k).lower() not in wanted]
    return out


def strip_inert_keywords(card: Card) -> Card:
    """``card`` without any keyword the engine has no behaviour for (`KEYWORDS_WITHOUT_BEHAVIOUR`, BUG-75).

    For a test whose subject is a real card's *other* text: such a keyword leaves the printed card UNMODELED, so its abilities
    would never be bound. Only the keyword lines (and a token's "with decayed") are removed.
    """
    from mtg_analyzer.parser.oracle.catalogue.keywords import KEYWORDS, KEYWORDS_WITHOUT_BEHAVIOUR

    displays = [KEYWORDS[slug].display for slug in KEYWORDS_WITHOUT_BEHAVIOUR]
    return without_keywords(card, *displays, drop_text=(" with decayed",))
