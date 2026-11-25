"""PAR-291 M5, RULE 701.13 / 406 / 108.3 / 601.2: "each opponent exiles cards from the top of their library until ..." and
the controller's cast riders (Fevered Suspicion, Dream Harvest, Tasha's Hideous Laughter, Krang & Shredder).

Real cards on a 3-player engine: every opponent digs their own library in turn order, a hit or the total mana value stops
the dig, a land adds 0, the controller (not the owner) casts what was exiled and a cast card goes to its owner's graveyard.
"""
import pytest

from test_par320_edict_counts_punishers import _three, _put, _real, _card
from mtg_analyzer.game.binding.core import bind_from_catalogue, build_effects
from mtg_analyzer.game.card_registry import is_card_covered
from mtg_analyzer.game.effects.core import GameContext
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle

CLAIMED = ("Fevered Suspicion", "Dream Harvest", "Tasha's Hideous Laughter", "Krang & Shredder")


@pytest.mark.parametrize("name", CLAIMED)
def test_real_cards_are_covered(name):
    assert is_card_covered(_real(name))


@pytest.mark.parametrize("text", [
    "Each opponent exiles cards from the top of their library until they exile a land card.",  # no row for a bare land
    "Each opponent exiles cards from the top of their library until they have exiled cards with total mana value 5 "
    "or greater. You may cast any number of spells from among those nonland cards without paying their mana costs.",
    "Each opponent exiles cards from the top of their library until they exile a nonland card. "
    "Until end of turn, you may cast cards exiled this way without paying their mana costs.",
    "Each player exiles cards from the top of their library until they exile a nonland card.",
    "Each opponent exiles cards from the top of your library until they exile a nonland card.",
])
def test_unsound_forms_stay_refused(text):
    assert not parse_oracle(_card("Neg", type_line="Sorcery", is_sorcery=True, oracle=text)).modeled


def _stack(eng, name, controller="p1"):
    obj = GameObject(_real(name), owner_id=controller, zone=Zone.STACK)
    obj.controller_id = controller
    bind_from_catalogue(obj)
    return obj


def _resolve(eng, obj):
    for spec in [s for s in parse_oracle(obj.card).specs if s.ability_kind in ("spell", "spell_effect", "triggered")]:
        for effect in build_effects(list(spec.effects), obj):
            effect.apply(GameContext(eng.state, eng.rules), None)
    eng.resolve_until_stable()


def _lib(eng, pid, *cards):
    """Put ``cards`` on the library of ``pid`` so that the first one listed is the top card."""
    objs = []
    player = eng.state.player_by_id(pid)
    for card in reversed(cards):
        obj = GameObject(card, owner_id=pid, zone=Zone.LIBRARY)
        obj.controller_id = pid
        player.library.append(obj)
        objs.append(obj)
    return list(reversed(objs))


def _land():
    return _card("Forest", type_line="Basic Land — Forest", is_land=True)


def _sorcery(name, mv):
    return _card(name, type_line="Sorcery", is_sorcery=True, oracle="You gain 2 life.",
                 mana_cost_string="{%d}" % mv, converted_mana_cost=mv)


def test_fevered_suspicion_digs_each_opponents_own_library_to_a_nonland_card():
    eng = _three()
    p2 = _lib(eng, "p2", _land(), _land(), _sorcery("Two", 2), _land())
    p3 = _lib(eng, "p3", _sorcery("Three", 3), _land())
    mine = _lib(eng, "p1", _sorcery("Mine", 1))
    _resolve(eng, _stack(eng, "Fevered Suspicion"))
    assert [o.zone for o in p2] == [Zone.EXILE, Zone.EXILE, Zone.EXILE, Zone.LIBRARY]
    assert [o.zone for o in p3] == [Zone.EXILE, Zone.LIBRARY]
    assert mine[0].zone is Zone.LIBRARY  # the controller never digs
    choice = eng.state.pending_choice
    assert choice["kind"] == "play_during_resolution" and choice["player_id"] == "p1"
    assert choice["repeat"] is True
    assert set(choice["instance_ids"]) == {p2[2].instance_id, p3[0].instance_id}  # the hits only, never the lands


