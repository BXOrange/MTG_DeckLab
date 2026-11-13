"""BUG-60: "…except it has Sakashima's other abilities" is part of the copy's copiable values (RULE 707.9a).

Every test uses the real cards (`CardDatabase`): Sakashima of a Thousand Faces enters as a copy of a real legendary
creature, then a real Clone copies the result. Casts go through the real engine flow (cast, the `enter_as_copy`
choice, resolution); the session tests drive `GameSession.legal_actions` / `apply_action` / `rewind` as the UI does.

Sakashima's "other abilities" are the legend-rule exemption and Partner (a keyword with no battlefield effect that
is still part of what a Clone copies). The enter-as-copy replacement itself is the ability being applied, not one of
the "other" ones.
"""

from __future__ import annotations

from mtg_analyzer.config import DB_PATH
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.services.card_database import CardDatabase
from mtg_analyzer.services.game_session import GameSession

SAKASHIMA = "Sakashima of a Thousand Faces"
CLONE = "Clone"
LEGEND_LAYER = "ignore_legend_rule"
LEGEND_LINE = 'the "legend rule" doesn\'t apply to permanents you control.'
ISAMARU = "Isamaru, Hound of Konda"
ENTER_AS_COPY_CHOICE = "enter_as_copy"
# Mana enough for Sakashima ({3}{U}) and Clone ({3}{U}) both, plus slack for a second Sakashima.
BIG_POOL = {"U": 4, "C": 12}

_DB = CardDatabase(DB_PATH)


def _real(name):
    return _DB.get_card(name)


def _game():
    engine = GameEngine.new_game([("p1", "Alice", []), ("p2", "Bob", [])], starting_hand=0)
    engine.begin_turn()
    engine.state.current_step = "main1"
    return engine, engine.state, engine.state.player_by_id("p1")


def _put(engine, p1, name, zone=Zone.HAND):
    obj = GameObject(_real(name), owner_id=p1.id, controller_id=p1.id, zone=zone)
    if zone == Zone.BATTLEFIELD:
        obj.summoning_sick = False
        engine.state.add_to_battlefield(obj)
    else:
        p1.zones[zone].append(obj)
    bind_from_catalogue(obj)
    return obj


def _enter_as_copy(engine, p1, spell, target):
    """Cast ``spell`` from hand and answer the enter-as-copy choice with ``target`` (RULE 614.1c)."""
    p1.mana_pool.add_many(BIG_POOL)
    engine.cast_spell(p1, spell)
    engine.resolve_until_stable()
    choice = engine.state.pending_choice
    assert choice and choice["kind"] == ENTER_AS_COPY_CHOICE
    option = next(o for o in choice["options"] if o.get("instance_id") == target.instance_id)
    engine.resolve_pending_choice(option["id"])
    engine.resolve_until_stable()
    engine.recompute_continuous_effects()
    assert spell.zone == Zone.BATTLEFIELD
    return spell


def _exempts_legend_rule(obj):
    return [a for a in obj.static_effects if a.layer == LEGEND_LAYER]


def _has_partner(obj):
    return "partner" in {str(k).lower() for k in (obj.card.keywords or [])}


def _sakashima_copy():
    """Sakashima entering as a copy of Isamaru; returns ``(engine, p1, isamaru, sakashima)``."""
    engine, state, p1 = _game()
    isamaru = _put(engine, p1, ISAMARU, Zone.BATTLEFIELD)
    sakashima = _enter_as_copy(engine, p1, _put(engine, p1, SAKASHIMA), isamaru)
    return engine, p1, isamaru, sakashima


# --- the copy itself -------------------------------------------------------------------------------------------


def test_sakashima_copy_has_the_legend_exemption_and_partner_and_coexists_with_the_original():
    engine, p1, isamaru, sakashima = _sakashima_copy()
    assert sakashima.name == ISAMARU
    assert len(_exempts_legend_rule(sakashima)) == 1
    assert _has_partner(sakashima)
    # RULE 704.5j: the exemption applies to its controller's permanents, so both Isamarus stay.
    engine.rules.check_state_based_actions()
    assert {sakashima, isamaru} <= set(engine.state.battlefield)


