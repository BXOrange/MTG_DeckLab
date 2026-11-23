"""PAR-286 milestone 1: activation trigger heads that name an actor or a keyword, on real cards.

``whenever <a player / an opponent> activates <a loyalty ability / an ability that isn't a mana ability>``,
``whenever you activate <a boast / an eternalize or embalm ability>`` and ``whenever you activate an ability of
<a creature / an Elemental / a Sarkhan planeswalker>`` (mana abilities included, RULE 605.1a only exempts them from the
stack). Every behaviour test drives the real activation on a real card and also shows a near miss that must not fire.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.config import DB_PATH
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.object_trigger_head import parse_object_trigger_head
from mtg_analyzer.parser.oracle.gate import MODELED, parse_oracle
from mtg_analyzer.services.card_database import CardDatabase

_DB = CardDatabase(DB_PATH)

#: Life lost to Burning-Tree Shaman / Gideon's damage and cards drawn by one trigger: one each, named so the
#: assertions read as rules text rather than as bare 1s.
ONE_TRIGGER = 1


def _card(name: str) -> Card:
    card = _DB.get_card(name)
    if card is None:
        pytest.skip(f"{name} not in the card cache")
    return card


def _engine() -> GameEngine:
    eng = GameEngine.new_game([("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    return eng


def _board(eng: GameEngine, card: Card, pid: str = "p1") -> GameObject:
    obj = GameObject(card, owner_id=pid, zone=Zone.BATTLEFIELD)
    obj.controller_id = pid
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    eng.state.add_to_battlefield(obj)
    return obj


def _named(eng: GameEngine, name: str, pid: str = "p1") -> GameObject:
    return _board(eng, _card(name), pid)


def _library(eng: GameEngine, pid: str, count: int = 5) -> None:
    for i in range(count):
        filler = Card(id=f"{pid}{i}", name=f"{pid} filler {i}", type_line="Instant")
        eng.state.player_by_id(pid).library.append(GameObject(filler, owner_id=pid, zone=Zone.LIBRARY))


def _walker(eng: GameEngine, pid: str, subtype: str) -> GameObject:
    card = Card(id=f"w-{pid}-{subtype}", name=f"Test {subtype}", type_line=f"Legendary Planeswalker — {subtype}",
                loyalty=4, oracle_text="+1: You gain 1 life.")
    walker = GameObject(card, owner_id=pid, zone=Zone.BATTLEFIELD)
    walker.controller_id = pid
    bind_from_catalogue(walker)
    eng.state.add_to_battlefield(walker)
    walker.counters["loyalty"] = 4
    return walker


def _ping(eng: GameEngine, who: str, sorcerer: GameObject) -> None:
    """``who`` activates Prodigal Sorcerer's (non-mana) ability, aimed at the Sorcerer's own controller's opponent."""
    player = eng.state.player_by_id(who)
    sorcerer.tapped = False
    eng.activate_ability(player, sorcerer, 0, targets=[eng.state.player_by_id("p2")])
    eng.resolve_until_stable()


# --- head grammar ------------------------------------------------------------------------------------------------


def test_head_shapes():
    shaman = parse_object_trigger_head("a player activates an ability that isn't a mana ability")
    assert (shaman.event, shaman.condition, shaman.trigger) == (
        "ACTIVATED_ABILITY", {"subject": "player", "scope": "any"}, {})
    gideon = parse_object_trigger_head("an opponent activates a loyalty ability")
    assert gideon.condition == {"subject": "player", "scope": "not_you"}
    assert gideon.trigger == {"filter": {"is_loyalty_ability": True}}
    boast = parse_object_trigger_head("you activate a boast ability")
    assert boast.trigger == {"filter": {"ability_keyword": "boast"}}
    either = parse_object_trigger_head("you activate an eternalize or embalm ability")
    assert either.trigger == {"filter": {"ability_keyword_in": ["embalm", "eternalize"]}}
    creature = parse_object_trigger_head("you activate an ability of a creature")
    assert creature.event == ["ACTIVATED_ABILITY", "MANA_ABILITY_ACTIVATED"]
    explicit = parse_object_trigger_head("you activate an ability of a creature that isn't a mana ability")
    assert explicit.event == "ACTIVATED_ABILITY"


@pytest.mark.parametrize("text", [
    "you activate an ability",  # which kind? mana abilities are not named
    "a player activates an ability",  # may include mana abilities and says nothing about the source
    "an opponent activates a boast ability",  # only your own boast is a head on any real card
    "an opponent activates an exhaust ability",
])
def test_unsupported_shapes_stay_unclaimed(text):
    assert parse_object_trigger_head(text) is None


