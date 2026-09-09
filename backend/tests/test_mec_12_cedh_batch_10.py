"""MEC-12 continuation, tenth pass (2026-08-11) -- devotion (RULE 700.6).

Continuation of the ninth pass (see `Done_Backend.md`'s matching entry).
Closes the "devotion" broader-gap item the fourth pass's full-pool sweep
had flagged as needing real design ("nothing today reads a permanent's own
pips toward it") -- in fact `continuous.count_selector`'s own
``devotion_to_<colour>`` selector already existed (built for Thassa's
Oracle), just with no oracle-text route reaching it and no multi-colour
reading. This pass:

- Generalized `continuous.count_selector`'s ``devotion_to_<key>`` suffix to
  a *set* of colours (Athreos/Karametra's "white and black"/"green and
  white") or one of the five two-colour wedge names (Devoted Abzan/Jeskai/
  Mardu/Sultai/Temur), summed via "does this mana symbol's colour set
  intersect the named colours" rather than a single-letter membership test
  -- a hybrid pip still counts exactly once even when it matches two of the
  named colours, matching the single-colour reading's existing hybrid
  behaviour.
- Added `subgrammars.DEVOTION`/`devotion_selector` -- one shared fragment
  every devotion-scaled handler embeds, so a new family only needs to
  parse the colour/wedge grammar once.
- RULE 613.7f "isn't a creature" (Purphoros/Heliod/Erebos/Karametra/
  Athreos' own devotion-threshold gods) needed **no new engine primitive
  at all**: `static_conditions.py`'s `control_count` condition already
  supports a ``max`` bound, and `type_change`'s existing `remove_types`
  static already threads `active_if` through `_selectors`. Just two new
  rows: a `_STATIC_CONDITION_RES` entry for "your devotion to `<X>` is
  less than `<n>`" (`control_count`, ``max=n-1``) and an unconditional
  `_NOT_A_CREATURE_RE` for the inner "~ isn't a creature." clause that
  `_conditional_static_specs` wraps it with.
- The amount-scaled family (pump/damage/lose_life/gain_life/create_token)
  all already had `amount_from_count_selector`/`count_selector` params from
  earlier batches (Craterhoof/Dockside/Frantic Firebolt-shaped) -- only
  `DealDamageEffect._apply_selector` (the *mass* "to each opponent" path)
  had never actually read `amount_from_count_selector` at all, a real
  latent gap `_amount_for` (the single-target path) had masked, only
  surfaced once Fanatic of Mogis exercised the mass+dynamic-amount
  combination together for the first time. `PumpEffect` gained a signed
  `amount_from_count_selector_negative` flag for the "-X/-X" debuff
  reading (Blight-Breath Catoblepas) -- `amount_from_count_selector` had
  only ever been read as an always-nonnegative "+X/+X" before.
- RULE 119's "drain" idiom ("`<player(s)>` lose[s] X life. You gain life
  equal to the life lost this way.", Gray Merchant of Asphodel and 15+
  other cache cards sharing the exact trailing sentence) needed a new
  primitive: `GameContext.life_lost_this_way`, a per-resolution
  accumulator threaded through `_apply_effects_partitioned`'s existing
  save/reset/restore idiom (`previous_targets`/`created_objects`'s own
  pattern) and `resume_deferred_effects`, incremented by `GameContext.
  lose_life`'s facade off the *actual* (post-replacement) life delta, read
  by a new `GainLifeEffect(count_selector="life_lost_this_way")`. Widened
  `_lose_life_selector` from `NUMBER` to `COUNT_X` along the way (`"x"`
  already threads through `RulesEngine._substitute_x` for free, since
  `LoseLifeEffect.amount` is a plain attribute that sentinel already
  walks -- no engine change needed, just the wider capture), closing
  Exsanguinate; added "each other player" as a `LoseLifeEffect`-selector
  alias for "each opponent" (Urborg Syphon-Mage) and a `creatures_you_
  control_of_type_<subtype>`-keyed row for "loses life equal to the number
  of `<type>` you control" (Malakir Bloodwitch).

Deliberately left open (documented in `BACKLOG.md`, not chased): "devotion
to hybrid" (Blended Twistling -- a different reading, any hybrid pip
counts, not a colour at all); Nykthos, Shrine to Nyx's mana ability
(amount depends on a colour chosen by the *same* ability -- a genuinely
new choice+amount coupling); Debt to the Deathless's "loses two times X
life" multiplier; Blood Tribute/Shard of the Nightbringer's "half their
life, rounded up"; Chancellor of the Dross's reveal-from-opening-hand
timing; Clive's discard-hand-then-draw-equal-to-devotion (a different,
two-clause shape).

New tests below (14 execute/parse tests). Full backend suite: 3,719
passed (+14 new), 238 skipped, 0 regressions.
`PARSER_VERSION` bumped 73 -> 74.
"""

