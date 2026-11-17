"""PAR-318: counts, shares and evasion measured on the defending player's board (RULE 506.2 / 509.1b / 205.3m).

Every engine case is three-player with two opponents that differ: the value or the condition must follow the player the
attacker attacks, never "an opponent".
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle


def _three_player():
    eng = GameEngine.new_game([("p1", "A", []), ("p2", "B", []), ("p3", "C", [])], starting_life=20, starting_hand=0)
    return eng, eng.state


def _put(state, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.controller_id = controller
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


def _creature(name, oracle="", type_line="Creature — Test", power=2, toughness=2):
    return Card(id=name, name=name, type_line=type_line, oracle_text=oracle, is_creature=True, power=power,
                toughness=toughness)


def _forest(name):
    return Card(id=name, name=name, type_line="Basic Land — Forest", is_land=True)


def _artifact(name):
    return Card(id=name, name=name, type_line="Artifact")


def _attack(eng, attackers, defender_id):
    state = eng.state
    state.current_step = "declare_attackers"
    eng.declare_attackers(state.active_player, [
        {"attacker": a, "defender": {"kind": "player", "id": defender_id}} for a in attackers
    ])
    eng.resolve_until_stable()
    state.current_step = "declare_blockers"


def _set_attacking(obj, defender_id):
    """Put ``obj`` in combat against ``defender_id`` without re-running a declaration (a creature attacks once a turn)."""
    obj.attacking = True
    obj.combat_defender = {"kind": "player", "id": defender_id}


def _clear_attacking(obj):
    obj.attacking = False
    obj.combat_defender = None


def _modeled(text):
    return parse_oracle(_creature("Zed", text)).coverage == "MODELED"


# -- parser -----------------------------------------------------------------------------------------------------------


def test_parser_claims_the_defender_conditioned_evasion_and_counts():
    assert _modeled("Zed can't be blocked unless defending player controls 3 or more creatures that share a creature type.")
    assert _modeled("Each creature you control can't be blocked as long as defending player controls an artifact land.")
    assert _modeled("As long as Zed isn't attacking, its power and toughness are each equal to the number of Forests you control. "
                    "As long as Zed is attacking, its power and toughness are each equal to the number of Forests defending player controls.")
    assert _modeled("Whenever Zed attacks, he gets +1/+0 until end of turn for each artifact defending player controls.")


def test_parser_leaves_unmodeled_neighbours_alone():
    # a block tax and an artist share are different mechanics: they must not be read as a plain restriction
    assert not _modeled("Zed can't be blocked unless defending player pays {3} for each creature they control that's blocking it.")
    assert not _modeled("Zed can't be blocked as long as defending player controls 2 or more nonland permanents that share an artist.")


# -- cant_be_blocked_unless / share a creature type -------------------------------------------------------------------


def test_graxiplon_evasion_follows_the_attacked_player():
    eng, state = _three_player()
    graxiplon = _put(state, _creature("Graxiplon", "Graxiplon can't be blocked unless defending player controls 3 or more "
                                                   "creatures that share a creature type."))
    # p2: three Elves; p3: three creatures but only two share a type
    p2 = [_put(state, _creature(f"Elf {i}", type_line="Creature — Elf"), "p2") for i in range(3)]
    p3 = [_put(state, _creature("Elf X", type_line="Creature — Elf"), "p3"),
          _put(state, _creature("Elf Y", type_line="Creature — Elf Druid"), "p3"),
          _put(state, _creature("Goblin Z", type_line="Creature — Goblin"), "p3")]
    eng.recompute_continuous_effects()
    _attack(eng, [graxiplon], "p2")
    assert eng.can_block(state.player_by_id("p2"), p2[0], graxiplon)
    _clear_attacking(graxiplon)
    _set_attacking(graxiplon, "p3")
    assert not eng.can_block(state.player_by_id("p3"), p3[0], graxiplon)


def test_share_a_creature_type_counts_the_largest_group_and_changelings_join_every_group():
    from mtg_analyzer.game.continuous import count_selector

    eng, state = _three_player()
    selector = {"zone": "battlefield", "of": "you", "filter": {"card_type": "creature"}, "share": "creature_type"}
    _put(state, _creature("Elf X", type_line="Creature — Elf"), "p2")
    _put(state, _creature("Elf Y", type_line="Creature — Elf Druid"), "p2")
    _put(state, _creature("Goblin Z", type_line="Creature — Goblin"), "p2")
    eng.recompute_continuous_effects()
    assert count_selector(state, "p2", selector) == 2
    shifter = _put(state, _creature("Shifter", "Changeling", type_line="Creature — Shapeshifter"), "p2")
    shifter.intrinsic_keywords.add("changeling")
    eng.recompute_continuous_effects()
    assert count_selector(state, "p2", selector) == 3
    assert count_selector(state, "p3", selector) == 0


def test_tanglewalker_gives_each_attacker_its_own_defenders_answer():
    eng, state = _three_player()
    _put(state, _creature("Tanglewalker", "Each creature you control can't be blocked as long as defending player controls "
                                          "an artifact land."))
    other = _put(state, _creature("Plain Bear"))
    p2_art_land = Card(id="Vault", name="Vault", type_line="Artifact Land", is_land=True)
    _put(state, p2_art_land, "p2")
    blocker2 = _put(state, _creature("Wall 2"), "p2")
    blocker3 = _put(state, _creature("Wall 3"), "p3")
    eng.recompute_continuous_effects()
    _attack(eng, [other], "p2")
    assert not eng.can_block(state.player_by_id("p2"), blocker2, other)  # p2 controls the artifact land
    _clear_attacking(other)
    _set_attacking(other, "p3")
    assert eng.can_block(state.player_by_id("p3"), blocker3, other)  # p3 does not


# -- defending-player count in a CDA and an amount --------------------------------------------------------------------


def test_gaeas_liege_cda_follows_the_defender_and_reverts_outside_combat():
    eng, state = _three_player()
    liege = _put(state, _creature("Gaeas Liege", "As long as Gaeas Liege isn't attacking, its power and toughness are each "
                                                 "equal to the number of Forests you control. As long as Gaeas Liege is "
                                                 "attacking, its power and toughness are each equal to the number of "
                                                 "Forests defending player controls.", power=0, toughness=0))
    _put(state, _forest("F1"))
    for i in range(2):
        _put(state, _forest(f"F2-{i}"), "p2")
    for i in range(4):
        _put(state, _forest(f"F3-{i}"), "p3")
    eng.recompute_continuous_effects()
    assert (liege.power, liege.toughness) == (1, 1)
    _set_attacking(liege, "p2")
    eng.recompute_continuous_effects()
    assert (liege.power, liege.toughness) == (2, 2)
    _clear_attacking(liege)
    _set_attacking(liege, "p3")
    eng.recompute_continuous_effects()
    assert (liege.power, liege.toughness) == (4, 4)
    _clear_attacking(liege)
    eng.recompute_continuous_effects()
    assert (liege.power, liege.toughness) == (1, 1)


def test_killmonger_pumps_per_artifact_the_attacked_player_controls():
    eng, state = _three_player()
    kill = _put(state, _creature("Killmonger", "Whenever Killmonger attacks, he gets +1/+0 until end of turn for each artifact "
                                               "defending player controls.", power=1, toughness=1))
    _put(state, _artifact("A2"), "p2")
    for i in range(3):
        _put(state, _artifact(f"A3-{i}"), "p3")
    _attack(eng, [kill], "p3")
    eng.recompute_continuous_effects()
    assert kill.power == 4


def test_cant_be_blocked_if_sibling_follows_the_controllers_board():
    # "can't be blocked if <C>" is the same restriction around a negated C (Geordi: a Spacecraft you control).
    eng, state = _three_player()
    geordi = _put(state, _creature("Geordi", "Geordi can't be blocked if you control a Spacecraft."))
    blocker = _put(state, _creature("Wall"), "p2")
    eng.recompute_continuous_effects()
    _set_attacking(geordi, "p2")
    assert eng.can_block(state.player_by_id("p2"), blocker, geordi)
    _put(state, Card(id="Ship", name="Ship", type_line="Artifact — Spacecraft"))
    eng.recompute_continuous_effects()
    assert not eng.can_block(state.player_by_id("p2"), blocker, geordi)
