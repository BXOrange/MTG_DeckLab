"""MEC-43 round 4D — control / zone changes / entry-choice statics.

Eight cards, each a genuinely different shape:

* Homeward Path — RULE 108.4/110.2's plain "each player gains control of
  all creatures they own" (`RegainControlOfOwnedCreaturesEffect`).
* Heliod, Sun-Crowned — a devotion-gated "isn't a creature" static
  (already parser-`MODELED`, copied verbatim since registering overrides
  the parser fallback entirely), a `EventType.LIFE_GAINED` counter
  trigger onto a new `targeting.py` kind
  (``creature_or_enchantment_you_control``), and a lifelink grant via the
  already-general `PumpEffect` 0/0-plus-keyword shape.
* Containment Priest — a new RULE 616.1-adjacent replacement,
  ``"uncast_creature_entry_exile"`` (`continuous.
  uncast_creature_entry_exiled`), checked at the same two graveyard/
  library-to-battlefield choke points `graveyard_library_entry_prohibited`
  already uses.
* Archon of Valor's Reach — reuses `ChooseNamedModeReplacement` (RULE
  601.2b) for its "choose a card type" pick and a new
  ``type_from_source_mode`` gate on `cast_prohibition`.
* Command Beacon — RULE 903.7's reverse direction, a new
  `PutCommanderIntoHandEffect`.
* Worldgorger Dragon — a new mandatory mass-exile selector
  (``"other_permanents_you_control"``) plus `track_exiled_with` wired into
  `ExileEffect`'s selector branch, and `ReturnAllExiledWithEffect` reused
  unchanged for the return half.
* Jodah, the Unifier — `"anthem"`'s existing ``power_count``/
  ``toughness_count`` (needing an explicit ``power``/``toughness`` of 1,
  the *per-unit* multiplier) plus a new `LegendarySpellFreeDigEffect`
  riding `RulesEngine.dig_until`.
* Kodama of the East Tree — a new `PutEqualOrLesserManaValueFromHandEffect`,
  a new ``"hand_to_battlefield"`` `request_choose_objects` action stamping
  `GameObject.entered_via_ability_id`, and a new ``not_entered_via_self``
  RULE 603.1 group-trigger condition (the Panharmonicon-shaped
  self-recursion guard the printed card requires).
"""

from __future__ import annotations

from mtg_analyzer.game import continuous
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.events import EventType, GameEvent
from mtg_analyzer.models.game_object import GameObject, Zone


def _named(name):
    from mtg_analyzer.config import DB_PATH
    from mtg_analyzer.services.card_database import CardDatabase

    return CardDatabase(DB_PATH).get_card(name)


def make_engine(*player_ids):
    return GameEngine.new_game(
        [(pid, pid, []) for pid in player_ids], starting_life=20, starting_hand=0
    )


def _card(name, type_line="Creature — Bear", cost="{1}{G}", cmc=2, **kw):
    # Only ``is_creature``/``is_instant``/``is_sorcery``/``is_land`` are
    # real `Card.__init__` flags -- ``is_artifact``/``is_enchantment``/
    # ``is_planeswalker`` are read-only properties derived from the
    # printed ``type_line`` instead, so they're never passed here.
    lowered = type_line.lower()
    for flag in ("instant", "sorcery", "land", "creature"):
        kw.setdefault(f"is_{flag}", flag in lowered)
    if kw.get("is_creature"):
        kw.setdefault("power", 2)
        kw.setdefault("toughness", 2)
    return Card(
        id=name, name=name, type_line=type_line, mana_cost_string=cost,
        converted_mana_cost=cmc, **kw,
    )


def _bf(state, card, controller="p1", sick=False, **kw):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD, **kw)
    obj.summoning_sick = sick
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


def _to_hand(state, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.HAND)
    bind_from_catalogue(obj)
    state.player_by_id(controller).hand.append(obj)
    return obj


def _to_library_top(state, card, controller="p1"):
    """`Player.library` is bottom-first (index 0), top-last — matching
    `player.library.pop()` reading the top card."""
    obj = GameObject(card, owner_id=controller, zone=Zone.LIBRARY)
    bind_from_catalogue(obj)
    state.player_by_id(controller).library.append(obj)
    return obj


def _fire_enters(state, obj, controller="p1"):
    state.fire_event(GameEvent(
        EventType.ENTERS_BATTLEFIELD, instance_id=obj.instance_id,
        controller_id=controller, object_types=sorted(obj.type_words),
    ))


def _fire_leaves(state, obj, controller="p1"):
    state.fire_event(GameEvent(
        EventType.LEAVES_BATTLEFIELD, instance_id=obj.instance_id,
        controller_id=controller, object_types=sorted(obj.type_words),
    ))


# ---------------------------------------------------------------------------
# Homeward Path
# ---------------------------------------------------------------------------


