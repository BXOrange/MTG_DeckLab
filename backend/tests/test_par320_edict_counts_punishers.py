"""PAR-320: edict counts (X / half / a third), punishers ("unless they pay / discard") and "if they can't" riders.

Parse shapes plus real-engine execution: three players with different boards, choices in APNAP order and sacrifices
together (RULE 101.4 / 608.2e), RULE 107.1a rounding per player, a punisher paid vs declined (RULE 118.12), a rider that
fires only for the player who could not sacrifice (RULE 701.17a), and a bot chooser answering from its own view.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue, build_effects
from mtg_analyzer.game.effects.core import GameContext
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.game.phases import GamePhase, GameStep
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.services.bots import create_bot
from mtg_analyzer.services.card_database import CardDatabase, DEFAULT_DB_PATH
from mtg_analyzer.services.game_session import GameSessionManager

GAINED = (
    "Tectonic Break", "Zodiark, Umbral God", "Rakdos the Defiler", "Lord Xander, the Collector", "Aether Barrier",
    "Spelltithe Enforcer", "Rishadan Cutpurse", "Rishadan Footpad", "Rishadan Brigand", "Bebop & Rocksteady",
    "Cruel Reality", "Doom Foretold", "Eldrazi Monument", "Lord of the Pit", "Liege of the Pit", "Rust Elemental",
)


def _real(name):
    card = CardDatabase(DEFAULT_DB_PATH).get_card(name)
    if card is None:
        pytest.skip("card cache not available")
    return card


def _card(name, type_line="Creature — Test", oracle="", **kw):
    return Card(id=name, name=name, type_line=type_line, oracle_text=oracle, **kw)


def _put(eng, card, controller):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.controller_id = controller
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    eng.state.add_to_battlefield(obj)
    return obj


def _creature(eng, name, controller, **kw):
    return _put(eng, _card(name, is_creature=True, power=2, toughness=2, **kw), controller)


def _land(eng, name, controller):
    return _put(eng, _card(name, type_line="Land", is_land=True), controller)


def _three(active="p1"):
    eng = GameEngine.new_game([("p1", "A", []), ("p2", "B", []), ("p3", "C", [])], starting_life=20, starting_hand=0)
    eng.state.active_player_index = next(i for i, p in enumerate(eng.state.players) if p.id == active)
    eng.state.current_step = "main1"
    return eng


def _ids(choice):
    return {o["instance_id"] for o in choice["options"] if "instance_id" in o}


def _answer(eng, obj):
    eng.resolve_pending_choice(str(obj.instance_id))
    eng.resolve_until_stable()


def _resolve_spell(eng, text, controller="p1", x=None, type_line="Sorcery", targets=None):
    """Resolve a spell's parsed effects as ``controller`` (no mana needed for the rules under test)."""
    spell = _card("Spell", type_line=type_line, is_sorcery=True, oracle=text)
    assert parse_oracle(spell).modeled, text
    obj = GameObject(spell, owner_id=controller, zone=Zone.STACK)
    obj.controller_id = controller
    bind_from_catalogue(obj)
    effects = build_effects([e for s in parse_oracle(spell).specs for e in s.effects], obj)
    if x is not None:
        eng.rules._substitute_x(effects, x)
    for effect in effects:
        effect.apply(GameContext(eng.state, eng.rules), targets)
    eng.resolve_until_stable()
    return obj


# -- parser -----------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("name", GAINED)
def test_real_cards_are_modeled(name):
    assert parse_oracle(_real(name)).modeled is True


