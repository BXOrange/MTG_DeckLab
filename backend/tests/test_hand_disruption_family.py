"""Tests for RULE 119/701.8's "Target opponent reveals their hand. You
choose a `<filter>` card from it. That player discards that card."
(Duress/Thoughtseize/Coercion/Despise-shaped) — `RevealHandChooseDiscardEffect`,
reusing `RulesEngine.request_choose_objects`'s pre-existing ``action="discard"``
general chooser (Tevesh Szat's sacrifice, Cloudstone Curio's bounce, …), just
sourced from a hand instead of the battlefield. The chooser is this effect's
controller (the caster), not the hand's owner — `_apply_chosen_object`'s
"discard" branch already resolves against the *object's own owner* regardless
of who picked it, so no new plumbing was needed there.
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.effects.core import GameContext, RevealHandChooseDiscardEffect
from mtg_analyzer.game.rules_engine import RulesEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.models.game_state import GameState
from mtg_analyzer.models.player import Player
from mtg_analyzer.parser.oracle import MODELED, parse_oracle


def _rules():
    p1 = Player(id="p1", life=20)
    p2 = Player(id="p2", life=20)
    state = GameState(players=[p1, p2])
    engine = RulesEngine(state)
    return engine, state, p1, p2


def _hand_card(player, name, type_line="Instant", **kw):
    is_instant = "Instant" in type_line
    is_sorcery = "Sorcery" in type_line
    is_land = "Land" in type_line
    is_creature = "Creature" in type_line
    obj = GameObject(
        Card(id=name, name=name, type_line=type_line, is_instant=is_instant,
             is_sorcery=is_sorcery, is_land=is_land, is_creature=is_creature, **kw),
        owner_id=player.id, zone=Zone.HAND,
    )
    player.add_to_zone(obj, Zone.HAND)
    return obj


# ---------------------------------------------------------------------------
# RevealHandChooseDiscardEffect.apply()
# ---------------------------------------------------------------------------


def test_bare_filter_offers_every_card_in_the_revealed_hand():
    engine, state, p1, p2 = _rules()
    a = _hand_card(p2, "Forest", type_line="Land")
    b = _hand_card(p2, "Bear", type_line="Creature")
    c = _hand_card(p2, "Bolt", type_line="Instant")
    ctx = GameContext(state, engine)

    RevealHandChooseDiscardEffect().apply(ctx, targets=[p2])

    choice = state.pending_choice
    assert choice is not None
    assert choice["action"] == "discard"
    offered = {o["instance_id"] for o in choice["options"] if "instance_id" in o}
    assert offered == {a.instance_id, b.instance_id, c.instance_id}


def test_duress_shaped_filter_excludes_lands_and_creatures():
    engine, state, p1, p2 = _rules()
    land = _hand_card(p2, "Forest", type_line="Land")
    creature = _hand_card(p2, "Bear", type_line="Creature")
    spell_a = _hand_card(p2, "Bolt", type_line="Instant")
    spell_b = _hand_card(p2, "Shock", type_line="Instant")
    ctx = GameContext(state, engine)

    RevealHandChooseDiscardEffect(exclude_land=True, exclude_creature=True).apply(
        ctx, targets=[p2]
    )

    choice = state.pending_choice
    offered = {o["instance_id"] for o in choice["options"] if "instance_id" in o}
    assert offered == {spell_a.instance_id, spell_b.instance_id}
    assert land in p2.hand and creature in p2.hand


def test_card_types_filter_only_offers_matching_types():
    engine, state, p1, p2 = _rules()
    creature_a = _hand_card(p2, "Bear", type_line="Creature")
    creature_b = _hand_card(p2, "Ox", type_line="Creature")
    spell = _hand_card(p2, "Bolt", type_line="Instant")
    ctx = GameContext(state, engine)

    RevealHandChooseDiscardEffect(card_types=["creature", "planeswalker"]).apply(
        ctx, targets=[p2]
    )

    choice = state.pending_choice
    offered = {o["instance_id"] for o in choice["options"] if "instance_id" in o}
    assert offered == {creature_a.instance_id, creature_b.instance_id}
    assert spell in p2.hand


def test_the_caster_not_the_revealed_players_hand_owner_makes_the_choice():
    # The choice is answered by resolving against whichever card was
    # picked — proving the picked card leaves the *target's* hand (not the
    # caster's) is the real assertion here.
    engine, state, p1, p2 = _rules()
    caster = GameObject(Card(id="Caster", name="Caster", type_line="Creature",
                              is_creature=True, power=2, toughness=2),
                         owner_id="p1", zone=Zone.BATTLEFIELD)
    state.add_to_battlefield(caster)
    target_card = _hand_card(p2, "Bolt", type_line="Instant")
    other_card = _hand_card(p2, "Shock", type_line="Instant")
    ctx = GameContext(state, engine)

    RevealHandChooseDiscardEffect(source=caster).apply(ctx, targets=[p2])
    engine.resolve_choose_objects_choice(target_card.instance_id)

    assert target_card in p2.graveyard
    assert target_card not in p2.hand
    assert other_card in p2.hand  # the un-chosen candidate stays put


def test_no_matching_cards_means_no_choice_opens():
    engine, state, p1, p2 = _rules()
    _hand_card(p2, "Forest", type_line="Land")
    ctx = GameContext(state, engine)

    RevealHandChooseDiscardEffect(exclude_land=True).apply(ctx, targets=[p2])

    assert state.pending_choice is None


def test_a_forced_choice_with_exactly_one_candidate_resolves_without_a_prompt():
    engine, state, p1, p2 = _rules()
    only = _hand_card(p2, "Bolt", type_line="Instant")
    ctx = GameContext(state, engine)

    RevealHandChooseDiscardEffect().apply(ctx, targets=[p2])

    assert state.pending_choice is None  # single candidate: no real decision
    assert only in p2.graveyard


# ---------------------------------------------------------------------------
# End to end: Duress (catalogue "spell_effect", via the oracle-text parser)
# ---------------------------------------------------------------------------


def _duress_card():
    return Card(
        id="Duress", name="Duress", type_line="Sorcery", mana_cost_string="{B}",
        converted_mana_cost=1, is_sorcery=True,
        oracle_text="Target opponent reveals their hand. You choose a "
                     "noncreature, nonland card from it. That player discards that card.",
    )


def test_duress_is_fully_modeled():
    result = parse_oracle(_duress_card())
    assert result.coverage == MODELED


def test_duress_end_to_end_discards_the_chosen_noncreature_nonland_card():
    engine, state, p1, p2 = _rules()
    land = _hand_card(p2, "Forest", type_line="Land")
    creature = _hand_card(p2, "Bear", type_line="Creature")
    spell = _hand_card(p2, "Counterspell", type_line="Instant")
    other_spell = _hand_card(p2, "Doom Blade", type_line="Instant")

    obj = GameObject(_duress_card(), owner_id="p1", zone=Zone.STACK)
    bind_from_catalogue(obj)
    assert obj.spell_effects
    ctx = GameContext(state, engine)
    for effect in obj.spell_effects:
        effect.apply(ctx, targets=[p2])

    choice = state.pending_choice
    offered = {o["instance_id"] for o in choice["options"] if "instance_id" in o}
    assert offered == {spell.instance_id, other_spell.instance_id}
    engine.resolve_choose_objects_choice(spell.instance_id)

    assert spell in p2.graveyard
    assert land in p2.hand
    assert creature in p2.hand
    assert other_spell in p2.hand
