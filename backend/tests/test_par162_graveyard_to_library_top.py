"""PAR-162: "put [up to one] target `<type>` card from your graveyard on top of your library" and its
plural, untargeted-pick and source-card siblings, all riding `return_from_graveyard`'s ``library_top`` destination
(RULE 401.4 order choice, RULE 400.7 new object, RULE 608.2b target that left)."""

from __future__ import annotations

import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.effects.core import GameContext
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.game.targeting import TargetSpec, legal_targets
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle import parse_oracle
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause

#: Mana comfortably above any cost a test spell or ability here asks for.
PLENTY_OF_MANA = 6


def _engine() -> GameEngine:
    return GameEngine.new_game([("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0)


def _card(name: str, text: str = "", type_line: str = "Creature — Bear") -> Card:
    creature = "Creature" in type_line
    return Card(
        id=name, name=name, type_line=type_line, is_creature=creature,
        is_land="Land" in type_line,
        is_instant=type_line.startswith("Instant"), is_sorcery=type_line.startswith("Sorcery"),
        power=2 if creature else None, toughness=2 if creature else None, oracle_text=text,
    )


def _in_graveyard(eng: GameEngine, card: Card, owner: str = "p1") -> GameObject:
    obj = GameObject(card, owner_id=owner, zone=Zone.GRAVEYARD)
    eng.state.player_by_id(owner).graveyard.append(obj)
    return obj


def _start_cast(eng: GameEngine, text: str, targets=None) -> GameObject:
    p1 = eng.state.players[0]
    spell = GameObject(_card("Spell", text, "Sorcery"), owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(spell)
    p1.hand.append(spell)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1.mana_pool.add_many({"C": PLENTY_OF_MANA})
    eng.cast_spell(p1, spell, targets=targets)
    return spell


def _cast(eng: GameEngine, text: str, targets=None) -> GameObject:
    spell = _start_cast(eng, text, targets)
    eng.resolve_until_stable()
    return spell


def _top_names(eng: GameEngine, owner: str = "p1", n: int = 3) -> list[str]:
    """Top card first."""
    return [o.card.name for o in reversed(eng.state.player_by_id(owner).library[-n:])]


def _lib(eng: GameEngine, owner: str = "p1") -> list[GameObject]:
    return eng.state.player_by_id(owner).library


# --- parse -------------------------------------------------------------------------------------------


@pytest.mark.parametrize("clause, params", [
    ("put target card from your graveyard on top of your library",
     {"target_kind": "graveyard_card", "destination": "library_top"}),
    ("put target creature card from your graveyard on top of your library",
     {"target_kind": "graveyard_creature", "destination": "library_top"}),
    ("put up to 1 target instant or sorcery card from your graveyard on top of your library",
     {"target_kind": "graveyard_instant_or_sorcery", "destination": "library_top", "optional": True}),
    ("put target zombie card from your graveyard on top of your library",
     {"target_kind": "graveyard_zombie_card", "destination": "library_top"}),
    ("put target creature or battle card from your graveyard on top of your library",
     {"target_kind": "graveyard_creature_or_battle", "destination": "library_top"}),
    ("put target artifact or creature card from your graveyard on top of your library",
     {"target_kind": "graveyard_artifact_or_creature", "destination": "library_top"}),
    ("put target noncreature, nonland card from your graveyard on top of your library",
     {"target_kind": "graveyard_noncreature_nonland", "destination": "library_top"}),
    ("put up to 3 target creature cards from your graveyard on top of your library",
     {"target_kind": "graveyard_creature", "destination": "library_top", "count": 3, "optional": True}),
    ("put target card from a graveyard on top of its owner's library",
     {"target_kind": "any_graveyard_card", "destination": "library_top"}),
    ("you may put a land card from your graveyard on top of your library",
     {"target_kind": "graveyard_land", "destination": "library_top", "pick": True, "optional": True}),
    ("put an instant, sorcery, or battle card from your graveyard on top of your library",
     {"target_kind": "graveyard_instant_sorcery_or_battle", "destination": "library_top", "pick": True}),
])
def test_forms_parse(clause, params):
    [spec] = match_clause(clause)
    assert spec.type == "return_from_graveyard" and spec.params == params


def test_source_card_form_parses():
    for clause in ("put this card from your graveyard on top of your library",
                   "put ~ from your graveyard on top of your library"):
        [spec] = match_clause(clause)
        assert spec.type == "return_self_from_graveyard_to_library_top" and spec.params == {}


@pytest.mark.parametrize("clause", [
    "put target creature card from your graveyard on top of its owner's library",  # contradicting possessives
    "put target creature card from a graveyard on top of your library",
    "put target blorp card from your graveyard on top of your library",
    "put target creature card from your graveyard on the bottom of your library",
    "put 1 target creature cards from your graveyard on top of your library",  # the plural row starts at two
])
def test_fails_closed(clause):
    assert match_clause(clause) is None


# --- execute -----------------------------------------------------------------------------------------


def test_targeted_card_goes_on_top_of_the_library():
    eng = _engine()
    bear = _in_graveyard(eng, _card("Bear"))
    other = _in_graveyard(eng, _card("Other"))
    _cast(eng, "Put target creature card from your graveyard on top of your library.", targets=[bear])
    assert _top_names(eng, n=1) == ["Bear"]
    assert bear not in eng.state.players[0].graveyard and other in eng.state.players[0].graveyard
    assert eng.state.pending_choice is None  # a single card has only one order


def test_type_filter_limits_the_legal_targets():
    eng = _engine()
    bear = _in_graveyard(eng, _card("Bear"))
    bolt = _in_graveyard(eng, _card("Bolt", type_line="Instant"))
    _in_graveyard(eng, _card("Forest", type_line="Basic Land — Forest"))
    ids = {o["instance_id"] for o in legal_targets(eng.state, "p1", TargetSpec(kind="graveyard_instant_or_sorcery"))}
    assert ids == {bolt.instance_id}
    ids = {o["instance_id"] for o in legal_targets(eng.state, "p1", TargetSpec(kind="graveyard_creature_or_battle"))}
    assert ids == {bear.instance_id}


def test_the_card_can_be_drawn_next():
    eng = _engine()
    bear = _in_graveyard(eng, _card("Bear"))
    _cast(eng, "Put target card from your graveyard on top of your library.", targets=[bear])
    assert bear.zone == Zone.LIBRARY  # RULE 400.7: a new zone stay, no longer the graveyard card
    eng.rules.draw(eng.state.players[0])
    assert bear in eng.state.players[0].hand


def test_a_target_that_left_the_graveyard_is_illegal_and_nothing_moves():
    eng = _engine()
    bear = _in_graveyard(eng, _card("Bear"))
    filler = _in_graveyard(eng, _card("Filler"))
    before = len(_lib(eng))
    _start_cast(eng, "Put target creature card from your graveyard on top of your library.", targets=[bear])
    eng.rules.exile(bear)  # in response, the target is exiled out of the graveyard
    eng.resolve_until_stable()
    assert len(_lib(eng)) == before and bear not in _lib(eng)
    assert filler in eng.state.players[0].graveyard and bear.zone == Zone.EXILE


def test_up_to_one_may_choose_no_target():
    eng = _engine()
    bear = _in_graveyard(eng, _card("Bear"))
    before = len(_lib(eng))
    _cast(eng, "Put up to one target creature card from your graveyard on top of your library.", targets=[])
    assert len(_lib(eng)) == before and bear in eng.state.players[0].graveyard


def test_several_cards_are_arranged_by_their_owner():
    eng = _engine()
    a, b, c = (_in_graveyard(eng, _card(n)) for n in ("A", "B", "C"))
    _cast(eng, "Put up to 3 target creature cards from your graveyard on top of your library.", targets=[a, b, c])
    pending = eng.state.pending_choice
    assert pending is not None and pending["kind"] == "reorder_top" and pending["player_id"] == "p1"
    assert {o["instance_id"] for o in pending["options"] if "instance_id" in o} == {
        a.instance_id, b.instance_id, c.instance_id}
    eng.resolve_pending_choice(str(b.instance_id))   # B goes on top
    eng.resolve_pending_choice(str(c.instance_id))   # then C; A is last
    eng.resolve_until_stable()
    assert eng.state.pending_choice is None
    assert _top_names(eng) == ["B", "C", "A"]


def test_declining_the_order_keeps_target_order_and_one_card_asks_nothing():
    eng = _engine()
    a, b = (_in_graveyard(eng, _card(n)) for n in ("A", "B"))
    _cast(eng, "Put up to 2 target creature cards from your graveyard on top of your library.", targets=[a, b])
    assert eng.state.pending_choice["kind"] == "reorder_top"
    eng.resolve_pending_choice("decline")
    assert _top_names(eng, n=2) == ["B", "A"]
    eng2 = _engine()
    only = _in_graveyard(eng2, _card("Only"))
    _cast(eng2, "Put up to 2 target creature cards from your graveyard on top of your library.", targets=[only])
    assert eng2.state.pending_choice is None and _top_names(eng2, n=1) == ["Only"]


def test_a_card_from_another_graveyard_goes_to_its_owners_library():
    eng = _engine()
    theirs = _in_graveyard(eng, _card("Theirs"), owner="p2")
    mine_before, theirs_before = len(_lib(eng)), len(_lib(eng, "p2"))
    _cast(eng, "Put target card from a graveyard on top of its owner's library.", targets=[theirs])
    assert len(_lib(eng)) == mine_before and len(_lib(eng, "p2")) == theirs_before + 1
    assert _top_names(eng, "p2", 1) == ["Theirs"]


def test_untargeted_pick_offers_only_matching_cards():
    eng = _engine()
    forest = _in_graveyard(eng, _card("Forest", type_line="Basic Land — Forest"))
    island = _in_graveyard(eng, _card("Island", type_line="Basic Land — Island"))
    bear = _in_graveyard(eng, _card("Bear"))
    _cast(eng, "You may put a land card from your graveyard on top of your library.")
    pending = eng.state.pending_choice
    assert pending is not None and pending["kind"] == "choose_objects"
    assert {o["instance_id"] for o in pending["options"] if "instance_id" in o} == {
        forest.instance_id, island.instance_id}
    eng.resolve_pending_choice(island.instance_id)
    eng.resolve_until_stable()
    assert _top_names(eng, n=1) == ["Island"]
    assert forest in eng.state.players[0].graveyard and bear in eng.state.players[0].graveyard


def test_source_card_returns_only_while_it_is_still_in_the_graveyard():
    from mtg_analyzer.game.effects.registry import EffectRegistry

    eng = _engine()
    card = _in_graveyard(eng, _card("Colossus"))
    effect = EffectRegistry.create("return_self_from_graveyard_to_library_top", {})
    effect.source = card
    effect.apply(GameContext(eng.state, eng.rules))
    assert _top_names(eng, n=1) == ["Colossus"] and card not in eng.state.players[0].graveyard
    gone = _in_graveyard(eng, _card("Gone"))
    effect2 = EffectRegistry.create("return_self_from_graveyard_to_library_top", {})
    effect2.source = gone
    eng.rules.exile(gone)
    effect2.apply(GameContext(eng.state, eng.rules))
    assert gone not in _lib(eng)


def test_graveyard_abilities_are_bound_to_the_graveyard():
    champion = GameObject(
        _card("Champion", "{5}{B}{B}: Put this card from your graveyard on top of your library."),
        owner_id="p1", zone=Zone.GRAVEYARD,
    )
    bind_from_catalogue(champion)
    [ability] = champion.activated_abilities
    assert ability.cost.graveyard_zone is True
    gate = GameObject(
        _card("Gate Colossus", "Whenever a Gate you control enters, you may put this card from your graveyard on "
                               "top of your library."),
        owner_id="p1", zone=Zone.GRAVEYARD,
    )
    bind_from_catalogue(gate)
    assert any(getattr(t, "functions_from_graveyard", False) for t in gate.triggered_abilities)


# --- real cards --------------------------------------------------------------------------------------


@pytest.mark.parametrize("name, text, type_line", [
    ("Golgari Thug", "When Golgari Thug dies, put target creature card from your graveyard on top of your library.",
     "Creature — Human Warrior"),
    ("Reclaim", "Put target card from your graveyard on top of your library.", "Instant"),
    ("Reinforcements", "Put up to three target creature cards from your graveyard on top of your library.", "Sorcery"),
    ("Glowspore Shaman", "When Glowspore Shaman enters, mill three cards. You may put a land card from your "
     "graveyard on top of your library.", "Creature — Elf Shaman"),
    ("Haunted Crossroads", "{B}: Put target creature card from your graveyard on top of your library.", "Enchantment"),
])
def test_real_cards_are_modeled(name, text, type_line):
    assert parse_oracle(_card(name, text, type_line)).modeled is True
