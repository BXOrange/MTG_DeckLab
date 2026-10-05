from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _derevi_empyrial_tactician() -> list[AbilitySpec]:
    """Flying
    When Derevi enters and whenever a creature you control deals combat
    damage to a player, you may tap or untap target permanent.
    {1}{G}{W}{U}: Put Derevi onto the battlefield from the command zone.

    — MEC-42. Flying is a plain printed keyword, recognized independent
    of catalogue registration. The shared "you may tap or untap target
    permanent" clause needed a genuine new choice — `TapEffect`'s existing
    ``untap`` bool is fixed at bind time, but this is a real decision at
    resolution, layered on top of RULE 115's own "up to one" target
    optionality — so `TapEffect.choose_tap_or_untap` opens a new, small
    `RulesEngine._request_tap_or_untap_choice` `pending_choice` instead of
    applying a fixed tap/untap directly; two `AbilitySpec`s (ETB self,
    and the already-general RULE 603.1 group-subject "a creature you
    control deals combat damage to a player" shape Bident of Thassa/
    Deepfathom Skulker/Rapacious Guest already use) share the same effect
    *shape*, each its own fresh `EffectSpec` instance.

    Documented simplification: the third ability — "{1}{G}{W}{U}: Put
    Derevi onto the battlefield from the command zone." — is a genuinely
    different mechanism from RULE 903's ordinary command-zone *casting*
    (which this engine already fully supports, tax and all): a bare
    battlefield-entry with no stack, spell, or ETB-timing restriction,
    activated from a zone (command) no other activated ability in this
    engine can be offered from. Left unmodeled — RULE 903's normal
    "cast Derevi from the command zone" path already reaches the same
    outcome (Derevi returns to the battlefield), just through the stack
    and at full (taxed) cost rather than this flat discount, so nothing
    about the card is actually unplayable without it.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("tap", {
                "target_kind": "permanent", "optional": True, "choose_tap_or_untap": True,
            })],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("tap", {
                "target_kind": "permanent", "optional": True, "choose_tap_or_untap": True,
            })],
            trigger={
                "event": EventType.DAMAGE,
                "condition": {"subject": "group", "type": "creature", "controller": "you", "other": False},
                "filter": {"combat": True, "is_player": True},
            },
        ),
    ]


register("Derevi, Empyrial Tactician", _derevi_empyrial_tactician)