@pytest.mark.parametrize("clause, divisor, up, flt", [
    ("each player sacrifices half the creatures they control of their choice, rounded down", 2, False, None),
    ("target opponent sacrifices half the nonland permanents they control of their choice, rounded up", 2, True,
     {"without_card_type": "land"}),
    ("each opponent sacrifices a third of the non-demon permanents they control of their choice, rounded up", 3, True,
     {"without_subtype": "demon"}),
])
def test_fraction_edicts_carry_divisor_and_the_printed_rounding(clause, divisor, up, flt):
    card = _card("Zed", type_line="Sorcery", is_sorcery=True, oracle=f"{clause[0].upper()}{clause[1:]}.")
    params = parse_oracle(card).specs[0].effects[0].params
    assert params["pool_fraction"] == {"divisor": divisor, "round_up": up}
    assert params.get("object_filter") == flt


@pytest.mark.parametrize("text", [
    "Each player sacrifices half the creatures they control of their choice.",  # no printed rounding: not claimed
    "Each player sacrifices half the creatures you control of their choice, rounded down.",  # two different players
    "Each opponent sacrifices a permanent of their choice unless you pay {1}.",  # payer is not the sacrificer
    "You sacrifice a permanent unless they discard a card.",
])
def test_near_misses_are_not_claimed(text):
    assert not parse_oracle(_card("Zed", type_line="Sorcery", is_sorcery=True, oracle=text)).modeled


# -- half / a third: counted per player over their own pool, chosen in APNAP order, sacrificed together ---------------


def _board(eng):
    return {
        "p1": [_creature(eng, f"A{i}", "p1") for i in range(5)],
        "p2": [_creature(eng, f"B{i}", "p2") for i in range(3)],
        "p3": [_creature(eng, "C0", "p3")],
    }


@pytest.mark.parametrize("rounding, expected", [("down", {"p1": 2, "p2": 1, "p3": 0}), ("up", {"p1": 3, "p2": 2, "p3": 1})])
def test_half_rounds_per_player_with_different_boards_in_apnap_order(rounding, expected):
    eng = _three(active="p2")
    board = _board(eng)
    _resolve_spell(eng, f"Each player sacrifices half the creatures they control of their choice, rounded {rounding}.")
    order = []
    while eng.state.pending_choice is not None:
        choice = eng.state.pending_choice
        order.append(choice["player_id"])
        # RULE 101.4: nothing leaves the battlefield until every player has chosen (RULE 608.2e)
        assert all(o.zone is Zone.BATTLEFIELD for objs in board.values() for o in objs)
        pool = [o for o in board[choice["player_id"]] if o.instance_id in _ids(choice)]
        _answer(eng, pool[0])
    for pid, n in expected.items():
        assert sum(o.zone is Zone.GRAVEYARD for o in board[pid]) == n, pid
    # APNAP: p2, then p3, then p1 -- a player whose whole pool is taken (p3's lone creature) has nothing to decide
    assert order == [p for p in ("p2", "p3", "p1") for _ in range(expected[p] if expected[p] < len(board[p]) else 0)]


def test_a_third_counts_over_the_filtered_pool_only():
    eng = _three()
    creatures = [_creature(eng, f"A{i}", "p1") for i in range(7)]
    lands = [_land(eng, f"L{i}", "p1") for i in range(6)]
    _resolve_spell(eng, "Target opponent sacrifices a third of the lands they control of their choice, rounded down.",
                   controller="p2", targets=[eng.state.player_by_id("p1")])
    assert eng.state.pending_choice["player_id"] == "p1"
    assert _ids(eng.state.pending_choice) == {o.instance_id for o in lands}  # six lands -> two picks; creatures aren't in
    for _ in range(2):
        _answer(eng, next(o for o in lands if o.zone is Zone.BATTLEFIELD))
    assert sum(o.zone is Zone.GRAVEYARD for o in lands) == 2 and all(c.zone is Zone.BATTLEFIELD for c in creatures)


