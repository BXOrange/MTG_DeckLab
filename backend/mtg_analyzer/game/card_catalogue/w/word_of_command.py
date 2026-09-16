from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _word_of_command() -> list[AbilitySpec]:
    """Look at target opponent's hand and choose a card from it. You
    control that player until Word of Command finishes resolving. The
    player plays that card if able. If it's a land card, they play it. If
    it's a nonland card, they cast it if able, without paying its mana
    cost if able. If the player can't, they reveal a hand with no cards
    that can be played or cast.

    — MEC-51b (RULE 720): `WordOfCommandEffect` opens a `word_of_command`
    pending choice addressed to the caster over the target's hand;
    `GameEngine._resume_word_of_command` then has the target play the pick
    (`play_land`, else `cast_without_paying`). The RULE 720 mana
    restriction is moot under the free cast, and (like every effect-driven
    free cast here — cascade/discover) the spell is cast without target
    selection: documented simplifications.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("word_of_command", {})],
        ),
    ]


register("Word of Command", _word_of_command)
