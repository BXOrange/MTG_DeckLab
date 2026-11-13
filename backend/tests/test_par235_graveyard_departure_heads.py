"""PAR-235 -- "is put into a graveyard from the battlefield" trigger heads.

* RULE 400.3: a card goes to its *owner's* graveyard, so "an opponent's graveyard" scopes the DIES event's owner, never
  the dying permanent's controller (a stolen creature dying goes to its owner).
* RULE 700.4: "dies" is "is put into a graveyard from the battlefield"; "any graveyard" / "a player's graveyard" are the
  unscoped spelling and "from play" the pre-2011 one.
* RULE 603.10a: "an attacking Kithkin or Elf" reads the combat status the permanent last had.
* RULE 603.2c: "3 or more artifacts and/or creatures you control are put into a graveyard" is one batch.
* The "A from the battlefield or B card from anywhere other than the battlefield" compound fires once per card.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.models.game.game_state import GameState
from mtg_analyzer.models.game.player import Player
from mtg_analyzer.parser.oracle import parse_oracle
from mtg_analyzer.parser.oracle.catalogue.object_trigger_head import parse_object_trigger_head

from tests.test_par119_object_trigger_head import _named

# ---------------------------------------------------------------------------
# Grammar
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "cond, owner",
    [
        ("a creature is put into an opponent's graveyard from the battlefield", "not_you"),
        ("an artifact is put into an opponent's graveyard from the battlefield", "not_you"),
        ("another artifact is put into your graveyard from the battlefield", "you"),
    ],
)
def test_owner_scoped_departure_head(cond, owner):
    head = parse_object_trigger_head(cond)
    assert head is not None and head.event == "DIES"
    assert head.condition["owner"] == owner and head.condition["controller"] == "any"


def test_attacking_subtype_alternation():
    head = parse_object_trigger_head("an attacking kithkin or elf is put into your graveyard from the battlefield")
    assert head is not None and head.condition["filter"] == {"subtype_any": ["kithkin", "elf"], "attacking": True}


def test_batch_head():
    head = parse_object_trigger_head("3 or more artifacts and/or creatures you control are put into a graveyard from the battlefield")
    assert head is not None and head.event == "EVENT_BATCH"
    assert head.trigger["batch"] == {"of": "DIES", "min": 3}
    assert head.condition["controller"] == "you"


@pytest.mark.parametrize(
    "cond",
    [
        "~ is put into an opponent's graveyard from the battlefield",
        "a creature is put into an opponent's graveyard from your library",
        "a creature is put into an opponent's library from the battlefield",
    ],
)
def test_near_misses_are_not_claimed(cond):
    head = parse_object_trigger_head(cond)
    assert head is None or head.event != "DIES"


@pytest.mark.parametrize(
    "name",
    [
        "Grim Feast", "Liability", "Kithkin Mourncaller",
    ],
)
def test_real_cards_are_modeled(name):
    assert parse_oracle(_named(name)).modeled is True


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------


def _game():
    players = [Player(id=f"p{i}", name=f"P{i}", life=20) for i in (1, 2)]
    state = GameState(players=players)
    engine = GameEngine(state)
    for player in players:
        for i in range(6):
            player.library.append(GameObject(Card(id=f"{player.id}L{i}", name=f"L{i}", type_line="Land"),
                                             owner_id=player.id, zone=Zone.LIBRARY))
    return engine, state


def _permanent(state, oracle="", name="Thing", types="Enchantment", owner="p1", controller=None, token=False):
    creature = "Creature" in types
    card = Card(id=name + owner, name=name, type_line=types, oracle_text=oracle, is_creature=creature,
                power=2 if creature else None, toughness=2 if creature else None)
    obj = GameObject(card, owner_id=owner, zone=Zone.BATTLEFIELD)
    obj.controller_id = controller or owner
    obj.is_token = token
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    obj.summoning_sick = False
    return obj


def _settle(engine, state):
    engine.resolve_until_stable()
    for _ in range(10):
        if not state.pending_choice:
            return
        engine.rules.resolve_choice("do")
        engine.resolve_until_stable()


def _kill(engine, obj):
    engine.rules.destroy(obj)
    engine.resolve_until_stable()


def test_opponent_graveyard_scopes_the_owner_not_the_controller():
    engine, state = _game()
    _permanent(state, "Whenever a creature is put into an opponent's graveyard from the battlefield, you gain 1 life.",
               name="Feast")
    stolen = _permanent(state, types="Creature — Bear", name="Stolen", owner="p2", controller="p1")
    _kill(engine, stolen)
    assert state.player_by_id("p1").life == 21  # p2 owns it, so it went to an opponent's graveyard
    mine_stolen = _permanent(state, types="Creature — Bear", name="Lent", owner="p1", controller="p2")
    _kill(engine, mine_stolen)
    assert state.player_by_id("p1").life == 21  # it went to my own graveyard
    theirs = _permanent(state, types="Creature — Bear", name="Theirs", owner="p2")
    _kill(engine, theirs)
    assert state.player_by_id("p1").life == 22


def test_nontoken_permanent_in_any_graveyard_liability_hits_the_owner():
    engine, state = _game()
    _permanent(state, name="Liability", oracle=_named("Liability").oracle_text)
    token = _permanent(state, types="Creature — Bear", name="Tok", owner="p2", token=True)
    _kill(engine, token)
    assert (state.player_by_id("p1").life, state.player_by_id("p2").life) == (20, 20)
    stolen = _permanent(state, types="Creature — Bear", name="Stolen", owner="p2", controller="p1")
    _kill(engine, stolen)
    assert (state.player_by_id("p1").life, state.player_by_id("p2").life) == (20, 19)  # "that player" owns the card


def test_attacking_kithkin_uses_last_known_combat_status():
    engine, state = _game()
    _permanent(state, "Whenever an attacking Kithkin or Elf is put into your graveyard from the battlefield, you gain 3 life.",
               name="Mourn")
    idle = _permanent(state, types="Creature — Kithkin Scout", name="Idle")
    _kill(engine, idle)
    assert state.player_by_id("p1").life == 20
    attacker = _permanent(state, types="Creature — Elf Scout", name="Attacker")
    attacker.attacking = True
    _kill(engine, attacker)
    assert state.player_by_id("p1").life == 23
    foreign = _permanent(state, types="Creature — Elf Scout", name="Foreign", owner="p2")
    foreign.attacking = True
    _kill(engine, foreign)
    assert state.player_by_id("p1").life == 23


def test_batch_fires_once_per_simultaneous_event():
    engine, state = _game()
    _permanent(state, "Whenever 3 or more artifacts and/or creatures you control are put into a graveyard from the "
                      "battlefield, you gain 1 life.", name="Batch")
    objs = [_permanent(state, types="Creature — Bear", name=f"B{i}") for i in range(4)]
    with state.simultaneous():
        for obj in objs:
            engine.rules.destroy(obj)
    engine.resolve_until_stable()
    assert state.player_by_id("p1").life == 21
    two = [_permanent(state, types="Creature — Bear", name=f"C{i}") for i in range(2)]
    with state.simultaneous():
        for obj in two:
            engine.rules.destroy(obj)
    engine.resolve_until_stable()
    assert state.player_by_id("p1").life == 21


COMPOUND = ("Whenever another artifact is put into your graveyard from the battlefield or an artifact card is put into "
            "your graveyard from anywhere other than the battlefield, you gain 1 life.")


def test_compound_fires_once_per_card():
    engine, state = _game()
    _permanent(state, COMPOUND, name="Watcher")
    on_board = _permanent(state, types="Artifact", name="Gadget")
    _kill(engine, on_board)
    assert state.player_by_id("p1").life == 21  # one trigger, not two
    p1 = state.player_by_id("p1")
    card = GameObject(Card(id="milled", name="Milled", type_line="Artifact"), owner_id="p1", zone=Zone.LIBRARY)
    p1.library.append(card)
    state.resync_graveyard_watch()  # a real game had the card from the start
    engine.rules.mill(p1, 1)
    state.announce_graveyard_arrivals()  # an SBA sweep closes the scope (RULE 704.3)
    engine.resolve_until_stable()
    assert p1.life == 22


@pytest.mark.parametrize(
    "name",
    [
        "Lurking Skirge", "Magus of the Bridge", "Seer of Stolen Sight", "Ulrich's Kindred", "Ultron the Annihilator",
        "Ultron's Auxiliary", "Viridian Revel",
    ],
)
def test_newly_claimed_cards_are_modeled(name):
    assert parse_oracle(_named(name)).modeled is True


def test_viridian_revel_ignores_who_controlled_the_artifact():
    engine, state = _game()
    _permanent(state, _named("Viridian Revel").oracle_text, name="Revel")
    p1 = state.player_by_id("p1")
    before = len(p1.hand)
    mine_lent = _permanent(state, types="Artifact", name="Lent", owner="p1", controller="p2")
    _kill(engine, mine_lent)
    _settle(engine, state)
    assert len(p1.hand) == before  # it went to my own graveyard
    stolen = _permanent(state, types="Artifact", name="Stolen", owner="p2", controller="p1")
    _kill(engine, stolen)
    _settle(engine, state)
    assert len(p1.hand) == before + 1


def test_grim_feast_gains_the_dead_creatures_toughness():
    engine, state = _game()
    _permanent(state, "Whenever a creature is put into an opponent's graveyard from the battlefield, you gain life "
                      "equal to its toughness.", name="Feast")
    victim = _permanent(state, types="Creature — Bear", name="Victim", owner="p2")
    victim.card.toughness = 5
    _kill(engine, victim)
    assert state.player_by_id("p1").life == 25


def test_ulrichs_kindred_targets_only_attacking_wolves_or_werewolves():
    # PAR-235 side effect: "target attacking Wolf or Werewolf" distributes "attacking" over the subtype alternation, so
    # the target must be attacking AND a Wolf or a Werewolf (RULE 115.1 / 506.4); then it gains indestructible.
    from mtg_analyzer.game.targeting import effects_target_specs, legal_targets

    engine, state = _game()
    kindred = _permanent(state, "Trample\n{3}{G}: Target attacking Wolf or Werewolf gains indestructible until end of turn.",
                         name="Ulrich's Kindred", types="Creature — Wolf")
    wolf = _permanent(state, name="Wolf", types="Creature — Wolf")
    werewolf = _permanent(state, name="Werewolf", types="Creature — Human Werewolf")
    bear = _permanent(state, name="Bear", types="Creature — Bear")
    idle_wolf = _permanent(state, name="Idle Wolf", types="Creature — Wolf")
    for attacker in (wolf, werewolf, bear):
        attacker.attacking = True
    spec = effects_target_specs(kindred.activated_abilities[0].effects)[0]
    legal = {o["instance_id"] for o in legal_targets(state, "p1", spec, source=kindred)}
    assert legal == {wolf.instance_id, werewolf.instance_id}
    assert idle_wolf.instance_id not in legal and bear.instance_id not in legal
