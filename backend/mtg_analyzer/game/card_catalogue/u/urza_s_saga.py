from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _urzas_saga() -> list[AbilitySpec]:
    """I — This Saga gains "{T}: Add {C}."
    II — This Saga gains "{2}, {T}: Create a 0/0 colorless Construct
    artifact creature token with 'This token gets +1/+1 for each artifact
    you control.'"
    III — Search your library for an artifact card with mana value 0 or 1,
    put it onto the battlefield, then shuffle.

    — Vivi B4 batch. Chapters I/II are `GrantSelfActivatedAbilityEffect`
    (RULE 714.2c's *lasting* self-grant — new, since a Saga chapter's
    "gains an ability" outlives the trigger that grants it, unlike the
    turn-scoped `grant_graveyard_cast_permission_this_turn` shape it
    otherwise mirrors), each wrapping the ability it grants as nested
    ``EffectSpec`` dicts. Chapter II's Construct token gets its own
    self-scaling +1/+1-per-artifact ability via `CreateTokenEffect.
    grant_self_anthem` (new — appends a real ``anthem``-shaped
    `StaticAbility` onto the *created token itself* rather than the
    effect's source, reusing the oracle-parsed "creatures you control get
    +N/+N" static's own ``power_count``/``toughness_count`` per-count
    scaling). Chapter III is a plain `search`. **Documented
    simplification**: chapter I's granted mana ability resolves through
    the stack like any other granted activated ability (`grant_activated_
    ability`'s general form) rather than as a genuine no-stack RULE 605.1a
    mana ability — functionally equivalent (the mana still reaches the
    pool), just one extra `activate_ability` step instead of an instant
    tap-for-mana shortcut.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("grant_self_activated_ability", {
                "cost": {"taps_self": True},
                "effects": [{"type": "add_mana", "params": {"colors": ["C"]}}],
            })],
            trigger={"event": "SAGA_CHAPTER", "chapter": [1]},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("grant_self_activated_ability", {
                "cost": {"mana": "{2}", "taps_self": True},
                "effects": [{"type": "create_token", "params": {
                    "power": 0, "toughness": 0, "colors": [], "subtypes": ["Construct"],
                    "token_name": "Construct", "is_artifact": True,
                    "grant_self_anthem": {
                        "power": 1, "toughness": 1,
                        "power_count": "artifacts_you_control",
                        "toughness_count": "artifacts_you_control",
                    },
                }}],
            })],
            trigger={"event": "SAGA_CHAPTER", "chapter": [2]},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("search", {
                "criteria": {"type": "Artifact", "max_mana_value": 1},
                "destination": "battlefield",
                "optional": False,
            })],
            trigger={"event": "SAGA_CHAPTER", "chapter": [3]},
        ),
    ]


register("Urza's Saga", _urzas_saga)
