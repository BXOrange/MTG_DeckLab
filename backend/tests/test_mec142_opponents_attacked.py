"""MEC-142 -- Battlefront: "the number of opponents you attacked this turn".

The count is a set of *defending players* over this turn's declared attacks
(RULE 508.1a): attacking a planeswalker or a battle counts for its controller /
protector (RULE 506.3d, 310.8d), the same opponent attacked in a second combat
counts once, and a creature put onto the battlefield attacking was never
declared (RULE 508.4). It is read three ways -- an amount ("where X is ..."), a
per-opponent token count, and a self cost reduction -- all through one
`continuous.count_selector` name.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game import continuous
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle

SELECTOR = "opponents_attacked_this_turn"

KORAK_TEXT = (
    "Battlefront — Whenever Korok attacks, creatures you control get +X/+X until end of turn, "
    "where X is the number of opponents you attacked this turn."
)
KURN_TEXT = (
    "Battlefront — Whenever Kurn attacks, you draw X cards and lose X life, "
    "where X is the number of opponents you attacked this turn."
)
TENOR_TEXT = (
    "Battlefront — Whenever this creature attacks, goad up to X target creatures, "
    "where X is the number of opponents you attacked this turn."
)
MARTOK_TEXT = (
    "Battlefront — Whenever you attack, put a +1/+1 counter on each of up to X target creatures you control, "
    "where X is the number of opponents you attacked this turn."
)
RITE_TEXT = (
    "Battlefront — Whenever you attack, for each opponent you attacked this turn, create a tapped and "
    "attacking 2/1 red Klingon Warrior creature token with haste."
)
ANGEL_TEXT = (
    "Flying, lifelink\nWhen this creature enters, create a number of 2/2 white Knight creature tokens with "
    "vigilance equal to the number of opponents you attacked this turn."
)
BEACON_TEXT = (
    "{T}: Choose a color. Add an amount of mana of that color equal to the number of opponents you attacked "
    "this turn."
)
OWN_THE_DAY_TEXT = (
    "Battlefront — This spell costs {1} less to cast for each opponent you attacked this turn.\n"
    "Untap all creatures that attacked this turn. After this main phase, there is an additional combat "
    "phase followed by an additional main phase."
)


def _engine(players=("p1", "p2", "p3", "p4")):
    eng = GameEngine.new_game([(p, p, []) for p in players], starting_life=20, starting_hand=0)
    eng.begin_turn()
    eng.state.current_phase, eng.state.current_step = "combat", "declare_attackers"
    return eng


def _put(eng, card, controller="p1", bind=True):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.controller_id = controller
    obj.summoning_sick = False
    if bind:
        bind_from_catalogue(obj)
    eng.state.add_to_battlefield(obj)
    return obj


def _bear(name="Bear"):
    return Card(id=name, name=name, type_line="Creature — Bear", is_creature=True, power=2, toughness=2)


def _walker():
    return Card(id="W", name="Walker", type_line="Legendary Planeswalker — Test", loyalty=5)


def _battle():
    return Card(
        id="B", name="Invasion of Testland", type_line="Battle — Siege", defense=3, layout="transform",
        back_name="Back", back_type_line="Creature — Phyrexian", back_power=3, back_toughness=3,
    )


def _card(**kw):
    """A card whose oracle text opens with the Battlefront label (kept in ``keywords`` the way Scryfall lists it)."""
    return Card(keywords=["Battlefront"], **kw)


def _player(pid):
    return {"kind": "player", "id": pid, "label": pid}


def _attack(eng, pairs):
    eng.declare_attackers(
        eng.state.active_player, [{"attacker": a, "defender": d} for a, d in pairs],
    )


def _count(eng, pid="p1"):
    return continuous.count_selector(eng.state, pid, SELECTOR)


# --- the engine count ------------------------------------------------------


def test_each_distinct_defending_player_counts_once():
    eng = _engine()
    a, b, c = (_put(eng, _bear(n)) for n in "abc")
    assert _count(eng) == 0
    _attack(eng, [(a, _player("p2")), (b, _player("p2")), (c, _player("p3"))])
    assert _count(eng) == 2  # p2 attacked by two creatures still counts once
    assert _count(eng, "p2") == 0  # per attacker: the defenders' own count is untouched


def test_attacking_a_planeswalker_counts_its_controller():
    # RULE 506.3d: attacking a planeswalker is attacking the player who controls it.
    eng = _engine()
    walker = _put(eng, _walker(), controller="p3", bind=False)
    a = _put(eng, _bear())
    _attack(eng, [(a, {"kind": "planeswalker", "instance_id": walker.instance_id})])
    assert _count(eng) == 1
    assert eng.state.opponents_attacked_this_turn["p1"] == {"p3"}


def test_attacking_a_battle_counts_its_protector_not_its_controller():
    # RULE 310.8d: the defending player of a battle is its protector (the attacker may control the Siege).
    eng = _engine(("p1", "p2"))
    battle = GameObject(_battle(), owner_id="p1", zone=Zone.BATTLEFIELD)
    battle.protector_id = "p2"
    eng.state.add_to_battlefield(battle)
    a = _put(eng, _bear())
    _attack(eng, [(a, {"kind": "battle", "instance_id": battle.instance_id})])
    assert eng.state.opponents_attacked_this_turn["p1"] == {"p2"}
    assert _count(eng) == 1


def test_a_second_combat_against_the_same_opponent_counts_once():
    eng = _engine()
    a = _put(eng, _bear())
    _attack(eng, [(a, _player("p2"))])
    # A second combat phase: the same creature attacks the same opponent again, plus a new one.
    b = _put(eng, _bear("b"))
    a.attacking, a.tapped = False, False  # the first combat ended; vigilance-free untap by an effect
    eng.state.current_step = "declare_attackers"
    _attack(eng, [(a, _player("p2")), (b, _player("p4"))])
    assert _count(eng) == 2


def test_a_creature_put_onto_the_battlefield_attacking_does_not_count():
    # RULE 508.4: it was never declared as an attacker, so no opponent was "attacked" by it.
    eng = _engine()
    eng.state.fire_event(GameEvent(
        EventType.ATTACKS, attacker="Token", player_id="p1", declared=False,
        defender_kind="player", defending_player_id="p3",
    ))
    assert _count(eng) == 0


def test_the_count_resets_with_the_turn():
    eng = _engine()
    a = _put(eng, _bear())
    _attack(eng, [(a, _player("p2"))])
    assert _count(eng) == 1
    eng.begin_turn()
    assert _count(eng, eng.state.active_player.id) == 0


# --- parsing ---------------------------------------------------------------


@pytest.mark.parametrize(
    "name, text",
    [
        ("Korok, Liberated Rage", KORAK_TEXT),
        ("Kurn, Son of Mogh", KURN_TEXT),
        ("Galvanizing Tenor", TENOR_TEXT),
        ("Martok, Hero of the Empire", MARTOK_TEXT),
        ("Rite of Ascension", RITE_TEXT),
        ("Militant Angel", ANGEL_TEXT),
        ("The Beacon of Kahless", BEACON_TEXT),
        ("Own the Day", OWN_THE_DAY_TEXT),
    ],
)
def test_battlefront_cards_are_modeled(name, text):
    card = _card(id=name, name=name, type_line="Sorcery" if name == "Own the Day" else "Creature — Test",
                 oracle_text=text, is_sorcery=name == "Own the Day")
    res = parse_oracle(card)
    assert res.modeled, res.unclaimed


def test_the_x_target_count_reads_the_named_selector_not_the_cast_x():
    res = parse_oracle(_card(id="t", name="Tenor", type_line="Creature — Klingon", oracle_text=TENOR_TEXT))
    goad = res.specs[0].effects[0]
    assert goad.type == "goad" and goad.params["count_selector"] == SELECTOR


# --- execution -------------------------------------------------------------


def test_korok_pumps_by_the_opponents_attacked():
    eng = _engine()
    korok = _put(eng, _card(id="k", name="Korok", type_line="Creature — Test", is_creature=True,
                           power=2, toughness=2, oracle_text=KORAK_TEXT.replace("Korok", "~")))
    other = _put(eng, _bear())
    _attack(eng, [(korok, _player("p2")), (other, _player("p3"))])
    eng.resolve_until_stable()
    eng.recompute_continuous_effects()
    assert (korok.power, other.power) == (4, 4)  # X = 2 opponents


def test_kurn_draws_and_loses_x():
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    for i in range(5):
        p1.library.append(GameObject(Card(id=f"L{i}", name=f"L{i}", type_line="Land"),
                                     owner_id="p1", zone=Zone.LIBRARY))
    kurn = _put(eng, _card(id="kurn", name="Kurn", type_line="Creature — Test", is_creature=True,
                          power=2, toughness=2, oracle_text=KURN_TEXT.replace("Kurn", "~")))
    life = p1.life
    _attack(eng, [(kurn, _player("p2"))])
    eng.resolve_until_stable()
    assert len(p1.hand) == 1 and p1.life == life - 1


def test_rite_of_ascension_makes_one_attacking_token_per_opponent():
    eng = _engine()
    _put(eng, _card(id="rite", name="Rite", type_line="Enchantment", oracle_text=RITE_TEXT))
    a, b = _put(eng, _bear("a")), _put(eng, _bear("b"))
    _attack(eng, [(a, _player("p2")), (b, _player("p3"))])
    eng._fire_player_attacked_events()  # combat locks in: one ATTACKERS_DECLARED for the whole declaration
    eng.resolve_until_stable()
    tokens = [o for o in eng.state.battlefield if o.is_token]
    assert len(tokens) == 2
    assert all(t.attacking and t.tapped for t in tokens)
    # RULE 508.4: the tokens enter attacking without being declared, so the count stays two.
    assert _count(eng) == 2
    # RULE 603.2: two opponents attacked is still one declaration, so the trigger fired once (not once per defender).
    assert len(tokens) == 2


def test_own_the_day_costs_one_less_per_opponent_attacked():
    eng = _engine()
    spell = GameObject(
        _card(id="otd", name="Own the Day", type_line="Sorcery", mana_cost_string="{4}{R}{R}",
             oracle_text=OWN_THE_DAY_TEXT, is_sorcery=True),
        owner_id="p1", zone=Zone.HAND,
    )
    bind_from_catalogue(spell)
    eng.state.player_by_id("p1").hand.append(spell)
    assert continuous.self_cost_reduction_for(spell, eng.state)[0] == 0
    a, b = _put(eng, _bear("a")), _put(eng, _bear("b"))
    _attack(eng, [(a, _player("p2")), (b, _player("p4"))])
    assert continuous.self_cost_reduction_for(spell, eng.state)[0] == 2


def test_own_the_day_untaps_creatures_that_attacked():
    eng = _engine()
    a, idle = _put(eng, _bear("a")), _put(eng, _bear("idle"))
    idle.tapped = True
    _attack(eng, [(a, _player("p2"))])
    assert a.tapped
    spell = parse_oracle(_card(id="otd", name="Own the Day", type_line="Sorcery", oracle_text=OWN_THE_DAY_TEXT,
                               is_sorcery=True))
    assert spell.modeled
    from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause

    spec = match_clause("untap all creatures that attacked this turn")[0]
    from mtg_analyzer.game.effects.registry import EffectRegistry
    from mtg_analyzer.game.effects.core import GameContext

    effect = EffectRegistry.create(spec.type, spec.params)
    effect.source = a  # the resolving spell's source; the group itself is controller-independent
    effect.apply(GameContext(eng.state, eng.rules), [])
    assert not a.tapped and idle.tapped  # only the declared attacker untaps
