from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


# ---------------------------------------------------------------------------
# PAR-78 residue: "sources of **the color of your choice**" (a chosen colour
# shielding against *every* matching source, not one chosen permanent) and
# a handful of other genuinely bespoke shapes the "prevent all damage that
# would be dealt to `<target>`" broad-recognition sweep left as SOLO —
# see BACKLOG.md's own PAR-78 entry for the family this closes out of.
# ---------------------------------------------------------------------------


def _avacyn_guardian_angel() -> list[AbilitySpec]:
    """Flying, vigilance
    {1}{W}: Prevent all damage that would be dealt to another target
    creature this turn by sources of the color of your choice.
    {5}{W}{W}: Prevent all damage that would be dealt to target player or
    planeswalker this turn by sources of the color of your choice.

    — Flying/vigilance are ordinary RULE 702 keywords (repeated here per
    Kithkin Armor's own "a registered card is trusted wholesale" caution,
    even though `parse_keywords` would likely fold them in anyway). Both
    activated abilities are RULE 615/616.1d's "sources of **the color** of
    your choice" shield — genuinely different from the Circle of
    Protection family's "**a source** of your choice"
    (`RequestPreventDamageSourceEffect`): the shield here has to match
    *every* source of the picked colour, not one specific permanent — see
    `RequestPreventDamageChosenColorEffect`. "target creature" already
    excludes this ability's own source (`legal_targets`' plain ``creature``
    kind), matching the printed "**another** target creature". The second
    ability drops "or planeswalker" from its target, the project's
    existing convention for this exact phrase (Boros Charm,
    `parser/oracle/catalogue/subgrammars.py`'s own "target player or
    planeswalker" → plain ``"player"`` row).
    """
    return [
        AbilitySpec("keyword", [], keyword={"name": "flying"}),
        AbilitySpec("keyword", [], keyword={"name": "vigilance"}),
        AbilitySpec(
            "activated",
            [EffectSpec("request_prevent_damage_chosen_color", {"target_kind": "creature"})],
            cost={"mana": "{1}{W}"},
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("request_prevent_damage_chosen_color", {"target_kind": "player"})],
            cost={"mana": "{5}{W}{W}"},
        ),
    ]


register("Avacyn, Guardian Angel", _avacyn_guardian_angel)
