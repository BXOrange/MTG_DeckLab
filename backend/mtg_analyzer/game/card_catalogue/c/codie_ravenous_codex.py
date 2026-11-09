from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _codie_ravenous_codex() -> list[AbilitySpec]:
    """Whenever you cast a prepared spell, copy it. You may choose new targets for the copy.
    {W}{U}{B}{R}{G}, {T}: Each creature you control becomes prepared. (Only creatures with prepare spells can become prepared.)

    RULE 722.3c: the cast event records the prepare-spell origin before
    the source loses its designation. Casting another spell from exile
    does not satisfy this trigger.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("copy_spell", {
                "spell_from_trigger_event": "instance_id", "choose_new_targets": True,
            })],
            trigger={
                "event": EventType.SPELL_CAST,
                "condition": {"subject": "group", "controller": "you"},
                "filter": {"prepared_spell": True},
            },
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("become_prepared", {"selector": "creatures_you_control"})],
            cost={"text": "{W}{U}{B}{R}{G}, {T}"},
        ),
    ]


register("Codie, Ravenous Codex", _codie_ravenous_codex)