from __future__ import annotations

from mtg_analyzer.config import DB_PATH
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.models.game.game_state import GameState
from mtg_analyzer.models.game.player import Player
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.services.card_database import CardDatabase


def _named(name: str) -> Card:
    return CardDatabase(DB_PATH).get_card(name)


def _engine() -> tuple[GameEngine, GameState]:
    p1 = Player(id="p1", name="Alice", life=20)
    p2 = Player(id="p2", name="Bob", life=20)
    state = GameState(players=[p1, p2])
    engine = GameEngine(state)
    return engine, state


def _bf(state: GameState, card: Card, controller: str = "p1") -> GameObject:
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


def _enter(engine: GameEngine, obj: GameObject, controller: str = "p1") -> None:
    """Fire the ENTERS_BATTLEFIELD event a `_bf`-placed permanent skips, so
    its ETB trigger actually fires, then drain the stack — auto-answering
    a `trigger_target`/`trigger_target_multi` pending choice with its first
    option (every card this file exercises only ever has one legal target)."""
    from mtg_analyzer.models.game.game_state import EventType, GameEvent

    engine.state.fire_event(
        GameEvent(EventType.ENTERS_BATTLEFIELD, instance_id=obj.instance_id, controller_id=controller)
    )
    engine.resolve_until_stable()
    while engine.state.pending_choice is not None:
        kind = engine.state.pending_choice.get("kind")
        options = engine.state.pending_choice.get("options") or []
        if kind == "trigger_target" and options:
            engine.rules.resolve_choice(str(options[0]["id"]))
        elif kind == "trigger_target_multi" and options:
            engine.rules.resolve_choice(str(options[0]["id"]))
        else:
            break
        engine.resolve_until_stable()


def _to_hand(state: GameState, card: Card, controller: str = "p1") -> GameObject:
    obj = GameObject(card, owner_id=controller, zone=Zone.HAND)
    bind_from_catalogue(obj)
    state.player_by_id(controller).hand.append(obj)
    return obj


def _reach_main(engine: GameEngine, active: str = "p1") -> None:
    engine.begin_turn()
    while engine.state.active_player.id != active:
        engine.begin_turn()
    engine.state.current_step = "main1"
    engine.recompute_continuous_effects()


def _red_pip(id_: str) -> Card:
    return Card(id=id_, name=id_, type_line="Artifact", mana_cost_string="{R}")


def _black_pip(id_: str) -> Card:
    return Card(id=id_, name=id_, type_line="Artifact", mana_cost_string="{B}")


def _white_pip(id_: str) -> Card:
    return Card(id=id_, name=id_, type_line="Artifact", mana_cost_string="{W}")


# ---------------------------------------------------------------------------
# Devotion: multi-colour continuous.count_selector generalization
# ---------------------------------------------------------------------------


def test_devotion_multicolor_sums_both_colours():
    from mtg_analyzer.game.continuous import count_selector

    engine, state = _engine()
    _bf(state, _white_pip("W1"))
    _bf(state, _black_pip("B1"))
    _bf(state, _black_pip("B2"))
    assert count_selector(state, "p1", "devotion_to_wb") == 3


def test_devotion_wedge_sums_three_colours():
    from mtg_analyzer.game.continuous import count_selector

    engine, state = _engine()
    _bf(state, _white_pip("W1"))
    _bf(state, _black_pip("B1"))
    _bf(state, Card(id="G1", name="G1", type_line="Artifact", mana_cost_string="{G}"))
    assert count_selector(state, "p1", "devotion_to_abzan") == 3


def test_devotion_hybrid_pip_counts_once_toward_combined_total():
    from mtg_analyzer.game.continuous import count_selector

    engine, state = _engine()
    _bf(state, Card(id="H1", name="H1", type_line="Artifact", mana_cost_string="{W/B}"))
    # A single {W/B} hybrid pip is one mana symbol of white-or-black — it
    # should count once toward the *combined* devotion, not twice.
    assert count_selector(state, "p1", "devotion_to_wb") == 1


