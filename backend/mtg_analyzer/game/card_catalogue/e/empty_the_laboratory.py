from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _empty_the_laboratory() -> list[AbilitySpec]:
    """Sacrifice X Zombies, then reveal cards from the top of your library until you reveal a number of Zombie
    creature cards equal to the number of Zombies sacrificed this way. Put those cards onto the battlefield and the
    rest on the bottom of your library in a random order.

    — Landslide's "this way" shape (PAR-132): a `mark_event_log` window around the sacrifice pick (`choose_objects`,
    ``count`` the announced X, RULE 107.3; a controller with fewer Zombies sacrifices what it has), then
    `reveal_until` (RULE 701.20, `reveal_until_matching`) whose ``count`` is the `sacrificed_this_way` operand -- the
    number actually sacrificed (RULE 608.2c), not X. The hits are Zombie *creature* cards (``all_types``) and enter
    the battlefield; everything else goes to the bottom in a random order.
    """
    return [
        AbilitySpec("spell_effect", [
            EffectSpec("mark_event_log", {}),
            EffectSpec("choose_objects", {
                "action": "sacrifice", "what": "permanent", "count_amount": {"kind": "x_paid", "of": "source"},
                "permanent_filter": {"subtype": "zombie"},
            }),
            EffectSpec("reveal_until", {
                "criteria": {"all_types": ["creature", "zombie"]},
                "count": {"kind": "sacrificed_this_way"},
                "hit_destination": "battlefield", "rest_destination": "library_bottom_random",
            }),
        ]),
    ]


register('Empty the Laboratory', _empty_the_laboratory)
