"""cEDH cube batch 25, wave 2 — the mana primitives.

The headline mechanism is the **triggered mana ability** (RULE 605.1b/605.4,
`TriggeredAbility.mana_ability`): an ability that triggers off a mana
ability and produces only mana never uses the stack — it resolves on the
spot, so its mana is spendable within the very payment that triggered it.
Wild Growth and Kinnan are both unplayable without that timing.

Also covered here: `GameContext.trigger_event` (RULE 603.1 — the firing
event exposed for exactly one resolution window), `MirrorProducedManaEffect`
(Kinnan's "any type *that permanent* produced"), `TapMatchingLandsEffect`
(Mana Web's could-produce sweep), and the generalized `pay_cost_then`
optional payment (RULE 118.3) plus a `source_state` intervening-if (RULE
603.4) that together finish Mana Vault.
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.models.game_state import GameState
from mtg_analyzer.models.player import Player


def _engine():
    p1 = Player(id="p1", life=20)
    p2 = Player(id="p2", life=20)
    state = GameState(players=[p1, p2])
    return GameEngine(state), state, p1, p2


def _named(name):
    from mtg_analyzer.config import DB_PATH
    from mtg_analyzer.services.card_database import CardDatabase

    return CardDatabase(DB_PATH).get_card(name)


def _land(name, subtype="Forest", text="{T}: Add {G}."):
    return Card(
        id=name, name=name, type_line=f"Basic Land — {subtype}", is_land=True,
        oracle_text=text,
    )


def _bf(state, card, controller="p1", obj=None):
    obj = obj or GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


# ---------------------------------------------------------------------------
# Wild Growth — RULE 605.4: no stack, mana available immediately
# ---------------------------------------------------------------------------


def test_wild_growth_adds_its_mana_without_using_the_stack():
    engine, state, p1, _ = _engine()
    forest = _bf(state, _land("Forest"))
    aura = GameObject(_named("Wild Growth"), owner_id="p1", zone=Zone.BATTLEFIELD)
    bind_from_catalogue(aura)
    aura.attached_to = forest.instance_id
    state.add_to_battlefield(aura)

    engine.tap_for_mana(p1, forest)

    # RULE 605.4: the extra {G} is in the pool *now* — not queued as a
    # trigger that would need a stack resolution first. That timing is the
    # entire card: mana arriving later couldn't pay for the spell you
    # tapped the land to cast.
    assert p1.mana_pool.total() == 2
    assert not state.stack
    assert engine.rules.pending_triggers == []


def test_wild_growth_stops_the_moment_it_is_unattached():
    """RULE 603.1's `attached_permanent` subject is re-read live, so an
    Aura that has come off needs no teardown to stop firing."""
    engine, state, p1, _ = _engine()
    forest = _bf(state, _land("Forest"))
    aura = GameObject(_named("Wild Growth"), owner_id="p1", zone=Zone.BATTLEFIELD)
    bind_from_catalogue(aura)
    aura.attached_to = None
    state.add_to_battlefield(aura)

    engine.tap_for_mana(p1, forest)

    assert p1.mana_pool.total() == 1


def test_wild_growth_ignores_a_different_land_being_tapped():
    engine, state, p1, _ = _engine()
    enchanted = _bf(state, _land("Forest"))
    other = _bf(state, _land("Forest2"))
    aura = GameObject(_named("Wild Growth"), owner_id="p1", zone=Zone.BATTLEFIELD)
    bind_from_catalogue(aura)
    aura.attached_to = enchanted.instance_id
    state.add_to_battlefield(aura)

    engine.tap_for_mana(p1, other)

    assert p1.mana_pool.total() == 1


# ---------------------------------------------------------------------------
# Kinnan — the produced *type* comes from the firing
# ---------------------------------------------------------------------------


def _rock(name="Basalt Monolith", text="{T}: Add {C}{C}{C}."):
    return Card(id=name, name=name, type_line="Artifact", oracle_text=text)


def test_kinnan_copies_the_type_the_permanent_actually_produced():
    engine, state, p1, _ = _engine()
    kinnan = GameObject(_named("Kinnan, Bonder Prodigy"), owner_id="p1", zone=Zone.BATTLEFIELD)
    bind_from_catalogue(kinnan)
    state.add_to_battlefield(kinnan)
    rock = _bf(state, _rock())

    engine.tap_for_mana(p1, rock)

    # {C}{C}{C} from the rock plus one more {C} — Kinnan mirrors the type
    # that permanent produced, not "any colour".
    assert p1.mana_pool.pool.get("C") == 4
    assert not state.stack


def test_kinnan_never_triggers_off_a_land():
    engine, state, p1, _ = _engine()
    kinnan = GameObject(_named("Kinnan, Bonder Prodigy"), owner_id="p1", zone=Zone.BATTLEFIELD)
    bind_from_catalogue(kinnan)
    state.add_to_battlefield(kinnan)
    forest = _bf(state, _land("Forest"))

    engine.tap_for_mana(p1, forest)

    assert p1.mana_pool.total() == 1  # "nonland permanent" only


def test_kinnan_never_triggers_off_an_opponents_tap():
    engine, state, p1, p2 = _engine()
    kinnan = GameObject(_named("Kinnan, Bonder Prodigy"), owner_id="p1", zone=Zone.BATTLEFIELD)
    bind_from_catalogue(kinnan)
    state.add_to_battlefield(kinnan)
    rock = _bf(state, _rock(), controller="p2")

    engine.tap_for_mana(p2, rock)

    assert p2.mana_pool.total() == 3  # "whenever *you* tap"
    assert p1.mana_pool.total() == 0


# ---------------------------------------------------------------------------
# Mana Web — could-produce, not did-produce
# ---------------------------------------------------------------------------


def test_mana_web_taps_every_land_that_could_make_the_same_type():
    engine, state, p1, p2 = _engine()
    web = GameObject(_named("Mana Web"), owner_id="p1", zone=Zone.BATTLEFIELD)
    bind_from_catalogue(web)
    state.add_to_battlefield(web)

    tapped = _bf(state, _land("Forest"), controller="p2")
    other_forest = _bf(state, _land("Forest2"), controller="p2")
    island = _bf(state, _land("Island", "Island", "{T}: Add {U}."), controller="p2")
    my_forest = _bf(state, _land("MyForest"), controller="p1")

    engine.tap_for_mana(p2, tapped)
    engine.resolve_until_stable()

    assert other_forest.tapped is True   # also makes {G}
    assert island.tapped is False        # makes {U} only
    assert my_forest.tapped is False     # "that player"'s lands only


def test_mana_web_uses_what_a_land_could_produce_not_what_it_did():
    """RULE 605.1a: a dual tapped for {U} still locks down every land making
    {U} *or* its other colour — the difference between Mana Web being a real
    prison piece and a rounding error."""
    engine, state, p1, p2 = _engine()
    web = GameObject(_named("Mana Web"), owner_id="p1", zone=Zone.BATTLEFIELD)
    bind_from_catalogue(web)
    state.add_to_battlefield(web)

    dual = _bf(
        state,
        Card(id="Tropical Island", name="Tropical Island",
             type_line="Land — Forest Island", is_land=True,
             oracle_text="{T}: Add {G} or {U}."),
        controller="p2",
    )
    forest = _bf(state, _land("Forest"), controller="p2")

    from mtg_analyzer.game.mana_abilities import mana_abilities_for

    u_option = next(
        i for i, opt in enumerate(mana_abilities_for(dual, state=state)[0].options)
        if opt.get("U")
    )
    engine.tap_for_mana(p2, dual, option_index=u_option)  # tapped for {U}
    engine.resolve_until_stable()

    assert p2.mana_pool.pool.get("U") == 1
    assert forest.tapped is True  # {G} is still a type the dual *could* make


def test_mana_web_leaves_the_controllers_own_taps_alone():
    engine, state, p1, _ = _engine()
    web = GameObject(_named("Mana Web"), owner_id="p1", zone=Zone.BATTLEFIELD)
    bind_from_catalogue(web)
    state.add_to_battlefield(web)
    mine = _bf(state, _land("Forest"))
    other = _bf(state, _land("Forest2"))

    engine.tap_for_mana(p1, mine)
    engine.resolve_until_stable()

    assert other.tapped is False  # "a land an *opponent* controls"


# ---------------------------------------------------------------------------
# Mana Vault — pay_cost_then + a source-state intervening-if
# ---------------------------------------------------------------------------


def _mana_vault(state, engine):
    vault = GameObject(_named("Mana Vault"), owner_id="p1", zone=Zone.BATTLEFIELD)
    bind_from_catalogue(vault)
    vault.summoning_sick = False
    state.add_to_battlefield(vault)
    return vault


def test_mana_vault_does_not_untap_in_the_untap_step():
    engine, state, p1, _ = _engine()
    vault = _mana_vault(state, engine)
    vault.tapped = True

    engine._step_untap()

    assert vault.tapped is True


def test_mana_vault_upkeep_offers_an_optional_four_to_untap():
    engine, state, p1, _ = _engine()
    vault = _mana_vault(state, engine)
    vault.tapped = True
    p1.mana_pool.add("C", 4)

    state.fire_event(_step_event("upkeep"))
    engine.rules.put_triggers_on_stack()
    engine.rules.resolve_top_of_stack()

    choice = state.pending_choice
    assert choice["kind"] == "pay_cost_then"
    engine.resolve_pending_choice("pay")

    assert vault.tapped is False
    assert p1.mana_pool.total() == 0


def test_declining_mana_vaults_upkeep_payment_leaves_it_tapped():
    engine, state, p1, _ = _engine()
    vault = _mana_vault(state, engine)
    vault.tapped = True
    p1.mana_pool.add("C", 4)

    state.fire_event(_step_event("upkeep"))
    engine.rules.put_triggers_on_stack()
    engine.rules.resolve_top_of_stack()
    engine.resolve_pending_choice("decline")

    assert vault.tapped is True
    assert p1.mana_pool.total() == 4  # nothing charged


def test_mana_vault_is_never_asked_when_the_payment_is_unaffordable():
    """The "don't stall on a choice nobody can act on" shortcut ward and
    `counter_unless_pays` already take."""
    engine, state, p1, _ = _engine()
    vault = _mana_vault(state, engine)
    vault.tapped = True

    state.fire_event(_step_event("upkeep"))
    engine.rules.put_triggers_on_stack()
    engine.rules.resolve_top_of_stack()

    assert state.pending_choice is None
    assert vault.tapped is True


def test_mana_vaults_draw_step_ping_only_fires_while_it_is_tapped():
    engine, state, p1, _ = _engine()
    vault = _mana_vault(state, engine)

    vault.tapped = False
    state.fire_event(_step_event("draw"))
    assert engine.rules.pending_triggers == []   # RULE 603.4 intervening-if

    vault.tapped = True
    state.fire_event(_step_event("draw"))
    engine.rules.put_triggers_on_stack()
    engine.rules.resolve_top_of_stack()

    assert p1.life == 19  # "it deals 1 damage to *you*"


def _step_event(step):
    """The `STEP_BEGIN` event the turn loop fires (RULE 500.7) — carrying no
    player of its own, which is why `phase_relation` resolves "your upkeep"
    against the live active player instead."""
    from mtg_analyzer.models.events import EventType, GameEvent

    return GameEvent(EventType.STEP_BEGIN, step=step)