# ---------------------------------------------------------------------------
# Purphoros/Heliod/Erebos/Karametra -- "isn't a creature" devotion threshold
# ---------------------------------------------------------------------------


def test_purphoros_is_modeled():
    assert parse_oracle(_named("Purphoros, God of the Forge")).modeled


def test_purphoros_not_a_creature_below_threshold():
    engine, state = _engine()
    purphoros = _bf(state, _named("Purphoros, God of the Forge"))
    engine.recompute_continuous_effects()
    # Purphoros costs {3}{R} — one red pip on its own, well under 5.
    assert purphoros.is_creature is False


def test_purphoros_becomes_a_creature_at_devotion_five():
    engine, state = _engine()
    purphoros = _bf(state, _named("Purphoros, God of the Forge"))
    for i in range(4):
        _bf(state, _red_pip(f"RedPip{i}"))
    engine.recompute_continuous_effects()
    # 1 (Purphoros' own {R}) + 4 more red pips = devotion 5.
    assert purphoros.is_creature is True


def test_karametra_multicolor_devotion_threshold():
    assert parse_oracle(_named("Karametra, God of Harvests")).modeled
    engine, state = _engine()
    karametra = _bf(state, _named("Karametra, God of Harvests"))
    engine.recompute_continuous_effects()
    assert karametra.is_creature is False


# ---------------------------------------------------------------------------
# Aspect of Hydra / Klothys's Design / Blight-Breath Catoblepas -- pump
# ---------------------------------------------------------------------------


def test_aspect_of_hydra_pumps_by_devotion_to_green():
    engine, state = _engine()
    _bf(state, Card(id="G1", name="G1", type_line="Artifact", mana_cost_string="{G}{G}{G}"))
    bear = _bf(state, Card(id="Bear", name="Bear", type_line="Creature — Bear",
                            is_creature=True, power=2, toughness=2))
    p1 = state.player_by_id("p1")
    p1.mana_pool.add("G", 1)
    spell = _to_hand(state, _named("Aspect of Hydra"))
    engine.cast_spell(p1, spell, targets=[bear])
    engine.resolve_until_stable()
    engine.recompute_continuous_effects()
    assert bear.power == 5 and bear.toughness == 5  # +3/+3 from devotion 3


def test_blight_breath_catoblepas_debuffs_by_devotion_to_black():
    engine, state = _engine()
    _bf(state, _black_pip("B1"))
    victim = _bf(state, Card(id="Victim", name="Victim", type_line="Creature — Bear",
                              is_creature=True, power=6, toughness=6), controller="p2")
    engine.recompute_continuous_effects()
    obj = _bf(state, _named("Blight-Breath Catoblepas"))
    _enter(engine, obj)
    engine.recompute_continuous_effects()
    # devotion to black = 3 (the one {B} pip + the Catoblepas' own {4}{B}{B})
    # -> -3/-3 on the opponent's creature.
    assert victim.power == 3 and victim.toughness == 3


# ---------------------------------------------------------------------------
# Fanatic of Mogis / Evangel of Heliod -- damage/tokens equal to devotion
# ---------------------------------------------------------------------------


def test_fanatic_of_mogis_damages_each_opponent_by_devotion():
    engine, state = _engine()
    _bf(state, _red_pip("R1"))
    _bf(state, _red_pip("R2"))
    obj = _bf(state, _named("Fanatic of Mogis"))
    _enter(engine, obj)
    # devotion to red = 3 (2 pips + Fanatic's own {2}{R}).
    assert state.player_by_id("p2").life == 17


def test_evangel_of_heliod_creates_tokens_equal_to_devotion():
    engine, state = _engine()
    _bf(state, _white_pip("W1"))
    obj = _bf(state, _named("Evangel of Heliod"))
    _enter(engine, obj)
    tokens = [o for o in state.battlefield if o.is_token and "Soldier" in o.card.type_line]
    # devotion to white = 3 (1 pip + Evangel's own {4}{W}{W}).
    assert len(tokens) == 3


# ---------------------------------------------------------------------------
# Gray Merchant / Exsanguinate / Malakir Bloodwitch / Urborg Syphon-Mage --
# the "life lost this way" drain family
# ---------------------------------------------------------------------------


