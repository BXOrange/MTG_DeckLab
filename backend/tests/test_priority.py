"""Interactive multiplayer priority (RULE 117) — the basic version.

`pass_priority()` with no argument keeps its solo/goldfish behaviour
unchanged (collapses to resolving the top of the stack immediately).
`pass_priority(player)` drives the real mechanic: priority only resolves
the stack once every living player has passed in succession, and any
player's real action reclaims priority for them.
"""

import pytest

from mtg_analyzer.models.card import Card
from mtg_analyzer.models.events import EventType
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.models.mana_cost import ManaCost
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.parser.oracle.spec import AbilitySpec, EffectSpec


def land(name="Forest", produces="Forest"):
    return Card(id=name, name=name, type_line=f"Basic Land — {produces}", is_land=True)


def instant(name="Shock", cost="{R}"):
    return Card(
        id=name, name=name, type_line="Instant",
        mana_cost_string=cost,
        converted_mana_cost=ManaCost.parse(cost).converted_mana_cost,
        is_instant=True,
    )


def make_engine():
    return GameEngine.new_game(
        [("p1", "Alice", [land()] * 5), ("p2", "Bob", [land()] * 5)],
        starting_life=20, starting_hand=0,
    )


def _hand_card(player, card):
    obj = GameObject(card, owner_id=player.id, zone=Zone.HAND)
    player.hand.append(obj)
    return obj


def test_active_player_gets_priority_at_turn_start():
    eng = make_engine()
    eng.begin_turn()
    assert eng.state.priority_player is eng.state.active_player


def test_solo_pass_priority_is_unaffected_by_the_new_mechanic():
    # No `player` arg: old, unconditional "resolve top of stack" behaviour.
    eng = make_engine()
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    bolt = _hand_card(p1, instant("Bolt", cost="{R}"))
    p1.mana_pool.add_many({"R": 1})
    eng.cast_spell(p1, bolt)
    assert eng.state.stack
    assert eng.pass_priority() is True
    assert not eng.state.stack


def test_non_holder_cannot_pass_priority():
    eng = make_engine()
    eng.begin_turn()  # p1 active, p1 holds priority
    p2 = eng.state.player_by_id("p2")
    with pytest.raises(ValueError):
        eng.pass_priority(p2)


def test_stack_waits_for_both_players_to_pass():
    eng = make_engine()
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    p2 = eng.state.player_by_id("p2")
    bolt = _hand_card(p1, instant("Bolt", cost="{R}"))
    p1.mana_pool.add_many({"R": 1})
    eng.cast_spell(p1, bolt)  # p1 acted → p1 reclaims priority
    assert eng.state.priority_player is p1

    # p1 passes: not everyone has passed yet (p2 hasn't), so nothing resolves
    # and priority moves to p2.
    assert eng.pass_priority(p1) is False
    assert eng.state.stack  # still on the stack
    assert eng.state.priority_player is p2

    # p2 passes too: now everyone has passed, so the top of the stack resolves.
    assert eng.pass_priority(p2) is True
    assert not eng.state.stack


def test_responding_in_the_priority_window_resets_the_passes():
    eng = make_engine()
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    p2 = eng.state.player_by_id("p2")
    bolt = _hand_card(p1, instant("Bolt", cost="{R}"))
    p1.mana_pool.add_many({"R": 1})
    eng.cast_spell(p1, bolt)

    assert eng.pass_priority(p1) is False  # p1 passes, waiting on p2
    assert eng.state.priority_player is p2

    # p2 responds instead of passing — casts their own instant.
    shock = _hand_card(p2, instant("Shock", cost="{R}"))
    p2.mana_pool.add_many({"R": 1})
    eng.cast_spell(p2, shock)
    assert len(eng.state.stack) == 2
    # p2's action reclaims priority; p1's earlier pass no longer counts.
    assert eng.state.priority_player is p2
    assert eng.pass_priority(p2) is False
    assert eng.state.priority_player is p1
    # Now both have passed on the current stack state (shock on top).
    assert eng.pass_priority(p1) is True
    assert len(eng.state.stack) == 1  # shock resolved, bolt remains


def test_priority_resets_to_active_player_after_something_resolves():
    eng = make_engine()
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    p2 = eng.state.player_by_id("p2")
    bolt = _hand_card(p1, instant("Bolt", cost="{R}"))
    p1.mana_pool.add_many({"R": 1})
    eng.cast_spell(p1, bolt)
    eng.pass_priority(p1)
    eng.pass_priority(p2)  # resolves
    assert eng.state.priority_player is p1
    assert eng.state.priority_passed == set()


