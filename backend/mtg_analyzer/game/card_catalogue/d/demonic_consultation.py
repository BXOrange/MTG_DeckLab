from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


# ---------------------------------------------------------------------------
# cEDH staples cube — batch 25, wave 4: naming a card, and the three loops
#
# Four genuinely new engine shapes, each previously listed as its own
# blocker:
#
# * **naming a card** (`_request_name_card`) — the only choice in the engine
#   whose answer space isn't enumerable from game state.
# * **dig-until-a-predicate** (`RulesEngine.dig_until`) — the cascade dig
#   generalized so both the predicate and both destinations are parameters.
# * **repeat-until-a-predicate** (`MillUntilCreatureEffect`) — every other
#   repetition here had its count fixed before it started.
# * **an open-ended loop** (`_request_look_top_pay_life_loop`) — bounded by
#   its own life payment rather than by any counter.
# ---------------------------------------------------------------------------


def _demonic_consultation() -> list[AbilitySpec]:
    """Choose a card name. Exile the top six cards of your library, then
    reveal cards from the top of your library until you reveal a card with
    the chosen name. Put that card into your hand and exile all other cards
    revealed this way.

    — Demonic Consultation. Two firsts, composed:

    * **Naming a card** (`NameCardThenEffect`). Every other `pending_choice`
      picks from a set the engine can enumerate; a player may name any card
      in Magic. So the choice offers the names the player can actually see
      (their own hand/library/graveyard) as *suggestions* and accepts an
      arbitrary string, which is then only ever compared against card names
      — never interpreted — keeping docs/09's security boundary intact.
    * **Dig-until-a-predicate** (`RulesEngine.dig_until`), the cascade dig
      with the predicate and both destinations made parameters. The chosen
      name reaches it through the ``"named_card"`` criteria sentinel,
      substituted at answer time exactly like `_substitute_x` handles an
      announced {X}.

    Naming a card that *isn't* in the library exiles the whole library
    rather than erroring — which is not a degenerate case but the actual
    cEDH line: Consultation into an empty library, then Thassa's Oracle.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("name_card_then", {
                "effects": [{
                    "type": "dig_until",
                    "params": {
                        "criteria": {"name": "named_card"},
                        "pre_exile": 6,
                        "hit_destination": "hand",
                        "rest_destination": "exile",
                    },
                }],
            })],
        ),
    ]


register("Demonic Consultation", _demonic_consultation)
