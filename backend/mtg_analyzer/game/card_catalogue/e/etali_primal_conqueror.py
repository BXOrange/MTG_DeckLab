from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _etali_primal_conqueror() -> list[AbilitySpec]:
    """Front face — Etali, Primal Conqueror ({5}{R}{R}, Legendary Creature
    — Elder Dinosaur, 7/7):
    Trample
    When Etali enters, each player exiles cards from the top of their
    library until they exile a nonland card. You may cast any number of
    spells from among the nonland cards exiled this way without paying
    their mana costs.
    {9}{G/P}: Transform Etali. Activate only as a sorcery.

    — checked against Scryfall's own rulings for this card (2026-09-04):
    the whole card had no catalogue entry at all, so it fell back to
    the RULE 702 keyword catalogue's Scryfall-anchored auto-bind alone —
    which would have been actively *wrong* here, not just incomplete.
    Scryfall's *card-level* ``keywords`` array on a transform DFC is the
    union of both faces (this card's is ``["Indestructible", "Transform",
    "Trample"]``), so an unregistered front face would auto-bind the back
    face's own Indestructible too; `remove_keyword` cancels that leak
    explicitly. ("Transform" itself isn't a recognized keyword slug, so it
    parses to nothing either way.) The ETB trigger reuses Etali, Primal
    Storm's `exile_top_from_each_player_cast_free`, widened with
    ``until_nonland=True`` to dig each player's library past any lands to
    the first nonland card (`RulesEngine._exile_top_until`, the same
    "keep exiling past lands" shape cascade/discover already use) instead
    of a fixed single top card — every card exiled along the way,
    including the lands, stays in exile per the ruling; only the nonland
    hit gets a free-cast window. The transform ability is a plain
    `EffectSpec("transform", {})` behind a sorcery-speed Phyrexian-mana
    cost.
    """
    return [
        AbilitySpec("keyword", [], keyword={"name": "trample"}),
        AbilitySpec(
            "static",
            [EffectSpec("remove_keyword", {"affects": "self", "keywords": ["indestructible"]})],
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("exile_top_from_each_player_cast_free", {"until_nonland": True})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("transform", {})],
            cost={"text": "{9}{G/P}", "sorcery_speed_only": True},
        ),
    ]


register("Etali, Primal Conqueror", _etali_primal_conqueror)
register("Etali, Primal Conqueror // Etali, Primal Sickness", _etali_primal_conqueror)