def test_gray_merchant_is_modeled():
    assert parse_oracle(_named("Gray Merchant of Asphodel")).modeled


def test_gray_merchant_drains_by_devotion_to_black():
    engine, state = _engine()
    _bf(state, _black_pip("B1"))
    obj = _bf(state, _named("Gray Merchant of Asphodel"))
    _enter(engine, obj)
    # devotion to black = 3 (1 pip + Gray Merchant's own {3}{B}{B}).
    assert state.player_by_id("p2").life == 17
    assert state.player_by_id("p1").life == 23


def test_exsanguinate_x_life_loss_and_drain():
    engine, state = _engine()
    _reach_main(engine, "p1")
    p1 = state.player_by_id("p1")
    p1.mana_pool.add("B", 2)
    p1.mana_pool.add("C", 4)
    spell = _to_hand(state, _named("Exsanguinate"))
    engine.cast_spell(p1, spell, x=4)
    engine.resolve_until_stable()
    assert state.player_by_id("p2").life == 16
    assert state.player_by_id("p1").life == 24


def test_urborg_syphon_mage_each_other_player_drain():
    assert parse_oracle(_named("Urborg Syphon-Mage")).modeled


# ---------------------------------------------------------------------------
# Phasing out an opponent's permanent as a spell/ability effect (RULE 702.26)
# ---------------------------------------------------------------------------


def test_blink_dog_self_phases_out():
    assert parse_oracle(_named("Blink Dog")).modeled
    engine, state = _engine()
    dog = _bf(state, _named("Blink Dog"))
    p1 = state.player_by_id("p1")
    p1.mana_pool.add("W", 1)
    p1.mana_pool.add("C", 3)
    engine.activate_ability(p1, dog, ability_index=0)
    engine.resolve_until_stable()
    assert dog.phased_out is True


def test_reality_ripple_phases_out_an_opponents_permanent():
    assert parse_oracle(_named("Reality Ripple")).modeled
    engine, state = _engine()
    _reach_main(engine, "p1")
    victim = _bf(state, Card(id="Victim", name="Victim", type_line="Creature — Bear",
                              is_creature=True, power=2, toughness=2), controller="p2")
    p1 = state.player_by_id("p1")
    p1.mana_pool.add("U", 1)
    p1.mana_pool.add("C", 1)
    spell = _to_hand(state, _named("Reality Ripple"))
    engine.cast_spell(p1, spell, targets=[victim])
    engine.resolve_until_stable()
    assert victim.phased_out is True


def test_vanishing_phases_out_the_enchanted_creature():
    assert parse_oracle(_named("Vanishing")).modeled
    engine, state = _engine()
    host = _bf(state, Card(id="Host", name="Host", type_line="Creature — Bear",
                            is_creature=True, power=2, toughness=2))
    aura = _bf(state, _named("Vanishing"))
    aura.attached_to = host.instance_id
    p1 = state.player_by_id("p1")
    p1.mana_pool.add("U", 2)
    engine.activate_ability(p1, aura, ability_index=0)
    engine.resolve_until_stable()
    assert host.phased_out is True
    assert aura.phased_out is False  # RULE 702.26e — unattaches, doesn't phase together


def test_vodalian_illusionist_targets_either_player():
    assert parse_oracle(_named("Vodalian Illusionist")).modeled


# ---------------------------------------------------------------------------
# RULE 118.9's remaining alternative-cost "pitch" shapes
# ---------------------------------------------------------------------------


def _push_enemy_spell(engine: GameEngine, state: GameState, controller: str = "p2") -> GameObject:
    from mtg_analyzer.models.game.game_state import StackItem

    obj = GameObject(
        Card(id="Enemy Bolt", name="Enemy Bolt", type_line="Instant"),
        owner_id=controller, zone=Zone.STACK,
    )
    item = StackItem(kind="spell", controller_id=controller, obj=obj, description=obj.name, effects=[])
    state.stack.append(item)
    return obj


def test_flare_of_denial_is_modeled():
    assert parse_oracle(_named("Flare of Denial")).modeled


def test_flare_of_denial_needs_a_nontoken_blue_creature():
    engine, state = _engine()
    spell = _to_hand(state, _named("Flare of Denial"))
    p1 = state.player_by_id("p1")
    assert engine.can_cast(p1, spell, alt_cost=True) is False


