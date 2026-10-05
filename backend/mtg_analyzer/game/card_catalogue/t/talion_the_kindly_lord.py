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
    The ETB choice is the shipped `ChooseNumberReplacement` (Sanctum
    Prelate's own free-text-numeric RULE 601.2b primitive — no "between 1
    and 10" range validation, the same accepted UI-level simplification
    Sanctum Prelate's own unranged pick already carries). The trigger
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
            [EffectSpec("choose_number_on_enter", {})],
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
