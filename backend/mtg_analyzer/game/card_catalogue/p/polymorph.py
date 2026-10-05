from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _polymorph() -> list[AbilitySpec]:
    """Destroy target creature. It can't be regenerated. Its controller
    reveals cards from the top of their library until they reveal a
    creature card. The player puts that card onto the battlefield, then
    shuffles all other cards revealed this way into their library.

    — MEC-12 (cEDH Kinnan). `DestroyExileThenControllerRevealCreatureEffect`
    is the new general primitive: one atomic effect rather than a two-effect
    list, since the dig has to be run by the *destroyed creature's own
    controller* (read before the RULE 400.7 zone change, the same "read it
    before it leaves the battlefield" idiom Nature's Claim's composition (`destroy` + a referent recipient, ENG-37)
    already uses) — not this spell's own caster. Reuses `dig_until`'s new
    ``rest_destination="library_shuffled"`` (a real shuffle, not just "the
    bottom in a random order" — the two read identically to a player, but
    match Polymorph's actual printed wording).
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("destroy_exile_then_controller_reveal_creature", {
                "target_kind": "creature", "mode": "destroy", "criteria": "Creature",
            })],
        ),
    ]


register("Polymorph", _polymorph)
