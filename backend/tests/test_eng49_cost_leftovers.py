"""ENG-49 — `costs.parse_activation_cost` no longer drops cost fragments.

A cost part no recognizer read used to vanish, so the ability was claimed
cheaper than printed (Fauna Shaman searched without discarding, Grim
Lavamancer pinged without exiling, Rootha copied without bouncing). The
recognizers now live in one grammar both sides share
(`parser/oracle/catalogue/cost_text.scan_cost_text`): it reports the words
nothing read, the segmenter leaves such an ability unclaimed, and the binder
refuses to bind one. The audit also widened the grammar so the common shapes
are *charged* rather than refused: "Sacrifice X/N `<type>s`", "an artifact or
creature", typed and random discards, graveyard exiles, "Exile this card from
your graveyard", "Return ~ to its owner's hand", counters removed "from ~".

Reference: mtg_analyzer/parser/oracle/catalogue/cost_text.py,
mtg_analyzer/game/costs.py (`_parse_text`), mtg_analyzer/game/engine/
activation_mixin.py, RULE 601.2b/602.1/602.2b/701.8d.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.costs import SACRIFICE_COUNT_X, parse_activation_cost
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.cost_text import scan_cost_text
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.services.card_database import CardDatabase, DEFAULT_DB_PATH

pytestmark = pytest.mark.skipif(
    not DEFAULT_DB_PATH.exists(), reason="card cache not present in this environment"
)


def _card(name: str):
    card = CardDatabase(DEFAULT_DB_PATH).get_card(name)
    if card is None:
        pytest.skip(f"{name!r} not present in the local card cache")
    return card


def engine():
    filler = _card("Grizzly Bears")
    eng = GameEngine.new_game(
        [("p1", "Alice", [filler] * 10), ("p2", "Bob", [filler] * 10)],
        starting_hand=0,
    )
    while eng.state.current_phase != "precombat_main":
        eng.advance_step()
    return eng, eng.state.player_by_id("p1")


def battlefield(eng, name, controller="p1"):
    obj = GameObject(_card(name), owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    eng.state.add_to_battlefield(obj)
    return obj


def in_zone(eng, name, zone, controller="p1"):
    obj = GameObject(_card(name), owner_id=controller, zone=zone)
    bind_from_catalogue(obj)
    player = eng.state.player_by_id(controller)
    {Zone.HAND: player.hand, Zone.GRAVEYARD: player.graveyard}[zone].append(obj)
    return obj


def resolve(eng):
    while eng.state.stack:
        eng.rules.resolve_top_of_stack()


# ---------------------------------------------------------------------------
# The grammar reports leftovers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("text", [
    "{1}, {T}, Sacrifice X lands",
    "{2}{B}, Sacrifice an artifact or creature",
    "{1}, Remove a fade counter from ~",
    "{G}, {T}, Discard a creature card",
    "{1}, Discard a card at random",
    "{R}, {T}, Exile two cards from your graveyard",
    "{B}, Exile this card from your graveyard",
    "{2}, Return ~ to its owner's hand",
    "Teleport — {3}{W}",
    "pay {x}",
])
def test_fully_read_costs_have_no_leftover(text):
    assert scan_cost_text(text).leftover is None
    assert parse_activation_cost(text).unrecognized is None


@pytest.mark.parametrize("text, leftover", [
    ("{1}, Discard a historic card", "Discard a historic card"),
    ("{3}, {T}, Sacrifice a creature of the chosen type", "of the chosen type"),
    ("{U}, Say your middle name", "Say your middle name"),
])
def test_unread_fragments_are_reported(text, leftover):
    assert parse_activation_cost(text).unrecognized == leftover


def test_parser_leaves_an_ability_with_a_leftover_unclaimed():
    """Sanctum Spirit's "Discard a historic card" is a filter the cost
    grammar doesn't read — the card stays UNMODELED rather than being
    claimed with a free activation."""
    assert parse_oracle(_card("Sanctum Spirit")).coverage == "UNMODELED"


def test_binder_refuses_a_hand_authored_cost_it_cannot_read():
    from mtg_analyzer.parser.oracle.spec import AbilitySpec, EffectSpec
    from mtg_analyzer.game.card_registry import core

    eng, _ = engine()
    name = "Grizzly Bears"
    saved = core._REGISTRY.get(name.lower())
    core._REGISTRY[name.lower()] = lambda: [AbilitySpec(
        "activated", [EffectSpec("draw", {"count": 1})],
        cost={"text": "{T}, Sacrifice a creature of the chosen type"},
    )]
    try:
        bear = battlefield(eng, name)
    finally:
        if saved is None:
            core._REGISTRY.pop(name.lower(), None)
        else:
            core._REGISTRY[name.lower()] = saved
    assert bear.activated_abilities == []


# ---------------------------------------------------------------------------
# The widened grammar is charged
# ---------------------------------------------------------------------------


def test_copper_leaf_angel_sacrifices_x_lands_for_x_counters():
    eng, p1 = engine()
    angel = battlefield(eng, "Copper-Leaf Angel")
    lands = [battlefield(eng, "Forest") for _ in range(3)]
    assert angel.activated_abilities[0].cost.sacrifice_count == (SACRIFICE_COUNT_X, "land")

    offer = next(
        a for a in eng.legal_actions(p1)
        if a.get("type") == "activate_ability" and a["instance_id"] == angel.instance_id
    )
    assert offer["has_x"] and offer["max_x"] == 3

    eng.activate_ability(p1, angel, 0, x=2)
    resolve(eng)

    assert sum(land.zone == Zone.GRAVEYARD for land in lands) == 2
    assert angel.counters.get("+1/+1", 0) == 2


def test_sacrifice_x_beyond_the_pool_is_refused():
    eng, p1 = engine()
    angel = battlefield(eng, "Copper-Leaf Angel")
    battlefield(eng, "Forest")
    ability = angel.activated_abilities[0]
    assert not eng._can_pay_activation_cost(p1, angel, ability.cost, x=2)


def test_fauna_shaman_must_discard_a_creature_card():
    eng, p1 = engine()
    shaman = battlefield(eng, "Fauna Shaman")
    ability = shaman.activated_abilities[0]
    p1.mana_pool.add("G", 1)
    in_zone(eng, "Lightning Bolt", Zone.HAND)
    assert not eng._can_pay_activation_cost(p1, shaman, ability.cost, x=0)

    bear = in_zone(eng, "Grizzly Bears", Zone.HAND)
    assert eng._can_pay_activation_cost(p1, shaman, ability.cost, x=0)
    eng.activate_ability(p1, shaman, 0)
    assert bear.zone == Zone.GRAVEYARD
    assert [c.name for c in p1.hand] == ["Lightning Bolt"]


def test_grim_lavamancer_exiles_two_graveyard_cards():
    eng, p1 = engine()
    lavamancer = battlefield(eng, "Grim Lavamancer")
    p1.mana_pool.add("R", 1)
    in_zone(eng, "Grizzly Bears", Zone.GRAVEYARD)
    ability = lavamancer.activated_abilities[0]
    assert not eng._can_pay_activation_cost(p1, lavamancer, ability.cost, x=0)

    in_zone(eng, "Lightning Bolt", Zone.GRAVEYARD)
    opponent = eng.state.player_by_id("p2")
    eng.activate_ability(p1, lavamancer, 0, targets=[opponent])

    assert p1.graveyard == []
    assert len(p1.exile) == 2


def test_graveyard_ability_exiles_its_own_source():
    """Adorned Crocodile's Renew: activated from the graveyard, paid by
    exiling the card itself — once."""
    eng, p1 = engine()
    croc = in_zone(eng, "Adorned Crocodile", Zone.GRAVEYARD)
    bear = battlefield(eng, "Grizzly Bears")
    p1.mana_pool.add("B", 2)
    ability = croc.activated_abilities[0]
    assert ability.cost.graveyard_zone and ability.cost.exile_self

    eng.activate_ability(p1, croc, 0, targets=[bear])
    resolve(eng)

    assert croc.zone == Zone.EXILE
    assert bear.counters.get("+1/+1", 0) == 1
    assert not eng._can_pay_activation_cost(p1, croc, ability.cost, x=0)


def test_rootha_returns_itself_to_hand_as_the_cost():
    eng, p1 = engine()
    rootha = battlefield(eng, "Rootha, Mercurial Artist")
    p1.mana_pool.add("C", 2)
    eng.activate_ability(p1, rootha, 0)
    assert rootha in p1.hand


def test_either_type_sacrifice_accepts_both_halves_and_nothing_else():
    eng, p1 = engine()
    cost = parse_activation_cost("{1}, Sacrifice an artifact or creature")
    assert cost.sacrifice == "artifact_or_creature"
    bear = battlefield(eng, "Grizzly Bears")
    forest = battlefield(eng, "Forest")
    assert eng._matches_sacrifice_type(bear, cost.sacrifice)
    assert not eng._matches_sacrifice_type(forest, cost.sacrifice)


def test_random_discard_cost_is_random_not_chosen(monkeypatch):
    eng, p1 = engine()
    cost = parse_activation_cost("{1}, Discard a card at random")
    assert cost.discard == 1 and cost.discard_random
    calls = []
    monkeypatch.setattr(eng.rules, "discard_random", lambda player, n, cause=None: calls.append(n))
    in_zone(eng, "Grizzly Bears", Zone.HAND)
    source = battlefield(eng, "Grizzly Bears")
    p1.mana_pool.add("C", 1)
    eng._pay_activation_cost(p1, source, cost, x=0)
    assert calls == [1]