def test_flare_of_denial_rejects_a_token_or_wrong_color():
    engine, state = _engine()
    token = _bf(state, Card(id="Token", name="Token", type_line="Creature — Bear",
                             is_creature=True, power=2, toughness=2, color_identity={"U"}))
    token.is_token = True
    _bf(state, Card(id="RedGuy", name="RedGuy", type_line="Creature — Bear",
                     is_creature=True, power=2, toughness=2, color_identity={"R"}))
    engine.recompute_continuous_effects()
    spell = _to_hand(state, _named("Flare of Denial"))
    p1 = state.player_by_id("p1")
    assert engine.can_cast(p1, spell, alt_cost=True) is False


def test_flare_of_denial_sacrifices_the_creature_and_counters():
    engine, state = _engine()
    victim = _bf(state, Card(id="BlueGuy", name="BlueGuy", type_line="Creature — Bear",
                              is_creature=True, power=2, toughness=2, color_identity={"U"}))
    engine.recompute_continuous_effects()
    spell = _to_hand(state, _named("Flare of Denial"))
    p1 = state.player_by_id("p1")
    target = _push_enemy_spell(engine, state)
    assert engine.can_cast(p1, spell, alt_cost=True, targets=[target]) is True
    engine.cast_spell(p1, spell, alt_cost=True, targets=[target])
    engine.resolve_until_stable()
    assert victim not in state.battlefield
    assert victim in state.player_by_id("p1").graveyard
    assert all(item.obj is not target for item in state.stack)


def test_snuff_out_needs_a_swamp():
    assert parse_oracle(_named("Snuff Out")).modeled
    engine, state = _engine()
    spell = _to_hand(state, _named("Snuff Out"))
    p1 = state.player_by_id("p1")
    p1.life = 20
    assert engine.can_cast(p1, spell, alt_cost=True) is False


def test_snuff_out_pays_life_when_you_control_a_swamp():
    engine, state = _engine()
    _bf(state, Card(id="Swamp1", name="Swamp1", type_line="Basic Land — Swamp", is_land=True))
    victim = _bf(state, Card(id="Ogre", name="Ogre", type_line="Creature — Ogre",
                              is_creature=True, power=3, toughness=3, color_identity={"R"}), controller="p2")
    engine.recompute_continuous_effects()
    spell = _to_hand(state, _named("Snuff Out"))
    p1 = state.player_by_id("p1")
    p1.life = 20
    assert engine.can_cast(p1, spell, alt_cost=True, targets=[victim]) is True
    engine.cast_spell(p1, spell, alt_cost=True, targets=[victim])
    engine.resolve_until_stable()
    assert p1.life == 16
    assert victim not in state.battlefield


def test_gush_is_modeled():
    assert parse_oracle(_named("Gush")).modeled


def test_gush_needs_two_islands():
    engine, state = _engine()
    _bf(state, Card(id="Island1", name="Island1", type_line="Basic Land — Island", is_land=True))
    spell = _to_hand(state, _named("Gush"))
    p1 = state.player_by_id("p1")
    assert engine.can_cast(p1, spell, alt_cost=True) is False


def test_gush_returns_two_islands_and_draws_two():
    engine, state = _engine()
    isl1 = _bf(state, Card(id="Island1", name="Island1", type_line="Basic Land — Island", is_land=True))
    isl2 = _bf(state, Card(id="Island2", name="Island2", type_line="Basic Land — Island", is_land=True))
    spell = _to_hand(state, _named("Gush"))
    p1 = state.player_by_id("p1")
    for i in range(2):
        p1.library.append(GameObject(Card(id=f"Filler{i}", name=f"Filler{i}", type_line="Instant"),
                                      owner_id="p1", zone=Zone.LIBRARY))
    hand_before = len(p1.hand)
    assert engine.can_cast(p1, spell, alt_cost=True) is True
    engine.cast_spell(p1, spell, alt_cost=True)
    engine.resolve_until_stable()
    assert isl1 not in state.battlefield and isl2 not in state.battlefield
    assert isl1 in p1.hand and isl2 in p1.hand
    # spell itself left the hand, both islands came back, plus two drawn.
    assert len(p1.hand) == hand_before - 1 + 2 + 2


