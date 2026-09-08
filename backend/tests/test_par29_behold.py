"""PAR-29 — RULE 701.4 Behold (Tarkir: Dragonstorm).

Behold is reached as an *additional cast cost*: "As an additional cost to
cast this spell, behold a `<type>` or pay {N}." `ActivationCost.behold`
holds the type word; `RulesEngine.behold(player, quality)` reveals a
matching permanent the player controls or a matching card from their hand,
firing `EventType.BEHELD` when one exists.

**Documented simplification** (mirrors `segmenter.
_ADDITIONAL_COST_PAY_LIFE_OR_MANA_RE`): the "or pay {N}" alternative isn't
modeled. The additional cost never blocks casting — a player with no
matching permanent/hand card still casts the spell, just without a behold.

Reference: game/costs.py (`behold`), game/rules/misc_mixin.py (`behold`),
game/engine/casting_mixin.py (`_pay_additional_cast_cost` /
`_can_pay_additional_cast_cost`), parser/oracle/segmenter.py
(`_ADDITIONAL_COST_BEHOLD_RE`, `_additional_cost_dict`).
"""

from __future__ import annotations

from mtg_analyzer.game.costs import parse_activation_cost
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.events import EventType
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.segmenter import (
    ParserProvenance,
    _additional_cost_dict,
    segment_line,
)


# --- parse -----------------------------------------------------------------


def test_behold_additional_cost_dict_forms():
    for text in ("behold a dragon or pay {1}", "behold a dragon"):
        assert _additional_cost_dict(text) == {"behold": "dragon"}
    assert _additional_cost_dict("behold an elf or pay {2}") == {"behold": "elf"}
    assert _additional_cost_dict("behold a merfolk or pay {2}") == {"behold": "merfolk"}


def test_behold_dict_adversarial_no_match():
    # the spell "Behold the Multiverse" must NOT be read as a behold
    # additional cost.
    assert _additional_cost_dict("behold the multiverse") is None
    assert _additional_cost_dict("behold a dragon, then draw a card") is None
    # the Lorwyn "Champion" cycle's "... and exile it" is its own
    # (mandatory) shape, `behold_exile`, not the plain `behold` (PAR-30).
    assert _additional_cost_dict("behold an elemental and exile it") == {
        "behold_exile": "elemental"
    }


def test_behold_line_claimed_on_a_creature_spell():
    # `allow_spell_effect=False` — the additional-cost wrapper is ungated
    # so a creature spell (Kinsbaile Aspirant) claims it too.
    seg = segment_line(
        "as an additional cost to cast this spell, behold a kithkin or pay {2}.",
        allow_spell_effect=False,
        provenance=ParserProvenance(),
        is_saga=False,
    )
    assert seg.claimed and seg.spec is not None
    assert seg.spec.additional_cost == {"behold": "kithkin"}


def test_real_behold_cards_modeled():
    for name, type_line, kw, text in [
        ("Caustic Exhale", "Sorcery", {},
         "As an additional cost to cast this spell, behold a Dragon or pay {1}.\n"
         "Destroy target creature."),
        ("Kinsbaile Aspirant", "Creature — Kithkin Soldier", dict(is_creature=True),
         "As an additional cost to cast this spell, behold a Kithkin or pay {2}.\n"
         "Whenever another creature you control enters, this creature gets "
         "+1/+1 until end of turn."),
    ]:
        c = Card(id=name[:3], name=name, type_line=type_line,
                 is_sorcery=(type_line == "Sorcery"),
                 mana_cost_string="{1}{B}", oracle_text=text, **kw)
        assert parse_oracle(c).modeled, name


# --- cost round-trip ------------------------------------------------------


def test_behold_cost_roundtrips():
    cost = parse_activation_cost({"behold": "dragon"})
    assert cost.behold == "dragon"
    assert cost.is_free is False
    assert "Behold a dragon" in cost.label()
    assert parse_activation_cost(cost.to_dict()).behold == "dragon"


# --- execute -------------------------------------------------------------------


def _engine():
    eng = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )
    return eng, eng.state


def _dragon_on_battlefield(state, pid):
    c = Card(id="drg", name="Dragon", type_line="Creature — Dragon",
             is_creature=True, power=4, toughness=4)
    o = GameObject(c, owner_id=pid, zone=Zone.BATTLEFIELD)
    o.controller_id = pid
    state.add_to_battlefield(o)
    return o


def test_behold_primitive_matches_permanent_then_hand():
    eng, state = _engine()
    p1 = state.player_by_id("p1")
    fired = []
    state.subscribe(lambda e: fired.append(e) if e.type == EventType.BEHELD else None)

    # no Dragon anywhere -> no behold, no event
    assert eng.rules.behold(p1, "dragon") is False
    assert fired == []

    # Dragon on the battlefield -> beholds it
    drg = _dragon_on_battlefield(state, "p1")
    assert eng.rules.behold(p1, "dragon") is True
    assert fired and fired[-1]["instance_id"] == drg.instance_id
    assert fired[-1]["player_id"] == "p1" and fired[-1]["quality"] == "dragon"

    # remove it, put a Dragon card in hand -> beholds from hand
    state.battlefield.remove(drg)
    hand_c = Card(id="dh", name="HandDragon", type_line="Creature — Dragon",
                  is_creature=True, power=2, toughness=2)
    p1.add_to_zone(GameObject(hand_c, owner_id="p1", zone=Zone.HAND), Zone.HAND)
    fired.clear()
    assert eng.rules.behold(p1, "dragon") is True
    assert len(fired) == 1


def test_behold_additional_cost_non_blocking_and_reveals():
    eng, state = _engine()
    p1 = state.player_by_id("p1")
    spell = GameObject(
        Card(id="cx", name="Caustic Exhale", type_line="Sorcery", is_sorcery=True),
        owner_id="p1", zone=Zone.STACK,
    )
    spell.additional_cast_cost = parse_activation_cost({"behold": "dragon"})

    # no Dragon -> still payable (documented: "or pay {N}" alt is dropped)
    assert eng._can_pay_additional_cast_cost(p1, spell, spell.additional_cast_cost, x=0)

    fired = []
    state.subscribe(lambda e: fired.append(e) if e.type == EventType.BEHELD else None)
    # pay with no Dragon -> no reveal
    eng._pay_additional_cast_cost(p1, spell, spell.additional_cast_cost, x=0)
    assert fired == []

    # pay with a Dragon controlled -> reveal fires
    _dragon_on_battlefield(state, "p1")
    eng._pay_additional_cast_cost(p1, spell, spell.additional_cast_cost, x=0)
    assert len(fired) == 1 and fired[0]["quality"] == "dragon"


def test_behold_creature_spell_binds_and_resolves_without_a_match():
    eng, state = _engine()
    p1 = state.player_by_id("p1")
    card = Card(
        id="ka", name="Kinsbaile Aspirant", type_line="Creature — Kithkin Soldier",
        is_creature=True, power=1, toughness=1, mana_cost_string="{1}{W}",
        oracle_text=(
            "As an additional cost to cast this spell, behold a Kithkin or pay {2}.\n"
            "Whenever another creature you control enters, this creature gets "
            "+1/+1 until end of turn."
        ),
    )
    obj = GameObject(card, owner_id="p1", zone=Zone.HAND)
    obj.controller_id = "p1"
    bind_from_catalogue(obj)
    assert obj.additional_cast_cost is not None
    assert obj.additional_cast_cost.behold == "kithkin"
    # no Kithkin controlled / in hand -> the additional cost is still payable
    assert eng._can_pay_additional_cast_cost(p1, obj, obj.additional_cast_cost, x=0)
