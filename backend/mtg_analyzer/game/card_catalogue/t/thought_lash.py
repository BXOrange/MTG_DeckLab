from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _thought_lash() -> list[AbilitySpec]:
    """Exile the top card of your library: Prevent the next 1 damage that
    would be dealt to you this turn.

    — Thought Lash. Only this repeatable activated ability is hand-authored
    here; the card's own Cumulative Upkeep (RULE 702.24) now binds for free
    regardless (MEC-16 — `game/binding/core.py`'s keyword dispatch reads
    `Card.keywords`/oracle text independently of whatever a hand-authored
    entry supplies), so it no longer needs claiming here. Its own trailing
    "when a player doesn't pay this enchantment's cumulative upkeep, that
    player exiles all cards from their library" rider is still unclaimed
    though — the base mechanic never fires a paid-vs-not-paid event a
    second trigger could hook, only a real but narrower residual gap now.
    This entry only supplies the activated ability so the shared
    `prevent_damage_shield` primitive has its second real, amount-capped/
    repeatable-use exercising card (Riot Control's own use is the single
    uncapped "all" case). The cost is a plain "Exile the top card of your
    library" cost (`costs.py`'s existing library-exile cost grammar); the
    effect passes ``amount=1`` — a fresh `RulesEngine.
    prevent_damage_to_player` shield is opened on each activation, so
    repeated activations in a turn stack independent 1-point shields
    exactly like `regenerate`'s own multiple-activations-stack behaviour.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("prevent_damage_shield", {"amount": 1})],
            cost={"text": "Exile the top card of your library"},
        )
    ]


register("Thought Lash", _thought_lash)
