"""PAR-130 — "target `<X>` that player controls" as a target-scope slot.

"That player" is antecedent-dependent. The slot composes onto every base pool
of the shared target grammar (`subgrammars.THAT_PLAYER_TARGET_KINDS`), but the
gate keeps an ability only when its *trigger head* names the player
(`gate._that_player_antecedent_ok`); the engine then reads that player off the
firing event (`targeting.trigger_player_antecedent`) — the damaged player, the
attacked player, the controller of a targeting spell, the active player of an
"each opponent's `<step>`" trigger. Three players throughout, so "an opponent"
and "that player" are observably different.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.game.targeting import TARGET_FRAMES, SCOPE_THAT_PLAYER
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.models.game.game_state import GameState
from mtg_analyzer.models.game.player import Player
from mtg_analyzer.parser.oracle import parse_oracle
from mtg_analyzer.parser.oracle.catalogue.subgrammars import (
    THAT_PLAYER_TARGET_KINDS,
    resolve_target_kind,
)
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.spec import EffectSpec


def _named(name):
    from mtg_analyzer.config import DB_PATH
    from mtg_analyzer.services.card_database import CardDatabase

    return CardDatabase(DB_PATH).get_card(name)


def _engine():
    players = [Player(id=f"p{i}", name=f"P{i}", life=20) for i in (1, 2, 3)]
    state = GameState(players=players)
    return GameEngine(state), state


def _bf(state, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.controller_id = controller
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


def _real(state, name, controller="p1"):
    card = _named(name)
    assert parse_oracle(card).modeled, parse_oracle(card).unclaimed
    return _bf(state, card, controller)


def _card(name, type_line, **kw):
    return Card(id=name, name=name, type_line=type_line, **kw)


def _bear(name, controller, state, **kw):
    return _bf(state, _card(name, "Creature — Bear", is_creature=True, power=2, toughness=2, **kw),
               controller)


def _artifact(name, controller, state):
    return _bf(state, _card(name, "Artifact"), controller)


def _pick(engine, state, wanted):
    """Answer the open trigger-target choice with ``wanted``; return the offer."""
    choice = state.pending_choice
    assert choice is not None and choice["kind"] in ("trigger_target", "trigger_target_multi"), choice
    offered = {o.get("instance_id") for o in choice["options"]} - {None}
    option = next(o for o in choice["options"] if o.get("instance_id") == wanted.instance_id)
    engine.rules.resolve_choice(option["id"])
    return offered


def _resolve(engine):
    engine.rules.resolve_top_of_stack()
    engine.rules.check_state_based_actions()


# ---------------------------------------------------------------------------
# Grammar
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("phrase, kind", [
    ("target creature that player controls", "creature_that_player_controls"),
    ("target artifact or enchantment that player controls",
     "artifact_or_enchantment_that_player_controls"),
    ("target nonland permanent that player controls", "nonland_permanent_that_player_controls"),
    ("target creature or planeswalker that player controls",
     "creature_or_planeswalker_that_player_controls"),
    ("target land that player controls", "land_that_player_controls"),
])
def test_slot_composes_onto_the_base_kind(phrase, kind):
    assert resolve_target_kind(phrase) == kind


def test_every_composed_kind_has_a_that_player_frame():
    # The parser can't import `game/`; this keeps the two tables in step.
    for kind in THAT_PLAYER_TARGET_KINDS.values():
        assert TARGET_FRAMES[kind].scope == SCOPE_THAT_PLAYER, kind


@pytest.mark.parametrize("oracle", [
    # No antecedent at all.
    "Destroy target creature that player controls.",
    "At the beginning of your upkeep, tap target creature that player controls.",
    # Merely mentioning a player is not a target antecedent.
    "When Foo enters, each opponent loses 1 life. Destroy target creature that player controls.",
])
def test_slot_fails_closed_without_a_trigger_antecedent(oracle):
    card = _card("Foo", "Creature — Test", oracle_text=oracle)
    assert not parse_oracle(card).modeled


@pytest.mark.parametrize("name", [
    "Aberrant", "Feline Sovereign", "Black Bolt, Inhuman King", "Throat Slitter",
    "Blind Zealot", "A-Dokuchi Silencer", "Rustmouth Ogre", "Sigil of Sleep",
])
def test_real_cards_are_modeled(name):
    assert parse_oracle(_named(name)).modeled


# ---------------------------------------------------------------------------
# Execute
# ---------------------------------------------------------------------------


def test_combat_damage_scopes_to_the_damaged_player():
    engine, state = _engine()
    aberrant = _real(state, "Aberrant")
    hit = _artifact("Hit Relic", "p2", state)
    other = _artifact("Other Relic", "p3", state)
    _artifact("Own Relic", "p1", state)

    engine.rules.deal_damage(state.player_by_id("p2"), 4, source=aberrant, combat=True)
    engine.rules.put_triggers_on_stack()
    assert _pick(engine, state, hit) == {hit.instance_id}
    _resolve(engine)

    assert hit.zone == Zone.GRAVEYARD
    assert other.zone == Zone.BATTLEFIELD


def test_combat_damage_batch_scopes_to_the_damaged_player():
    engine, state = _engine()
    _real(state, "Feline Sovereign")
    cat = _bf(state, _card("Cat", "Creature — Cat", is_creature=True, power=2, toughness=2))
    hit = _artifact("Hit Relic", "p3", state)
    _artifact("Other Relic", "p2", state)
    engine.recompute_continuous_effects()

    engine._apply_combat_damage([(state.player_by_id("p3"), cat.power, cat)])
    engine.rules.put_triggers_on_stack()
    assert _pick(engine, state, hit) == {hit.instance_id}
    _resolve(engine)

    assert hit.zone == Zone.GRAVEYARD


def test_nonblack_filter_survives_the_scope():
    engine, state = _engine()
    slitter = _real(state, "Throat Slitter")
    white = _bear("White Bear", "p2", state, color_identity={"W"})
    _bear("Black Bear", "p2", state, color_identity={"B"})
    _bear("Elsewhere", "p3", state, color_identity={"W"})
    engine.recompute_continuous_effects()

    engine.rules.deal_damage(state.player_by_id("p2"), 2, source=slitter, combat=True)
    engine.rules.put_triggers_on_stack()
    assert _pick(engine, state, white) == {white.instance_id}
    _resolve(engine)

    assert white.zone == Zone.GRAVEYARD


def test_becomes_target_scopes_to_the_targeting_spells_controller():
    engine, state = _engine()
    bolt = _real(state, "Black Bolt, Inhuman King")
    theirs = _artifact("Caster's Relic", "p3", state)
    _artifact("Bystander's Relic", "p2", state)

    state.fire_event(GameEvent(
        EventType.BECOMES_TARGET, instance_id=bolt.instance_id, target_controller_id="p1",
        is_player=False, controller_id="p3", item_kind="spell", stack_id=None,
    ))
    engine.rules.put_triggers_on_stack()
    assert _pick(engine, state, theirs) == {theirs.instance_id}
    _resolve(engine)

    assert theirs.zone == Zone.GRAVEYARD


def test_each_opponents_step_scopes_to_the_active_player():
    engine, state = _engine()
    oracle = "At the beginning of each opponent's upkeep, tap target creature that player controls."
    listener = _card("Listener", "Enchantment", oracle_text=oracle)
    assert parse_oracle(listener).modeled
    _bf(state, listener)
    active = _bear("Active Bear", "p3", state)
    _bear("Idle Bear", "p2", state)
    state.active_player_index = 2  # p3's turn

    state.fire_event(GameEvent(EventType.STEP_BEGIN, step="upkeep", phase="beginning"))
    engine.rules.put_triggers_on_stack()
    assert _pick(engine, state, active) == {active.instance_id}
    _resolve(engine)

    assert active.tapped


def test_no_player_in_the_event_offers_nothing():
    # A trigger whose event names nobody fails closed rather than guessing.
    from mtg_analyzer.game.targeting import TargetSpec, legal_targets

    _, state = _engine()
    _bear("Bear", "p2", state)
    spec = TargetSpec(kind="creature_that_player_controls")
    assert legal_targets(state, "p1", spec) == []
    assert legal_targets(state, "p1", spec, trigger_event=GameEvent(EventType.DRAW)) == []


@pytest.mark.parametrize("item_kind", ["spell", "ability"])
def test_spell_or_ability_head_fires_for_both_item_kinds(item_kind):
    # "a spell or ability" used to be an exact-match filter value the event
    # never carries, so the whole Illusion cycle never sacrificed itself.
    engine, state = _engine()
    bear = _real(state, "Phantasmal Bear")
    state.fire_event(GameEvent(
        EventType.BECOMES_TARGET, instance_id=bear.instance_id, target_controller_id="p1",
        is_player=False, controller_id="p2", item_kind=item_kind, stack_id=None,
    ))
    engine.rules.put_triggers_on_stack()
    _resolve(engine)
    assert bear.zone == Zone.GRAVEYARD


def test_reflexive_payoff_keeps_the_damaged_player():
    # "you may discard a card. When you do, destroy target … that player
    # controls" — the reflexive trigger carries the outer DAMAGE event.
    engine, state = _engine()
    silencer = _real(state, "A-Dokuchi Silencer")
    state.player_by_id("p1").hand.append(
        GameObject(_card("Junk", "Instant"), owner_id="p1", zone=Zone.HAND))
    hit = _bear("Hit", "p2", state)
    _bear("Other", "p3", state)
    engine.recompute_continuous_effects()

    engine.rules.deal_damage(state.player_by_id("p2"), 1, source=silencer, combat=True)
    engine.rules.put_triggers_on_stack()
    engine.rules.resolve_top_of_stack()  # the "you may discard" asks on resolution
    pay = next(o for o in state.pending_choice["options"] if o["id"] == "pay")
    engine.rules.resolve_choice(pay["id"])
    engine.rules.put_triggers_on_stack()
    assert _pick(engine, state, hit) == {hit.instance_id}
    _resolve(engine)

    assert hit.zone == Zone.GRAVEYARD


# ---------------------------------------------------------------------------
# "for each opponent/player, … target <X> that player controls"
# ---------------------------------------------------------------------------


def _enter(engine, state, obj):
    state.fire_event(GameEvent(
        EventType.ENTERS_BATTLEFIELD, instance_id=obj.instance_id,
        controller_id=obj.controller_id, object_types=sorted(obj.type_words),
    ))
    engine.rules.put_triggers_on_stack()


def test_per_opponent_offers_one_round_per_opponent_scoped_to_them():
    engine, state = _engine()
    sentinel = _real(state, "Tri-Sentinel, Act of Vengeance")
    b2 = _bear("P2 Bear", "p2", state)
    b3 = _bear("P3 Bear", "p3", state)
    mine = _bear("My Bear", "p1", state)
    engine.recompute_continuous_effects()

    _enter(engine, state, sentinel)
    assert _pick(engine, state, b2) == {b2.instance_id}
    assert _pick(engine, state, b3) == {b3.instance_id}
    _resolve(engine)

    assert b2.zone == Zone.GRAVEYARD and b3.zone == Zone.GRAVEYARD
    assert mine.zone == Zone.BATTLEFIELD


def test_per_player_includes_you():
    engine, state = _engine()
    oracle = "When Listener enters, for each player, destroy up to one target creature that player controls."
    listener = _card("Listener", "Enchantment", oracle_text=oracle)
    assert parse_oracle(listener).modeled
    obj = _bf(state, listener)
    mine = _bear("My Bear", "p1", state)
    b2 = _bear("P2 Bear", "p2", state)
    b3 = _bear("P3 Bear", "p3", state)

    _enter(engine, state, obj)
    assert _pick(engine, state, mine) == {mine.instance_id}
    assert _pick(engine, state, b2) == {b2.instance_id}
    assert _pick(engine, state, b3) == {b3.instance_id}
    _resolve(engine)

    assert {mine.zone, b2.zone, b3.zone} == {Zone.GRAVEYARD}


def test_opponent_with_nothing_legal_is_skipped_not_fatal():
    # RULE 601.2c: no target is chosen for that player; the rest still resolve.
    engine, state = _engine()
    thief = _real(state, "Enigma Thief")
    relic = _artifact("P3 Relic", "p3", state)  # p2 controls no nonland permanent

    _enter(engine, state, thief)
    assert _pick(engine, state, relic) == {relic.instance_id}
    _resolve(engine)

    assert relic.zone == Zone.HAND


def test_linked_exile_returns_every_card_it_took():
    engine, state = _engine()
    kenway = _real(state, "Haytham Kenway")
    b2 = _bear("P2 Bear", "p2", state)
    b3 = _bear("P3 Bear", "p3", state)
    engine.recompute_continuous_effects()

    _enter(engine, state, kenway)
    _pick(engine, state, b2)
    _pick(engine, state, b3)
    _resolve(engine)
    assert b2.zone == Zone.EXILE and b3.zone == Zone.EXILE

    engine.rules.destroy(kenway)
    engine.rules.put_triggers_on_stack()
    _resolve(engine)
    returned = {o.name for o in state.battlefield}
    assert {"P2 Bear", "P3 Bear"} <= returned


# ---------------------------------------------------------------------------
# The cast path: a spell offers one requirement per player round
# ---------------------------------------------------------------------------


def _sorcery(state, oracle, controller="p1"):
    card = _card("Heist", "Sorcery", oracle_text=oracle, is_sorcery=True,
                 mana_cost_string="{U}", converted_mana_cost=1)
    assert parse_oracle(card).modeled, parse_oracle(card).unclaimed
    obj = GameObject(card, owner_id=controller, zone=Zone.HAND)
    bind_from_catalogue(obj)
    player = state.player_by_id(controller)
    player.add_to_zone(obj, Zone.HAND)
    player.mana_pool.add("U", 1)
    state.current_step = "main1"
    return obj, player


def _offer(engine, player, spell):
    action = next(a for a in engine.legal_actions(player)
                  if a["type"] == "cast_spell" and a.get("instance_id") == spell.instance_id)
    return [{o["instance_id"] for o in req["options"]} for req in action.get("targets", [])]


_THIEVERY = "For each opponent, gain control of target permanent that player controls."


def test_spell_offers_one_scoped_round_per_opponent():
    engine, state = _engine()
    b2 = _bear("P2 Bear", "p2", state)
    b3 = _bear("P3 Bear", "p3", state)
    _bear("My Bear", "p1", state)
    spell, p1 = _sorcery(state, _THIEVERY)

    assert _offer(engine, p1, spell) == [{b2.instance_id}, {b3.instance_id}]
    engine.cast_spell(p1, spell, target_groups=[[b2], [b3]])
    engine.resolve_until_stable()

    # RULE 611.2: no duration — the steal outlives the turn.
    assert b2.controller_id == "p1" and b3.controller_id == "p1"
    engine._step_cleanup()
    assert b2.controller_id == "p1"


def test_spell_rejects_two_picks_from_one_opponent():
    engine, state = _engine()
    b2 = _bear("P2 Bear", "p2", state)
    c2 = _bear("P2 Cub", "p2", state)
    _bear("P3 Bear", "p3", state)
    spell, p1 = _sorcery(state, _THIEVERY)

    with pytest.raises(ValueError):
        engine.cast_spell(p1, spell, target_groups=[[b2], [c2]])


def test_spell_with_one_live_round_takes_a_flat_target_list():
    # p2 controls nothing: their round isn't offered and the flat list is p3's.
    engine, state = _engine()
    b3 = _bear("P3 Bear", "p3", state)
    spell, p1 = _sorcery(state, _THIEVERY)

    assert _offer(engine, p1, spell) == [{b3.instance_id}]
    engine.cast_spell(p1, spell, targets=[b3])
    engine.resolve_until_stable()
    assert b3.controller_id == "p1"


def test_any_number_of_opponents_rounds_are_declinable():
    engine, state = _engine()
    b2 = _bear("P2 Bear", "p2", state)
    b3 = _bear("P3 Bear", "p3", state)
    spell, p1 = _sorcery(
        state, "For any number of opponents, destroy target nonland permanent that player controls.")

    engine.cast_spell(p1, spell, target_groups=[[], [b3]])
    engine.resolve_until_stable()
    assert b2.zone == Zone.BATTLEFIELD and b3.zone == Zone.GRAVEYARD


def test_activated_ability_offers_and_validates_one_round_per_opponent():
    engine, state = _engine()
    device = _card(
        "Recall Device", "Artifact",
        oracle_text=("{T}: For each opponent, return up to one target artifact or creature "
                     "that player controls to its owner's hand."),
    )
    result = parse_oracle(device)
    assert result.modeled, result.unclaimed
    source = _bf(state, device)
    b2 = _bear("P2 Bear", "p2", state)
    b3 = _bear("P3 Bear", "p3", state)

    action = next(
        a for a in engine.legal_actions(state.player_by_id("p1"))
        if a.get("type") == "activate_ability" and a.get("instance_id") == source.instance_id
    )
    assert [{o["instance_id"] for o in req["options"]} for req in action["targets"]] == [
        {b2.instance_id}, {b3.instance_id},
    ]
    with pytest.raises(ValueError, match="legal target"):
        engine.activate_ability(
            state.player_by_id("p1"), source, target_groups=[[b2], [b2]],
        )

    engine.activate_ability(
        state.player_by_id("p1"), source, target_groups=[[b2], [b3]],
    )
    engine.resolve_until_stable()
    assert b2.zone == Zone.HAND and b3.zone == Zone.HAND


def test_scoped_round_keeps_the_mana_value_cap():
    engine, state = _engine()
    small = _bf(state, _card("P2 Small", "Creature — Bear", is_creature=True, power=1,
                             toughness=1, converted_mana_cost=2), "p2")
    _bf(state, _card("P2 Big", "Creature — Bear", is_creature=True, power=5,
                     toughness=5, converted_mana_cost=5), "p2")
    spell, p1 = _sorcery(state, (
        "For each opponent, gain control of up to one target creature or planeswalker "
        "that player controls with mana value 3 or less."))

    assert _offer(engine, p1, spell) == [{small.instance_id}]


def test_plain_that_player_still_needs_an_antecedent_on_a_spell():
    card = _card("Foo", "Sorcery", oracle_text="Gain control of target artifact that player controls.")
    assert not parse_oracle(card).modeled


def test_prior_target_controller_is_the_antecedent_and_is_server_validated():
    engine, state = _engine()
    dealer = _bf(state, _card(
        "P2 Giant", "Creature — Giant", is_creature=True, power=4, toughness=4,
    ), "p2")
    same = _bear("P2 Bear", "p2", state)
    other = _bear("P3 Bear", "p3", state)
    spell, p1 = _sorcery(state, (
        "Target creature an opponent controls deals damage equal to its power to another "
        "target creature that player controls. The Ring tempts you."
    ))

    with pytest.raises(ValueError, match="that player"):
        engine.cast_spell(p1, spell, target_groups=[[dealer], [other]])

    engine.cast_spell(p1, spell, target_groups=[[dealer], [same]])
    engine.resolve_until_stable()
    assert same.zone == Zone.GRAVEYARD


@pytest.mark.parametrize("name", [
    "Blatant Thievery", "Bilbo's Burglaring", "Tempted by the Oriq", "Windgrace's Judgment",
    "Keiga, the Tide Star", "Invoke the Winds", "Riptide Entrancer",
])
def test_real_steals_are_modeled(name):
    assert parse_oracle(_named(name)).modeled


def test_gain_control_with_a_duration_is_not_the_permanent_row():
    permanent = match_clause("gain control of target artifact. untap it")
    assert permanent[0].params["duration"] == "permanent" and permanent[0].params["untap"]
    assert match_clause("gain control of target spell") is None or all(
        s.params.get("duration") != "permanent" for s in match_clause("gain control of target spell"))
    eot = match_clause("gain control of target creature until end of turn")
    assert eot[0].params.get("duration", "end_of_turn") == "end_of_turn"


# ---------------------------------------------------------------------------
# Antecedent amount used by a that-player damage body
# ---------------------------------------------------------------------------


def test_that_much_damage_requires_an_amount_carrying_trigger():
    specs = match_clause("it deals that much damage to target creature")
    assert specs == [EffectSpec("damage", {
        "amount_from_trigger_event": "that_much", "target_kind": "creature",
    })]
    assert not parse_oracle(_card(
        "Unsafe", "Sorcery", is_sorcery=True,
        oracle_text="Unsafe deals that much damage to target creature.",
    )).modeled


@pytest.mark.parametrize("name", [
    "Mordant Dragon", "Skirk Commando", "Snapping Thragg", "Spark Mage",
])
def test_optional_have_it_deal_damage_uses_the_plain_damage_body(name):
    result = parse_oracle(_named(name))
    assert result.modeled, result.unclaimed


def test_that_much_damage_executes_from_damage_event_and_keeps_that_player_scope():
    engine, state = _engine()
    card = _card(
        "Reflector", "Creature — Test", is_creature=True, power=2, toughness=2,
        oracle_text=("Whenever Reflector deals combat damage to a player, it deals that much "
                     "damage to target creature that player controls."),
    )
    result = parse_oracle(card)
    assert result.modeled, result.unclaimed
    reflector = _bf(state, card)
    hit = _bf(state, _card("Hit", "Creature — Bear", is_creature=True, power=2, toughness=5), "p2")
    _bf(state, _card("Elsewhere", "Creature — Bear", is_creature=True, power=2, toughness=5), "p3")

    engine.rules.deal_damage(state.player_by_id("p2"), 3, source=reflector, combat=True)
    engine.rules.put_triggers_on_stack()
    assert _pick(engine, state, hit) == {hit.instance_id}
    _resolve(engine)

    assert hit.damage_marked == 3