def test_the_controller_casts_opponent_cards_and_they_go_to_their_owners_graveyards():
    eng = _three()
    p2 = _lib(eng, "p2", _sorcery("Two", 2))
    p3 = _lib(eng, "p3", _sorcery("Three", 3))
    me = eng.state.player_by_id("p1")
    _resolve(eng, _stack(eng, "Fevered Suspicion"))
    eng.play_resolution_card(me, p2[0])
    item = eng.state.stack[-1]
    assert item.controller_id == "p1" and item.obj is p2[0]  # RULE 601.2: the controller casts, the owner does not
    eng.resolve_until_stable()
    # "any number": the pool is offered again for the second card
    assert eng.state.pending_choice["kind"] == "play_during_resolution"
    eng.play_resolution_card(me, p3[0])
    eng.resolve_until_stable()
    assert p2[0] in eng.state.player_by_id("p2").graveyard  # RULE 108.3: the owner's graveyard
    assert p3[0] in eng.state.player_by_id("p3").graveyard
    assert p2[0] not in me.graveyard and p3[0] not in me.graveyard
    assert eng.state.pending_choice is None


def test_declining_leaves_the_cards_exiled_and_a_dry_library_stops_the_dig():
    eng = _three()
    p2 = _lib(eng, "p2", _land(), _land())  # no nonland card: the library runs out
    p3 = _lib(eng, "p3", _sorcery("Three", 3))
    _resolve(eng, _stack(eng, "Fevered Suspicion"))
    assert [o.zone for o in p2] == [Zone.EXILE, Zone.EXILE] and not eng.state.player_by_id("p2").library
    eng.resolve_pending_choice("decline")
    eng.resolve_until_stable()
    assert p3[0].zone is Zone.EXILE and eng.state.pending_choice is None


def test_turn_order_decides_who_digs_first():
    eng = _three(active="p2")
    order = []
    original = eng.rules._exile_library_top

    def spy(player):
        order.append(player.id)
        return original(player)

    eng.rules._exile_library_top = spy
    _lib(eng, "p1", _sorcery("A", 1))
    _lib(eng, "p3", _sorcery("B", 1))
    _resolve(eng, _stack(eng, "Fevered Suspicion", controller="p2"))
    assert order == ["p3", "p1"]  # APNAP from the active player p2, skipping the controller


def test_tasha_stops_each_opponent_at_total_mana_value_and_a_land_adds_nothing():
    eng = _three()
    p2 = _lib(eng, "p2", _sorcery("Ten", 10), _land(), _sorcery("Ten b", 10), _sorcery("Three", 3))
    p3 = _lib(eng, "p3", _land(), _land(), _sorcery("Five", 5))  # 5 < 20: the whole library goes
    _resolve(eng, _stack(eng, "Tasha's Hideous Laughter"))
    assert [o.zone for o in p2] == [Zone.EXILE] * 3 + [Zone.LIBRARY]  # 10 + 0 + 10 = 20 stops it
    assert all(o.zone is Zone.EXILE for o in p3) and not eng.state.player_by_id("p3").library
    assert eng.state.pending_choice is None  # no cast rider


def test_tasha_counts_only_the_cards_this_instruction_exiled():
    eng = _three()
    pre = _lib(eng, "p2", _sorcery("Old", 9))
    eng.rules._exile_library_top(eng.state.player_by_id("p2"))  # already in exile before the spell
    assert pre[0].zone is Zone.EXILE
    p2 = _lib(eng, "p2", _sorcery("Nine", 9), _sorcery("Ten", 10), _sorcery("Eleven", 11))
    _resolve(eng, _stack(eng, "Tasha's Hideous Laughter"))
    assert [o.zone for o in p2] == [Zone.EXILE, Zone.EXILE, Zone.EXILE]  # 9 + 10 = 19, 11 more gives 30