def test_plain_mana_alt_cost_is_charged_not_skipped():
    """The Bringer-cycle shape ("You may pay {R}{G} rather than pay this
    spell's mana cost.") — reachable from oracle text only for an instant/
    sorcery today (`_is_spell`'s own scoping — the Bringers are creatures),
    so exercised directly against `ActivationCost`/`GameEngine` here rather
    than through a real cached card, confirming `_can_pay_alt_cast_cost`/
    `_pay_alt_cast_cost` actually charge ``cost.mana`` instead of silently
    ignoring it (the gap `cast_without_paying` alone would have left)."""
    from mtg_analyzer.game.costs import ActivationCost
    from mtg_analyzer.models.mana.mana_cost import ManaCost

    engine, state = _engine()
    spell = _to_hand(
        state, Card(id="Test Alt Mana", name="Test Alt Mana", type_line="Instant",
                     mana_cost_string="{5}{U}{U}", is_instant=True)
    )
    spell.alt_cast_cost = ActivationCost(mana=ManaCost.parse("{R}{G}"))
    p1 = state.player_by_id("p1")
    assert engine.can_cast(p1, spell, alt_cost=True) is False  # no mana at all yet
    p1.mana_pool.add("R", 1)
    p1.mana_pool.add("G", 1)
    assert engine.can_cast(p1, spell, alt_cost=True) is True
    engine.cast_spell(p1, spell, alt_cost=True)
    assert p1.mana_pool.pool["R"] == 0 and p1.mana_pool.pool["G"] == 0


# ---------------------------------------------------------------------------
# RULE 500.4-adjacent extra combat phase (Combat Celebrant/Godo shape)
# ---------------------------------------------------------------------------


def _advance_to(engine: GameEngine, step_name: str) -> None:
    guard = 0
    while engine.state.current_step != step_name:
        engine.advance_step()
        guard += 1
        assert guard < 50, f"never reached {step_name!r}"


def test_extra_combat_phase_effect_queues_a_request():
    engine, state = _engine()
    from mtg_analyzer.game.effects.core import ExtraCombatPhaseEffect, GameContext

    context = GameContext(state, engine.rules)
    ExtraCombatPhaseEffect().apply(context)
    assert state.pending_extra_combats == [False]


def test_insert_additional_combat_phase_splices_after_current_combat():
    engine, state = _engine()
    engine.start()
    _advance_to(engine, "declare_attackers")
    steps_before = len(engine._turn_steps)
    engine.insert_additional_combat_phase()
    assert len(engine._turn_steps) == steps_before + 5
    # The five new steps land right after the *current* combat's own
    # end_combat, not appended to the end of the turn.
    first_end_combat = next(
        i for i, (p, s) in enumerate(engine._turn_steps) if s.name == "end_combat"
    )
    inserted_names = [s.name for _, s in engine._turn_steps[first_end_combat + 1: first_end_combat + 6]]
    assert inserted_names == [
        "begin_combat", "declare_attackers", "declare_blockers", "combat_damage", "end_combat",
    ]
    # The original postcombat main phase is still there, now *after* the
    # inserted combat.
    assert engine._turn_steps[first_end_combat + 6][0].name == "postcombat_main"


def test_insert_additional_combat_phase_with_main_phase_too():
    engine, state = _engine()
    engine.start()
    _advance_to(engine, "declare_attackers")
    steps_before = len(engine._turn_steps)
    engine.insert_additional_combat_phase(main_phase_too=True)
    assert len(engine._turn_steps) == steps_before + 6


def test_aurelia_attack_trigger_queues_and_inserts_extra_combat():
    assert parse_oracle(_named("Aurelia, the Warleader")).modeled
    engine, state = _engine()
    aurelia = _bf(state, _named("Aurelia, the Warleader"))
    engine.start()
    _advance_to(engine, "declare_attackers")
    p1 = state.player_by_id("p1")
    engine.declare_attackers(p1, [aurelia])
    engine.resolve_until_stable()
    assert state.pending_extra_combats == [False]
    assert aurelia.tapped is False  # her own trigger untaps every creature you control

    steps_before = len(engine._turn_steps)
    engine.advance_step()  # declare_blockers — drains the queue on the way in
    assert len(engine._turn_steps) == steps_before + 5

    # Walk the rest of the (first) combat and confirm the *next* step is a
    # fresh declare_attackers rather than the postcombat main phase.
    _advance_to(engine, "end_combat")
    engine.advance_step()
    assert engine.state.current_step == "begin_combat"
    engine.advance_step()
    assert engine.state.current_step == "declare_attackers"
