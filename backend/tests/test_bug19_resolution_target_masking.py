"""BUG-19 -- RULE 608.2b/400.7: every illegal target (left its zone, new object, hexproof now) is blanked
at resolution while the legal ones are still affected; all-illegal fizzles."""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from tests.support.game import make_engine


def _creature(name, text="", power=2, toughness=4):
    return Card(id=name, name=name, type_line="Creature — Test", oracle_text=text, is_creature=True,
                power=power, toughness=toughness)


def _engine():
    eng = make_engine([_creature(f"Filler {i}") for i in range(5)],
                      [_creature(f"Other {i}") for i in range(5)], hand=0)
    eng.state.current_step = "main1"
    return eng


def _put(eng, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.controller_id = controller
    obj.summoning_sick = False
    eng.state.add_to_battlefield(obj)
    bind_from_catalogue(obj)
    return obj


def _fire(eng, text, targets, groups=None):
    p1 = eng.state.player_by_id("p1")
    src = _put(eng, _creature("Source", f"{{R}}: {text}", 1, 1))
    p1.mana_pool.add_many({"R": 1})
    eng.activate_ability(p1, src, targets=list(targets), target_groups=groups)
    return src


PING = "Source deals 2 damage to target creature and 3 damage to target player."


def test_exiled_target_takes_no_damage_while_the_player_still_does():
    eng = _engine()
    victim = _put(eng, _creature("Victim"), controller="p2")
    p2 = eng.state.player_by_id("p2")
    life = p2.life
    _fire(eng, PING, [victim, p2], [[victim], [p2]])
    eng.rules.exile(victim)
    eng.resolve_until_stable()
    assert p2.life == life - 3
    assert victim.zone == Zone.EXILE and not victim.damage_marked


def test_blinked_target_is_a_new_object_and_is_not_hit():
    eng = _engine()
    victim = _put(eng, _creature("Victim"), controller="p2")
    p2 = eng.state.player_by_id("p2")
    life = p2.life
    _fire(eng, PING, [victim, p2], [[victim], [p2]])
    eng.rules.blink(victim)
    eng.resolve_until_stable()
    assert p2.life == life - 3
    assert not victim.damage_marked


def test_hexproof_target_is_skipped_but_player_is_hit():
    eng = _engine()
    victim = _put(eng, _creature("Victim"), controller="p2")
    p2 = eng.state.player_by_id("p2")
    life = p2.life
    _fire(eng, PING, [victim, p2], [[victim], [p2]])
    victim.intrinsic_keywords = set(victim.intrinsic_keywords) | {"hexproof"}
    eng.resolve_until_stable()
    assert p2.life == life - 3
    assert not victim.damage_marked


def test_all_targets_illegal_fizzles():
    eng = _engine()
    victim = _put(eng, _creature("Victim"), controller="p2")
    other = _put(eng, _creature("Other"), controller="p2")
    src = _fire(eng, "Destroy target creature and tap target creature.", [victim, other], [[victim], [other]])
    eng.rules.exile(victim)
    eng.rules.exile(other)
    eng.resolve_until_stable()
    assert not eng.state.stack and src.zone == Zone.BATTLEFIELD


def test_fight_with_a_departed_fighter_deals_no_damage():
    # RULE 701.14b: if either creature is an illegal target, no damage is dealt.
    eng = _engine()
    mine = _put(eng, _creature("Mine", power=3), controller="p1")
    theirs = _put(eng, _creature("Theirs", power=3), controller="p2")
    _fire(eng, "Target creature you control fights target creature you don't control.",
          [mine, theirs], [[mine], [theirs]])
    eng.rules.exile(theirs)
    eng.resolve_until_stable()
    assert not mine.damage_marked and not theirs.damage_marked


def test_masked_resolution_survives_clone():
    eng = _engine()
    victim = _put(eng, _creature("Victim"), controller="p2")
    p2 = eng.state.player_by_id("p2")
    life = p2.life
    _fire(eng, PING, [victim, p2], [[victim], [p2]])
    eng.rules.exile(victim)
    import copy
    clone = copy.deepcopy(eng)
    for e in (eng, clone):
        e.resolve_until_stable()
    assert clone.state.player_by_id("p2").life == life - 3 == p2.life


def test_divided_spell_exiled_target_gets_nothing_and_legal_keeps_its_share():
    # RULE 601.2d/608.2b: Arc Lightning (a spell: `_apply_effects_partitioned` path, unpartitioned single
    # requirement). Its split of 3 is 2 + 1; the exiled target's share is not dealt and not redistributed.
    from mtg_analyzer.config import DB_PATH
    from mtg_analyzer.game.game_engine import GameEngine
    from mtg_analyzer.services.card_database import CardDatabase
    from tests.support.catalogue import battlefield_object

    eng = GameEngine.new_game([("p1", "A", []), ("p2", "B", [])], starting_hand=0, starting_life=20)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.players[0]
    victims = [battlefield_object(eng, "p2", f"S{i}", "Creature", is_creature=True, power=1, toughness=9)
               for i in range(2)]
    spell = GameObject(CardDatabase(DB_PATH).get_card("Arc Lightning"), owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(spell)
    p1.hand.append(spell)
    p1.mana_pool.add_many({"C": 2, "R": 1})
    eng.cast_spell(p1, spell, targets=victims)
    eng.rules.exile(victims[1])
    eng.resolve_until_stable()
    assert victims[0].damage_marked == 2
    assert victims[1].zone == Zone.EXILE and victims[1].damage_marked == 0


def test_ability_whose_source_was_sacrificed_still_skips_the_exiled_target():
    eng = _engine()
    victim = _put(eng, _creature("Victim"), controller="p2")
    p2 = eng.state.player_by_id("p2")
    p1 = eng.state.player_by_id("p1")
    life = p2.life
    src = _put(eng, _creature("Bomb", "{R}, Sacrifice Bomb: Bomb deals 2 damage to target creature "
                                     "and 3 damage to target player.", 1, 1))
    p1.mana_pool.add_many({"R": 1})
    eng.activate_ability(p1, src, targets=[victim, p2], target_groups=[[victim], [p2]])
    assert src.zone != Zone.BATTLEFIELD, "fixture: sacrificed as a cost"
    eng.rules.exile(victim)
    eng.resolve_until_stable()
    assert p2.life == life - 3
    assert victim.zone == Zone.EXILE and not victim.damage_marked
