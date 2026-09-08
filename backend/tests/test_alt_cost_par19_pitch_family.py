"""PAR-19's own wider "pitch" residue past MEC-12/MEC-15's already-shipped
shapes: the counted `exile_hand_card_color` sibling (Soul Spike/Sunscour/
Allosaurus Rider/Commandeer/Fury of the Horde's "exile 2 `<color>` cards
from your hand…"), a `not_your_turn`-gated singular exile (Force of Virtue/
Force of Despair/Force of Rage), a combined `pay_life`+`exile_hand_card_color`
(Contagion/Force of Rowan), and the discard-zone "Pitch" basic-land cycle
(Abolish/Flameshot/Outbreak/Snag's "discard a `<basic land type>` card…").

None of the first three need new *payment* machinery beyond the new counted
key itself — `_can_pay_alt_cast_cost`/`_pay_alt_cast_cost` already check
`pay_life`/`exile_hand_card_color`/`condition` independently, so combining
them just works. `discard_land_type` is the one genuinely new payment
component (the discard zone had no alt-cast route at all before this).
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle
from mtg_analyzer.parser.oracle.spec import ParserProvenance
from mtg_analyzer.parser.oracle.segmenter import segment_line


def make_engine(*player_ids):
    return GameEngine.new_game(
        [(pid, pid, []) for pid in player_ids], starting_life=20, starting_hand=0
    )


def hand_card(state, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.HAND)
    bind_from_catalogue(obj)
    state.player_by_id(controller).hand.append(obj)
    return obj


def battlefield_card(state, card, controller="p2"):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


def plains_card(name="A Plains"):
    return Card(id=name, name=name, type_line="Basic Land — Plains", is_land=True)


# -- exile_hand_card_color_count: "exile 2 <color> cards…" -------------------


def soul_spike_card():
    return Card(
        id="Soul Spike", name="Soul Spike", type_line="Sorcery", is_sorcery=True,
        mana_cost_string="{3}{B}{B}", converted_mana_cost=5,
        oracle_text="You may exile 2 black cards from your hand rather than "
                    "pay this spell's mana cost.\n"
                    "Target creature gets -5/-5 until end of turn.",
    )


def test_soul_spike_is_modeled():
    result = parse_oracle(soul_spike_card())
    assert result.coverage != UNMODELED
    assert result.unclaimed == []


def test_exile_hand_card_color_count_clause_parses():
    seg = segment_line(
        "you may exile 2 black cards from your hand rather than pay this "
        "spell's mana cost.",
        allow_spell_effect=True,
        provenance=ParserProvenance(),
    )
    assert seg.claimed is True
    assert seg.spec is not None
    assert seg.spec.alt_cost == {"exile_hand_card_color_count": [2, "B"]}


def test_soul_spike_alt_cost_needs_two_black_cards_in_hand():
    eng = make_engine("p1", "p2")
    obj = hand_card(eng.state, soul_spike_card())
    eng.state.current_step = "main1"

    assert eng.can_cast(eng.state.active_player, obj, alt_cost=True) is False

    black_1 = hand_card(eng.state, Card(
        id="B1", name="B1", type_line="Creature — Bear", is_creature=True,
        color_identity={"B"}, power=1, toughness=1,
    ))
    assert eng.can_cast(eng.state.active_player, obj, alt_cost=True) is False

    black_2 = hand_card(eng.state, Card(
        id="B2", name="B2", type_line="Creature — Bear", is_creature=True,
        color_identity={"B"}, power=1, toughness=1,
    ))
    assert eng.can_cast(eng.state.active_player, obj, alt_cost=True) is True

    victim = battlefield_card(eng.state, Card(
        id="Victim", name="Victim", type_line="Creature — Bear", is_creature=True,
        power=2, toughness=2,
    ))
    eng.cast_spell(eng.state.active_player, obj, targets=[victim], alt_cost=True)
    assert black_1 not in eng.state.active_player.hand
    assert black_2 not in eng.state.active_player.hand
    assert any(item.obj is obj for item in eng.state.stack)


# -- not_your_turn-gated singular exile ---------------------------------------


def force_of_virtue_card():
    return Card(
        id="Force of Virtue", name="Force of Virtue", type_line="Instant", is_instant=True,
        mana_cost_string="{3}{W}{W}", converted_mana_cost=5,
        oracle_text="If it's not your turn, you may exile a white card from "
                    "your hand rather than pay this spell's mana cost.\n"
                    "Creatures you control get +1/+1 until end of turn.",
    )


def test_force_of_virtue_is_modeled():
    result = parse_oracle(force_of_virtue_card())
    assert result.coverage != UNMODELED
    assert result.unclaimed == []


def test_force_of_virtue_alt_cost_only_payable_off_your_turn():
    eng = make_engine("p1", "p2")
    obj = hand_card(eng.state, force_of_virtue_card())
    hand_card(eng.state, Card(
        id="W1", name="W1", type_line="Creature — Bear", is_creature=True,
        color_identity={"W"}, power=1, toughness=1,
    ))
    eng.state.current_step = "main1"
    eng.state.active_player_index = 0  # p1's own turn

    # Your own turn: the alt cost's condition isn't met.
    assert eng.can_cast(eng.state.active_player, obj, alt_cost=True) is False

    eng.state.active_player_index = 1  # p2's turn — not p1's
    assert eng.can_cast(eng.state.player_by_id("p1"), obj, alt_cost=True) is True


# -- pay_life + exile_hand_card_color combined --------------------------------


def contagion_card():
    return Card(
        id="Contagion", name="Contagion", type_line="Sorcery", is_sorcery=True,
        mana_cost_string="{2}{B}", converted_mana_cost=3,
        oracle_text="You may pay 1 life and exile a black card from your "
                    "hand rather than pay this spell's mana cost.\n"
                    "Target creature gets -2/-2 until end of turn.",
    )


def test_contagions_alt_cost_line_is_claimed():
    result = parse_oracle(contagion_card())
    assert not any("rather than pay" in line for line in result.unclaimed)


def test_contagion_alt_cost_pays_life_and_exiles_a_black_card():
    eng = make_engine("p1", "p2")
    obj = hand_card(eng.state, contagion_card())
    eng.state.current_step = "main1"

    assert eng.can_cast(eng.state.active_player, obj, alt_cost=True) is False

    black = hand_card(eng.state, Card(
        id="B1", name="B1", type_line="Creature — Bear", is_creature=True,
        color_identity={"B"}, power=1, toughness=1,
    ))
    assert eng.can_cast(eng.state.active_player, obj, alt_cost=True) is True

    victim = battlefield_card(eng.state, Card(
        id="Victim", name="Victim", type_line="Creature — Bear", is_creature=True,
        power=2, toughness=2,
    ))
    life_before = eng.state.active_player.life
    eng.cast_spell(eng.state.active_player, obj, targets=[victim], alt_cost=True)
    assert eng.state.active_player.life == life_before - 1
    assert black not in eng.state.active_player.hand


# -- discard_land_type: the "Pitch" basic-land cycle --------------------------


def abolish_card():
    return Card(
        id="Abolish", name="Abolish", type_line="Instant", is_instant=True,
        mana_cost_string="{1}{W}{W}", converted_mana_cost=3,
        oracle_text="You may discard a Plains card rather than pay this "
                    "spell's mana cost.\n"
                    "Destroy target artifact or enchantment.",
    )


def test_abolish_is_modeled():
    result = parse_oracle(abolish_card())
    assert result.coverage != UNMODELED
    assert result.unclaimed == []


def test_discard_land_type_clause_parses_to_expected_params():
    seg = segment_line(
        "you may discard a plains card rather than pay this spell's mana cost.",
        allow_spell_effect=True,
        provenance=ParserProvenance(),
    )
    assert seg.claimed is True
    assert seg.spec is not None
    assert seg.spec.alt_cost == {"discard_land_type": "plains"}


def test_abolish_alt_cost_needs_a_plains_in_hand():
    eng = make_engine("p1", "p2")
    obj = hand_card(eng.state, abolish_card())
    eng.state.current_step = "main1"

    assert eng.can_cast(eng.state.active_player, obj, alt_cost=True) is False

    plains = hand_card(eng.state, plains_card())
    assert eng.can_cast(eng.state.active_player, obj, alt_cost=True) is True

    trinket = battlefield_card(eng.state, Card(id="Trinket", name="Trinket", type_line="Artifact"))
    eng.cast_spell(eng.state.active_player, obj, targets=[trinket], alt_cost=True)
    assert plains not in eng.state.active_player.hand
    assert plains in eng.state.active_player.graveyard
    assert any(item.obj is obj for item in eng.state.stack)


def test_abolish_alt_cost_is_not_paid_by_a_non_plains_land():
    eng = make_engine("p1", "p2")
    obj = hand_card(eng.state, abolish_card())
    hand_card(eng.state, Card(
        id="A Forest", name="A Forest", type_line="Basic Land — Forest", is_land=True,
    ))
    eng.state.current_step = "main1"

    assert eng.can_cast(eng.state.active_player, obj, alt_cost=True) is False


def test_abolish_alt_cost_does_not_discard_the_spell_itself():
    # The spell being cast is itself in hand while `can_cast`/`cast_spell`
    # run — a Plains-typed spell (none exist, but the exclusion is the same
    # `exclude=obj` idiom every other alt-cast payment helper uses) must
    # never be its own payment.
    eng = make_engine("p1", "p2")
    obj = hand_card(eng.state, abolish_card())
    eng.state.current_step = "main1"
    plains = hand_card(eng.state, plains_card())

    from mtg_analyzer.game.costs import ActivationCost

    cost = ActivationCost(discard_land_type="plains")
    assert eng._discard_land_type_candidate(eng.state.active_player, "plains", exclude=obj) is plains
    assert eng._discard_land_type_candidate(eng.state.active_player, "plains", exclude=plains) is None
