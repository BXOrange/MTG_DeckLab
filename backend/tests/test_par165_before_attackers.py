"""PAR-165 -- "Activate only during your turn, before attackers are declared." (RULE 602.5d, RULE 508.1).

Parse: the clause is claimed as the own-turn marker plus a step cut-off marker and folds into
`ActivationCost.only_before_attackers`.  Engine: legal through the beginning phase, precombat main and beginning of
combat of the controller's own turn; illegal from the declare attackers step on, in the postcombat main and on any
opponent's turn.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone

LU_SU_TEXT = "{T}: Draw a card. Activate only during your turn, before attackers are declared."
LIBRARY_FILLER = 40


def _engine() -> GameEngine:
    eng = GameEngine.new_game([("p1", "P1", []), ("p2", "P2", [])], starting_life=20, starting_hand=0)
    for player in eng.state.players:
        for n in range(LIBRARY_FILLER):
            player.add_to_zone(
                GameObject(Card(id=f"f{player.id}{n}", name="Filler", type_line="Land", is_land=True),
                           owner_id=player.id, zone=Zone.LIBRARY),
                Zone.LIBRARY,
            )
    eng.start()
    return eng


def _lu_su(eng, controller="p1"):
    obj = GameObject(
        Card(id="Lu Su", name="Lu Su, Wu Advisor", type_line="Legendary Creature -- Human Advisor",
             is_creature=True, power=2, toughness=4, oracle_text=LU_SU_TEXT),
        owner_id=controller, zone=Zone.BATTLEFIELD,
    )
    obj.controller_id = controller
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    eng.state.add_to_battlefield(obj)
    return obj


def _run_to_step(eng, step):
    guard = 0
    while eng.state.current_step != step:
        eng.advance_step()
        guard += 1
        assert guard < 80, f"never reached {step!r}"


def _can(eng, obj, player_id="p1"):
    [ability] = obj.activated_abilities
    obj.tapped = False
    return eng.can_activate(eng.state.player_by_id(player_id), obj, ability)


def test_clause_is_modeled_and_folds_into_the_cost_flag():
    eng = _engine()
    [ability] = _lu_su(eng).activated_abilities
    assert ability.cost.only_before_attackers is True
    assert ability.cost.only_during_your_turn is True


@pytest.mark.parametrize("step", ["upkeep", "draw", "main1", "begin_combat"])
def test_legal_before_the_declare_attackers_step_on_own_turn(step):
    eng = _engine()
    obj = _lu_su(eng)
    _run_to_step(eng, step)
    assert eng.state.active_player.id == "p1"
    assert _can(eng, obj)


@pytest.mark.parametrize("step", ["declare_attackers", "declare_blockers", "combat_damage", "end_combat", "main2", "end_step"])
def test_illegal_from_declare_attackers_on(step):
    eng = _engine()
    obj = _lu_su(eng)
    _run_to_step(eng, "main1")
    try:
        _run_to_step(eng, step)
    except AssertionError:
        pytest.skip(f"step {step} skipped with no attackers")
    assert not _can(eng, obj)


def test_illegal_on_opponents_turn():
    eng = _engine()
    obj = _lu_su(eng)
    _run_to_step(eng, "main1")
    guard = 0
    while eng.state.active_player.id != "p2" or eng.state.current_step != "main1":
        eng.advance_step()
        guard += 1
        assert guard < 120
    assert not _can(eng, obj)


# ---------------------------------------------------------------------------
# The family's remaining effect bodies, executed against the real engine
# ---------------------------------------------------------------------------

def _card_obj(eng, name, oracle, type_line="Creature -- Human", zone=Zone.BATTLEFIELD, owner="p1", **kw):
    is_creature = "Creature" in type_line
    pt = {"power": 2, "toughness": 2} if is_creature else {}
    obj = GameObject(Card(id=name, name=name, type_line=type_line, oracle_text=oracle,
                          is_creature=is_creature, **pt, **kw),
                     owner_id=owner, zone=zone)
    obj.controller_id = owner
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    if zone is Zone.BATTLEFIELD:
        eng.state.add_to_battlefield(obj)
    else:
        eng.state.player_by_id(owner).add_to_zone(obj, zone)
    return obj


def _activate(eng, src, targets=None):
    eng.activate_ability(eng.state.player_by_id("p1"), src, 0, targets=targets or [])
    eng.resolve_until_stable()


def test_stone_catapult_destroys_only_a_tapped_nonblack_creature():
    eng = _engine()
    _run_to_step(eng, "main1")
    catapult = _card_obj(eng, "Stone Catapult",
                         "{T}: Destroy target tapped nonblack creature. Activate only during your turn, before attackers are declared.")
    green = _card_obj(eng, "Green", "", owner="p2", color_identity=["G"])
    black = _card_obj(eng, "Black", "", owner="p2", color_identity=["B"])
    untapped = _card_obj(eng, "Untapped", "", owner="p2", color_identity=["G"])
    green.tapped = black.tapped = True
    from mtg_analyzer.game.targeting import effects_target_specs, legal_targets
    [spec] = effects_target_specs(catapult.activated_abilities[0].effects)
    ids = {o["instance_id"] for o in legal_targets(eng.state, "p1", spec, source=catapult)}
    assert ids == {green.instance_id}
    _activate(eng, catapult, [green])
    assert green.zone is Zone.GRAVEYARD and black.zone is Zone.BATTLEFIELD and untapped.zone is Zone.BATTLEFIELD


def test_xiahou_dun_returns_only_a_black_card_to_hand():
    eng = _engine()
    _run_to_step(eng, "main1")
    dun = _card_obj(eng, "Xiahou Dun", "Sacrifice ~: Return target black card from your graveyard to your hand. "
                    "Activate only during your turn, before attackers are declared.")
    black = _card_obj(eng, "BlackCard", "", type_line="Sorcery", zone=Zone.GRAVEYARD, color_identity=["B"])
    red = _card_obj(eng, "RedCard", "", type_line="Sorcery", zone=Zone.GRAVEYARD, color_identity=["R"])
    from mtg_analyzer.game.targeting import effects_target_specs, legal_targets
    [spec] = effects_target_specs(dun.activated_abilities[0].effects)
    assert {o["instance_id"] for o in legal_targets(eng.state, "p1", spec, source=dun)} == {black.instance_id}
    _activate(eng, dun, [black])
    assert black.zone is Zone.HAND and red.zone is Zone.GRAVEYARD and dun.zone is Zone.GRAVEYARD


def test_loyal_retainers_reanimates_only_a_legendary_creature_card():
    eng = _engine()
    _run_to_step(eng, "main1")
    ret = _card_obj(eng, "Loyal Retainers", "Sacrifice ~: Return target legendary creature card from your graveyard to the battlefield. "
                    "Activate only during your turn, before attackers are declared.")
    legend = _card_obj(eng, "Legend", "", type_line="Legendary Creature -- Human", zone=Zone.GRAVEYARD)
    legend.card.is_legendary = True
    plain = _card_obj(eng, "Plain", "", zone=Zone.GRAVEYARD)
    from mtg_analyzer.game.targeting import effects_target_specs, legal_targets
    [spec] = effects_target_specs(ret.activated_abilities[0].effects)
    assert {o["instance_id"] for o in legal_targets(eng.state, "p1", spec, source=ret)} == {legend.instance_id}
    _activate(eng, ret, [legend])
    assert legend.zone is Zone.BATTLEFIELD and plain.zone is Zone.GRAVEYARD


def test_coastal_wizard_bounces_itself_and_another_creature():
    eng = _engine()
    _run_to_step(eng, "main1")
    wiz = _card_obj(eng, "Coastal Wizard", "{T}: Return ~ and another target creature to their owners' hands. "
                    "Activate only during your turn, before attackers are declared.")
    other = _card_obj(eng, "Other", "", owner="p2")
    from mtg_analyzer.game.targeting import effects_target_specs, legal_targets
    [spec] = effects_target_specs(wiz.activated_abilities[0].effects)
    assert wiz.instance_id not in {o["instance_id"] for o in legal_targets(eng.state, "p1", spec, source=wiz)}
    _activate(eng, wiz, [other])
    assert wiz.zone is Zone.HAND and other.zone is Zone.HAND


def test_mana_ability_carries_the_before_attackers_gate():
    from mtg_analyzer.game.mana_abilities import parse_mana_abilities

    card = Card(id="m", name="Mana Dork", type_line="Creature -- Elf", is_creature=True, power=1, toughness=1,
                oracle_text="{T}: Add {G}. Activate only during your turn, before attackers are declared.")
    [ability] = parse_mana_abilities(card)
    assert ability.cost.only_before_attackers is True and ability.cost.only_during_your_turn is True