@pytest.mark.parametrize("name", [
    "Burning-Tree Shaman", "Gideon the Oathless", "Frenzied Raider", "Vizier of the Anointed",
    "Sarkhan's Whelp", "Ceaseless Searblades", "Elrond, Moon-Reader",
])
def test_real_cards_are_modeled(name):
    assert parse_oracle(_card(name)).coverage == MODELED


# --- a player activates an ability that isn't a mana ability (Burning-Tree Shaman) ---------------------------------


def test_burning_tree_shaman_pings_whoever_activates_a_non_mana_ability():
    eng = _engine()
    _named(eng, "Burning-Tree Shaman")
    mine = _named(eng, "Prodigal Sorcerer", "p1")
    theirs = _named(eng, "Prodigal Sorcerer", "p2")
    p1, p2 = eng.state.player_by_id("p1"), eng.state.player_by_id("p2")

    # Prodigal Sorcerer also deals its own 1 damage (to p2) -- so measure p1's life for p1's activation.
    before = p1.life
    _ping(eng, "p1", mine)
    assert before - p1.life == ONE_TRIGGER

    before = p2.life
    _ping(eng, "p2", theirs)
    assert before - p2.life == ONE_TRIGGER + ONE_TRIGGER  # the Sorcerer's own ping and "that player"'s trigger


def test_burning_tree_shaman_ignores_mana_abilities():
    eng = _engine()
    _named(eng, "Burning-Tree Shaman")
    elves = _named(eng, "Llanowar Elves")
    p1 = eng.state.player_by_id("p1")
    before = p1.life
    eng.tap_for_mana(p1, elves)
    eng.resolve_until_stable()
    assert p1.life == before


# --- an opponent activates a loyalty ability (Gideon the Oathless) ------------------------------------------------


def test_gideon_punishes_only_an_opponents_loyalty_ability():
    eng = _engine()
    _named(eng, "Gideon the Oathless", "p1")
    p1, p2 = eng.state.player_by_id("p1"), eng.state.player_by_id("p2")
    their_walker = _walker(eng, "p2", "Chandra")
    my_walker = _walker(eng, "p1", "Chandra")
    their_sorcerer = _named(eng, "Prodigal Sorcerer", "p2")

    before = p2.life
    eng.state.active_player_index = 1  # RULE 606.3: a loyalty ability is activated on its controller's own turn
    eng.activate_ability(p2, their_walker, 0)  # the opponent's loyalty ability: +1, they gain 1 life
    eng.resolve_until_stable()
    eng.state.active_player_index = 0
    assert before + 1 - p2.life == ONE_TRIGGER  # +1 life from the walker, -1 from Gideon

    before = p2.life
    eng.activate_ability(p1, my_walker, 0)  # my own loyalty ability: no trigger
    eng.resolve_until_stable()
    assert p2.life == before

    before = (p1.life, p2.life)
    their_sorcerer.tapped = False
    eng.activate_ability(p2, their_sorcerer, 0, targets=[p1])  # their non-loyalty ability: no trigger
    eng.resolve_until_stable()
    assert (p1.life, p2.life) == (before[0] - ONE_TRIGGER, before[1])


# --- you activate a boast ability (Frenzied Raider) ------------------------------------------------------------


def test_frenzied_raider_grows_on_a_boast_activation_only():
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    raider = _named(eng, "Frenzied Raider")
    champion = _named(eng, "Goldmaw Champion")
    sorcerer = _named(eng, "Prodigal Sorcerer")
    target = _named(eng, "Llanowar Elves", "p2")

    _ping(eng, "p1", sorcerer)  # an ordinary activated ability
    assert raider.counters.get("+1/+1", 0) == 0

    champion.attacked_this_turn = True  # "Activate only if this creature attacked this turn"
    p1.mana_pool.add_many({"W": 1, "C": 1})
    eng.activate_ability(p1, champion, 0, targets=[target])
    eng.resolve_until_stable()
    assert raider.counters.get("+1/+1") == ONE_TRIGGER


# --- you activate an eternalize or embalm ability (Vizier of the Anointed) ---------------------------------------


def _graveyard_keyword_card(eng: GameEngine, keyword: str, cost: str) -> GameObject:
    card = Card(id=f"gy-{keyword}", name=f"{keyword} Bear", type_line="Creature — Bear", is_creature=True,
                power=2, toughness=2, keywords=[keyword.capitalize()], oracle_text=f"{keyword.capitalize()} {cost}")
    obj = GameObject(card, owner_id="p1", zone=Zone.GRAVEYARD)
    bind_from_catalogue(obj)
    eng.state.player_by_id("p1").graveyard.append(obj)
    return obj


