"""PAR-107…114 residue batches, part 11 — "`<player>` skips their next untap step / draw step / combat phase".

`skip_next_step` used to skip only the controller's own next draw step (Elfhame Sanctuary). It now takes a player
target (Fatigue, Stonehorn Dignitary, Moment of Silence, Yosei), `each_opponent` (Brine Elemental) or the firing
event's player (Blinding Angel, Shisato), and a skipped *phase* passes over every one of its steps (RULE 500.11).

Reference: game/effects/core.py (`SkipNextStepEffect`), game/engine/turn_loop_mixin.py (`_run_step`),
game/phases.py (`GamePhase.skipped`), parser/oracle/catalogue/handlers.py (`_SKIP_THEIR_NEXT_RE`).
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import build_effects
from mtg_analyzer.game.effects.core import GameContext, _apply_effects_partitioned
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.game.phases import default_turn_sequence
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.spec import EffectSpec


def _engine():
    eng = GameEngine.new_game([("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0)
    eng.begin_turn()
    return eng


def _skip(eng, step, targets=None, **params):
    source = GameObject(Card(id="s", name="Src", type_line="Creature", is_creature=True, power=1, toughness=1),
                        owner_id="p1", zone=Zone.BATTLEFIELD)
    source.controller_id = "p1"
    effects = build_effects([EffectSpec("skip_next_step", {"step": step, **params})], source)
    _apply_effects_partitioned(effects, GameContext(eng.state, eng.rules), targets, None, source=source)


def test_real_cards_parse():
    for name, text, type_line in [
        ("Fatigue", "Target player skips their next draw step.", "Sorcery"),
        ("Moment of Silence", "Target player skips their next combat phase this turn.", "Instant"),
        ("Stonehorn Dignitary", "When this creature enters, target opponent skips their next combat phase.",
         "Creature — Elephant"),
        ("Brine Elemental", "When this creature is turned face up, each opponent skips their next untap step.",
         "Creature — Elemental"),
        ("Blinding Angel", "Flying\nWhenever this creature deals combat damage to a player, that player skips "
         "their next combat phase.", "Creature — Angel"),
    ]:
        result = parse_oracle(Card(id=name, name=name, type_line=type_line, oracle_text=text,
                                   is_creature="Creature" in type_line, is_sorcery=type_line == "Sorcery",
                                   is_instant=type_line == "Instant"))
        assert result.modeled, (name, result.unclaimed)


def test_that_player_after_an_earlier_pick_is_not_read_as_the_event_player():
    result = parse_oracle(Card(id="d", name="Dovin", type_line="Planeswalker — Dovin", oracle_text=(
        "−9: Tap all permanents target opponent controls. That player skips their next untap step.")))
    assert not result.modeled


def test_target_player_loses_only_their_own_next_draw_step():
    eng = _engine()
    p1, p2 = (eng.state.player_by_id(i) for i in ("p1", "p2"))
    _skip(eng, "draw", targets=[p2], target_kind="player")
    assert not eng.rules.should_skip_step(p1, "draw")  # the caster keeps theirs
    assert eng.rules.should_skip_step(p2, "draw")
    assert not eng.rules.should_skip_step(p2, "draw")  # spent: only the *next* one


def test_each_opponent_skips_and_the_caster_does_not():
    eng = _engine()
    _skip(eng, "untap", selector="each_opponent")
    assert not eng.rules.should_skip_step(eng.state.player_by_id("p1"), "untap")
    assert eng.rules.should_skip_step(eng.state.player_by_id("p2"), "untap")


def test_a_skipped_combat_phase_passes_over_every_step_of_it_once():
    eng = _engine()
    p2 = eng.state.player_by_id("p2")
    eng.state.active_player_index = 1
    _skip(eng, "combat", targets=[p2], target_kind="player")
    begun: list[str] = []
    real_fire = eng.state.fire_event

    def spy(event, *a, **kw):
        if event.type == EventType.STEP_BEGIN:
            begun.append(event.get("step"))
        return real_fire(event, *a, **kw)

    eng.state.fire_event = spy
    for _ in range(2):  # this turn's combat phase, then a later one
        phases = {ph.name: ph for ph in default_turn_sequence().phases}
        combat = phases["combat"]
        for step in combat.steps:
            eng._run_step(combat, step)
        if _ == 0:
            assert combat.skipped and begun == []
    assert begun == ["begin_combat", "declare_attackers", "declare_blockers", "combat_damage", "end_combat"][:len(begun)]
    assert len(begun) >= 4  # the second (unskipped) combat phase ran


def test_blinding_angel_skips_the_damaged_players_combat_not_its_controllers():
    from mtg_analyzer.game.binding.core import bind_from_catalogue

    eng = _engine()
    p1, p2 = eng.state.player_by_id("p1"), eng.state.player_by_id("p2")
    angel = GameObject(Card(id="a", name="Blinding Angel", type_line="Creature — Angel", is_creature=True,
                            power=3, toughness=3, oracle_text=("Flying\nWhenever this creature deals combat damage "
                                                               "to a player, that player skips their next combat "
                                                               "phase.")), owner_id="p1", zone=Zone.BATTLEFIELD)
    angel.controller_id = "p1"
    bind_from_catalogue(angel)
    eng.state.add_to_battlefield(angel)
    eng.rules.deal_damage(p2, 3, source=angel, combat=True)
    assert eng.rules.put_triggers_on_stack() == 1
    eng.rules.resolve_top_of_stack()
    assert eng.rules.should_skip_step(p2, "combat") and not eng.rules.should_skip_step(p1, "combat")
