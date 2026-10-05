from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _kamahl_heart_of_krosa() -> list[AbilitySpec]:
    """At the beginning of combat on your turn, creatures you control get
    +3/+3 and gain trample until end of turn.
    {1}{G}: Until end of turn, target land you control becomes a 1/1
    Elemental creature with vigilance, indestructible, and haste. It's
    still a land.
    Partner (You can have two commanders if both have partner.)

    — Partner and the combat-trigger pump are already parser-`MODELED`
    (`gate.parse_oracle` claims both; copied verbatim here rather than
    re-derived, per the hand-author-card skill's own guidance) — hand-
    authoring is only needed at all because of the third ability's "target
    land you control becomes a 1/1 … creature … It's still a land" shape
    (MEC-12), which no prior card had needed: RULE 611's `GrantUntilEffect`
    already covers "until end of turn", and `targeting.py` already has
    ``land_you_control``, but nothing had chained *two* `grant_until`
    statics onto the *same* resolve-time target before. Built as two
    ordinary `grant_until` `EffectSpec`s in one effect list — the first
    targets the land and stamps a `type_change` (``add_types=["creature"]``,
    literal 1/1), the second reuses `GameContext.previous_targets` via
    `GrantUntilEffect`'s own existing ``previous_subject`` pronoun (the
    same "Tap target land. It doesn't untap …" idiom `_apply_effects_
    partitioned` already threads through any effect exposing `target_specs`)
    to lay a `grant_keyword` static onto that exact land without
    re-targeting — no new engine primitive, just the first card to combine
    two already-shipped ones this way. "It's still a land" needs no code:
    `type_change`'s ``add_types`` only *adds* the creature type, never
    removing land — though it did surface a real, general bug fixed
    alongside this card: see Ashaya, Soul of the Wild's own entry just
    below for the `GameObject.is_land` fix that direction depends on too.
    """
    return [
        AbilitySpec(
            "keyword", [], keyword={"name": "partner"},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("pump", {
                "power": 3, "toughness": 3, "keywords": ["trample"],
                "selector": "creatures_you_control",
            })],
            trigger={
                "event": "STEP_BEGIN",
                "filter": {"step": "begin_combat"},
                "phase_relation": "you",
            },
        ),
        AbilitySpec(
            "activated",
            [
                EffectSpec("grant_until", {
                    "static": {"type": "type_change", "params": {
                        "add_types": ["creature"], "power": 1, "toughness": 1,
                    }},
                    "duration": "end_of_turn", "target_kind": "land_you_control",
                }),
                EffectSpec("grant_until", {
                    "static": {"type": "grant_keyword", "params": {
                        "keywords": ["vigilance", "indestructible", "haste"],
                    }},
                    "duration": "end_of_turn", "target_kind": None,
                    "previous_subject": True,
                }),
            ],
            cost={"mana": "{1}{G}"},
        ),
    ]


register("Kamahl, Heart of Krosa", _kamahl_heart_of_krosa)