def test_homeward_path_gives_stolen_creatures_back_to_their_owners():
    eng = make_engine("p1", "p2")
    homeward_path = _bf(eng.state, _named("Homeward Path"))
    # Stolen: p2 owns it, but p1 currently controls it.
    stolen = GameObject(_card("Stolen Bear"), owner_id="p2", zone=Zone.BATTLEFIELD)
    stolen.controller_id = "p1"
    bind_from_catalogue(stolen)
    eng.state.add_to_battlefield(stolen)
    # An ordinary permanent shouldn't be touched.
    mine = _bf(eng.state, _card("My Own Bear"), controller="p1")

    eng.activate_ability(eng.state.player_by_id("p1"), homeward_path, 0)
    eng.resolve_until_stable()

    assert stolen.controller_id == "p2"
    assert mine.controller_id == "p1"


# ---------------------------------------------------------------------------
# Heliod, Sun-Crowned
# ---------------------------------------------------------------------------


def test_heliod_sun_crowned_life_gain_counter_and_lifelink_grant():
    eng = make_engine("p1", "p2")
    heliod = _bf(eng.state, _named("Heliod, Sun-Crowned"))
    p1 = eng.state.player_by_id("p1")
    bear = _bf(eng.state, _card("Bear"), controller="p1")

    eng.rules.gain_life(p1, 3)
    eng.resolve_until_stable()

    choice = eng.state.pending_choice
    assert choice is not None and choice["kind"] == "trigger_target"
    eng.rules.resolve_trigger_target_choice(bear.instance_id)
    eng.resolve_until_stable()

    assert bear.counters.get("+1/+1", 0) == 1

    eng.rules.add_mana(p1, "W", 2)
    eng.activate_ability(p1, heliod, 0, targets=[bear])
    eng.resolve_until_stable()

    assert "lifelink" in bear.temp_keywords


# ---------------------------------------------------------------------------
# Containment Priest
# ---------------------------------------------------------------------------


def test_containment_priest_exiles_a_reanimated_creature_instead():
    from mtg_analyzer.game.effects.core import GameContext, ReturnFromGraveyardEffect

    eng = make_engine("p1", "p2")
    _bf(eng.state, _named("Containment Priest"))
    victim = GameObject(_card("Fodder"), owner_id="p1", zone=Zone.GRAVEYARD)
    eng.state.active_player.graveyard.append(victim)

    effect = ReturnFromGraveyardEffect(target=victim, destination="battlefield")
    context = GameContext(eng.state, eng.rules)
    effect.apply(context, targets=[victim])

    assert victim not in eng.state.active_player.graveyard
    assert victim not in eng.state.battlefield
    assert victim in eng.state.active_player.exile


def test_without_containment_priest_reanimation_still_works():
    from mtg_analyzer.game.effects.core import GameContext, ReturnFromGraveyardEffect

    eng = make_engine("p1", "p2")
    victim = GameObject(_card("Fodder"), owner_id="p1", zone=Zone.GRAVEYARD)
    eng.state.active_player.graveyard.append(victim)

    effect = ReturnFromGraveyardEffect(target=victim, destination="battlefield")
    context = GameContext(eng.state, eng.rules)
    effect.apply(context, targets=[victim])

    assert victim in eng.state.battlefield


# ---------------------------------------------------------------------------
# Archon of Valor's Reach
# ---------------------------------------------------------------------------


def test_archon_of_valors_reach_locks_out_the_chosen_type_for_every_player():
    eng = make_engine("p1", "p2")
    archon = GameObject(_named("Archon of Valor's Reach"), owner_id="p1", zone=Zone.BATTLEFIELD)
    bind_from_catalogue(archon)
    assert len(archon.enter_choice_effects) == 1

    eng.rules._offer_enter_choices(archon, lambda: None)
    choice = eng.state.pending_choice
    assert choice is not None and choice["kind"] == "choose_named_mode"
    option_ids = {o["id"] for o in choice["options"]}
    assert option_ids == {"artifact", "enchantment", "instant", "sorcery", "planeswalker"}
    eng.rules.resolve_enter_choice("sorcery")
    eng.state.add_to_battlefield(archon)
    assert archon.chosen_mode == "sorcery"

    sorcery_spell = _to_hand(eng.state, _card("Bonfire", "Sorcery", "{1}{R}", 2))
    creature_spell = _to_hand(eng.state, _card("Some Bear"))

    # Unscoped ("Players can't...") — blocked for both this card's own
    # controller and an opponent.
    assert continuous.cast_prohibited(eng.state, eng.state.player_by_id("p1"), sorcery_spell.card) is True
    assert continuous.cast_prohibited(eng.state, eng.state.player_by_id("p2"), sorcery_spell.card) is True
    # A creature spell is untouched — only the chosen type is locked out.
    assert continuous.cast_prohibited(eng.state, eng.state.player_by_id("p1"), creature_spell.card) is False


# ---------------------------------------------------------------------------
# Command Beacon
# ---------------------------------------------------------------------------