def test_the_enter_as_copy_replacement_itself_is_not_kept():
    _, _, _, sakashima = _sakashima_copy()
    assert not sakashima.enter_as_copy_effects


def test_the_exemption_is_stored_in_the_copiable_values_not_only_bound():
    _, _, _, sakashima = _sakashima_copy()
    assert LEGEND_LINE in [line.lower() for line in sakashima.card.granted_ability_lines]


# --- a Clone of the copy, and chains (RULE 707.9a / 707.9b) -----------------------------------------------------


def test_a_clone_of_the_sakashima_copy_has_the_legend_exemption_and_partner():
    engine, p1, isamaru, sakashima = _sakashima_copy()
    clone = _enter_as_copy(engine, p1, _put(engine, p1, CLONE), sakashima)
    assert clone.name == ISAMARU
    assert len(_exempts_legend_rule(clone)) == 1 and _has_partner(clone)
    assert _exempts_legend_rule(clone)[0].source is clone  # rebound for the Clone, not shared with Sakashima
    engine.rules.check_state_based_actions()
    assert {sakashima, isamaru, clone} <= set(engine.state.battlefield)


def test_a_chained_copy_of_the_clone_has_it_too_and_never_twice():
    engine, p1, isamaru, sakashima = _sakashima_copy()
    first = _enter_as_copy(engine, p1, _put(engine, p1, CLONE), sakashima)
    second = _enter_as_copy(engine, p1, _put(engine, p1, CLONE), first)
    for permanent in (first, second):
        assert len(_exempts_legend_rule(permanent)) == 1
        assert _has_partner(permanent)
    assert _exempts_legend_rule(second)[0].source is second


def test_a_copy_of_the_original_isamaru_does_not_get_the_exemption():
    engine, p1, isamaru, sakashima = _sakashima_copy()
    clone = _enter_as_copy(engine, p1, _put(engine, p1, CLONE), isamaru)
    assert not _exempts_legend_rule(clone) and not _has_partner(clone)


def test_a_sakashima_copying_a_sakashima_copy_keeps_the_exemption_exactly_once():
    engine, p1, isamaru, sakashima = _sakashima_copy()
    second = _enter_as_copy(engine, p1, _put(engine, p1, SAKASHIMA), sakashima)
    assert second.name == ISAMARU
    assert len(_exempts_legend_rule(second)) == 1


def test_two_sakashima_copies_coexist_but_without_it_the_legend_rule_applies():
    engine, p1, isamaru, sakashima = _sakashima_copy()
    other = _enter_as_copy(engine, p1, _put(engine, p1, SAKASHIMA), isamaru)
    engine.rules.check_state_based_actions()
    assert {isamaru, sakashima, other} <= set(engine.state.battlefield)
    # An ordinary Clone of Isamaru has no exemption, but the controller still has one through a Sakashima copy.
    plain = _enter_as_copy(engine, p1, _put(engine, p1, CLONE), isamaru)
    engine.rules.check_state_based_actions()
    assert plain in engine.state.battlefield


def test_legend_rule_still_applies_when_nothing_exempts_it():
    engine, state, p1 = _game()
    isamaru = _put(engine, p1, ISAMARU, Zone.BATTLEFIELD)
    clone = _enter_as_copy(engine, p1, _put(engine, p1, CLONE), isamaru)
    engine.rules.check_state_based_actions()
    if state.pending_choice:  # RULE 704.5j: the controller picks which legendary permanent to keep
        engine.resolve_pending_choice(state.pending_choice["options"][0]["id"])
    survivors = [o for o in state.battlefield if o.name == ISAMARU]
    assert len(survivors) == 1 and clone.name == ISAMARU


# --- clone / undo -----------------------------------------------------------------------------------------------


