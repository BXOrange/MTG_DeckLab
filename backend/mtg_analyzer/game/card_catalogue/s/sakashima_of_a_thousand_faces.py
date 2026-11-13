from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register

# The normalized printed line of the exemption (see `static_handlers._IGNORE_LEGEND_RULE_RE`).
LEGEND_RULE_LINE = "the \"legend rule\" doesn't apply to permanents you control."


def _sakashima_of_a_thousand_faces() -> list[AbilitySpec]:
    """You may have Sakashima enter as a copy of another creature you
    control, except it has Sakashima's other abilities.
    The "legend rule" doesn't apply to permanents you control.

    — MEC-12 (cEDH staples 2). Two specs: the ordinary `enter_as_copy`
    replacement (``target_kind="creature_you_control"``,
    ``keep_own_abilities=True`` — RULE 707.2 would otherwise erase
    Sakashima's own printed abilities entirely, but the "except" clause adds
    them back onto the copy, snapshotted before the copy runs and reattached
    after in `_resume_enter_as_copy`, stored as the copy's copiable values per RULE 707.9a: the legend line as an
    ability line, Partner as a keyword); and a standing
    `ignore_legend_rule` static (RULE 704.5j) so two same-named legendary
    permanents — Sakashima-as-a-copy and the original it copied, or any
    other pair — can coexist under its controller. Partner is a keyword the copy keeps
    (`keep_own_abilities` carries the copier's own keywords too).
    """
    return [
        AbilitySpec(
            "enter_replacement",
            [EffectSpec("enter_as_copy", {
                "target_kind": "creature_you_control", "keep_own_abilities": True,
            })],
        ),
        AbilitySpec(
            "static",
            [EffectSpec("ignore_legend_rule", {"affects": "you"})],
            # RULE 707.9a: the printed line is what a copy stores in its copiable values (`keep_as_copiable`); it
            # parses on its own to this same spec, so a Clone of the copy re-binds the exemption from it.
            raw_text=LEGEND_RULE_LINE,
        ),
    ]


register("Sakashima of a Thousand Faces", _sakashima_of_a_thousand_faces)
