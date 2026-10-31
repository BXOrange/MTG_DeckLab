"""ENG-53: every instance of a triggered keyword triggers separately (RULE 113.2c, 702.116b Myriad, 702.83b Exalted,
702.92b Battle cry, 702.86b Annihilator, 702.45b Bushido, 702.23b Rampage). Keywords are a set on the object, so the
instance count comes from `combat.keyword_instances` (printed + layer-6 grants + temp_keywords)."""

from __future__ import annotations

from mtg_analyzer.game import combat
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone


def _creature(name, keywords=None, power=2, toughness=2, oracle_text=""):
    return Card(id=name, name=name, type_line="Creature — Human", is_creature=True, power=power, toughness=toughness,
                oracle_text=oracle_text, keywords=list(keywords or []))


def _engine(*ids):
    ids = ids or ("p1", "p2")
    eng = GameEngine.new_game([(i, i, []) for i in ids], starting_life=20, starting_hand=0)
    eng.start()
    return eng


def _put(eng, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    eng.state.add_to_battlefield(obj)
    bind_from_catalogue(obj)
    return obj


def _to(eng, step):
    while eng.state.current_step != step:
        eng.advance_step()


def _sublime(name):
    return _creature(name, ["Flying", "Exalted"], 4, 3,
                     "Flying\nExalted\nOther creatures you control have exalted.")


# -- the count API ---------------------------------------------------------


def test_instance_counts_sum_printed_grants_and_temp():
    eng = _engine()
    obj = _put(eng, _creature("Rafiq", ["Exalted"]))
    eng.recompute_continuous_effects()
    assert combat.keyword_instances(obj, "exalted") == 1
    obj.temp_keywords.add("exalted")
    eng.recompute_continuous_effects()
    assert combat.keyword_instances(obj, "exalted") == 2
    assert combat.keyword_instances(obj, "flying") == 0
    obj.temp_keywords.add("flying")
    eng.recompute_continuous_effects()
    assert combat.keyword_instances(obj, "flying") == 1  # redundant keywords still read as one


# -- Myriad (RULE 702.116b) -----------------------------------------------


def _attack_alone(eng, attacker):
    _to(eng, "declare_attackers")
    eng.declare_attackers(eng.state.active_player, [{"attacker": attacker, "defender": {"kind": "player", "id": "p2"}}])


def _yes_all(eng):
    for _ in range(30):
        eng.resolve_until_stable()
        choice = eng.state.pending_choice
        if not choice:
            return
        eng.rules.resolve_choice("yes" if choice["kind"] == "composite_optional" else "decline")
    raise AssertionError("choices did not settle")


def test_printed_plus_granted_myriad_makes_two_token_sets():
    eng = _engine("p1", "p2", "p3")
    # Multiplayer turn one includes a draw; keep the attacker in the game.
    player = eng.state.player_by_id("p1")
    player.add_to_zone(GameObject(_creature("Draw filler"), owner_id="p1", zone=Zone.LIBRARY), Zone.LIBRARY)
    attacker = _put(eng, _creature("Myriad Bear", ["Myriad"]))
    attacker.temp_keywords.add("myriad")
    eng.recompute_continuous_effects()
    _attack_alone(eng, attacker)
    _yes_all(eng)
    assert not player.has_lost
    assert len([o for o in eng.state.battlefield if o.is_token and o.name == "Myriad Bear"]) == 2


def test_single_myriad_still_one_token_set():
    eng = _engine("p1", "p2", "p3")
    # Multiplayer turn one includes a draw; keep the attacker in the game.
    player = eng.state.player_by_id("p1")
    player.add_to_zone(GameObject(_creature("Draw filler"), owner_id="p1", zone=Zone.LIBRARY), Zone.LIBRARY)
    attacker = _put(eng, _creature("Myriad Bear", ["Myriad"]))
    eng.recompute_continuous_effects()
    _attack_alone(eng, attacker)
    _yes_all(eng)
    assert not player.has_lost
    assert len([o for o in eng.state.battlefield if o.is_token and o.name == "Myriad Bear"]) == 1


# -- Exalted (RULE 702.83b) ------------------------------------------------


def test_granted_exalted_triggers():
    eng = _engine()
    _put(eng, _sublime("Sublime Archangel"))
    bear = _put(eng, _creature("Bear"))
    eng.recompute_continuous_effects()
    _to(eng, "declare_attackers")
    eng.declare_attackers(eng.state.active_player, [bear])
    eng.advance_step()
    eng.resolve_until_stable()
    assert (bear.power, bear.toughness) == (4, 4)  # SA's own exalted + the bear's granted one


def test_two_instances_on_one_permanent_give_plus_two_each():
    eng = _engine()
    a = _put(eng, _sublime("Archangel A"))
    _put(eng, _sublime("Archangel B"))  # grants A a second exalted instance, and vice versa
    eng.recompute_continuous_effects()
    assert combat.keyword_instances(a, "exalted") == 2
    _to(eng, "declare_attackers")
    eng.declare_attackers(eng.state.active_player, [a])
    eng.advance_step()
    eng.resolve_until_stable()
    assert (a.power, a.toughness) == (8, 7)  # four instances across two permanents: +4/+4


def test_exalted_from_two_permanents_still_one_each():
    eng = _engine()
    _put(eng, _creature("Rafiq", ["Exalted"], 3, 3))
    _put(eng, _creature("Rafiq Twin", ["Exalted"], 3, 3))
    lone = _put(eng, _creature("Lone"))
    _to(eng, "declare_attackers")
    eng.declare_attackers(eng.state.active_player, [lone])
    eng.advance_step()
    eng.resolve_until_stable()
    assert (lone.power, lone.toughness) == (4, 4)


# -- Battle cry (RULE 702.92b) ----------------------------------------------


def test_printed_plus_granted_battle_cry_pumps_twice():
    eng = _engine()
    crier = _put(eng, _creature("Accorder Paladin", ["Battle Cry"], 3, 1))
    crier.temp_keywords.add("battle_cry")
    ally = _put(eng, _creature("Ally"))
    eng.recompute_continuous_effects()
    _to(eng, "declare_attackers")
    eng.declare_attackers(eng.state.active_player, [crier, ally])
    eng.resolve_until_stable()
    assert (ally.power, ally.toughness) == (4, 2)
    assert crier.power == 3


# -- Annihilator / Bushido (parametric: separate N per instance) -----------


def _annihilator_attack(grant):
    eng = _engine()
    atk = _put(eng, _creature("Eldrazi", ["Annihilator"], 5, 5, "Annihilator 1"))
    if grant:
        atk.temp_parametric_keywords["annihilator"] = grant
    eng.recompute_continuous_effects()
    victims = [_put(eng, _creature(f"V{i}"), "p2") for i in range(4)]
    _to(eng, "declare_attackers")
    eng.declare_attackers(eng.state.active_player, [{"attacker": atk, "defender": {"kind": "player", "id": "p2"}}])
    for _ in range(20):
        eng.resolve_until_stable()
        choice = eng.state.pending_choice
        if not choice:
            break
        first = (choice.get("options") or choice.get("candidates") or choice.get("choices") or [None])[0]
        eng.rules.resolve_choice(str(first["id"] if isinstance(first, dict) else first))
    return [v for v in victims if v in eng.state.battlefield]


def test_annihilator_instances_sum_their_own_n():
    assert len(_annihilator_attack(0)) == 3  # Annihilator 1
    assert len(_annihilator_attack(2)) == 1  # printed 1 + granted 2


def test_bushido_instances_each_pump_their_own_n():
    eng = _engine()
    samurai = _put(eng, _creature("Samurai", ["Bushido"], 2, 2, "Bushido 1"))
    samurai.temp_parametric_keywords["bushido"] = 2
    blocker = _put(eng, _creature("Wall", None, 0, 9), "p2")
    eng.recompute_continuous_effects()
    _to(eng, "declare_attackers")
    eng.declare_attackers(eng.state.active_player, [{"attacker": samurai, "defender": {"kind": "player", "id": "p2"}}])
    eng.advance_step()  # declare_blockers
    eng.declare_blockers(eng.state.player_by_id("p2"), [(blocker, samurai)], pay_block_tax=False)
    eng.resolve_until_stable()
    assert (samurai.power, samurai.toughness) == (2 + 1 + 2, 2 + 1 + 2)  # one trigger per instance, each its own N


# -- Rampage (RULE 702.23b) --------------------------------------------------


def test_rampage_places_one_trigger_per_instance():
    eng = _engine()
    atk = _put(eng, _creature("Rampager", [], 3, 3))
    atk.parametric_keywords["rampage"] = {"n": 1}
    atk._granted_parametric_keywords["rampage"] = 2
    placed = []
    eng.rules._place_trigger = lambda ability, **kw: placed.append(ability.description)
    eng.rules.check_rampage(atk, 3)
    assert placed == ["Rampage 1", "Rampage 2"]


# -- Flanking (RULE 702.25) --------------------------------------------------


def _flank_block(attacker_kws=("Flanking",), blocker_kws=(), blocker_toughness=1, extra_flank=False):
    eng = _engine()
    atk = _put(eng, _creature("Knight", list(attacker_kws), 2, 2))
    if extra_flank:
        atk.temp_keywords.add("flanking")
    blocker = _put(eng, _creature("Blocker", list(blocker_kws), 2, blocker_toughness), "p2")
    eng.recompute_continuous_effects()
    _to(eng, "declare_attackers")
    eng.declare_attackers(eng.state.active_player, [{"attacker": atk, "defender": {"kind": "player", "id": "p2"}}])
    eng.advance_step()
    eng.declare_blockers(eng.state.player_by_id("p2"), [(blocker, atk)], pay_block_tax=False)
    eng.resolve_until_stable()
    return eng, atk, blocker


def test_flanking_shrinks_a_plain_blocker():
    eng, atk, blocker = _flank_block(blocker_toughness=3)
    assert (blocker.power, blocker.toughness) == (1, 2)


def test_flanking_minus_one_kills_a_one_toughness_blocker_before_damage():
    eng, atk, blocker = _flank_block(blocker_toughness=1)
    assert blocker not in eng.state.battlefield
    assert blocker in eng.state.player_by_id("p2").graveyard  # dead from the trigger alone, before combat damage


def test_blocker_with_flanking_is_not_shrunk():
    eng, atk, blocker = _flank_block(blocker_kws=("Flanking",), blocker_toughness=3)
    assert (blocker.power, blocker.toughness) == (2, 3)


def test_two_flanking_instances_trigger_twice():
    eng, atk, blocker = _flank_block(blocker_toughness=4, extra_flank=True)
    assert (blocker.power, blocker.toughness) == (0, 2)


# -- Prowess / Mentor: printed once, granted once, both twice -----------------


def _spell(name="Shock"):
    return Card(id=name, name=name, type_line="Instant", is_instant=True)


def _prowess_toughness(printed, granted):
    eng = _engine()
    monk = _put(eng, _creature("Monk", ["Prowess"] if printed else [], 1, 1))
    if granted:
        monk.temp_keywords.add("prowess")
    eng.recompute_continuous_effects()
    _to(eng, "main1")
    spell = GameObject(_spell(), owner_id="p1", zone=Zone.HAND)
    eng.state.player_by_id("p1").add_to_zone(spell, Zone.HAND)
    eng.cast_spell(eng.state.player_by_id("p1"), spell) if hasattr(eng, "cast_spell") else None
    eng.resolve_until_stable()
    return monk.power


def test_prowess_printed_granted_and_both():
    assert _prowess_toughness(True, False) == 2
    assert _prowess_toughness(False, True) == 2
    assert _prowess_toughness(True, True) == 3


def _mentor_counters(printed, granted):
    eng = _engine()
    mentor = _put(eng, _creature("Mentor", ["Mentor"] if printed else [], 3, 3))
    if granted:
        mentor.temp_keywords.add("mentor")
    small = _put(eng, _creature("Small", None, 1, 1))
    eng.recompute_continuous_effects()
    _to(eng, "declare_attackers")
    eng.declare_attackers(eng.state.active_player, [mentor, small])
    for _ in range(10):
        eng.resolve_until_stable()
        choice = eng.state.pending_choice
        if not choice:
            break
        first = (choice.get("options") or choice.get("candidates") or choice.get("choices") or [None])[0]
        eng.rules.resolve_choice(str(first["id"] if isinstance(first, dict) else first))
    return small.counters.get("+1/+1", 0)


def test_mentor_printed_granted_and_both():
    assert _mentor_counters(True, False) == 1
    assert _mentor_counters(False, True) == 1
    assert _mentor_counters(True, True) == 2


def _real_card_flanked(name, blocker_keywords=()):
    from mtg_analyzer.config import DB_PATH
    from mtg_analyzer.services.card_database import CardDatabase
    import pytest

    card = CardDatabase(DB_PATH).get_card(name)
    if card is None:
        pytest.skip(f"{name} not in the card cache")
    eng = _engine()
    atk = _put(eng, card)
    blocker = _put(eng, _creature("Blocker", list(blocker_keywords), 2, 3), "p2")
    eng.recompute_continuous_effects()
    _to(eng, "declare_attackers")
    eng.declare_attackers(eng.state.active_player, [{"attacker": atk, "defender": {"kind": "player", "id": "p2"}}])
    eng.advance_step()
    eng.declare_blockers(eng.state.player_by_id("p2"), [(blocker, atk)], pay_block_tax=False)
    eng.resolve_until_stable()
    return blocker


def test_parser_built_flanking_card_triggers():
    assert _real_card_flanked("Suq'Ata Lancer").toughness == 2


def test_hand_authored_sidar_kondo_triggers():
    # Sidar's own restriction lets only flying/reach creatures block it.
    assert _real_card_flanked("Sidar Kondo of Jamuraa", ["Flying"]).toughness == 2
