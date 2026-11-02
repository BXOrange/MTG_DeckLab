from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _echocasting_symposium() -> list[AbilitySpec]:
    "Target player creates a token that's a copy of target creature you control.\nParadigm (Then exile this spell. After you first resolve a spell with this name, you may cast a copy of it from exile without paying its mana cost at the beginning of each of your first main phases.)"
    return [
        AbilitySpec(
            'spell_effect',
            [
                EffectSpec('target_player_copies_creature', {}),
                # RULE 702.192a: Paradigm's "Then exile this spell"; the recurring cast-copy half is driven from
                # exile by `effects.paradigm.collect_paradigm_triggers`.
                EffectSpec('paradigm_exile', {}),
            ],
            raw_text="target player creates a token that's a copy of target creature you control.",
        ),
    ]


register('Echocasting Symposium', _echocasting_symposium)
