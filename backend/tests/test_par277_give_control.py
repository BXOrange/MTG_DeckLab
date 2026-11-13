"""PAR-277: the Donate family -- a control change whose recipient is not the ability's controller.

"Target player gains control of target permanent you control." (Donate, Harmless Offering, Wrong Turn, Bazaar Trader,
Bill Ferny, Rules of Acquisition, Blim, Discerning Financier), the "if they do" gate (RULE 608.2c) and the
former-controller referent ("that opponent draws ...").
"""
from __future__ import annotations

import pytest

from mtg_analyzer.config import DB_PATH
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
from mtg_analyzer.services.card_database import CardDatabase
from tests.support.game import creature, make_engine

DB = CardDatabase(DB_PATH)

CARDS = [
    "Bazaar Trader", "Blim, Comedic Genius", "Discerning Financier", "Donate", "Harmless Offering", "Wrong Turn",
    "Bill Ferny, Bree Swindler", "Rules of Acquisition",
]


def game(players=2):
    libraries = [(f"p{i}", f"P{i}", [creature(f"Lib{i}-{n}") for n in range(12)]) for i in range(1, players + 1)]
    from mtg_analyzer.game.game_engine import GameEngine
    eng = GameEngine.new_game(libraries, starting_life=20, starting_hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    return eng


def board(eng, card, owner="p1"):
    obj = GameObject(card, owner_id=owner, zone=Zone.BATTLEFIELD)
    bind_from_catalogue(obj)
    obj.summoning_sick = False
    eng.state.add_to_battlefield(obj)
    return obj


def cast(eng, name, targets, mana, **kwargs):
    """Cast the real card from p1's hand and resolve the stack."""
    card = DB.get_card(name)
    assert card is not None and parse_oracle(card).modeled, name
    spell = GameObject(card, owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(spell)
    p1 = eng.state.player_by_id("p1")
    p1.hand.append(spell)
    p1.mana_pool.add_many(mana)
    eng.cast_spell(p1, spell, targets=targets, **kwargs)
    eng.resolve_until_stable()
    return spell


@pytest.mark.parametrize("name", CARDS)
def test_real_cards_are_modeled(name):
    card = DB.get_card(name)
    assert card is not None and parse_oracle(card).modeled


@pytest.mark.parametrize("text", [
    "target opponent gains control of target tapped creature",  # a quality would be dropped: unclaimed
    "target player gains control of target permanent an opponent controls",  # nothing of the caster's to donate
    "target opponent gains control of target land you control until end of turn",  # a duration is another row
    "target opponent gains control of target creature you control. if they do, target creature gets +1/+1",
])
def test_adversarial_variants_stay_unclaimed(text):
    assert parse_effect_body(text + ".") is None


def test_give_control_parses_the_player_then_the_permanent():
    specs = match_clause("target opponent gains control of target horse you control")
    assert [s.type for s in specs] == ["give_control"]
    assert specs[0].params == {
        "recipient": "target_opponent", "target_kind": "permanent_you_control", "creature_filter": {"subtype": "Horse"}}


def test_if_they_do_rider_is_gated_and_unconditional_sentences_are_not():
    gated = parse_effect_body("target opponent gains control of target permanent you control. if they do, you draw 3 cards.")
    assert gated[1].condition == {"kind": "control_changed_this_way"}
    plain = parse_effect_body("choose another player. that player gains control of target treasure you control. you draw a card.")
    assert [s.type for s in plain] == ["give_control", "draw"] and plain[1].condition is None


def test_donate_changes_control_and_it_stays_after_the_source_is_gone():
    eng = game()
    bear = board(eng, creature("Bear"))
    p2 = eng.state.player_by_id("p2")
    spell = cast(eng, "Donate", [p2, bear], {"U": 1, "C": 2})
    assert bear.controller_id == "p2" and bear.owner_id == "p1"
    assert spell.zone == Zone.GRAVEYARD  # the instant-speed source is long gone; control is indefinite (RULE 611.2a)
    eng.state.current_step = "cleanup"
    eng._step_cleanup()
    assert bear.controller_id == "p2"
    assert bear.summoning_sick  # RULE 302.6: it has not been under p2's control since their turn began


def test_harmless_offering_hands_over_a_noncreature_permanent():
    eng = game()
    rock = board(eng, Card(id="rock", name="Rock", type_line="Artifact"))
    cast(eng, "Harmless Offering", [eng.state.player_by_id("p2"), rock], {"R": 1, "C": 2})
    assert rock.controller_id == "p2"


def test_donate_target_must_be_yours():
    eng = game()
    theirs = board(eng, creature("Theirs"), "p2")
    from mtg_analyzer.game.targeting import legal_targets
    effect = __import__("mtg_analyzer.game.binding.core", fromlist=["build_effects"]).build_effects(
        parse_effect_body("target player gains control of target permanent you control."), None)[0]
    options = legal_targets(eng.state, "p1", effect.extra_target_specs[0])
    assert theirs.instance_id not in {o.get("instance_id") for o in options}


def test_wrong_turn_takes_any_creature_and_an_already_owned_one_changes_nothing():
    eng = game()
    theirs = board(eng, creature("Theirs"), "p2")
    mine = board(eng, creature("Mine"))
    p2 = eng.state.player_by_id("p2")
    cast(eng, "Wrong Turn", [p2, mine], {"U": 1, "C": 2})
    assert mine.controller_id == "p2"
    cast(eng, "Wrong Turn", [p2, theirs], {"U": 1, "C": 2})
    assert theirs.controller_id == "p2"  # already theirs: nothing happens, no crash


def test_illegal_permanent_at_resolution_does_nothing():
    eng = game()
    bear = board(eng, creature("Bear"))
    p2 = eng.state.player_by_id("p2")
    card = DB.get_card("Donate")
    spell = GameObject(card, owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(spell)
    p1 = eng.state.player_by_id("p1")
    p1.hand.append(spell)
    p1.mana_pool.add_many({"U": 1, "C": 2})
    eng.cast_spell(p1, spell, targets=[p2, bear])
    bear.controller_id = "p2"  # control changed in response: "target permanent you control" is no longer legal
    eng.resolve_until_stable()
    assert bear.controller_id == "p2" and not eng.rules.context.former_controller_ids


def test_bazaar_trader_gives_an_artifact_creature_or_land_but_not_an_enchantment():
    eng = game()
    trader = board(eng, DB.get_card("Bazaar Trader"))
    land = board(eng, Card(id="forest", name="Forest", type_line="Basic Land — Forest", is_land=True))
    aura = board(eng, Card(id="ench", name="Ench", type_line="Enchantment"))
    p2 = eng.state.player_by_id("p2")
    from mtg_analyzer.game.targeting import legal_targets
    from mtg_analyzer.game.binding.core import build_effects
    effect, = build_effects(parse_effect_body("target player gains control of target artifact, creature, or land you control."), trader)
    spec = effect.extra_target_specs[0]
    ids = {o.get("instance_id") for o in legal_targets(eng.state, "p1", spec, trader)}
    assert land.instance_id in ids and trader.instance_id in ids and aura.instance_id not in ids
    eng.activate_ability(eng.state.player_by_id("p1"), trader, targets=[p2, land])
    eng.resolve_until_stable()
    assert land.controller_id == "p2"


def _mode_effects(name, index, source):
    """The bound effects of one printed mode bullet of a real card, read from its Oracle text."""
    from mtg_analyzer.game.binding.core import build_effects
    from mtg_analyzer.parser.oracle.normalize import normalize
    card = DB.get_card(name)
    bullets = [line for line in normalize(card.oracle_text, card.name).split("\n") if line.startswith("•")]
    body = bullets[index].lstrip("• ").split(" — ", 1)[-1] if "—" in bullets[index] else bullets[index].lstrip("• ")
    specs = parse_effect_body(body)
    assert specs is not None, body
    return build_effects(specs, source)


def _run(eng, effects, targets, source):
    from mtg_analyzer.game.effects.core import _apply_effects_partitioned
    _apply_effects_partitioned(effects, eng.rules.context, targets, None, source=source)


def test_bill_ferny_if_they_do_removes_it_from_combat_and_makes_treasures():
    eng = game()
    ferny = board(eng, DB.get_card("Bill Ferny, Bree Swindler"))
    horse = board(eng, creature("Pony", type_line="Creature — Horse"))
    ferny.attacking = True
    _run(eng, _mode_effects("Bill Ferny, Bree Swindler", 1, ferny), [eng.state.player_by_id("p2"), horse], ferny)
    assert horse.controller_id == "p2" and ferny.attacking is False
    assert sum(1 for o in eng.state.permanents_controlled_by("p1") if o.name == "Treasure") == 3


def test_bill_ferny_rider_is_skipped_when_the_target_is_not_a_horse():
    eng = game()
    ferny = board(eng, DB.get_card("Bill Ferny, Bree Swindler"))
    bear = board(eng, creature("Bear"))  # not a Horse: an illegal target for the permanent
    ferny.attacking = True
    _run(eng, _mode_effects("Bill Ferny, Bree Swindler", 1, ferny), [eng.state.player_by_id("p2"), bear], ferny)
    assert bear.controller_id == "p1" and ferny.attacking is True
    assert not [o for o in eng.state.permanents_controlled_by("p1") if o.name == "Treasure"]


def test_rules_of_acquisition_donate_mode_draws_only_if_they_took_it():
    eng = game()
    mine = board(eng, creature("Mine"))
    p1, p2 = eng.state.player_by_id("p1"), eng.state.player_by_id("p2")
    hand_before = len(p1.hand)
    cast(eng, "Rules of Acquisition", [p2, mine], {"U": 2, "C": 3}, mode=1)
    assert mine.controller_id == "p2" and len(p1.hand) == hand_before + 3


def test_rules_of_acquisition_steal_mode_draws_for_the_former_controller():
    eng = game()
    theirs = board(eng, creature("Theirs"), "p2")
    p1, p2 = eng.state.player_by_id("p1"), eng.state.player_by_id("p2")
    opp_hand, my_hand = len(p2.hand), len(p1.hand)
    cast(eng, "Rules of Acquisition", [theirs], {"U": 2, "C": 3}, mode=0)
    assert theirs.controller_id == "p1" and len(p2.hand) == opp_hand + 3 and len(p1.hand) == my_hand


def test_financier_chooses_the_only_other_player_and_draws():
    eng = game()
    fin = board(eng, DB.get_card("Discerning Financier"))
    treasure = board(eng, Card(id="t", name="Treasure", type_line="Token Artifact — Treasure"))
    assert fin.activated_abilities
    p1 = eng.state.player_by_id("p1")
    p1.mana_pool.add_many({"W": 1, "C": 2})
    hand_before = len(p1.hand)
    eng.activate_ability(p1, fin, targets=[treasure])
    eng.resolve_until_stable()
    assert treasure.controller_id == "p2" and len(p1.hand) == hand_before + 1


def test_financier_asks_when_several_players_remain():
    eng = game(players=3)
    fin = board(eng, DB.get_card("Discerning Financier"))
    treasure = board(eng, Card(id="t", name="Treasure", type_line="Token Artifact — Treasure"))
    p1 = eng.state.player_by_id("p1")
    p1.mana_pool.add_many({"W": 1, "C": 2})
    hand_before = len(p1.hand)
    eng.activate_ability(p1, fin, targets=[treasure])
    eng.resolve_until_stable()
    choice = eng.state.pending_choice
    assert choice is not None and choice["kind"] == "give_control_recipient"
    assert {o["id"] for o in choice["options"]} == {"p2", "p3"}
    eng.rules.resolve_choice("p3")
    eng.resolve_until_stable()
    assert treasure.controller_id == "p3" and len(p1.hand) == hand_before + 1


def test_blim_hands_a_permanent_to_the_damaged_player_and_each_player_pays_for_foreign_permanents():
    eng = game()
    blim = board(eng, DB.get_card("Blim, Comedic Genius"))
    gift = board(eng, creature("Gift"))
    p1, p2 = eng.state.player_by_id("p1"), eng.state.player_by_id("p2")
    for i in range(3):
        p1.hand.append(GameObject(creature(f"H1-{i}"), owner_id="p1", zone=Zone.HAND))
        p2.hand.append(GameObject(creature(f"H2-{i}"), owner_id="p2", zone=Zone.HAND))
    eng.rules.deal_damage(p2, 2, source=blim, combat=True)
    eng.resolve_until_stable()
    assert eng.state.pending_choice["kind"] == "trigger_target"
    eng.rules.resolve_choice(str(gift.instance_id))
    eng.resolve_until_stable()
    assert gift.controller_id == "p2" and gift.owner_id == "p1"
    discard = eng.state.pending_choice  # p2, the player who now controls a permanent they don't own, picks the discard
    assert discard["action"] == "discard" and discard["player_id"] == "p2" and discard["count"] == 1
    eng.rules.resolve_choice(discard["options"][0]["id"])
    eng.resolve_until_stable()
    # p2 controls one permanent it does not own: loses 1 life (plus the 2 damage) and discards 1; p1 controls none.
    assert p2.life == 20 - 2 - 1 and len(p2.hand) == 2
    assert p1.life == 20 and len(p1.hand) == 3


def test_control_stays_with_the_recipient_after_the_source_permanent_leaves():
    eng = game()
    trader = board(eng, DB.get_card("Bazaar Trader"))
    land = board(eng, Card(id="forest", name="Forest", type_line="Basic Land — Forest", is_land=True))
    eng.activate_ability(eng.state.player_by_id("p1"), trader, targets=[eng.state.player_by_id("p2"), land])
    eng.resolve_until_stable()
    eng.rules.move_to_graveyard(trader) if hasattr(eng.rules, "move_to_graveyard") else eng.state.battlefield.remove(trader)
    eng.recompute_continuous_effects()
    assert land.controller_id == "p2" and land.owner_id == "p1"


def test_a_donated_attacker_leaves_combat():
    eng = game()
    attacker = board(eng, creature("Attacker"))
    attacker.attacking = True
    cast(eng, "Donate", [eng.state.player_by_id("p2"), attacker], {"U": 1, "C": 2})
    assert attacker.controller_id == "p2" and attacker.attacking is False  # RULE 506.4
