"""PAR-30 — the Lorwyn "Champion" cycle reflavoured (Collect Evidence /
Forage / Blight activated-body residue).

"As an additional cost to cast this spell, behold a <type> and exile it."
is a *mandatory* additional cast cost (no "or pay {N}" alternative — unlike
PAR-29's `behold`): `ActivationCost.behold_exile`, recognised by
`segmenter._ADDITIONAL_COST_BEHOLD_EXILE_RE`, charged by
`GameEngine._pay_additional_cast_cost` (exile a matching permanent/hand
card, stamp `GameObject.linked_exile_id`), and refused by
`_can_pay_additional_cast_cost` when nothing matches.

The paired "when ~ leaves the battlefield, return the exiled card to its
owner's **hand**." trigger is `ReturnLinkedExileEffect(destination="hand")`
— `handlers._RETURN_EXILED_CARD_RE`'s widened "to its owner's hand" branch.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.segmenter import _additional_cost_dict
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.game.binding.core import bind_from_catalogue

from tests.support.game import creature, make_engine, obj_on_battlefield


_CLACHAN_TEXT = (
    "Flash\n"
    "As an additional cost to cast this spell, behold a Kithkin and exile it. "
    "(Exile a Kithkin you control or a Kithkin card from your hand.)\n"
    "Other Kithkin you control get +1/+1.\n"
    "When Champion of the Clachan leaves the battlefield, return the exiled "
    "card to its owner's hand."
)


def _clachan() -> Card:
    return Card(
        id="clachan", name="Champion of the Clachan",
        type_line="Creature — Kithkin Knight",
        mana_cost_string="{3}{W}", converted_mana_cost=4,
        is_creature=True, power=3, toughness=3,
        oracle_text=_CLACHAN_TEXT,
    )


# --- parse ---------------------------------------------------------------

def test_additional_cost_dict_recognises_behold_exile():
    assert _additional_cost_dict("behold a kithkin and exile it") == {
        "behold_exile": "kithkin"
    }
    # plain "behold a <type> [or pay {N}]" is still the other shape
    assert _additional_cost_dict("behold a dragon") == {"behold": "dragon"}


def test_return_exiled_card_to_hand_claimed():
    specs = parse_effect_body("return the exiled card to its owner's hand")
    assert specs is not None
    assert specs[0].type == "return_linked_exile"
    assert specs[0].params.get("destination") == "hand"
    # the battlefield form is unchanged
    bf = parse_effect_body(
        "return the exiled card to the battlefield under its owner's control"
    )
    assert bf[0].params.get("destination") in (None, "battlefield")


def test_clachan_modeled_with_both_halves():
    r = parse_oracle(_clachan())
    assert r.modeled is True
    add = next(s for s in r.specs if s.additional_cost)
    assert add.additional_cost == {"behold_exile": "kithkin"}
    ltb = next(
        s for s in r.specs if (s.trigger or {}).get("event") == "LEAVES_BATTLEFIELD"
    )
    assert ltb.effects[0].type == "return_linked_exile"
    assert ltb.effects[0].params["destination"] == "hand"


def test_champions_of_the_perfect_modeled_via_parser():
    # The hand-authored stopgap is retired — the whole card parses now.
    perfect = Card(
        id="perfect", name="Champions of the Perfect",
        type_line="Creature — Elf Warrior",
        mana_cost_string="{3}{G}", converted_mana_cost=4,
        is_creature=True, power=3, toughness=3,
        oracle_text=(
            "As an additional cost to cast this spell, behold an Elf and exile "
            "it. (Exile an Elf you control or an Elf card from your hand.)\n"
            "Whenever you cast a creature spell, draw a card.\n"
            "When Champions of the Perfect leaves the battlefield, return the "
            "exiled card to its owner's hand."
        ),
    )
    r = parse_oracle(perfect)
    assert r.modeled is True
    assert any(s.additional_cost == {"behold_exile": "elf"} for s in r.specs)


# --- execute -----------------------------------------------------------

def _setup(kithkin_on_bf: bool = True, kithkin_in_hand: bool = False):
    champ = _clachan()
    eng = make_engine([champ], [creature("Bear")], hand=1)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    p1.mana_pool.add_many({"W": 4})
    kith = None
    if kithkin_on_bf:
        kith = obj_on_battlefield(
            eng.state, eng,
            creature("Goldmeadow Harrier", type_line="Creature — Kithkin Soldier"),
            controller="p1",
        )
        bind_from_catalogue(kith)
    if kithkin_in_hand:
        kc = creature("Kinsbaile Skirmisher", type_line="Creature — Kithkin Soldier")
        kith = GameObject(kc, owner_id="p1", zone=Zone.HAND)
        p1.hand.append(kith)
    ch = p1.hand[0]
    bind_from_catalogue(ch)
    return eng, p1, ch, kith


def test_behold_exile_paid_from_battlefield_and_returned_to_hand():
    eng, p1, ch, kith = _setup(kithkin_on_bf=True)
    assert eng.can_cast(p1, ch) is True
    eng.cast_spell(p1, ch)
    eng.resolve_until_stable()

    assert kith.zone == Zone.EXILE
    assert ch.zone == Zone.BATTLEFIELD
    assert ch.linked_exile_id == kith.instance_id

    # anthem live: another Kithkin gets +1/+1
    other = obj_on_battlefield(
        eng.state, eng,
        creature("Springjack Shepherd", type_line="Creature — Kithkin Shaman"),
        controller="p1",
    )
    bind_from_catalogue(other)
    eng.recompute_continuous_effects()
    assert other.power == 3 and other.toughness == 3

    eng.rules.put_into_graveyard(ch)
    eng.resolve_until_stable()
    assert kith.zone == Zone.HAND
    assert kith.owner_id == "p1"


def test_behold_exile_paid_from_hand():
    eng, p1, ch, kith = _setup(kithkin_on_bf=False, kithkin_in_hand=True)
    assert eng.can_cast(p1, ch) is True
    eng.cast_spell(p1, ch)
    eng.resolve_until_stable()
    assert kith.zone == Zone.EXILE
    assert ch.linked_exile_id == kith.instance_id


def test_behold_exile_blocks_cast_when_no_kithkin():
    eng, p1, ch, _ = _setup(kithkin_on_bf=False, kithkin_in_hand=False)
    assert eng.can_cast(p1, ch) is False


# --- Champion of the Path: "it deals damage equal to its power to each
#     opponent" off a group-subject ETB trigger --------------------------

def test_champion_of_the_path_damage_trigger():
    path = Card(
        id="path", name="Champion of the Path",
        type_line="Creature — Elemental Sorcerer",
        mana_cost_string="{4}{R}", converted_mana_cost=5,
        is_creature=True, power=3, toughness=3,
        oracle_text=(
            "Whenever another Elemental you control enters, it deals damage "
            "equal to its power to each opponent."
        ),
    )
    r = parse_oracle(path)
    assert r.modeled is True
    trig = next(
        s for s in r.specs if (s.trigger or {}).get("event") == "ENTERS_BATTLEFIELD"
    )
    assert trig.effects[0].type == "subject_damages_each_opponent_equal_to_power"

    elem = creature(
        "Fire Elemental", cost="{3}{R}",
        type_line="Creature — Elemental", power=5, toughness=4,
    )
    eng = make_engine([elem], [creature("Bear")], hand=1)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    p2 = eng.state.player_by_id("p2")
    champ = obj_on_battlefield(eng.state, eng, path, controller="p1")
    bind_from_catalogue(champ)
    p1.mana_pool.add_many({"R": 1, "C": 3})
    ec = p1.hand[0]
    bind_from_catalogue(ec)
    eng.cast_spell(p1, ec)
    eng.resolve_until_stable()
    assert p2.life == 15  # 5 power → 5 to each opponent
