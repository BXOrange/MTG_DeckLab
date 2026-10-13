"""PAR-163 -- the duration "until the end of your next turn" (RULE 611.2 / 514.2).

The shared clock is `durations.owners_next_turn_has_ended`: an effect created in turn N by player P ends at the
*cleanup of P's next turn* -- not the turn it was made in, even when that is P's own, and not an opponent's turn in
between.  Every family below runs the live engine through the current turn, an opponent's turn and P's next turn, and
asserts the effect holds up to that cleanup and is gone right after it: control changes (`gain_control_until_eot`
with ``duration="end_of_your_next_turn"``), exile-and-may-play permissions, the discard-trigger exile, and a floating
grant (`GrantUntilEffect`).  Extra turns, a departed player and undo (snapshots) are covered too.
"""

from __future__ import annotations

import copy

import pytest

from mtg_analyzer.game import combat, durations
from mtg_analyzer.game.binding.core import build_effects
from mtg_analyzer.game.effects.core import GameContext, StaticAbility, _apply_effects_partitioned
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
from mtg_analyzer.parser.oracle.spec import EffectSpec

LIBRARY_FILLER = 40  # enough draws that no test can deck out


def _engine(players: int = 2) -> GameEngine:
    eng = GameEngine.new_game(
        [(f"p{i + 1}", f"P{i + 1}", []) for i in range(players)], starting_life=20, starting_hand=0,
    )
    for player in eng.state.players:
        for n in range(LIBRARY_FILLER):
            player.add_to_zone(
                GameObject(Card(id=f"f{player.id}{n}", name="Filler", type_line="Land", is_land=True),
                           owner_id=player.id, zone=Zone.LIBRARY),
                Zone.LIBRARY,
            )
    eng.start()
    return eng


def _creature(eng, owner, name="Bear"):
    obj = GameObject(
        Card(id=name, name=name, type_line="Creature -- Bear", is_creature=True, power=2, toughness=2,
             mana_cost_string="{2}", converted_mana_cost=2),
        owner_id=owner, zone=Zone.BATTLEFIELD,
    )
    obj.controller_id = owner
    eng.state.add_to_battlefield(obj)
    return obj


def _source(eng, controller="p1", name="Source"):
    src = GameObject(Card(id=name, name=name, type_line="Enchantment"), owner_id=controller, zone=Zone.BATTLEFIELD)
    src.controller_id = controller
    eng.state.add_to_battlefield(src)
    return src


def _run_to_step(eng, step):
    guard = 0
    while eng.state.current_step != step:
        eng.advance_step()
        guard += 1
        assert guard < 80, f"never reached {step!r}"


def _into_next_turn(eng, step="main1"):
    """Finish the current turn (its cleanup runs) and play into ``step`` of the next one."""
    turn = eng.state.internal_turn.number
    guard = 0
    while eng.state.internal_turn.number == turn:
        eng.advance_step()
        guard += 1
        assert guard < 80
    _run_to_step(eng, step)


def _through(eng, check):
    """Walk P1's effect through its whole life: ``check(point)`` is called at every checkpoint.

    Created on P1's own turn (turn 1).  Checkpoints: ``own_cleanup`` (cleanup of the creating turn), ``opp_turn``
    (P2's turn), ``opp_cleanup``, ``next_main`` (P1's next turn, main phase), ``next_end`` (its end step), ``after``
    (its cleanup).
    """
    _run_to_step(eng, "cleanup")
    check("own_cleanup")
    _into_next_turn(eng)
    assert eng.state.active_player.id == "p2"
    check("opp_turn")
    _run_to_step(eng, "cleanup")
    check("opp_cleanup")
    _into_next_turn(eng)
    assert eng.state.active_player.id == "p1"
    check("next_main")
    _run_to_step(eng, "end")
    check("next_end")
    _run_to_step(eng, "cleanup")
    check("after")


def _apply(eng, specs, src, targets=None, trigger_event=None):
    effects = build_effects(specs, source=src)
    ctx = GameContext(eng.state, eng.rules)
    if trigger_event is not None:
        ctx.trigger_event = trigger_event
    _apply_effects_partitioned(effects, ctx, targets or [], None, source=src)
    eng.recompute_continuous_effects()