def test_dream_harvest_opens_a_free_cast_window_over_every_exiled_nonland_card():
    eng = _three()
    p2 = _lib(eng, "p2", _land(), _sorcery("Two", 2), _sorcery("Four", 4), _sorcery("Rest", 1))
    p3 = _lib(eng, "p3", _sorcery("Six", 6), _sorcery("Rest", 1))
    _resolve(eng, _stack(eng, "Dream Harvest"))
    assert [o.zone for o in p2] == [Zone.EXILE] * 3 + [Zone.LIBRARY]  # 0 + 2 + 4 >= 5
    assert [o.zone for o in p3] == [Zone.EXILE, Zone.LIBRARY]
    state = eng.state
    for obj in (p2[1], p2[2], p3[0]):
        assert obj.instance_id in state.free_cast_instance_ids and obj.controller_id == "p1"
    assert p2[0].instance_id not in state.free_cast_instance_ids  # a land can't be cast
    me = state.player_by_id("p1")
    eng.cast_spell(me, p3[0])
    assert state.stack[-1].controller_id == "p1" and state.stack[-1].obj is p3[0]  # no mana paid: it is free
    eng.resolve_until_stable()
    assert p3[0] in state.player_by_id("p3").graveyard


def test_krang_links_every_exiled_card_to_itself():
    eng = _three()
    krang = _put(eng, _real("Krang & Shredder"), "p1")
    p2 = _lib(eng, "p2", _land(), _sorcery("Two", 2), _sorcery("Rest", 1))
    p3 = _lib(eng, "p3", _sorcery("Three", 3))
    for spec in [s for s in parse_oracle(krang.card).specs if s.ability_kind == "triggered"][:1]:
        for effect in build_effects(list(spec.effects), krang):
            effect.apply(GameContext(eng.state, eng.rules), None)
    eng.resolve_until_stable()
    assert [o.zone for o in p2] == [Zone.EXILE, Zone.EXILE, Zone.LIBRARY]
    assert set(krang.exiled_with_ids) == {p2[0].instance_id, p2[1].instance_id, p3[0].instance_id}


def test_a_bot_answers_the_cast_choice_from_its_own_view_and_legal_actions():
    from mtg_analyzer.services.bots import create_bot
    from mtg_analyzer.services.game_session import GameSessionManager

    session = GameSessionManager().create_multiplayer(
        [{"player_id": p, "name": p, "library": [_land()] * 30} for p in ("p1", "p2", "p3")],
        mulligan_style="none", keep_history=False,
    )
    for p in ("p1", "p2", "p3"):
        session.apply_action({"type": "keep_hand", "bottom_instance_ids": []}, actor_id=p)
    eng = session.engine
    controller = eng.state.active_player.id
    other = next(p.id for p in eng.state.players if p.id != controller)
    _lib(eng, other, _sorcery("Hit", 2))
    _resolve(eng, _stack(eng, "Fevered Suspicion", controller=controller))
    choice = eng.state.pending_choice
    assert choice and choice["kind"] == "play_during_resolution" and choice["player_id"] == controller
    actions = session.legal_actions(perspective=controller)
    assert [a for a in actions if a["type"] in ("cast_spell", "decline", "pass_choice", "choose_none")]
    for p in eng.state.players:
        if p.id != controller:
            assert not [a for a in session.legal_actions(perspective=p.id) if a["type"] == "cast_spell"]
    action = create_bot("greedy", controller).decide(session.view(perspective=controller), actions)
    assert action["type"] in ("cast_spell", "decline", "pass_choice", "choose_none")
    session.apply_action(action, actor_id=controller)
    if action["type"] == "cast_spell":
        assert eng.state.stack or eng.state.player_by_id(other).graveyard  # the bot cast the opponent's card
