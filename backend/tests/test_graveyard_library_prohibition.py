"""RULE 601.3a-adjacent Grafdigger's Cage/Weathered Runestone: "`<type>`
cards in graveyards and libraries can't enter the battlefield." + "Players
can't cast spells from graveyards or libraries." — MEC-12's last two
"broader gaps" (the players-can't-verb family's own graveyard/library-cast
half, and a genuine multi-site entry prohibition).

The cast half is one choke point (`GameEngine.can_cast`, gating every
graveyard/library-cast permission this engine has at once). The entry half
is deliberately *not* a universal `GameState.add_to_battlefield` hook —
there's no single site every graveyard/library-to-battlefield route already
funnels through — so it's checked at the two real ones:
`ReturnFromGraveyardEffect` (reanimation) and `RulesEngine._finish_search`
(a library/graveyard tutor whose destination is the battlefield). A
prohibited card simply stays where it was, per the real card's own ruling.
"""

from __future__ import annotations

from mtg_analyzer.game.effect_binder import bind_from_catalogue
from mtg_analyzer.game.effects import ReturnFromGraveyardEffect
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle


def make_engine(*player_ids):
    return GameEngine.new_game(
        [(pid, pid, []) for pid in player_ids], starting_life=20, starting_hand=0
    )


def cage_card():
    return Card(
        id="Grafdigger's Cage", name="Grafdigger's Cage", type_line="Artifact",
        oracle_text="Creature cards in graveyards and libraries can't enter "
                    "the battlefield.\n"
                    "Players can't cast spells from graveyards or libraries.",
    )


def runestone_card():
    return Card(
        id="Weathered Runestone", name="Weathered Runestone", type_line="Artifact",
        oracle_text="Nonland permanent cards in graveyards and libraries "
                    "can't enter the battlefield.\n"
                    "Players can't cast spells from graveyards or libraries.",
    )


def creature_card(name="Fodder"):
    return Card(
        id=name, name=name, type_line="Creature — Bear", is_creature=True,
        power=2, toughness=2, mana_cost_string="{2}{B}", converted_mana_cost=3,
    )


def instant_with_flashback(name="Flashy Bolt"):
    return Card(
        id=name, name=name, type_line="Instant", is_instant=True,
        mana_cost_string="{R}", converted_mana_cost=1,
        oracle_text="Flashback {2}{R}",
        keywords=["Flashback"],
    )


def put_bf(state, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


def test_grafdiggers_cage_is_modeled():
    result = parse_oracle(cage_card())
    assert result.coverage != UNMODELED
    assert result.unclaimed == []


def test_weathered_runestone_is_modeled():
    result = parse_oracle(runestone_card())
    assert result.coverage != UNMODELED
    assert result.unclaimed == []


def test_cage_blocks_flashback_casting_from_the_graveyard():
    eng = make_engine("p1", "p2")
    put_bf(eng.state, cage_card())
    spell_card = instant_with_flashback()
    obj = GameObject(spell_card, owner_id="p1", zone=Zone.GRAVEYARD)
    bind_from_catalogue(obj)
    eng.state.active_player.graveyard.append(obj)
    eng.rules.add_mana(eng.state.active_player, "R", 3)
    eng.state.current_step = "main1"

    assert eng.can_cast(eng.state.active_player, obj, alt_cost=False) is False


def test_without_the_cage_flashback_casting_from_the_graveyard_works():
    eng = make_engine("p1", "p2")
    spell_card = instant_with_flashback()
    obj = GameObject(spell_card, owner_id="p1", zone=Zone.GRAVEYARD)
    bind_from_catalogue(obj)
    eng.state.active_player.graveyard.append(obj)
    eng.rules.add_mana(eng.state.active_player, "R", 3)
    eng.state.current_step = "main1"

    assert eng.can_cast(eng.state.active_player, obj, alt_cost=False) is True


def test_cage_does_not_block_casting_from_hand():
    eng = make_engine("p1", "p2")
    put_bf(eng.state, cage_card())
    spell_card = instant_with_flashback()
    obj = GameObject(spell_card, owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(obj)
    eng.state.active_player.hand.append(obj)
    eng.rules.add_mana(eng.state.active_player, "R", 1)

    assert eng.can_cast(eng.state.active_player, obj, alt_cost=False) is True


def test_cage_stops_a_creature_from_reanimation():
    eng = make_engine("p1", "p2")
    put_bf(eng.state, cage_card())
    victim = GameObject(creature_card(), owner_id="p1", zone=Zone.GRAVEYARD)
    eng.state.active_player.graveyard.append(victim)

    effect = ReturnFromGraveyardEffect(target=victim, destination="battlefield")
    from mtg_analyzer.game.effects import GameContext
    context = GameContext(eng.state, eng.rules)
    effect.apply(context, targets=[victim])

    assert victim in eng.state.active_player.graveyard
    assert victim not in eng.state.battlefield


def test_without_the_cage_reanimation_works():
    eng = make_engine("p1", "p2")
    victim = GameObject(creature_card(), owner_id="p1", zone=Zone.GRAVEYARD)
    eng.state.active_player.graveyard.append(victim)

    effect = ReturnFromGraveyardEffect(target=victim, destination="battlefield")
    from mtg_analyzer.game.effects import GameContext
    context = GameContext(eng.state, eng.rules)
    effect.apply(context, targets=[victim])

    assert victim not in eng.state.active_player.graveyard
    assert victim in eng.state.battlefield


def test_cage_stops_a_tutored_creature_from_reaching_the_battlefield():
    eng = make_engine("p1", "p2")
    put_bf(eng.state, cage_card())
    quarry = GameObject(creature_card("Tutored Beast"), owner_id="p1", zone=Zone.LIBRARY)
    eng.state.active_player.library.append(quarry)
    player = eng.state.active_player

    eng.rules.request_search(player, criteria="Creature", destination="battlefield")
    eng.rules.resolve_search_choice(quarry.instance_id)

    assert quarry in eng.state.active_player.library
    assert quarry not in eng.state.battlefield


def test_runestone_stops_a_noncreature_permanent_from_reanimation():
    eng = make_engine("p1", "p2")
    put_bf(eng.state, runestone_card())
    artifact_card = Card(
        id="Some Artifact", name="Some Artifact", type_line="Artifact",
        mana_cost_string="{2}", converted_mana_cost=2,
    )
    victim = GameObject(artifact_card, owner_id="p1", zone=Zone.GRAVEYARD)
    eng.state.active_player.graveyard.append(victim)

    effect = ReturnFromGraveyardEffect(
        target=victim, destination="battlefield", target_kind="graveyard_artifact",
    )
    from mtg_analyzer.game.effects import GameContext
    context = GameContext(eng.state, eng.rules)
    effect.apply(context, targets=[victim])

    assert victim in eng.state.active_player.graveyard
    assert victim not in eng.state.battlefield


def test_runestone_does_not_stop_a_land_from_reanimation():
    eng = make_engine("p1", "p2")
    put_bf(eng.state, runestone_card())
    land_card = Card(
        id="Some Land", name="Some Land", type_line="Land — Forest", is_land=True,
    )
    victim = GameObject(land_card, owner_id="p1", zone=Zone.GRAVEYARD)
    eng.state.active_player.graveyard.append(victim)

    effect = ReturnFromGraveyardEffect(
        target=victim, destination="battlefield", target_kind="graveyard_land",
    )
    from mtg_analyzer.game.effects import GameContext
    context = GameContext(eng.state, eng.rules)
    effect.apply(context, targets=[victim])

    assert victim not in eng.state.active_player.graveyard
    assert victim in eng.state.battlefield