def test_a_cloned_game_state_keeps_the_copiable_exemption():
    engine, p1, isamaru, sakashima = _sakashima_copy()
    cloned = engine.state.clone()
    copy_obj = next(o for o in cloned.battlefield if o.instance_id == sakashima.instance_id)
    assert LEGEND_LINE in [line.lower() for line in copy_obj.card.granted_ability_lines]
    assert len(_exempts_legend_rule(copy_obj)) == 1


def _session_with(*hand_names):
    engine, state, p1 = _game()
    isamaru = _put(engine, p1, ISAMARU, Zone.BATTLEFIELD)
    for name in hand_names:
        _put(engine, p1, name)
    p1.mana_pool.add_many(BIG_POOL)
    return GameSession(engine, require_setup=False), isamaru


def _cast_and_copy(session, spell, target):
    """Cast ``spell`` through the session's own legal actions and answer the enter-as-copy choice with ``target``."""
    cast = next(a for a in session.legal_actions("p1")
                if a["type"] == "cast_spell" and a.get("instance_id") == spell.instance_id)
    session.apply_action(cast, "p1")
    session.engine.resolve_until_stable()
    choice = session.engine.state.pending_choice
    assert choice and choice["kind"] == ENTER_AS_COPY_CHOICE
    option = next(o for o in choice["options"] if o.get("instance_id") == target.instance_id)
    session.apply_action({"type": "choose", "option_id": option["id"]}, "p1")
    session.engine.resolve_until_stable()
    session.engine.recompute_continuous_effects()


def test_session_flow_sakashima_then_clone_and_undo_keeps_the_exemption():
    session, isamaru = _session_with(SAKASHIMA, CLONE)
    p1 = session.engine.state.player_by_id("p1")
    sakashima = next(o for o in p1.hand if o.card.name == SAKASHIMA)
    clone = next(o for o in p1.hand if o.card.name == CLONE)
    _cast_and_copy(session, sakashima, isamaru)
    assert sakashima.name == ISAMARU and len(_exempts_legend_rule(sakashima)) == 1

    p1.mana_pool.add_many(BIG_POOL)
    _cast_and_copy(session, clone, sakashima)
    live_clone = next(o for o in session.engine.state.battlefield if o.instance_id == clone.instance_id)
    assert len(_exempts_legend_rule(live_clone)) == 1 and _has_partner(live_clone)

    # Undo the Clone's answer and its cast: the surviving Sakashima copy still has the exemption.
    session.rewind(2)
    state = session.engine.state
    survivor = next(o for o in state.battlefield if o.instance_id == sakashima.instance_id)
    assert LEGEND_LINE in [line.lower() for line in survivor.card.granted_ability_lines]
    assert len(_exempts_legend_rule(survivor)) == 1
    assert not any(o.instance_id == clone.instance_id for o in state.battlefield)


def test_rewinding_the_sakashima_answer_restores_sakashima_in_hand_without_the_exemption():
    session, isamaru = _session_with(SAKASHIMA)
    p1 = session.engine.state.player_by_id("p1")
    sakashima = p1.hand[0]
    _cast_and_copy(session, sakashima, isamaru)
    session.rewind(2)
    state = session.engine.state
    back = next(o for o in state.player_by_id("p1").hand if o.card.name == SAKASHIMA)
    assert not back.card.granted_ability_lines  # the card is Sakashima again, no leftover copiable values


def test_other_keep_own_abilities_cards_are_not_on_the_enter_as_copy_path():
    """The Misty Stepper and The Playful Winners say "its other abilities" too but are unparsed (UNMODELED), and
    Vesuvan Doppelganger's "this ability" is a quoted upkeep become-a-copy (BUG-56's path), so Sakashima is the only
    card whose enter-as-copy spec carries `keep_own_abilities`."""
    from mtg_analyzer.game import card_registry

    for name in (SAKASHIMA, "The Misty Stepper", "The Playful Winners", "Vesuvan Doppelganger"):
        specs = card_registry.specs_for(_real(name))
        keeps = [e for sp in specs for e in sp.effects
                 if e.type == "enter_as_copy" and e.params.get("keep_own_abilities")]
        assert bool(keeps) == (name == SAKASHIMA), name
