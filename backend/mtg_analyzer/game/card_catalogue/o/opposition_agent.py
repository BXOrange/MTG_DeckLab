from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _opposition_agent() -> list[AbilitySpec]:
    """Flash
    You control your opponents while they're searching their libraries.
    While an opponent is searching their library, they exile each card
    they find. You may play those cards for as long as they remain
    exiled, and you may spend mana as though it were mana of any color to
    cast them.

    — MEC-39. Flash is the ordinary keyword fold-in. The "you control
    your opponents while searching" clause is deliberately not modeled as
    a genuine RULE 269.4 control exchange of the player — this engine's
    search flow has no other decision point during a search a real
    control swap would change (the searching player still picks which
    cards they find; only where those cards end up is redirected), so
    the second, fully mechanical paragraph already describes the whole
    gameplay outcome. `RulesEngine._finish_search` now consults a new
    `StaticAbility` layer, `"search_redirect"` (`continuous.search_
    redirect_controller_for`), right where it computes each found card's
    destination: an opponent's search has *every* found card's
    destination overridden to exile, and the already-shipped `GameState.
    exile_cast_condition`/`mana_wildcard_permission` pair (every other
    "play a card from exile" mechanism already uses these) is granted to
    this permanent's controller rather than the found card's own owner —
    the one genuine generalization needed, since every existing grantor
    of those two maps had only ever pointed them at the exiled card's own
    owner.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("search_redirect", {})],
        ),
    ]


register("Opposition Agent", _opposition_agent)