def _equipment(name="Bonesplitter", cost="{1}"):
    # `_attachment_legal` (game/rules/casting_mixin.py) only recognizes an
    # Equipment permanent via `GameObject.parametric_keywords`, populated at
    # bind time from the card's *Scryfall-style* `keywords` array
    # (`parse_keywords` is anchored on it, not a raw oracle-text regex) — a
    # bare "Equip {cost}" line with no `keywords=["Equip"]` silently binds
    # nothing (see `tests/test_eng_batch_9_11_13_14.py`'s own `_equipment`).
    return Card(
        id=name, name=name, type_line="Legendary Artifact — Equipment",
        mana_cost_string=cost,
        converted_mana_cost=ManaCost.parse(cost).converted_mana_cost,
        keywords=["Equip"],
        oracle_text=f"Equip {cost}",
    )


def _battlefield_card(engine, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    bind_from_catalogue(obj)
    engine.state.add_to_battlefield(obj)
    return obj


def _bound_hand_card(player, card):
    # `_hand_card` above deliberately stays unbound (Bolt/Shock have no
    # abilities these tests care about) — the Equipment cards here need
    # `parametric_keywords` populated *before* casting, or `attach_to_target`
    # silently refuses the attach later with no error (`_attachment_kind`
    # returns `None`).
    obj = GameObject(card, owner_id=player.id, zone=Zone.HAND)
    bind_from_catalogue(obj)
    player.hand.append(obj)
    return obj


def test_single_pass_priority_places_a_trigger_the_resolution_just_fired():
    """A trigger fired by what a `pass_priority()` call just resolved must be
    placed (RULE 117.5) within that *same* call, not left stranded in
    `rules.pending_triggers` until some later, unrelated `pass_priority`
    happens to flush it.

    Regression for a real bug found investigating a "Sigarda's Aid never
    triggers" report: `resolve_until_stable()` already loops correctly (so
    a raw `cast_spell` + `resolve_until_stable` repro looked fine), but
    every session-driven game passes priority one object at a time
    (`GameSession._dispatch_pass_priority`) — exactly the path a real
    player's single "Pass" click after casting an Equipment spell takes.
    Before the fix, that click resolved the Equipment (firing Sigarda's
    Aid's "whenever an Equipment you control enters" trigger into
    `rules.pending_triggers`) but returned with an empty `state.stack` and
    no `pending_choice` — nothing in the view hinted a second click was
    needed, so the attach trigger silently never surfaced.
    """
    eng = make_engine()
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    _battlefield_card(eng, Card(id="Sigarda's Aid", name="Sigarda's Aid", type_line="Enchantment"))
    knight = _battlefield_card(eng, Card(
        id="Knight", name="Knight", type_line="Creature — Knight",
        is_creature=True, power=2, toughness=2,
    ))
    equip = _bound_hand_card(p1, _equipment())
    p1.mana_pool.add_many({"C": 1})
    eng.cast_spell(p1, equip)

    assert eng.pass_priority() is True  # resolves the Equipment spell
    assert not eng.state.stack
    choice = eng.state.pending_choice
    assert choice is not None and choice.get("kind") == "trigger_target", (
        "the trigger this resolution fired should already be placed (and "
        f"its own target choice opened), not stranded: {eng.rules.pending_triggers!r}"
    )
    eng.rules.resolve_trigger_target_choice(str(knight.instance_id))
    eng.pass_priority()  # resolves the now-stacked triggered ability
    equip_obj = next(o for o in eng.state.battlefield if o.card.name == equip.card.name)
    assert equip_obj.attached_to == knight.instance_id


def test_interactive_pass_priority_places_a_trigger_the_resolution_just_fired():
    """Same bug, the multiplayer (`pass_priority(player)`) branch: once
    every living player has passed and the stack resolves, anything that
    resolution triggers must be placed before this call returns too."""
    eng = make_engine()
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    p2 = eng.state.player_by_id("p2")
    _battlefield_card(eng, Card(id="Sigarda's Aid", name="Sigarda's Aid", type_line="Enchantment"))
    knight = _battlefield_card(eng, Card(
        id="Knight", name="Knight", type_line="Creature — Knight",
        is_creature=True, power=2, toughness=2,
    ))
    equip = _bound_hand_card(p1, _equipment())
    p1.mana_pool.add_many({"C": 1})
    eng.cast_spell(p1, equip)  # p1 acted → p1 reclaims priority

    assert eng.pass_priority(p1) is False  # waiting on p2
    assert eng.pass_priority(p2) is True  # everyone passed → resolves
    assert not eng.state.stack
    choice = eng.state.pending_choice
    assert choice is not None and choice.get("kind") == "trigger_target"
    eng.rules.resolve_trigger_target_choice(str(knight.instance_id))
    eng.pass_priority(p1)
    eng.pass_priority(p2)  # resolves the now-stacked triggered ability
    equip_obj = next(o for o in eng.state.battlefield if o.card.name == equip.card.name)
    assert equip_obj.attached_to == knight.instance_id


def test_interactive_pass_priority_stops_cleanly_when_a_resolution_ends_the_game():
    """Bug report: Vraska, Golgari Queen's −9 emblem ("Whenever a creature
    you control deals combat damage to a player, that player loses the
    game.") appeared to hang/crash the backend. Reproduced here as closely
    as a unit test can: the emblem's own triggered ability resolves via the
    *interactive* `pass_priority(player)` branch (RULE 117.3-4, the one a
    real multiplayer table uses), and that resolution ends the game outright
    mid-call — there is no "next window" for a lone remaining opponent.

    Before the fix, `pass_priority` didn't check `state.game_over` after
    `resolve_top_of_stack()` (unlike `resolve_until_stable`, which already
    did): it kept going — placing any further triggers, handing priority
    back to the active player — on a game state that had, a few lines
    earlier, already ended. That's the asymmetry this test pins down: any
    resolution that ends the game must make `pass_priority` stop exactly
    like it already does everywhere else, and a caller (e.g. the
    multiplayer watchdog's `pass_for_absent_players`) that keeps asking for
    passes afterward must see `game_over` rather than a still-live-looking
    priority player.
    """
    eng = make_engine()
    eng.interactive_priority = True
    eng.start()
    while eng.state.current_step != "declare_attackers":
        eng.advance_step()
    p1 = eng.state.active_player
    p2 = next(p for p in eng.state.players if p is not p1)
    attacker = _battlefield_card(eng, Card(
        id="Fighter", name="Fighter", type_line="Creature — Human",
        is_creature=True, power=2, toughness=2,
    ), controller=p1.id)
    attacker.summoning_sick = False

    emblem_ability = AbilitySpec(
        "triggered",
        [EffectSpec("lose_game_trigger_damaged_player", {})],
        trigger={
            "event": EventType.DAMAGE,
            "condition": {"subject": "group", "type": "creature", "controller": "you", "combat": True},
        },
        raw_text="Whenever a creature you control deals combat damage to a "
                 "player, that player loses the game.",
    )
    eng.rules.create_emblem(p1, emblem_ability.to_dict())

    eng.declare_attackers(p1, [attacker])
    eng.advance_step()  # → declare_blockers
    eng.declare_blockers(p2, [])
    eng.advance_step()  # → combat_damage: deals damage, queues the trigger

    # RULE 117.5: place the queued trigger, then both players pass on it —
    # the interactive-priority path a real multiplayer table drives.
    holder = eng.state.priority_player
    other = p2 if holder is p1 else p1
    assert eng.pass_priority(holder) is False  # waiting on the other player
    assert eng.pass_priority(other) is True  # everyone passed → resolves

    assert p2.has_lost is True
    assert eng.state.game_over is True
    assert eng.state.winner_id == p1.id
    # The concrete bug: without the fix, `pass_priority` fell through to
    # `give_priority(active_player)` after resolving the game-ending
    # trigger, leaving `priority_player`/`priority_passed` looking exactly
    # like a fresh, still-live priority window — `GameSession.view()`
    # reports both straight off `GameState` with no `game_over` override
    # (`services/game_session.py`'s `"priority"` block), so a real
    # multiplayer client would keep showing the active player as still up
    # and their "Passen" button still enabled for a game that already
    # ended, rather than a clean, past-tense game-over board.
    assert eng.state.priority_player is other
    assert eng.state.priority_passed == {p1.id, p2.id}
    # A caller that (not knowing the game just ended) asks for one more
    # pass must get a clean, harmless no-op — not a crash, and not a call
    # that keeps advancing a game that is already over.
    assert eng.pass_priority(p1) is False
