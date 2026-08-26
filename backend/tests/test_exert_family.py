"""RULE 702.19 Exert: a declare-attackers-time optional choice ("as it's
declared as an attacker, its controller may exert it") whose one real
consequence is "it doesn't untap during its controller's next untap step" —
plus, on almost every printed exert creature, a "When you do, <effect>"
trigger and occasionally a player-scoped "whenever you exert a creature,
<effect>" payoff.

Modeled as three pieces: `GameEngine.declare_attackers`'s own ``exert`` flag
per attacker entry (RULE 508.1a/702.19a decide it in the same breath as the
attack itself, no separate `pending_choice`), `GameObject.skip_next_untap`
(a one-shot flag `_step_untap` consumes and clears — distinct from the
sticky `skip_untap` toggle), and `EventType.EXERTED` for both trigger
shapes. `combat.has(obj, "exert")` needs no catalogue change — Scryfall
already tags these `keywords: ['Exert']` even though the ability is spelled
out in full sentences with no bare reminder-text keyword line.

Combat Celebrant is hand-authored (`ability_catalogue.py`) rather than left
to the generic parser handler: its own "if ~ hasn't been exerted this turn"
guard is a real correctness requirement, not a flavour nuance — without it,
its own granted extra combat phase would let it exert, and grant, another
extra combat phase forever.
"""

from __future__ import annotations

from mtg_analyzer.game.ability_catalogue import is_registered
from mtg_analyzer.game.effect_binder import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.events import EventType
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle


def creature(name, oracle_text="", power=2, toughness=2, keywords=None, **kw):
    return Card(
        id=name, name=name, type_line=kw.pop("type_line", "Creature — Human"),
        is_creature=True, power=power, toughness=toughness,
        oracle_text=oracle_text, keywords=list(keywords or []), **kw,
    )


def _land(name="Forest"):
    return Card(id=name, name=name, type_line="Basic Land — Forest", is_land=True)


def make_engine(*player_ids):
    return GameEngine.new_game(
        [(pid, pid, [_land(), _land()]) for pid in player_ids],
        starting_life=20, starting_hand=0,
    )


def put(state, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


def _to_declare_attackers(eng):
    eng.begin_turn()
    eng.state.current_step = "declare_attackers"


# -- parse-side coverage ------------------------------------------------------


def test_bare_exert_rider_is_modeled():
    card = creature(
        "Plain Exerter", "You may exert ~ as it attacks.", keywords=["Exert"],
    )
    result = parse_oracle(card)
    assert result.coverage != UNMODELED
    assert result.unclaimed == []


def test_exert_when_you_do_trigger_is_modeled():
    card = creature(
        "Bonus Exerter",
        "You may exert ~ as it attacks. When you do, it gets +1/+1 until end of turn.",
        keywords=["Exert"],
    )
    result = parse_oracle(card)
    assert result.coverage != UNMODELED
    assert result.unclaimed == []


def test_whenever_you_exert_a_creature_trigger_is_modeled():
    card = creature(
        "Exert Payoff",
        "Whenever you exert a creature, draw a card.",
    )
    result = parse_oracle(card)
    assert result.coverage != UNMODELED
    assert result.unclaimed == []


def test_combat_celebrant_is_modeled_and_hand_authored():
    card = creature(
        "Combat Celebrant",
        "If this creature hasn't been exerted this turn, you may exert it "
        "as it attacks. When you do, untap all other creatures you control "
        "and after this phase, there is an additional combat phase.",
        power=4, toughness=1, keywords=["Exert"],
        type_line="Creature — Human Warrior",
    )
    result = parse_oracle(card)
    assert result.coverage != UNMODELED
    assert is_registered("Combat Celebrant") is True


# -- execute-side behaviour ---------------------------------------------------


def test_exerting_sets_skip_next_untap_and_fires_exerted_event():
    eng = make_engine("p1", "p2")
    _to_declare_attackers(eng)
    attacker = put(eng.state, creature("Exerter", keywords=["Exert"]))

    eng.declare_attackers(eng.state.active_player, [{"attacker": attacker, "exert": True}])

    assert attacker.skip_next_untap is True
    assert attacker.exerted_this_turn is True
    assert any(
        e.type == EventType.EXERTED and e.get("instance_id") == attacker.instance_id
        for e in eng.state.event_log
    )


def test_exert_is_refused_without_the_keyword():
    eng = make_engine("p1", "p2")
    _to_declare_attackers(eng)
    attacker = put(eng.state, creature("No Exert Here"))

    try:
        eng.declare_attackers(eng.state.active_player, [{"attacker": attacker, "exert": True}])
        assert False, "expected a ValueError"
    except ValueError:
        pass


def test_exerted_creature_skips_exactly_its_next_untap_step():
    eng = make_engine("p1", "p2")
    _to_declare_attackers(eng)
    attacker = put(eng.state, creature("Exerter", keywords=["Exert"]))
    eng.declare_attackers(eng.state.active_player, [{"attacker": attacker, "exert": True}])
    attacker.tapped = True

    eng._step_untap()
    assert attacker.tapped is True  # skipped once
    assert attacker.skip_next_untap is False  # consumed

    eng._step_untap()
    assert attacker.tapped is False  # untaps normally the turn after


def test_when_you_do_bonus_fires_on_exert():
    eng = make_engine("p1", "p2")
    _to_declare_attackers(eng)
    attacker = put(eng.state, creature(
        "Bonus Exerter",
        "You may exert ~ as it attacks. When you do, draw a card.",
        keywords=["Exert"],
    ))
    player = eng.state.active_player
    hand_before = len(player.hand)

    eng.declare_attackers(player, [{"attacker": attacker, "exert": True}])
    eng.resolve_until_stable()

    assert len(player.hand) == hand_before + 1


def test_player_scoped_exert_payoff_fires():
    eng = make_engine("p1", "p2")
    _to_declare_attackers(eng)
    attacker = put(eng.state, creature("Exerter", keywords=["Exert"]))
    payoff = put(eng.state, creature(
        "Exert Payoff", "Whenever you exert a creature, draw a card.",
    ))
    player = eng.state.active_player
    hand_before = len(player.hand)

    eng.declare_attackers(player, [{"attacker": attacker, "exert": True}])
    eng.resolve_until_stable()

    assert len(player.hand) == hand_before + 1
    assert payoff  # keeps the payoff permanent referenced/used


def test_combat_celebrant_does_not_infinite_loop_on_a_repeat_exert():
    eng = make_engine("p1", "p2")
    _to_declare_attackers(eng)
    celeb = put(eng.state, creature(
        "Combat Celebrant",
        "If this creature hasn't been exerted this turn, you may exert it "
        "as it attacks. When you do, untap all other creatures you control "
        "and after this phase, there is an additional combat phase.",
        power=4, toughness=1, keywords=["Exert"],
        type_line="Creature — Human Warrior",
    ))

    eng.declare_attackers(eng.state.active_player, [{"attacker": celeb, "exert": True}])
    eng.resolve_until_stable()
    assert len(eng.state.pending_extra_combats) == 1

    # A second exert this same turn (as if it attacked again via the extra
    # combat it just granted) must not grant yet another one.
    celeb.attacking = False
    celeb.tapped = False
    eng.state.current_step = "declare_attackers"
    eng.declare_attackers(eng.state.active_player, [{"attacker": celeb, "exert": True}])
    eng.resolve_until_stable()
    assert len(eng.state.pending_extra_combats) == 1
