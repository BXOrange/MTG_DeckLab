from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _talion_the_kindly_lord() -> list[AbilitySpec]:
    """Flying
    As Talion enters, choose a number between 1 and 10.
    Whenever an opponent casts a spell with mana value, power, or
    toughness equal to the chosen number, that player loses 2 life and
    you draw a card.

    — MEC-43 round 4B. Flying folds in via the ordinary keyword catalogue.
    The entry choice uses `ChooseNumberReplacement` with the printed
    range 1 through 10 (RULE 614.12). The trigger
    needed one new predicate (``spell_characteristic_equals_chosen_
    number``, `effect_binder._trigger_condition`) comparing `SPELL_CAST`'s
    ``mana_value``/``power``/``toughness`` (the latter two newly stamped
    onto the event by `RulesEngine.cast_spell`/`cast_without_paying`)
    against `GameObject.chosen_number`; "that player loses 2 life" is
    `LoseLifeEffect`'s existing ``selector="event_player"`` (Sheoldred,
    the Apocalypse's own precedent).
    """
    return [
        AbilitySpec(
            "enter_replacement",
            [EffectSpec("choose_number_on_enter", {"minimum": 1, "maximum": 10})],
        ),
        AbilitySpec(
            "triggered",
            [
                EffectSpec("lose_life", {"selector": "event_player", "amount": 2}),
                EffectSpec("draw", {"count": 1}),
            ],
            trigger={
                "event": EventType.SPELL_CAST,
                "condition": {"subject": "group", "controller": "not_you"},
                "spell_characteristic_equals_chosen_number": True,
            },
        ),
    ]


register("Talion, the Kindly Lord", _talion_the_kindly_lord)