@pytest.mark.parametrize("keyword,cost,mana,draws", [
    ("embalm", "{W}", {"W": 1}, ONE_TRIGGER),
    ("eternalize", "{U}", {"U": 1}, ONE_TRIGGER),
    ("unearth", "{B}", {"B": 1}, 0),  # near miss: another graveyard keyword ability
])
def test_vizier_draws_for_eternalize_and_embalm_only(keyword, cost, mana, draws):
    eng = _engine()
    _library(eng, "p1")
    _named(eng, "Vizier of the Anointed")
    ghost = _graveyard_keyword_card(eng, keyword, cost)
    p1 = eng.state.player_by_id("p1")
    index = next(i for i, a in enumerate(ghost.activated_abilities) if a.cost.graveyard_zone)
    p1.mana_pool.add_many(mana)
    before = len(p1.hand)
    eng.activate_ability(p1, ghost, index)
    eng.resolve_until_stable()
    assert len(p1.hand) - before == draws


# --- you activate an ability of a creature / an Elemental / a Sarkhan planeswalker --------------------------------


def test_elrond_draws_for_a_creatures_ability_including_mana_but_once_per_turn():
    eng = _engine()
    _library(eng, "p1")
    _named(eng, "Elrond, Moon-Reader")
    p1 = eng.state.player_by_id("p1")
    elves = _named(eng, "Llanowar Elves")
    forest = _board(eng, Card(id="f", name="Forest", type_line="Basic Land — Forest", is_land=True,
                              oracle_text="{T}: Add {G}."))
    before = len(p1.hand)
    eng.tap_for_mana(p1, forest)  # a land's mana ability: not a creature's
    eng.resolve_until_stable()
    assert len(p1.hand) == before

    eng.tap_for_mana(p1, elves)  # a creature's mana ability
    eng.resolve_until_stable()
    assert len(p1.hand) - before == ONE_TRIGGER

    sorcerer = _named(eng, "Prodigal Sorcerer")
    _ping(eng, "p1", sorcerer)  # "triggers only once each turn"
    assert len(p1.hand) - before == ONE_TRIGGER


def test_elrond_ignores_an_opponents_creature_and_a_noncreature_ability():
    eng = _engine()
    _library(eng, "p1")
    _named(eng, "Elrond, Moon-Reader")
    p1 = eng.state.player_by_id("p1")
    theirs = _named(eng, "Prodigal Sorcerer", "p2")
    before = len(p1.hand)
    _ping(eng, "p2", theirs)
    assert len(p1.hand) == before
    _walker_obj = _walker(eng, "p1", "Chandra")
    eng.activate_ability(p1, _walker_obj, 0)
    eng.resolve_until_stable()
    assert len(p1.hand) == before


def test_ceaseless_searblades_pumps_for_an_elemental_ability_only():
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    searblades = _named(eng, "Ceaseless Searblades")
    hound = _named(eng, "Fiery Hellhound")  # an Elemental
    sorcerer = _named(eng, "Prodigal Sorcerer")  # not an Elemental
    eng.recompute_continuous_effects()
    base = searblades.power

    _ping(eng, "p1", sorcerer)
    eng.recompute_continuous_effects()
    assert searblades.power == base

    p1.mana_pool.add_many({"R": 1})
    eng.activate_ability(p1, hound, 0)
    eng.resolve_until_stable()
    eng.recompute_continuous_effects()
    assert searblades.power == base + 1


def test_sarkhans_whelp_pings_for_a_sarkhan_ability_only():
    eng = _engine()
    p1, p2 = eng.state.player_by_id("p1"), eng.state.player_by_id("p2")
    _named(eng, "Sarkhan's Whelp")
    chandra = _walker(eng, "p1", "Chandra")
    sarkhan = _named(eng, "Sarkhan, Fireblood")
    sarkhan.counters["loyalty"] = 3

    eng.activate_ability(p1, chandra, 0)
    eng.resolve_until_stable()
    assert eng.state.pending_choice is None  # a Chandra's ability opens no Whelp target prompt
    assert p2.life == 20

    sarkhan.counters["loyalty"] = 3
    eng.activate_ability(p1, sarkhan, 0)
    eng.resolve_until_stable()
    choice = eng.state.pending_choice
    assert choice is not None and choice["kind"] == "trigger_target"  # the Whelp's "any target" prompt
    eng.resolve_pending_choice("p2")
    eng.resolve_until_stable()
    assert p2.life == 20 - ONE_TRIGGER