# --- the shared clock ------------------------------------------------------------------------------------------------


def test_clock_waits_for_the_owners_next_turn_not_the_creating_turn():
    eng = _engine()
    created = eng.state.internal_turn.number
    assert not durations.owners_next_turn_has_ended(eng.state, "p1", created)  # p1's own turn it was created in
    _run_to_step(eng, "cleanup")
    assert not durations.owners_next_turn_has_ended(eng.state, "p1", created)  # RULE 514.2: still the same turn
    _into_next_turn(eng)
    assert not durations.owners_next_turn_has_ended(eng.state, "p1", created)  # an opponent's turn
    _into_next_turn(eng)
    assert eng.state.active_player.id == "p1"
    assert durations.owners_next_turn_has_ended(eng.state, "p1", created)


def test_clock_ends_for_a_player_who_left_the_game():
    eng = _engine(3)
    eng.state.player_by_id("p1").has_lost = True
    assert durations.owners_next_turn_has_ended(eng.state, "p1", eng.state.internal_turn.number)


# --- family 1: control changes ---------------------------------------------------------------------------------------


_WYLL = ("gain control of target artifact or creature an opponent controls with mana value 4 or less "
         "until the end of your next turn.")


def _take(eng, target, controller="p1"):
    _apply(eng, parse_effect_body(_WYLL), _source(eng, controller), [target])


def test_wyll_parses_to_the_next_turn_control_change():
    specs = parse_effect_body(_WYLL)
    assert [s.type for s in specs] == ["gain_control_until_eot"]
    assert specs[0].params["duration"] == "end_of_your_next_turn"
    assert specs[0].params["max_mana_value"] == 4
    assert specs[0].params["haste"] is False and specs[0].params["untap"] is False


def test_control_change_lasts_through_the_takers_next_turn_cleanup():
    eng = _engine()
    victim = _creature(eng, "p2")
    _take(eng, victim)
    assert victim.controller_id == "p1"
    seen = {}
    _through(eng, lambda point: seen.__setitem__(point, victim.controller_id))
    assert seen == {
        "own_cleanup": "p1", "opp_turn": "p1", "opp_cleanup": "p1",
        "next_main": "p1", "next_end": "p1", "after": "p2",
    }
    assert victim.control_change_until_owner_turn is None


def test_control_change_ends_at_the_extra_turn_cleanup_when_that_is_the_takers_next_turn():
    # RULE 500.7: P1's next turn is the extra turn that follows this one, so it ends at *that* cleanup.
    eng = _engine()
    victim = _creature(eng, "p2")
    _take(eng, victim)
    eng.state.extra_turns.append("p1")
    _run_to_step(eng, "cleanup")
    assert victim.controller_id == "p1"
    _into_next_turn(eng)
    assert eng.state.active_player.id == "p1"  # the extra turn, not p2's
    assert victim.controller_id == "p1"
    _run_to_step(eng, "cleanup")
    assert victim.controller_id == "p2"


def test_control_change_is_handed_back_when_the_taker_leaves_the_game():
    # RULE 800.4a: continuous effects giving the departed player control end.
    eng = _engine(3)
    victim = _creature(eng, "p2")
    _take(eng, victim)
    assert victim.controller_id == "p1"
    p1 = eng.state.player_by_id("p1")
    p1.has_lost = True
    eng.rules.remove_player_from_game(p1)
    assert victim.controller_id == "p2"
    assert victim in eng.state.battlefield


def test_control_change_record_survives_a_snapshot_round_trip():
    eng = _engine()
    victim = _creature(eng, "p2")
    _take(eng, victim)
    clone = copy.deepcopy(victim)
    assert clone.control_change_until_owner_turn == victim.control_change_until_owner_turn
    assert clone.control_change_until_owner_turn["player_id"] == "p1"


