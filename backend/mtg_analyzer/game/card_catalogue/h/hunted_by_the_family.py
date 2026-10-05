from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


# ---------------------------------------------------------------------------
# MEC-52 — Reanimator-token & villainous-choice residue (PAR-29's keyword
# trail, PAR-30 close-out). The three cards left after The Master, Gallifrey's
# End: each blocks on a distinct engine primitive, not oracle grammar, so
# they're hand-authored here (the primitives themselves — the villainous
# ``previous_target_controller`` per-target sweep, `dig_until`'s
# ``digger``/``caster`` split, the summed-MV damage source — are general).
# ---------------------------------------------------------------------------


def _hunted_by_the_family() -> list[AbilitySpec]:
    """Choose up to four target creatures you don't control. For each of
    them, that creature's controller faces a villainous choice — That
    creature becomes a 1/1 white Human creature and loses all abilities, or
    you create a token that's a copy of it.

    — MEC-52. `FaceVillainousChoiceEffect` ``subject="previous_target_
    controller"``: the RULE 115 targets are the creatures ("up to four" ⇒
    ``optional`` + ``count=4`` on the effect's own `target_spec`), and each
    one's controller gets its *own* queued `villainous_choice`
    (`_request_villainous_choice(rounds=…)`) with that creature baked in as
    the RULE 608.2 referent. Option A is one indefinite RULE 611 grant
    (`grant_until` ``previous_subject`` / ``duration="rest_of_game"``) that
    bundles the layer-4 P/T+type change, the layer-5 colour set and the
    layer-6 lose-all-abilities — the same three statics Kenrith's
    Transformation stacks, here aimed at the villainous creature rather
    than an enchanted one. Option B is PAR-18's `copy_permanent`
    ``referent="previous"``, made under *your* control ("you create").
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("face_villainous_choice", {
                "subject": "previous_target_controller",
                "option_a": [{
                    "type": "grant_until",
                    "params": {
                        "previous_subject": True,
                        "duration": "rest_of_game",
                        "static": {"type": "type_change", "params": {
                            "add_types": ["creature"], "set_subtypes": ["Human"],
                            "power": 1, "toughness": 1,
                        }},
                        "extra_statics": [
                            {"type": "color_change", "params": {"colors": ["W"], "set": True}},
                            {"type": "remove_all_abilities", "params": {}},
                        ],
                    },
                }],
                "option_b": [{
                    "type": "copy_permanent",
                    "params": {"target_kind": None, "referent": "previous"},
                }],
            })],
        ),
    ]


register("Hunted by The Family", _hunted_by_the_family)
