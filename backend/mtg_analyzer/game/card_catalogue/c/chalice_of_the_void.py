from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _chalice_of_the_void() -> list[AbilitySpec]:
    """This artifact enters with X charge counters on it.
    Whenever a player casts a spell with mana value equal to the number
    of charge counters on this artifact, counter that spell.

    — MEC-43, the "counter-trigger sibling" of Gaddock Teeg/Sanctum
    Prelate's `cast_prohibition` cluster: unlike those two, Chalice
    doesn't stop the spell from being *cast* at all — it lets it be cast
    and then counters it, RULE 701.5's actual mechanism, so this is a
    triggered ability rather than a third `cast_prohibition`. The first
    clause needs no code at all: `card_registry.entry_counters`
    (`parser.oracle.catalogue.counters.entry_counters`) already recognizes
    "enters with X `<kind>` counters" generically off the card's own raw
    oracle text at every battlefield-entry site, independent of whether
    the card has a catalogue registration — confirmed live against this
    card's cached text. The trigger reuses `CounterSpellEffect.
    target_from_trigger_event` (Vexing Bauble's own "if no mana was spent
    to cast it, counter that spell" shape) for "counter *that* spell" —
    the very spell whose cast fired this ability, not a chosen target —
    and a new `mana_value_equals_source_counters` trigger-condition key
    (`effect_binder._trigger_condition`) for the live "mana value == this
    permanent's own charge-counter count" comparison, since no existing
    predicate reads a counter count off the ability's own source.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("counter", {"target_from_trigger_event": "instance_id"})],
            trigger={
                "event": "SPELL_CAST",
                "condition": {"subject": "group"},
                "mana_value_equals_source_counters": "charge",
            },
        ),
    ]


register("Chalice of the Void", _chalice_of_the_void)
