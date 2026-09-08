"""MEC-33 — Omen Machine. "Players can't draw cards. At the beginning of
each player's draw step, that player exiles the top card of their library.
If it's a land card, the player puts it onto the battlefield. Otherwise,
the player casts it without paying its mana cost if able."

Two independent pieces: the already-shipped `draw_limit` primitive
(`continuous.max_draws_per_turn`, Spirit of the Labyrinth/Narset, Parter of
Veils) at `max_per_turn=0`, and a new `STEP_BEGIN`-on-"draw"-with-no-
`phase_relation` trigger (fires once per turn, for whoever the active
player is) chaining `ExileTopOfLibraryEffect`'s new `player_selector=
"active_player"` into the new `LandOrFreeCastEffect`.

Reference: docs/implementation-state/Done_Backend.md "MEC-33" entry.
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone


def creature(name="Bear", power=2, toughness=2, **kw):
    return Card(id=name, name=name, type_line=kw.pop("type_line", "Creature — Bear"),
                is_creature=True, power=power, toughness=toughness, **kw)


def land(name="Forest"):
    return Card(id=name, name=name, type_line="Basic Land — Forest", is_land=True)


def any_target_instant(name="Shock", cost="{R}"):
    return Card(id=name, name=name, type_line="Instant", is_instant=True,
                mana_cost_string=cost, converted_mana_cost=1,
                oracle_text="~ deals 2 damage to any target.")


def two_player_engine(p1_library, p2_library=()):
    eng = GameEngine.new_game(
        [("p1", "Alice", list(p1_library)), ("p2", "Bob", list(p2_library))],
        starting_life=20, starting_hand=0,
    )
    p1 = eng.state.player_by_id("p1")
    p2 = eng.state.player_by_id("p2")
    for c in list(p1.library) + list(p2.library):
        bind_from_catalogue(c)
    return eng, p1, p2


def _put_omen_machine(eng, controller="p1"):
    from mtg_analyzer.config import DB_PATH
    from mtg_analyzer.services.card_database import CardDatabase

    card = CardDatabase(DB_PATH).get_card("Omen Machine")
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    eng.state.add_to_battlefield(obj)
    bind_from_catalogue(obj)
    eng.recompute_continuous_effects()
    return obj


def _advance_to_draw_step(eng):
    eng.start()
    while eng.state.current_step != "draw":
        eng.advance_step()


def test_players_cant_draw_cards_at_all():
    eng, p1, p2 = two_player_engine([land(), land()])
    _put_omen_machine(eng)
    eng.rules.draw(p1, 3)
    assert p1.hand == []
    eng.rules.draw(p2, 1)
    assert p2.hand == []


def test_players_cant_draw_cards_applies_to_omen_machines_own_controller_too():
    # Unqualified "Players can't draw cards" — unlike Stranglehold's own
    # "opponents"-scoped search prohibition, this restricts everyone,
    # including whoever controls Omen Machine.
    eng, p1, p2 = two_player_engine([land()])
    _put_omen_machine(eng, controller="p1")
    eng.rules.draw(p1, 1)
    assert p1.hand == []


def test_draw_step_exiles_and_puts_a_land_onto_the_battlefield():
    eng, p1, p2 = two_player_engine([creature("Bear"), land("Forest")])
    _put_omen_machine(eng)
    _advance_to_draw_step(eng)
    eng.resolve_until_stable()
    assert [c.name for c in p1.library] == ["Bear"]
    battlefield_names = {o.name for o in eng.state.battlefield if o.controller_id == "p1"}
    assert "Forest" in battlefield_names
    assert p1.exile == []


def test_draw_step_opens_a_free_cast_window_for_a_nonland_card():
    eng, p1, p2 = two_player_engine([land(), any_target_instant("Shock")])
    _put_omen_machine(eng)
    life_before = p2.life
    _advance_to_draw_step(eng)
    eng.resolve_until_stable()
    assert [c.name for c in p1.library] == ["Forest"]
    shock = next(o for o in p1.exile if o.name == "Shock")
    assert shock.instance_id in eng.state.free_cast_instance_ids
    # The controller decides to cast and deliberately chooses the opponent.
    eng.cast_spell(p1, shock, targets=[p2])
    eng.resolve_until_stable()
    assert "Shock" in [o.name for o in p1.graveyard]
    assert p2.life == life_before - 2


def test_draw_step_leaves_an_uncastable_nonland_card_exiled():
    # A targeted spell with no legal target anywhere ("if able" — RULE
    # 601.2c) simply can't be cast, so it stays exactly where
    # `ExileTopOfLibraryEffect` left it.
    targeted_creature_removal = Card(
        id="Doom Blade", name="Doom Blade", type_line="Instant", is_instant=True,
        mana_cost_string="{1}{B}", converted_mana_cost=2,
        oracle_text="Destroy target nonblack creature.",
    )
    eng, p1, p2 = two_player_engine([land(), targeted_creature_removal])
    _put_omen_machine(eng)
    _advance_to_draw_step(eng)
    eng.resolve_until_stable()
    assert "Doom Blade" in [o.name for o in p1.exile]
    assert p1.graveyard == []


def test_draw_step_fires_once_per_turn_for_whichever_player_is_active():
    # No `phase_relation` at all — this is what makes "each player's draw
    # step" reach both players over the course of the game, not just
    # Omen Machine's own controller.
    eng, p1, p2 = two_player_engine([land("P1 Land")], [land("P2 Land")])
    _put_omen_machine(eng, controller="p1")
    _advance_to_draw_step(eng)
    eng.resolve_until_stable()
    assert any(o.name == "P1 Land" for o in eng.state.battlefield if o.controller_id == "p1")

    eng.advance_step()
    while eng.state.current_step != "draw" or eng.state.active_player.id != "p2":
        eng.advance_step()
    eng.resolve_until_stable()
    assert any(o.name == "P2 Land" for o in eng.state.battlefield if o.controller_id == "p2")
