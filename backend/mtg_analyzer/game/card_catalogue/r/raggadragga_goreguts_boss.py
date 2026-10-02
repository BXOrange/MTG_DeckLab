from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _raggadragga_goreguts_boss() -> list[AbilitySpec]:
    """Each creature you control with a mana ability gets +2/+2.
    Whenever a creature you control with a mana ability attacks, untap it.
    Whenever you cast a spell, if at least seven mana was spent to cast it,
    untap target creature. It gets +7/+7 and gains trample until end of turn.

    — PLAY-ALL Step 2 (Raggadragga). The spell trigger is the parser's own
    claim, reproduced verbatim. The other two use the new
    ``has_mana_ability`` object-filter key (`combat.matches_object_filter`,
    printed or granted mana abilities via `mana_abilities_for`): an `anthem`
    over ``creatures_you_control`` and the parser's "whenever a creature you
    control attacks, untap it" group trigger (``trigger_subject`` untap) with
    the key in its group filter.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("anthem", {
                "power": 2, "toughness": 2, "affects": "creatures_you_control",
                "object_filter": {"has_mana_ability": True},
            })],
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("tap", {
                "target_kind": "trigger_subject", "untap": True, "trigger_event_key": "__group_subject__",
            })],
            trigger={
                "event": EventType.ATTACKS,
                "condition": {
                    "subject": "group", "controller": "you", "other": False, "type": "creature",
                    "filter": {"has_mana_ability": True},
                },
            },
        ),
        AbilitySpec(
            "triggered",
            [
                EffectSpec("tap", {"target_kind": "creature", "untap": True}),
                EffectSpec("pump", {"power": 7, "toughness": 7, "previous_subject": True, "keywords": ["trample"]}),
            ],
            trigger={
                "event": EventType.SPELL_CAST, "condition": {"subject": "you"},
                "spell_mana_spent_at_least": 7,
            },
        ),
    ]


register("Raggadragga, Goreguts Boss", _raggadragga_goreguts_boss)
