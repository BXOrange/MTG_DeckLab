from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _sevinnes_reclamation() -> list[AbilitySpec]:
    """Return target permanent card with mana value 3 or less from your
    graveyard to the battlefield. If this spell was cast from a
    graveyard, you may copy this spell and may choose a new target for
    the copy.
    Flashback {4}{W} (You may cast this card from your graveyard for its
    flashback cost. Then exile it.)

    — MEC-42. Flashback is a plain printed cost-bearing keyword, already
    read straight off `parametric_keywords` independent of catalogue
    registration. The reanimation half is `ReturnFromGraveyardEffect`'s
    already-general ``target_kind="graveyard_permanent"``/``max_mana_
    value`` (RULE 701.3 family). "If this spell was cast from a
    graveyard, you may copy this spell..." needed a genuine new self-copy
    primitive — new `RulesEngine.copy_self_spell`, the sibling of `copy_
    spell` that builds the copy `StackItem` directly off this spell's own
    `GameObject` rather than looking up a live stack entry, since by the
    time this trailing clause resolves the original has already been
    popped off `GameState.stack` for resolution. Reads `GameObject.
    cast_via_flashback` directly (still true at this point — the "exile
    instead of graveyard" clearing happens only after every effect,
    this one included, has resolved). **Documented simplification**: "may
    choose a new target" keeps the original's own already-gathered target
    by default (RULE 707.10c's default outcome) rather than opening a
    genuine new-target choice — the same "no real new-targeting yet"
    simplification `CopySpellEffect` already documents for every other
    copy-a-spell card in this engine, not a fresh gap; reanimating the
    same (now already-battlefield) permanent a second time is simply a
    no-op, same as a real player declining to bother re-choosing.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("return_from_graveyard", {
                    "target_kind": "graveyard_permanent", "max_mana_value": 3,
                    "destination": "battlefield",
                }),
                EffectSpec("if_else", {"condition": {"kind": "source_cast_via_flashback"},
                            "then": [{"type": "copy_self_spell", "params": {}}], "else": []}),
            ],
        ),
    ]


register("Sevinne's Reclamation", _sevinnes_reclamation)