def test_treasure_nabber_takes_the_rock_on_the_opponents_turn_and_returns_it_after_its_own_next_turn():
    from mtg_analyzer.game.binding.core import bind_from_catalogue

    eng = _engine()
    nabber = GameObject(
        Card(id="nab", name="Treasure Nabber", type_line="Creature -- Goblin Rogue", is_creature=True, power=3,
             toughness=2,
             oracle_text="Whenever an opponent taps an artifact for mana, gain control of that artifact until the "
                         "end of your next turn."),
        owner_id="p1", zone=Zone.BATTLEFIELD,
    )
    nabber.controller_id = "p1"
    eng.state.add_to_battlefield(nabber)
    bind_from_catalogue(nabber)
    rock = GameObject(Card(id="rock", name="Sol Ring", type_line="Artifact", oracle_text="{T}: Add {C}{C}."),
                      owner_id="p2", zone=Zone.BATTLEFIELD)
    rock.controller_id = "p2"
    eng.state.add_to_battlefield(rock)
    bind_from_catalogue(rock)
    _run_to_step(eng, "cleanup")
    _into_next_turn(eng)
    assert eng.state.active_player.id == "p2"
    eng.tap_for_mana(eng.state.player_by_id("p2"), rock)
    eng.resolve_until_stable()
    assert rock.controller_id == "p1"  # taken mid-way through p2's own turn
    _run_to_step(eng, "cleanup")
    assert rock.controller_id == "p1"  # p2's cleanup is not p1's turn
    _into_next_turn(eng)
    assert eng.state.active_player.id == "p1"
    assert rock.controller_id == "p1"
    _run_to_step(eng, "cleanup")
    assert rock.controller_id == "p2"


# --- family 2: exile and "you may play that card" --------------------------------------------------------------------


_SCROLLSMITH = ("exile target noncreature, nonland card from your graveyard. "
                "until the end of your next turn, you may cast that card.")


@pytest.mark.parametrize("oracle", [
    "When ~ enters, exile target noncreature, nonland card from your graveyard. Until the end of your next turn, "
    "you may cast that card.",
    "When ~ enters, exile target card with a cycling ability from your graveyard. Until the end of your next turn, "
    "you may play that card.",
    "When ~ enters, exile target equipment, instant, or sorcery card from your graveyard. Until the end of your next "
    "turn, you may play that card.",
    "When ~ enters, exile up to one target instant or sorcery card from your graveyard. You may cast that card until "
    "the end of your next turn.",
    "Exile target creature. Until the end of your next turn, you may cast that card and you may spend mana as "
    "though it were mana of any color to cast that spell.",
])
def test_exile_then_play_window_cards_are_modeled(oracle):
    spell = not oracle.startswith("When")
    card = Card(id="x", name="Windowed", type_line="Sorcery" if spell else "Creature -- Bear", is_sorcery=spell,
                is_creature=not spell, power=None if spell else 1, toughness=None if spell else 1, oracle_text=oracle)
    assert parse_oracle(card).modeled is True


def test_a_play_sentence_needs_exactly_one_window_phrase():
    assert match_clause("you may cast that card") is None
    assert match_clause(
        "until the end of your next turn, you may cast that card until the end of your next turn"
    ) is None


def _graveyard_spell(name, cost="{2}", cmc=2):
    return GameObject(
        Card(id=name, name=name, type_line="Sorcery", is_sorcery=True, mana_cost_string=cost,
             converted_mana_cost=cmc),
        owner_id="p1", zone=Zone.GRAVEYARD,
    )


def _scrollsmith(eng, card):
    p1 = eng.state.player_by_id("p1")
    p1.add_to_zone(card, Zone.GRAVEYARD)
    _apply(eng, parse_effect_body(_SCROLLSMITH), _source(eng), [card])
    return p1


def test_graveyard_exile_play_window_persists_then_lapses_at_the_next_turn_cleanup():
    eng = _engine()
    card = _graveyard_spell("Old Sorcery")
    p1 = _scrollsmith(eng, card)
    assert card.zone == Zone.EXILE
    assert eng._has_temp_play_permission(card, p1)
    assert card.instance_id in eng.state.temp_play_spells_only  # "cast": never a land play
    seen = {}
    _through(eng, lambda point: seen.__setitem__(point, eng._has_temp_play_permission(card, p1)))
    assert seen == {
        "own_cleanup": True, "opp_turn": True, "opp_cleanup": True, "next_main": True, "next_end": True,
        "after": False,
    }
    assert card.instance_id not in eng.state.temp_play_permissions


