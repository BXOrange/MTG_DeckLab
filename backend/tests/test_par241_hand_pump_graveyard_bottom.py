"""PAR-241 -- signed "gets -N/-N for each card in your hand" and "put target card from your graveyard on the
bottom of your library" as an activated ability, both executed on real cards through the engine."""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.game.targeting import TargetSpec, legal_targets
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.static_handlers import static_effect_specs
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
from mtg_analyzer.parser.oracle.spec import EffectSpec

_HAND = {"zone": "hand", "of": "you"}
_TRAWLER_TEXT = "{2}: Put target card from your graveyard on the bottom of your library."


def _engine() -> GameEngine:
    return GameEngine.new_game([("p1", "A", []), ("p2", "B", [])], starting_life=20, starting_hand=0)


def _filler(name: str, owner: str, zone: Zone) -> GameObject:
    return GameObject(Card(id=name, name=name, type_line="Instant", is_instant=True), owner_id=owner, zone=zone)


def _slag(eng, controller="p1"):
    card = Card(id="Dread Slag", name="Dread Slag", type_line="Creature — Elemental Horror", is_creature=True,
                power=6, toughness=6, oracle_text="Trample\nThis creature gets -4/-4 for each card in your hand.")
    obj = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    obj.controller_id = controller
    bind_from_catalogue(obj)
    eng.state.add_to_battlefield(obj)
    return obj


def _trawler(eng):
    card = Card(id="Tomb Trawler", name="Tomb Trawler", type_line="Artifact Creature — Golem", is_creature=True,
                power=0, toughness=4, oracle_text=_TRAWLER_TEXT)
    obj = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    eng.state.add_to_battlefield(obj)
    return obj


def test_signed_for_each_parses():
    assert static_effect_specs("~ gets -1/-1 for each card in your hand") == [EffectSpec("anthem", {
        "affects": "self", "power": -1, "toughness": -1, "power_count": _HAND, "toughness_count": _HAND})]


def test_graveyard_bottom_parses_and_keeps_scope():
    assert parse_effect_body("put target card from your graveyard on the bottom of your library.") == [
        EffectSpec("return_to_library", {"target_kind": "graveyard_card", "position": "bottom"})]
    # Mixed possessives would put the card in a library other than the one named: stay unclaimed.
    assert parse_effect_body("put target card from a graveyard on the bottom of your library.") is None
    assert parse_effect_body("put target card from your graveyard on the bottom of its owner's library.") is None


def test_real_cards_modeled():
    for name, text in (("Tomb Trawler", _TRAWLER_TEXT),
                       ("Geralf's Masterpiece", "This creature gets -1/-1 for each card in your hand.")):
        card = Card(id=name, name=name, type_line="Artifact Creature", is_creature=True, power=3, toughness=3,
                    oracle_text=text)
        assert parse_oracle(card).modeled


def test_hand_size_scales_pt_both_ways_and_ignores_opponent_hand():
    eng = _engine()
    p1, p2 = eng.state.players
    slag = _slag(eng)
    eng.recompute_continuous_effects()
    assert (slag.power, slag.toughness) == (6, 6)
    p1.hand.append(_filler("a", "p1", Zone.HAND))
    p2.hand.extend(_filler(f"o{i}", "p2", Zone.HAND) for i in range(3))
    eng.recompute_continuous_effects()
    assert (slag.power, slag.toughness) == (2, 2)  # the opponent's three cards do not count
    p1.hand.pop()
    eng.recompute_continuous_effects()
    assert (slag.power, slag.toughness) == (6, 6)


def test_count_uses_current_controller_hand():
    eng = _engine()
    p1, p2 = eng.state.players
    slag = _slag(eng, controller="p2")  # opponent gained control: "your hand" is theirs (RULE 109.5)
    p1.hand.extend(_filler(f"m{i}", "p1", Zone.HAND) for i in range(3))
    p2.hand.append(_filler("t", "p2", Zone.HAND))
    eng.recompute_continuous_effects()
    assert (slag.power, slag.toughness) == (2, 2)


def test_zero_toughness_dies_through_sba():
    eng = _engine()
    p1 = eng.state.players[0]
    slag = _slag(eng)
    p1.hand.extend(_filler(f"h{i}", "p1", Zone.HAND) for i in range(2))  # 6 - 8 < 0
    eng.recompute_continuous_effects()
    eng.rules.check_state_based_actions()
    assert slag in p1.graveyard and slag not in eng.state.battlefield


def test_graveyard_targets_are_own_graveyard_only_and_empty_means_none():
    eng = _engine()
    p1, p2 = eng.state.players
    trawler = _trawler(eng)
    spec = TargetSpec(kind="graveyard_card")
    assert legal_targets(eng.state, "p1", spec, trawler) == []
    mine = _filler("mine", "p1", Zone.GRAVEYARD)
    theirs = _filler("theirs", "p2", Zone.GRAVEYARD)
    p1.graveyard.append(mine)
    p2.graveyard.append(theirs)
    ids = [t.get("instance_id") for t in legal_targets(eng.state, "p1", spec, trawler)]
    assert ids == [mine.instance_id]


def test_activation_puts_card_on_bottom_preserving_order_and_fizzles_when_gone():
    eng = _engine()
    p1, p2 = eng.state.players
    trawler = _trawler(eng)
    top, bottom = _filler("top", "p1", Zone.LIBRARY), _filler("bottom", "p1", Zone.LIBRARY)
    p1.library[:] = [top, bottom]
    dead = _filler("dead", "p1", Zone.GRAVEYARD)
    p1.graveyard.append(dead)
    p1.mana_pool.add_many({"C": 2})
    eng.activate_ability(p1, trawler, ability_index=0, targets=[dead])
    eng.resolve_until_stable()
    # index 0 is the bottom of the library; the rest keeps its relative order
    assert p1.library == [dead, top, bottom] and dead.zone is Zone.LIBRARY and dead not in p1.graveyard

    # Fizzle: the target leaves the graveyard before resolution.
    gone = _filler("gone", "p1", Zone.GRAVEYARD)
    p1.graveyard.append(gone)
    p1.mana_pool.add_many({"C": 2})
    eng.activate_ability(p1, trawler, ability_index=0, targets=[gone])
    p1.graveyard.remove(gone)
    gone.zone = Zone.EXILE
    eng.resolve_until_stable()
    assert gone not in p1.library


def test_signed_siblings_claimed_by_the_widened_row_execute():
    # Nyxathid (chosen player's hand) and Mogg Squad (other creatures on the battlefield) share the signed row.
    eng = _engine()
    p1, p2 = eng.state.players
    nyx = GameObject(Card(id="Nyxathid", name="Nyxathid", type_line="Creature — Elemental", is_creature=True,
                          power=7, toughness=7,
                          oracle_text="As this creature enters, choose an opponent.\n"
                                      "This creature gets -1/-1 for each card in the chosen player's hand."),
                     owner_id="p1", zone=Zone.BATTLEFIELD)
    bind_from_catalogue(nyx)
    eng.state.add_to_battlefield(nyx)
    nyx.chosen_player_id = "p2"
    p2.hand.extend(_filler(f"o{i}", "p2", Zone.HAND) for i in range(2))
    p1.hand.append(_filler("mine", "p1", Zone.HAND))  # your own hand does not count
    eng.recompute_continuous_effects()
    assert (nyx.power, nyx.toughness) == (5, 5)
