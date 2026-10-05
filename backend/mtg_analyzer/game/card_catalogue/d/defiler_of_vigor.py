from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register

#: RULE 110.4 — every permanent type; "permanent spell" is a spell of any of these.
_PERMANENT_TYPES = ["creature", "artifact", "enchantment", "land", "planeswalker", "battle"]


def _defiler_of_vigor() -> list[AbilitySpec]:
    """Trample
    As an additional cost to cast green permanent spells, you may pay 2 life.
    Those spells cost {G} less to cast if you paid life this way. This effect
    reduces only the amount of green mana you pay.
    Whenever you cast a green permanent spell, put a +1/+1 counter on each
    creature you control.

    — PLAY-ALL Step 2 (Kodama). Trample is the keyword fold-in. The optional
    life cost is the new `pip_life_option` static (`continuous.pip_life_options_for`,
    consulted by `GameEngine._adjust_cost`): one ``{G}`` of a green permanent spell
    becomes a Phyrexian ``{G/P}`` — pay the mana or 2 life, which is exactly
    "pay 2 life, the spell costs {G} less" and reduces only green mana by
    construction. The trigger is the parser's own `add_counters` over
    ``each_creature_you_control`` on a green `SPELL_CAST`, narrowed here to
    *permanent* spells (the parser drops the word, so its claim would also fire for
    a green instant or sorcery). **Documented simplification:** the life payment is
    the solver's choice — like any printed Phyrexian pip it is used when the green
    mana isn't there, not asked about up front.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("pip_life_option", {
                "color": "G", "pips": 1, "spell_color": "G", "spell_type": _PERMANENT_TYPES,
            })],
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("add_counters", {"kind": "+1/+1", "selector": "each_creature_you_control", "count": 1})],
            trigger={
                "event": EventType.SPELL_CAST,
                "condition": {"subject": "you"},
                "spell_filter": {
                    "color": "G",
                    "any_of": [{"card_type": t} for t in _PERMANENT_TYPES],
                },
            },
        ),
    ]


register("Defiler of Vigor", _defiler_of_vigor)