def test_the_play_window_is_castable_in_the_takers_next_turn_main_phase():
    eng = _engine()
    card = _graveyard_spell("Free Sorcery", cost="", cmc=0)
    p1 = _scrollsmith(eng, card)
    _run_to_step(eng, "cleanup")
    _into_next_turn(eng)
    _into_next_turn(eng)  # back on p1's turn, main phase
    assert eng.state.active_player.id == "p1"
    assert eng.can_cast(p1, card)


def test_play_window_ends_at_the_extra_turn_cleanup_when_that_is_the_next_turn():
    eng = _engine()
    card = _graveyard_spell("Old Sorcery")
    p1 = _scrollsmith(eng, card)
    eng.state.extra_turns.append("p1")
    _run_to_step(eng, "cleanup")
    _into_next_turn(eng)
    assert eng.state.active_player.id == "p1"
    assert eng._has_temp_play_permission(card, p1)
    _run_to_step(eng, "cleanup")
    assert not eng._has_temp_play_permission(card, p1)


def test_hurl_through_hell_window_belongs_to_the_caster_and_carries_the_wildcard():
    specs = parse_effect_body(
        "exile target creature. until the end of your next turn, you may cast that card and you may spend mana "
        "as though it were mana of any color to cast that spell."
    )
    assert [s.type for s in specs] == ["exile", "grant_play_window_previous_exiled"]
    assert specs[1].params == {"only_spells": True, "mana_wildcard": "color"}
    eng = _engine()
    victim = _creature(eng, "p2")
    _apply(eng, specs, _source(eng), [victim])
    assert victim.zone == Zone.EXILE
    assert eng.state.mana_wildcard_permission[victim.instance_id] == "color"
    assert eng.state.temp_play_permission_player[victim.instance_id] == "p1"
    assert eng._has_temp_play_permission(victim, eng.state.player_by_id("p1"))
    assert not eng._has_temp_play_permission(victim, eng.state.player_by_id("p2"))
    seen = {}
    p1 = eng.state.player_by_id("p1")
    _through(eng, lambda point: seen.__setitem__(point, eng._has_temp_play_permission(victim, p1)))
    assert [seen[k] for k in ("own_cleanup", "opp_turn", "next_main", "after")] == [True, True, True, False]


def test_moonstone_discard_exile_window():
    card = Card(
        id="ms", name="Moonstone, Harsh Mistress", type_line="Legendary Creature -- Human Rogue", is_creature=True,
        power=2, toughness=3,
        oracle_text="Whenever you discard a card, you may exile that card from your graveyard. If you do, until the "
                    "end of your next turn, you may play that card.",
    )
    assert parse_oracle(card).modeled is True
    specs = parse_effect_body(
        "exile that card from your graveyard. if you do, until the end of your next turn, you may play that card."
    )
    assert [(s.type, s.params) for s in specs] == [
        ("exile_triggering_discard_may_play_this_turn", {"same_turn_only": False})
    ]
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    discarded = _graveyard_spell("Discarded")
    p1.add_to_zone(discarded, Zone.GRAVEYARD)
    _apply(eng, specs, _source(eng), trigger_event={"instance_id": discarded.instance_id})
    assert discarded.zone == Zone.EXILE
    seen = {}
    _through(eng, lambda point: seen.__setitem__(point, eng._has_temp_play_permission(discarded, p1)))
    assert [seen[k] for k in ("own_cleanup", "opp_turn", "next_main", "next_end", "after")] == [
        True, True, True, True, False,
    ]


def test_this_turn_discard_exile_now_lapses_at_cleanup():
    # Containment Construct's "this turn" permission used to carry no holder and so was never swept.
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    discarded = _graveyard_spell("Discarded")
    p1.add_to_zone(discarded, Zone.GRAVEYARD)
    _apply(eng, [EffectSpec("exile_triggering_discard_may_play_this_turn", {})], _source(eng),
           trigger_event={"instance_id": discarded.instance_id})
    assert eng._has_temp_play_permission(discarded, p1)
    _run_to_step(eng, "cleanup")
    assert not eng._has_temp_play_permission(discarded, p1)