def test_controller_half_sacrifice_is_the_controllers_own_pool():
    eng = _three()
    mine = [_creature(eng, f"A{i}", "p1") for i in range(3)] + [_creature(eng, "Dem", "p1", type_line="Creature — Demon")]
    theirs = [_creature(eng, f"B{i}", "p2") for i in range(4)]
    _resolve_spell(eng, "Sacrifice half the non-demon permanents you control, rounded up.")
    assert eng.state.pending_choice["player_id"] == "p1"
    assert _ids(eng.state.pending_choice) == {o.instance_id for o in mine[:3]}  # the Demon is not in the pool
    for _ in range(2):  # half of 3, rounded up
        _answer(eng, next(o for o in mine[:3] if o.zone is Zone.BATTLEFIELD))
    assert sum(o.zone is Zone.GRAVEYARD for o in mine) == 2
    assert all(o.zone is Zone.BATTLEFIELD for o in theirs)


def test_discard_half_the_hand_rounds_down_for_the_chosen_opponent():
    eng = _three()
    p2 = eng.state.player_by_id("p2")
    for i in range(5):
        obj = GameObject(_card(f"H{i}", type_line="Sorcery"), owner_id="p2", zone=Zone.HAND)
        p2.hand.append(obj)
    _resolve_spell(eng, "Target opponent discards half the cards in their hand, rounded down.", targets=[p2])
    for _ in range(2):
        choice = eng.state.pending_choice
        assert choice["player_id"] == "p2"
        _answer(eng, next(o for o in p2.hand if o.instance_id in _ids(choice)))
    assert len(p2.hand) == 3


def test_x_is_the_spells_announced_x():
    eng = _three()
    lands = {p: [_land(eng, f"{p}L{i}", p) for i in range(4)] for p in ("p1", "p2", "p3")}
    _resolve_spell(eng, "Each player sacrifices x lands of their choice.", x=2)
    while eng.state.pending_choice is not None:
        choice = eng.state.pending_choice
        pool = [o for o in lands[choice["player_id"]] if o.instance_id in _ids(choice)]
        _answer(eng, pool[0])
    assert all(sum(o.zone is Zone.GRAVEYARD for o in objs) == 2 for objs in lands.values())


# -- punisher: the asked player decides (RULE 118.12) -------------------------------------------------------------------


def test_punisher_discard_paid_by_one_opponent_and_declined_by_the_other():
    eng = _three()
    p2_creature = _creature(eng, "B0", "p2")
    p3_creature = _creature(eng, "C0", "p3")
    for pid in ("p2", "p3"):
        eng.state.player_by_id(pid).hand.append(GameObject(_card(f"Card-{pid}", type_line="Sorcery"), owner_id=pid, zone=Zone.HAND))
    _resolve_spell(eng, "Each opponent sacrifices a creature of their choice unless they discard a card.")
    asked = []
    while eng.state.pending_choice is not None:
        choice = eng.state.pending_choice
        asked.append(choice["player_id"])
        assert choice["kind"] == "pay_cost_then"
        eng.resolve_pending_choice("pay" if choice["player_id"] == "p2" else "decline")
        eng.resolve_until_stable()
    assert asked == ["p2", "p3"]
    assert p2_creature.zone is Zone.BATTLEFIELD and len(eng.state.player_by_id("p2").hand) == 0  # paid: discarded instead
    assert p3_creature.zone is Zone.GRAVEYARD and len(eng.state.player_by_id("p3").hand) == 1  # declined: sacrificed


def test_punisher_player_who_cannot_pay_is_not_asked_and_sacrifices():
    eng = _three()
    victim = _creature(eng, "B0", "p2")  # p2 has no card to discard
    _resolve_spell(eng, "Each opponent sacrifices a creature of their choice unless they discard a card.")
    assert eng.state.pending_choice is None and victim.zone is Zone.GRAVEYARD


def _cast_creature_as(eng, pid):
    """``pid`` casts a creature spell, so a "whenever a player casts a creature spell" trigger sees their cast."""
    bear = GameObject(_card("Bear", type_line="Creature — Bear", is_creature=True, power=2, toughness=2,
                            mana_cost_string="{1}"), owner_id=pid, zone=Zone.HAND)
    bind_from_catalogue(bear)
    player = eng.state.player_by_id(pid)
    player.hand.append(bear)
    player.mana_pool.add_many({"C": 1})  # pays the Bear itself; the Barrier's {1} must come from a land
    eng.cast_spell(player, bear)
    eng.resolve_until_stable()


