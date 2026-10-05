from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _ensnared_by_the_mara() -> list[AbilitySpec]:
    """Each opponent faces a villainous choice — They exile cards from the
    top of their library until they exile a nonland card, then you may cast
    that card without paying its mana cost, or that player exiles the top
    four cards of their library and Ensnared by the Mara deals damage equal
    to the total mana value of those exiled cards to that player.

    — MEC-52. A plain ``each_opponent`` villainous choice; both option
    bodies are past the parser's villainous grammar but reach existing/
    widened primitives directly: option A is `dig_until` with the new
    ``digger="facing"`` (the opponent's library) + ``caster="controller"``
    (RULE 601.3e — *you* become the free-cast card's controller) and
    ``hit_destination="cast_free_window"`` (a genuine "you may", with the
    RULE-shaped "return it if uncast" delayed half); option B is the new
    a composed exile plus summed-mana-value damage source.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("face_villainous_choice", {
                "subject": "each_opponent",
                "option_a": [{
                    "type": "dig_until",
                    "params": {
                        "criteria": {"without_type": "land"},
                        "digger": "facing",
                        "caster": "controller",
                        "hit_destination": "cast_free_window",
                        "rest_destination": "exile",
                    },
                }],
                "option_b": [{
                    "type": "seq", "params": {"effects": [
                        {"type": "exile_top_of_library", "params": {
                            "count": 4, "player_selector": "target",
                        }},
                        {"type": "bind", "params": {
                            "name": "mv",
                            "amount": {"kind": "moved_sum", "characteristic": "mana_value"},
                            "effects": [{"type": "damage", "params": {
                                "amount": "$mv", "target_kind": "any",
                            }}],
                        }},
                    ]},
                }],
            })],
        ),
    ]


register("Ensnared by the Mara", _ensnared_by_the_mara)