def test_lidless_gaze_style_each_library_window_with_any_type_mana():
    specs = parse_effect_body(
        "exile the top card of each player's library. until the end of your next turn, you may play those cards, "
        "and mana of any type can be spent to cast those spells."
    )
    assert [(s.type, s.params) for s in specs] == [(
        "impulsive_draw",
        {"count": 1, "same_turn_only": False, "each_player": True, "mana_wildcard": "type"},
    )]
    eng = _engine(2)
    _apply(eng, specs, _source(eng))
    p1 = eng.state.player_by_id("p1")
    exiled = [o for p in eng.state.players for o in p.exile]
    assert len(exiled) == 2
    seen = {}
    _through(eng, lambda point: seen.__setitem__(
        point, all(eng._has_temp_play_permission(o, p1) for o in exiled)))
    assert [seen[k] for k in ("own_cleanup", "opp_turn", "next_main", "after")] == [True, True, True, False]


def test_snowslope_hunter_style_activation_restrictions_are_both_kept():
    card = Card(
        id="sh", name="Snowslope Hunter", type_line="Creature -- Human Warrior", is_creature=True, power=2,
        toughness=3,
        oracle_text="Sacrifice another creature or artifact: Exile the top card of your library. You may play it "
                    "until the end of your next turn. Activate only during your turn and only once each turn.",
    )
    assert parse_oracle(card).modeled is True
    specs = parse_effect_body("activate only during your turn and only once each turn.")
    assert [s.type for s in specs] == ["only_during_your_turn_marker", "once_per_turn_marker"]


def test_mosswood_dreadknight_adventure_window_parse():
    specs = parse_effect_body("cast it from your graveyard as an adventure until the end of your next turn.")
    assert [s.type for s in specs] == ["grant_self_adventure_cast_from_graveyard"]


# --- family 3: floating grants (GrantUntilEffect) --------------------------------------------------------------------


def test_grants_and_pumps_parse_to_the_new_duration():
    specs = match_clause("target creature gains flying until the end of your next turn")
    assert [(s.type, s.params["duration"]) for s in specs] == [("grant_until", "end_of_your_next_turn")]
    specs = match_clause("target creature gets +2/+0 until the end of your next turn")
    assert [(s.type, s.params["duration"]) for s in specs] == [("grant_until", "end_of_your_next_turn")]


def test_floating_grant_holds_until_the_creators_next_turn_cleanup():
    eng = _engine()
    bear = _creature(eng, "p1")
    _apply(eng, match_clause("target creature gains flying until the end of your next turn"), _source(eng), [bear])
    assert combat.has(bear, "flying")
    seen = {}

    def check(point):
        eng.recompute_continuous_effects()
        seen[point] = combat.has(bear, "flying")

    _through(eng, check)
    assert seen == {
        "own_cleanup": True, "opp_turn": True, "opp_cleanup": True, "next_main": True, "next_end": True,
        "after": False,
    }
    assert eng.state.floating_statics == []


def test_floating_grant_made_on_an_opponents_turn_still_waits_for_the_creators_turn():
    # Created by P1 during P2's turn (instant speed): P2's own cleanup must not end it.
    eng = _engine()
    bear = _creature(eng, "p1")
    _run_to_step(eng, "cleanup")
    _into_next_turn(eng)
    assert eng.state.active_player.id == "p2"
    _apply(eng, match_clause("target creature gains flying until the end of your next turn"), _source(eng), [bear])
    _run_to_step(eng, "cleanup")
    eng.recompute_continuous_effects()
    assert combat.has(bear, "flying")  # p2's cleanup: the creator's next turn has not been played yet
    _into_next_turn(eng)
    assert eng.state.active_player.id == "p1"
    eng.recompute_continuous_effects()
    assert combat.has(bear, "flying")
    _run_to_step(eng, "cleanup")
    eng.recompute_continuous_effects()
    assert not combat.has(bear, "flying")


def test_floating_grant_ends_when_its_creator_has_left():
    eng = _engine(3)
    bear = _creature(eng, "p2")
    _apply(eng, match_clause("target creature gains flying until the end of your next turn"), _source(eng), [bear])
    assert combat.has(bear, "flying")
    eng.state.player_by_id("p1").has_lost = True
    assert durations.sweep(eng.state, "cleanup") is True
    assert eng.state.floating_statics == []


def test_describe_names_the_new_duration():
    ability = StaticAbility("ability", affects="objects", params={})
    ability.duration = "end_of_your_next_turn"
    assert durations.describe(ability) == "bis zum Ende deines nächsten Zuges"
