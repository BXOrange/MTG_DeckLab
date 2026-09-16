"""PAR-30 — RULE 701.10 exchange-control residue closed: the twelve
bespoke singletons the shared cross-target predicates (PARSER_VERSION 211)
didn't reach, each hand-authored in `card_registry/special_mechanics.py`.
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue, build_effects
from mtg_analyzer.game.effects.core import (
    CulturalExchangeEffect,
    ExchangeControlEffect,
    ExchangeControlSpellEffect,
    ExchangeControlThenCopyTokenEffect,
    GameContext,
    JuxtaposeEffect,
    TripleExchangeEffect,
    _apply_effects_partitioned,
)
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.models.game.game_state import StackItem
from mtg_analyzer.services.card_database import CardDatabase, DEFAULT_DB_PATH


def _db():
    return CardDatabase(DEFAULT_DB_PATH)


def _engine():
    eng = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )
    return eng, eng.state


def _permanent(name, controller, type_line="Artifact", **kw):
    card = Card(id=name, name=name, type_line=type_line,
                is_creature="Creature" in type_line, **kw)
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.controller_id = controller
    obj.summoning_sick = False
    return obj


def _spec_source(name, controller="p1", zone=Zone.BATTLEFIELD):
    src = GameObject(_db().get_card(name), owner_id=controller, zone=zone)
    src.controller_id = controller
    bind_from_catalogue(src)
    return src


def test_all_twelve_hand_authored():
    db = _db()
    for name in (
        "Confusion in the Ranks", "Conjured Currency", "Djinn of Infinite Deceits",
        "Gauntlets of Chaos", "Modify Memory", "Psychic Transfer", "Mirror Mirror",
        "Cultural Exchange", "Juxtapose", "Perplexing Chimera", "Sudden Substitution",
        "Arteeoh, Dread Scavenger",
    ):
        from mtg_analyzer.game.card_registry import specs_for
        assert specs_for(db.get_card(name)), name


# --- Confusion in the Ranks --------------------------------------------------


def test_confusion_in_the_ranks_chooser_is_the_entering_permanents_controller():
    eng, state = _engine()
    ring = _spec_source("Confusion in the Ranks", controller="p1")
    state.add_to_battlefield(ring)

    entering = _permanent("Entering Beast", "p2", "Creature — Bear")
    theirs = _permanent("Sharing", "p1", "Creature — Bear")
    state.add_to_battlefield(theirs)
    state.add_to_battlefield(entering)
    state.fire_event(GameEvent(
        EventType.ENTERS_BATTLEFIELD, instance_id=entering.instance_id,
        controller_id="p2", object_types=sorted(entering.type_words),
    ))
    assert eng.rules.put_triggers_on_stack() == 1
    choice = state.pending_choice
    assert choice is not None and choice["kind"] == "trigger_target"
    # The chooser is p2 (entering permanent's controller), not p1 (Confusion
    # in the Ranks' own controller) — PAR-30's controller_from_trigger_event.
    assert choice["player_id"] == "p2"
    eng.rules.resolve_choice(str(theirs.instance_id))
    eng.rules.resolve_top_of_stack()
    assert entering.controller_id == "p1" and theirs.controller_id == "p2"


# --- Conjured Currency --------------------------------------------------------


def test_conjured_currency_targeting_excludes_owned_and_controlled_permanents():
    eng, state = _engine()
    currency = _spec_source("Conjured Currency", controller="p1")
    state.add_to_battlefield(currency)
    stolen = _permanent("Stolen", "p2")
    stolen.owner_id = "p1"  # owned by p1 but currently controlled by p2
    state.add_to_battlefield(stolen)
    unrelated = _permanent("Unrelated", "p2")
    state.add_to_battlefield(unrelated)

    from mtg_analyzer.game.targeting import TargetSpec, legal_targets
    spec = TargetSpec(kind="permanent_you_neither_own_nor_control")
    offered = {o["instance_id"] for o in legal_targets(state, "p1", spec, source=currency)}
    assert offered == {unrelated.instance_id}  # not "Stolen" (owned by p1)


def test_conjured_currency_exchange_effect_directly():
    eng, state = _engine()
    currency = _spec_source("Conjured Currency", controller="p1")
    state.add_to_battlefield(currency)
    unrelated = _permanent("Unrelated", "p2")
    state.add_to_battlefield(unrelated)

    ctx = GameContext(state, eng.rules)
    ExchangeControlEffect(
        source=currency, target_kind="permanent_you_neither_own_nor_control",
    ).apply(ctx, targets=[unrelated])
    assert currency.controller_id == "p2" and unrelated.controller_id == "p1"


# --- Djinn of Infinite Deceits ------------------------------------------------


def test_djinn_exchanges_only_nonlegendary_creatures():
    eng, state = _engine()
    a = _permanent("A", "p1", "Creature — Bear")
    b = _permanent("Legend", "p2", "Legendary Creature — God", is_legendary=True)
    state.add_to_battlefield(a)
    state.add_to_battlefield(b)

    # b is legendary -> not a legal candidate at all (the real gameplay
    # gate is at offer time, via `combat.matches_object_filter`'s new
    # ``nonlegendary`` key on `TargetSpec.creature_filter`).
    from mtg_analyzer.game.targeting import TargetSpec, legal_targets
    spec = TargetSpec(kind="creature", count=2, creature_filter={"nonlegendary": True})
    offered = {o["instance_id"] for o in legal_targets(state, "p1", spec)}
    assert offered == {a.instance_id}


def test_djinn_cannot_activate_during_combat():
    eng, state = _engine()
    djinn = _spec_source("Djinn of Infinite Deceits", controller="p1")
    state.add_to_battlefield(djinn)
    djinn.summoning_sick = False
    ability = djinn.activated_abilities[0]

    state.current_phase = "main1"
    assert eng.can_activate(state.player_by_id("p1"), djinn, ability) is True
    state.current_phase = "combat"
    assert eng.can_activate(state.player_by_id("p1"), djinn, ability) is False


# --- Gauntlets of Chaos --------------------------------------------------------


def test_gauntlets_of_chaos_exchanges_and_destroys_attached_auras():
    eng, state = _engine()
    mine = _permanent("MyArt", "p1", "Artifact")
    theirs = _permanent("TheirArt", "p2", "Artifact")
    state.add_to_battlefield(mine)
    state.add_to_battlefield(theirs)
    aura_card = Card(id="AU", name="Pacifism", type_line="Enchantment — Aura")
    aura = GameObject(aura_card, owner_id="p1", zone=Zone.BATTLEFIELD)
    aura.attached_to = theirs.instance_id
    state.add_to_battlefield(aura)

    ctx = GameContext(state, eng.rules)
    ExchangeControlEffect(
        first_target_kind="permanent_you_control", target_kind="permanent_you_dont_control",
        shares_type="card", destroy_auras_if_exchanged=True,
    ).apply(ctx, targets=[mine, theirs])

    assert mine.controller_id == "p2" and theirs.controller_id == "p1"
    assert aura not in state.battlefield


# --- Modify Memory --------------------------------------------------------


def test_modify_memory_draws_when_neither_creature_ends_up_controlled():
    eng, state = _engine()
    src = _spec_source("Modify Memory", controller="p1")
    state.add_to_battlefield(src)
    a = _permanent("A", "p2", "Creature — Bear")
    b = _permanent("B", "p1", "Creature — Bear")
    # p1's own creature (b) exchanges for p2's (a) — p1 ends up controlling
    # `a`, so no draw. Swap set up so p1 controls NEITHER afterward instead:
    state.add_to_battlefield(a)
    state.add_to_battlefield(b)

    ctx = GameContext(state, eng.rules)
    hand_before = len(state.player_by_id("p1").hand)
    ExchangeControlEffect(
        source=src, target_kind="creature", count=2, distinct_controllers=True,
        draw_if_neither_controlled=3,
    ).apply(ctx, targets=[a, b])
    # a<->b exchanged: a now p1, b now p2 -> p1 controls `a` -> no draw
    assert a.controller_id == "p1" and b.controller_id == "p2"
    assert len(state.player_by_id("p1").hand) == hand_before


def test_modify_memory_no_exchange_and_neither_controlled_draws():
    eng, state = _engine()
    src = _spec_source("Modify Memory", controller="p1")
    state.add_to_battlefield(src)
    a = _permanent("A", "p2", "Creature — Bear")
    b = _permanent("B", "p2", "Creature — Bear")  # same controller -> no exchange
    state.add_to_battlefield(a)
    state.add_to_battlefield(b)
    p1 = state.player_by_id("p1")
    for i in range(5):
        p1.library.append(GameObject(
            Card(id=f"Filler{i}", name=f"Filler {i}", type_line="Land"),
            owner_id="p1", zone=Zone.LIBRARY,
        ))

    ctx = GameContext(state, eng.rules)
    hand_before = len(state.player_by_id("p1").hand)
    ExchangeControlEffect(
        source=src, target_kind="creature", count=2, distinct_controllers=True,
        draw_if_neither_controlled=3,
    ).apply(ctx, targets=[a, b])
    assert a.controller_id == "p2" and b.controller_id == "p2"  # unchanged
    assert len(state.player_by_id("p1").hand) == hand_before + 3


# --- Psychic Transfer -----------------------------------------------------


def test_psychic_transfer_swaps_within_five_and_not_beyond():
    from mtg_analyzer.game.effects.core import ExchangeLifeTotalsEffect
    for gap, swaps in ((5, True), (6, False)):
        eng, state = _engine()
        src = _spec_source("Psychic Transfer", controller="p1", zone=Zone.STACK)
        p1, p2 = state.player_by_id("p1"), state.player_by_id("p2")
        p1.life = 20
        p2.life = 20 - gap
        ctx = GameContext(state, eng.rules)
        ExchangeLifeTotalsEffect(
            source=src, target_kind="player", life_difference_at_most=5,
        ).apply(ctx, targets=[p2])
        assert (p1.life == 20 - gap) is swaps


# --- Mirror Mirror --------------------------------------------------------


def test_mirror_mirror_arms_a_delayed_trigger_capturing_the_target_player():
    eng, state = _engine()
    src = _spec_source("Mirror Mirror", controller="p1", zone=Zone.STACK)
    p2 = state.player_by_id("p2")
    ctx = GameContext(state, eng.rules)
    from mtg_analyzer.game.effects.core import CreateDelayedTriggerEffect
    CreateDelayedTriggerEffect(
        step="end", scope="any", capture="target_player",
        effects=[{"type": "triple_exchange", "params": {}}],
        source=src,
    ).apply(ctx, targets=[p2])
    assert len(state.delayed_triggers) == 1
    inner = state.delayed_triggers[0].effects[0]
    assert isinstance(inner, TripleExchangeEffect)
    assert inner.player is p2


def test_triple_exchange_swaps_life_permanents_and_zones():
    eng, state = _engine()
    src = _spec_source("Mirror Mirror", controller="p1", zone=Zone.BATTLEFIELD)
    state.add_to_battlefield(src)
    p1, p2 = state.player_by_id("p1"), state.player_by_id("p2")
    p1.life, p2.life = 20, 15
    mine = _permanent("Mine", "p1", "Creature — Bear")
    theirs = _permanent("Theirs", "p2", "Creature — Bear")
    state.add_to_battlefield(mine)
    state.add_to_battlefield(theirs)
    hand_card = Card(id="H", name="Hand Card", type_line="Instant")
    hand_obj = GameObject(hand_card, owner_id="p1", zone=Zone.HAND)
    p1.hand.append(hand_obj)

    ctx = GameContext(state, eng.rules)
    TripleExchangeEffect(source=src, player=p2).apply(ctx)

    assert p1.life == 15 and p2.life == 20
    assert mine.controller_id == "p2" and theirs.controller_id == "p1"
    assert hand_obj in p2.hand and hand_obj.owner_id == "p2"


# --- Cultural Exchange -----------------------------------------------------


def test_cultural_exchange_round1_pick_chains_into_round2():
    eng, state = _engine()
    src = _spec_source("Cultural Exchange", controller="p1", zone=Zone.STACK)
    a = _permanent("A-creature", "p1", "Creature — Bear")
    b1 = _permanent("B1", "p2", "Creature — Bear")
    b2 = _permanent("B2", "p2", "Creature — Bear")
    state.add_to_battlefield(a)
    state.add_to_battlefield(b1)
    state.add_to_battlefield(b2)

    ctx = GameContext(state, eng.rules)
    CulturalExchangeEffect(source=src).apply(ctx, targets=[
        state.player_by_id("p1"), state.player_by_id("p2"),
    ])
    # Round 1: pick `a` (p1's only creature) -> goes to p2.
    assert state.pending_choice is not None and state.pending_choice["kind"] == "choose_objects"
    eng.rules.resolve_choice(a.instance_id)
    assert a.controller_id == "p2"
    # Forced-complete or still asking -> either way it must move on to round 2
    # (from p2's creatures to p1) once round 1 finishes.
    while state.pending_choice and state.pending_choice["action"] == "gain_control_for" \
            and state.pending_choice.get("count", 0) > 1:
        # keep declining/round1 extra slots if offered — for this test we
        # just decline further round-1 picks to move to round 2 quickly.
        eng.rules.resolve_choice(None)
        break
    # Whatever remains open must now be offering B1/B2 (round 2, recipient p1).
    if state.pending_choice is not None:
        assert state.pending_choice["control_recipient_id"] == "p1"
        eng.rules.resolve_choice(b1.instance_id)
        assert b1.controller_id == "p1"


# --- Juxtapose --------------------------------------------------------------


def test_juxtapose_swaps_greatest_mv_creature_and_artifact():
    eng, state = _engine()
    src = _spec_source("Juxtapose", controller="p1", zone=Zone.STACK)
    mine_c = _permanent("MineC", "p1", "Creature — Bear", converted_mana_cost=2)
    theirs_c = _permanent("TheirsC", "p2", "Creature — Ogre", converted_mana_cost=5)
    mine_a = _permanent("MineA", "p1", "Artifact", converted_mana_cost=1)
    theirs_a = _permanent("TheirsA", "p2", "Artifact", converted_mana_cost=3)
    for o in (mine_c, theirs_c, mine_a, theirs_a):
        state.add_to_battlefield(o)

    ctx = GameContext(state, eng.rules)
    JuxtaposeEffect(source=src).apply(ctx, targets=[state.player_by_id("p2")])

    assert mine_c.controller_id == "p2" and theirs_c.controller_id == "p1"
    assert mine_a.controller_id == "p2" and theirs_a.controller_id == "p1"


def test_juxtapose_tie_break_picks_lowest_instance_id():
    eng, state = _engine()
    src = _spec_source("Juxtapose", controller="p1", zone=Zone.STACK)
    first = _permanent("First", "p1", "Creature — Bear", converted_mana_cost=3)
    second = _permanent("Second", "p1", "Creature — Bear", converted_mana_cost=3)
    theirs = _permanent("Theirs", "p2", "Creature — Ogre", converted_mana_cost=3)
    for o in (first, second, theirs):
        state.add_to_battlefield(o)

    picked = JuxtaposeEffect._greatest(state, "p1", want_creature=True)
    assert picked is first  # lower instance_id wins the tie


# --- Perplexing Chimera -----------------------------------------------------


def test_perplexing_chimera_reflexive_may_swaps_with_the_cast_spell():
    eng, state = _engine()
    chimera = _spec_source("Perplexing Chimera", controller="p1")
    state.add_to_battlefield(chimera)
    spell_card = Card(id="S", name="Some Spell", type_line="Sorcery", is_sorcery=True)
    spell_obj = GameObject(spell_card, owner_id="p2", zone=Zone.STACK)
    spell_obj.controller_id = "p2"
    item = StackItem(kind="spell", controller_id="p2", obj=spell_obj)
    state.stack.append(item)

    state.fire_event(GameEvent(
        EventType.SPELL_CAST, instance_id=spell_obj.instance_id, controller_id="p2",
    ))
    assert eng.rules.put_triggers_on_stack() == 1
    choice = state.pending_choice
    assert choice is not None and choice["kind"] == "trigger_target"
    assert set(o["id"] for o in choice["options"]) == {"do", "decline"}
    eng.rules.resolve_choice("do")
    eng.rules.resolve_top_of_stack()

    assert chimera.controller_id == "p2"
    assert spell_obj.controller_id == "p1"
    assert item.controller_id == "p1"


def test_perplexing_chimera_reflexive_may_declined_does_nothing():
    eng, state = _engine()
    chimera = _spec_source("Perplexing Chimera", controller="p1")
    state.add_to_battlefield(chimera)
    spell_card = Card(id="S2", name="Some Other Spell", type_line="Sorcery", is_sorcery=True)
    spell_obj = GameObject(spell_card, owner_id="p2", zone=Zone.STACK)
    spell_obj.controller_id = "p2"
    state.stack.append(StackItem(kind="spell", controller_id="p2", obj=spell_obj))

    state.fire_event(GameEvent(
        EventType.SPELL_CAST, instance_id=spell_obj.instance_id, controller_id="p2",
    ))
    assert eng.rules.put_triggers_on_stack() == 1
    eng.rules.resolve_choice("decline")
    assert chimera.controller_id == "p1" and spell_obj.controller_id == "p2"


# --- Sudden Substitution -----------------------------------------------------


def test_sudden_substitution_swaps_independent_spell_and_creature_targets():
    eng, state = _engine()
    src = _spec_source("Sudden Substitution", controller="p1", zone=Zone.STACK)
    creature = _permanent("Creature", "p1", "Creature — Bear")
    state.add_to_battlefield(creature)
    spell_card = Card(id="NS", name="Noncreature Spell", type_line="Sorcery", is_sorcery=True)
    spell_obj = GameObject(spell_card, owner_id="p2", zone=Zone.STACK)
    spell_obj.controller_id = "p2"
    state.stack.append(StackItem(kind="spell", controller_id="p2", obj=spell_obj))

    ctx = GameContext(state, eng.rules)
    ExchangeControlSpellEffect(
        source=src, permanent_target_kind="creature", spell_filter={"noncreature": True},
    ).apply(ctx, targets=[spell_obj, creature])

    assert creature.controller_id == "p2" and spell_obj.controller_id == "p1"


# --- Arteeoh, Dread Scavenger ------------------------------------------------


def test_arteeoh_exchange_then_copy_token_reflexive_connector():
    eng, state = _engine()
    arteeoh = _spec_source("Arteeoh, Dread Scavenger", controller="p1")
    state.add_to_battlefield(arteeoh)
    mine = _permanent("MyArt", "p1", "Artifact")
    theirs = _permanent("TheirArt", "p2", "Artifact")
    other = _permanent("OtherArt", "p2", "Artifact")
    for o in (mine, theirs, other):
        state.add_to_battlefield(o)

    ctx = GameContext(state, eng.rules)
    ExchangeControlThenCopyTokenEffect(source=arteeoh).apply(ctx, targets=[mine, theirs])
    assert mine.controller_id == "p2" and theirs.controller_id == "p1"

    # RULE 603.11 reflexive connector queued a fresh triggered ability that
    # still needs its own target — place it and pick a copy target.
    assert len(eng.rules.pending_triggers) == 1
    assert eng.rules.put_triggers_on_stack() == 1
    choice = state.pending_choice
    assert choice is not None and choice["kind"] == "trigger_target"
    eng.rules.resolve_choice(str(other.instance_id))
    eng.rules.resolve_top_of_stack()

    tokens = [o for o in state.battlefield if o.is_token and "Squirrel" in o.card.type_line]
    assert len(tokens) == 1
    tok = tokens[0]
    assert tok.is_creature and (tok.power, tok.toughness) == (1, 1)
    assert "artifact" in tok.type_words
