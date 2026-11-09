"""PAR-248 — "When ~ enters, exile all creature cards from your graveyard." (Zombie Mob, Yggdrasil, Rebirth Engine).

RULE 406.2 / 701.13a: an untargeted mass exile of the controller's own graveyard, narrowed to creature cards
(`exile_all_graveyards` with ``controller_only`` + ``card_type``). It never targets, so it works with no choice
and with an empty graveyard.
"""

from __future__ import annotations

from mtg_analyzer.game import combat
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.spec import EffectSpec

ORACLE = "When ~ enters, exile all creature cards from your graveyard."
EXPECTED = [EffectSpec("exile_all_graveyards", {"controller_only": True, "card_type": "creature", "track_exiled_with": True})]


def _source() -> Card:
    return Card(id="zm", name="Zombie Mob", type_line="Creature — Zombie", is_creature=True, power=1, toughness=1,
                oracle_text="When Zombie Mob enters, exile all creature cards from your graveyard.")


def test_clause_parses():
    assert match_clause("exile all creature cards from your graveyard") == EXPECTED


def test_siblings_keep_their_scope():
    assert match_clause("exile all graveyards") == [EffectSpec("exile_all_graveyards", {})]
    assert match_clause("exile each opponent's graveyard") == [EffectSpec("exile_all_graveyards", {"opponents_only": True})]


def test_card_modeled():
    assert parse_oracle(_source()).modeled


def _run(p1_gy, p2_gy):
    eng = GameEngine.new_game([("p1", "A", []), ("p2", "B", [])], starting_life=20, starting_hand=0)
    state = eng.state
    objs = {}
    for pid, cards in (("p1", p1_gy), ("p2", p2_gy)):
        for card in cards:
            o = GameObject(card, owner_id=pid, zone=Zone.GRAVEYARD)
            state.player_by_id(pid).graveyard.append(o)
            objs[card.name] = o
    src = GameObject(_source(), owner_id="p1", zone=Zone.BATTLEFIELD)
    bind_from_catalogue(src)
    state.add_to_battlefield(src)
    state.fire_event(GameEvent(EventType.ENTERS_BATTLEFIELD, instance_id=src.instance_id))
    eng.resolve_until_stable()
    return eng, state, objs


def test_enters_exiles_only_own_creature_cards():
    bear = Card(id="b", name="Bear", type_line="Creature — Bear", is_creature=True, power=2, toughness=2)
    spell = Card(id="s", name="Bolt", type_line="Instant", is_instant=True)
    foe = Card(id="f", name="Foe", type_line="Creature — Elf", is_creature=True, power=1, toughness=1)
    _, state, o = _run([bear, spell], [foe])
    p1, p2 = state.player_by_id("p1"), state.player_by_id("p2")
    assert o["Bear"] in p1.exile
    assert o["Bolt"] in p1.graveyard
    assert o["Foe"] in p2.graveyard
    assert state.pending_choice is None


def test_enters_with_empty_graveyard_is_a_noop():
    _, state, _ = _run([], [])
    assert not state.player_by_id("p1").exile
    assert state.pending_choice is None


# --- Yggdrasil: the entry exile is "exiled with" the source (RULE 607.2a) ------------------------------------

YGG_ORACLE = (
    "When Yggdrasil enters, exile all creature cards from your graveyard.\n"
    "{T}: Exile the top three cards of your library.\n"
    "{4}, {T}: Put a creature card exiled with Yggdrasil onto the battlefield under your control. "
    "It gains haste until end of turn. Activate only as a sorcery."
)


def _ygg_game(graveyard):
    from test_mec106_gift import _engine as gift_engine

    eng = gift_engine()
    state = eng.state
    p1 = state.player_by_id("p1")
    objs = []
    for card in graveyard:
        o = GameObject(card, owner_id="p1", zone=Zone.GRAVEYARD)
        p1.graveyard.append(o)
        objs.append(o)
    ygg = GameObject(
        Card(id="ygg", name="Yggdrasil, Rebirth Engine", type_line="Legendary Artifact Creature — Elk",
             is_creature=True, power=3, toughness=3, oracle_text=YGG_ORACLE),
        owner_id="p1", zone=Zone.BATTLEFIELD,
    )
    ygg.summoning_sick = False
    bind_from_catalogue(ygg)
    state.add_to_battlefield(ygg)
    state.fire_event(GameEvent(EventType.ENTERS_BATTLEFIELD, instance_id=ygg.instance_id))
    eng.resolve_until_stable()
    return eng, p1, ygg, objs


def _bear(name):
    return Card(id=name, name=name, type_line="Creature — Bear", is_creature=True, power=2, toughness=2)


def _reanimate(eng, p1, ygg):
    p1.mana_pool.add("C", 4)
    ygg.tapped = False
    eng.activate_ability(p1, ygg, ability_index=1)
    eng.resolve_until_stable()


def test_ygg_entry_exile_is_linked_and_return_ability_reanimates_with_haste():
    eng, p1, ygg, (bears,) = _ygg_game([_bear("Grizzly Bears")])
    assert bears.zone == Zone.EXILE
    _reanimate(eng, p1, ygg)
    assert eng.state.pending_choice is None
    assert bears.zone == Zone.BATTLEFIELD and bears.controller_id == "p1"
    eng.recompute_continuous_effects()
    assert combat.has(bears, "haste") and not combat.has(ygg, "haste")  # "it" is the returned card, not Yggdrasil


def test_ygg_top_three_exile_stays_reachable_and_noncreature_is_not_offered():
    eng, p1, ygg, (entry_bear,) = _ygg_game([_bear("Entry Bear")])
    p1.library.clear()
    top_bear = GameObject(_bear("Top Bear"), owner_id="p1", zone=Zone.LIBRARY)
    land = GameObject(Card(id="l", name="Plains", type_line="Basic Land — Plains", is_land=True),
                      owner_id="p1", zone=Zone.LIBRARY)
    filler = GameObject(Card(id="f", name="Filler", type_line="Land", is_land=True), owner_id="p1", zone=Zone.LIBRARY)
    p1.library.extend([filler, land, top_bear])  # top of library is the end of the list
    ygg.tapped = False
    eng.activate_ability(p1, ygg, ability_index=0)
    eng.resolve_until_stable()
    assert top_bear.zone == land.zone == Zone.EXILE
    # Two creature cards are linked now: the ability asks for one, never both, and never the land.
    _reanimate(eng, p1, ygg)
    choice = eng.state.pending_choice
    assert choice is not None
    offered = {str(o) for o in (choice.get("options") or choice.get("object_ids") or [])}
    assert str(land.instance_id) not in offered
    eng.resolve_pending_choice(str(top_bear.instance_id))
    eng.resolve_until_stable()
    assert top_bear.zone == Zone.BATTLEFIELD
    assert entry_bear.zone == Zone.EXILE and land.zone == Zone.EXILE


def test_ygg_entry_exile_that_does_not_reach_exile_is_not_linked():
    eng, p1, ygg, _ = _ygg_game([])
    bears = GameObject(_bear("Stays"), owner_id="p1", zone=Zone.GRAVEYARD)
    p1.graveyard.append(bears)
    eng.state.track_exiled_with(ygg, bears)  # not in exile: no link recorded
    assert bears.instance_id not in ygg.exiled_with_ids