def test_command_beacon_returns_the_commander_from_the_command_zone_to_hand():
    eng = make_engine("p1", "p2")
    beacon = _bf(eng.state, _named("Command Beacon"))
    p1 = eng.state.player_by_id("p1")
    commander = GameObject(
        _card("My Commander", "Legendary Creature — Human", "{2}{W}", 3),
        owner_id="p1", zone=Zone.COMMAND, is_commander=True,
    )
    bind_from_catalogue(commander)
    p1.add_to_zone(commander, Zone.COMMAND)

    eng.activate_ability(p1, beacon, 0)
    eng.resolve_until_stable()

    assert commander in p1.hand
    assert commander not in p1.command
    assert beacon not in eng.state.battlefield  # sacrificed as part of the cost


# ---------------------------------------------------------------------------
# Worldgorger Dragon
# ---------------------------------------------------------------------------


def test_worldgorger_dragon_exiles_other_permanents_then_returns_them_on_leaving():
    eng = make_engine("p1", "p2")
    mine1 = _bf(eng.state, _card("Mine1", "Artifact", "{1}", 1), controller="p1")
    mine2 = _bf(eng.state, _card("Mine2"), controller="p1")
    theirs = _bf(eng.state, _card("Theirs"), controller="p2")
    dragon = GameObject(_named("Worldgorger Dragon"), owner_id="p1", zone=Zone.BATTLEFIELD)
    bind_from_catalogue(dragon)
    eng.state.add_to_battlefield(dragon)

    _fire_enters(eng.state, dragon)
    eng.resolve_until_stable()

    assert mine1 not in eng.state.battlefield
    assert mine2 not in eng.state.battlefield
    assert theirs in eng.state.battlefield  # not "you control" — untouched
    assert dragon in eng.state.battlefield  # not "other" — untouched
    assert set(dragon.exiled_with_ids) == {mine1.instance_id, mine2.instance_id}

    _fire_leaves(eng.state, dragon)
    eng.resolve_until_stable()

    assert mine1 in eng.state.battlefield
    assert mine2 in eng.state.battlefield
    assert dragon.exiled_with_ids == []


# ---------------------------------------------------------------------------
# Jodah, the Unifier
# ---------------------------------------------------------------------------


def test_jodah_the_unifier_anthem_counts_himself():
    eng = make_engine("p1", "p2")
    jodah = _bf(eng.state, _named("Jodah, the Unifier"))
    eng.recompute_continuous_effects()
    assert (jodah.power, jodah.toughness) == (6, 6)  # printed 5/5, +1/+1 for himself

    other_legend = _bf(
        eng.state, _card("Second Legend", "Legendary Creature — Elf", "{1}{G}", 2),
        controller="p1",
    )
    eng.recompute_continuous_effects()
    assert (jodah.power, jodah.toughness) == (7, 7)
    assert (other_legend.power, other_legend.toughness) == (4, 4)


def test_jodah_the_unifier_digs_for_a_cheaper_legendary_after_a_legendary_cast_from_hand():
    eng = make_engine("p1", "p2")
    _bf(eng.state, _named("Jodah, the Unifier"))
    p1 = eng.state.player_by_id("p1")

    big_legend = _to_hand(
        eng.state, _card("Big Legend", "Legendary Creature — Giant", "{4}", 4),
    )
    filler = _to_library_top(eng.state, _card("Filler Land", "Land", "", 0))
    cheap_legend = _to_library_top(
        eng.state, _card("Cheap Legend", "Legendary Creature — Elf", "{1}", 1),
    )  # on top — the last one appended is popped first

    eng.rules.add_mana(p1, "G", 4)
    eng.state.current_step = "main1"
    eng.cast_spell(p1, big_legend)
    eng.resolve_until_stable()

    assert cheap_legend in p1.exile
    assert filler in p1.library
    assert eng.can_cast(p1, cheap_legend, alt_cost=False) is True


# ---------------------------------------------------------------------------
# Kodama of the East Tree
# ---------------------------------------------------------------------------


def test_kodama_of_the_east_tree_puts_a_permanent_from_hand_and_does_not_loop_on_its_own_put():
    eng = make_engine("p1", "p2")
    kodama = _bf(eng.state, _named("Kodama of the East Tree"))
    p1 = eng.state.player_by_id("p1")

    cheap = _to_hand(eng.state, _card("Cheap Artifact", "Artifact", "{1}", 1))
    too_expensive = _to_hand(eng.state, _card("Pricey Artifact", "Artifact", "{5}", 5))

    entering = GameObject(_card("Entering Thing", "Artifact", "{2}", 2), owner_id="p1", zone=Zone.BATTLEFIELD)
    bind_from_catalogue(entering)
    eng.state.add_to_battlefield(entering)
    _fire_enters(eng.state, entering)
    eng.resolve_until_stable()

    choice = eng.state.pending_choice
    assert choice is not None and choice["kind"] == "choose_objects"
    offered_ids = {o.get("instance_id") for o in choice["options"] if "instance_id" in o}
    assert cheap.instance_id in offered_ids
    assert too_expensive.instance_id not in offered_ids  # mana value too high

    eng.rules.resolve_choose_objects_choice(cheap.instance_id)
    eng.resolve_until_stable()

    assert cheap in eng.state.battlefield
    assert cheap.entered_via_ability_id == kodama.instance_id
    # Kodama's own put must not have re-triggered Kodama — no new choice.
    assert eng.state.pending_choice is None
