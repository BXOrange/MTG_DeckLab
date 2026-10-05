"""Combat Calligrapher creates attacking Inkling tokens."""

from __future__ import annotations

from mtg_analyzer.game.card_registry import _REGISTRY, is_registered, specs_for
from mtg_analyzer.game.binding.core import bind_ability, bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone


def _calligrapher_card():
    return Card(id="cc", name="Combat Calligrapher", type_line="Creature — Bird Cleric",
                is_creature=True, power=3, toughness=3,
                oracle_text=("Flying\nInklings can't attack you or planeswalkers you "
                             "control.\nWhenever a player attacks one of your opponents, "
                             "that attacking player creates a tapped 2/1 white and black "
                             "Inkling creature token with flying that's attacking that "
                             "opponent."))


def test_registered_and_binds():
    assert is_registered("Combat Calligrapher")
    specs = _REGISTRY["combat calligrapher"]()
    assert len(specs) == 2
    static, trig = specs
    assert static.effects[0].type == "cant_attack_defender"
    assert static.effects[0].params["attacker_filter"] == {"subtype": "Inkling"}
    assert trig.trigger["event"] == "PLAYER_ATTACKED"
    assert trig.trigger["defender_is_opponent"] is True
    assert trig.effects[0].type == "attacker_creates_attacking_token"
    src = GameObject(_calligrapher_card(), owner_id="p1", zone=Zone.BATTLEFIELD)
    src.controller_id = "p1"
    for s in specs:
        s.validate()
        bind_ability(s, src)


def test_specs_for_real_card():
    assert specs_for(_calligrapher_card())


def test_attacker_makes_a_tapped_attacking_inkling_when_an_opponent_is_attacked():
    eng = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", []), ("p3", "Cara", [])],
        starting_life=20, starting_hand=0,
    )
    eng.state.active_player_index = 1  # p2 is attacking this combat
    eng.state.current_phase = "combat"
    eng.state.current_step = "declare_attackers"
    cc = GameObject(_calligrapher_card(), owner_id="p1", zone=Zone.BATTLEFIELD)
    cc.controller_id = "p1"
    cc.summoning_sick = False
    eng.state.add_to_battlefield(cc)
    bind_from_catalogue(cc)
    eng.recompute_continuous_effects()

    before = len(eng.state.battlefield)
    # p2 attacks p3 (one of p1's opponents)
    attacker = GameObject(
        Card(id="attacker", name="Attacker", type_line="Creature — Human",
             is_creature=True, power=2, toughness=2),
        owner_id="p2", zone=Zone.BATTLEFIELD,
    )
    attacker.controller_id = "p2"
    attacker.attacking = True
    attacker.combat_defender = {"kind": "player", "id": "p3", "label": "Cara"}
    eng.state.add_to_battlefield(attacker)
    eng.state.fire_event(GameEvent(
        EventType.PLAYER_ATTACKED, attacking_player_id="p2", defending_player_id="p3",
        player_id="p2", count=1,
    ))
    eng.resolve_until_stable()

    inklings = [o for o in eng.state.battlefield
                if "Inkling" in (o.card.type_line or "")]
    assert len(inklings) == 1
    tok = inklings[0]
    assert tok.controller_id == "p2"       # the attacking player controls it
    assert tok.tapped
    assert tok.attacking
    assert (tok.combat_defender or {}).get("id") == "p3"


def test_no_token_when_the_controller_is_the_one_attacked():
    eng = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0,
    )
    cc = GameObject(_calligrapher_card(), owner_id="p1", zone=Zone.BATTLEFIELD)
    cc.controller_id = "p1"
    cc.summoning_sick = False
    eng.state.add_to_battlefield(cc)
    bind_from_catalogue(cc)
    eng.recompute_continuous_effects()

    eng.state.fire_event(GameEvent(
        EventType.PLAYER_ATTACKED, attacking_player_id="p2", defending_player_id="p1",
        player_id="p2", count=1,
    ))
    eng.resolve_until_stable()
    assert not [o for o in eng.state.battlefield if "Inkling" in (o.card.type_line or "")]