def _barrier_board(with_mana):
    eng = _three(active="p1")
    eng.begin_turn()  # a real turn, so the caster has priority in a main phase
    eng.state.current_step = "main1"
    caster = eng.state.active_player.id
    owner = "p3" if caster != "p3" else "p2"
    _put(eng, _real("Aether Barrier"), owner)  # the barrier's controller is not the one asked: the caster is
    fodder = [_creature(eng, f"R{i}", caster) for i in range(2)]
    if with_mana:
        _put(eng, _real("Forest"), caster)
    return eng, caster, fodder


@pytest.mark.parametrize("answer, sacrificed", [("pay", 0), ("decline", 1)])
def test_event_player_punisher_paid_vs_declined(answer, sacrificed):
    eng, caster, fodder = _barrier_board(with_mana=True)
    _cast_creature_as(eng, caster)
    choice = eng.state.pending_choice
    assert choice["kind"] == "pay_cost_then" and choice["player_id"] == caster
    eng.resolve_pending_choice(answer)
    eng.resolve_until_stable()
    if sacrificed:
        choice = eng.state.pending_choice
        assert choice["player_id"] == caster
        _answer(eng, fodder[0])
    assert eng.state.pending_choice is None
    assert sum(o.zone is Zone.GRAVEYARD for o in fodder) == sacrificed


def test_event_player_punisher_that_cannot_pay_is_not_asked():
    eng, caster, fodder = _barrier_board(with_mana=False)
    _cast_creature_as(eng, caster)
    choice = eng.state.pending_choice
    assert choice["kind"] != "pay_cost_then" and choice["player_id"] == caster
    _answer(eng, fodder[1])
    assert fodder[1].zone is Zone.GRAVEYARD


# -- "if they can't": the rider is per player -----------------------------------------------------------------------


def _upkeep(eng, active):
    eng.state.active_player_index = next(i for i, p in enumerate(eng.state.players) if p.id == active)
    eng._run_step(GamePhase("beginning", []), GameStep("upkeep", gives_priority=True))
    eng.resolve_until_stable()


def test_cant_rider_fires_only_for_the_player_who_could_not_sacrifice():
    eng = _three()
    _put(eng, _real("Cruel Reality"), "p1")  # Aura: enchanted-player upkeep; the edict text is under test, not the attach
    eng.state.player_by_id("p2").life = 20
    eng.state.player_by_id("p3").life = 20
    aura_player = eng.state.player_by_id("p2")
    pw = _put(eng, _card("Walker", type_line="Planeswalker — Test"), "p3")
    for obj in eng.state.battlefield:
        if obj.name == "Cruel Reality":
            obj.attached_to = None
    # p2 has no creature or planeswalker; p3 has a planeswalker
    _resolve_spell(eng, "Target player sacrifices a creature or planeswalker of their choice. If they can't, they lose 5 life.",
                   targets=[aura_player])
    assert aura_player.life == 15  # could not sacrifice: loses 5
    _resolve_spell(eng, "Target player sacrifices a creature or planeswalker of their choice. If they can't, they lose 5 life.",
                   targets=[eng.state.player_by_id("p3")])
    if eng.state.pending_choice is not None:
        _answer(eng, pw)
    assert eng.state.player_by_id("p3").life == 20 and pw.zone is Zone.GRAVEYARD  # could sacrifice: no rider


