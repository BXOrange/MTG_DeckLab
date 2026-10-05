from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _penance() -> list[AbilitySpec]:
    """Put a card from your hand on top of your library: The next time a
    black or red source of your choice would deal damage this turn,
    prevent that damage.

    — Penance (MEC-30, Phase 8). Unlike every other card in this family,
    the printed text has no "to you" at all — "prevent that damage"
    protects whoever the chosen source would have hit, not one fixed
    recipient — `RequestPreventDamageSourceEffect`'s new ``recipient=
    "any"`` (reaching `RulesEngine.prevent_damage_from_source`'s existing
    unscoped-recipient shield via `_apply_chosen_object`'s matching
    branch, rather than `prevent_damage_to_player`/`_to_target`'s fixed-
    recipient ones). ``source_filter``'s ``color_any`` (already shipped for
    Greater Realm of Preservation) covers "a black **or** red source"
    directly. The cost is the new "put a card from your hand on top of
    your library" non-mana cost (`costs.py`'s own
    ``_PUT_HAND_CARD_ON_LIBRARY_RE``/`RulesEngine.put_hand_card_on_top_of_
    library`) — which card leaves the hand is a genuine RULE 602.1 choice,
    resolved the same "chosen_ids, or auto-pick" way a plain discard-N cost
    already is (`ActivationMixin._resolve_put_hand_card_cost`).
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("request_prevent_damage_source", {
                "source_filter": {"color_any": ["B", "R"]}, "amount": "all", "recipient": "any",
            })],
            cost={"text": "Put a card from your hand on top of your library"},
        ),
    ]


register("Penance", _penance)