def test_upkeep_cant_rider_names_the_active_player_and_the_controller_separately():
    eng = _three()
    _put(eng, _real("Doom Foretold"), "p1")
    p1, p2, p3 = (eng.state.player_by_id(p) for p in ("p1", "p2", "p3"))
    p1.library.extend(GameObject(_card(f"Lib{i}", type_line="Sorcery"), owner_id="p1", zone=Zone.LIBRARY) for i in range(3))
    p2_hand = GameObject(_card("Spare", type_line="Sorcery"), owner_id="p2", zone=Zone.HAND)
    p2.hand.append(p2_hand)
    _land(eng, "Forest", "p2")  # only a land: not a nonland permanent, so p2 can't sacrifice
    p1_life, p2_life = p1.life, p2.life
    _upkeep(eng, "p2")
    assert p2.life == p2_life - 2 and p2_hand not in p2.hand  # they discard and lose 2 life
    assert p1.life == p1_life + 2 and len(p1.hand) == 1  # "you gain 2 life" and "you draw a card" (not p2)
    assert len(p2.hand) == 0 and len(p3.hand) == 0
    assert any(o.is_token and o.controller_id == "p1" for o in eng.state.battlefield)  # "you create a 2/2 Knight"
    assert all(o.name != "Doom Foretold" for o in eng.state.battlefield)  # "then you sacrifice ~"
    assert p3.life == 20


def test_cant_rider_of_a_controller_sacrifice_excludes_the_source():
    eng = _three()
    lord = _put(eng, _real("Lord of the Pit"), "p1")
    life = eng.state.player_by_id("p1").life
    _upkeep(eng, "p1")  # no other creature: the source itself is not an eligible pick, so the rider fires
    assert lord.zone is Zone.BATTLEFIELD and eng.state.player_by_id("p1").life == life - 7
    other = _creature(eng, "Fodder", "p1")
    _upkeep(eng, "p1")
    if eng.state.pending_choice is not None:
        _answer(eng, other)
    assert other.zone is Zone.GRAVEYARD and eng.state.player_by_id("p1").life == life - 7


# -- a bot chooser answers from its own view --------------------------------------------------------------------------


def test_a_bot_answers_a_half_edict_from_its_own_view_and_legal_actions():
    land = Card(id="Forest", name="Forest", type_line="Basic Land — Forest", is_land=True)
    session = GameSessionManager().create_multiplayer(
        [{"player_id": p, "name": p, "library": [land] * 30} for p in ("p1", "p2", "p3")],
        mulligan_style="none", keep_history=False,
    )
    for p in ("p1", "p2", "p3"):
        session.apply_action({"type": "keep_hand", "bottom_instance_ids": []}, actor_id=p)
    eng = session.engine
    state = eng.state
    controller = state.active_player.id
    victim = "p3" if controller != "p3" else "p2"
    other = "p2" if victim == "p3" else "p3"
    mine = [_creature(eng, f"M{i}", victim) for i in range(5)]
    _put(eng, _card("Wall", type_line="Artifact"), victim)
    elsewhere = _creature(eng, "Other", other)
    spell = _card("Edict", type_line="Sorcery", is_sorcery=True,
                  oracle="Target player sacrifices half the creatures they control of their choice, rounded down.")
    assert parse_oracle(spell).modeled
    obj = GameObject(spell, owner_id=controller, zone=Zone.STACK)
    obj.controller_id = controller
    bind_from_catalogue(obj)
    for effect in build_effects([e for s in parse_oracle(spell).specs for e in s.effects], obj):
        effect.apply(GameContext(state, eng.rules), [state.player_by_id(victim)])
    for _ in range(2):  # half of five, rounded down
        assert state.pending_choice["player_id"] == victim
        assert not [act for act in session.legal_actions(perspective=other) if act["type"] == "choose"]
        actions = session.legal_actions(perspective=victim)
        offered = {act["instance_id"] for act in actions if act["type"] == "choose"}
        assert offered <= {o.instance_id for o in mine} and offered
        action = create_bot("greedy", victim).decide(session.view(perspective=victim), actions)
        assert action["type"] == "choose"
        session.apply_action(action, actor_id=victim)
    assert sum(o.zone is Zone.GRAVEYARD for o in mine) == 2 and elsewhere.zone is Zone.BATTLEFIELD
