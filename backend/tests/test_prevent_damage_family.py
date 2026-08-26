"""MEC-30: carding the standing `prevent_damage` replacement family (RULE
615/616.1) and its new "a source of your choice" one-shot sibling.

`game/effects.py`'s `_prevent_damage_replacement` (`ReplacementRegistry`'s
``"prevent_damage"``) existed but was never bound to any real card — see
`docs/implementation-state/Done_Backend.md`'s "MEC-30" entry. This batch:

* widens ``to``/``recipient_filter``/``recipient_union``/``source_filter``/
  ``amount``/``amount_count_selector``/``rider`` on that factory (Sphere
  cycle/Urza's Armor/Daunting Defender/Shield of the Realm-shaped standing
  shields, Absorb N);
* wires RULE 613.6's ``active_if`` generically onto *any* replacement via
  `effect_binder.build_replacements` (Hedron-Field Purists' Leveler bands);
* fixes `models.emblem.Emblem` having no `replacement_effects` list and
  `RulesEngine._all_replacement_effects` never scanning `player.emblems`
  (Ajani Steadfast's own emblem);
* adds `RulesEngine.prevent_damage_to_player`/`_to_target`'s new
  ``watched_source_id``/``rider`` params plus the new `prevent_damage_
  from_source` (Circle of Protection/Rune of Protection's "a source of your
  choice" one-shot shield, `RequestPreventDamageSourceEffect`/`request_
  choose_objects`'s new ``"remember_source"`` action).

Execute tests throughout — a real `RulesEngine`/board, real damage dealt,
the resulting life/marked-damage/hand-size checked — not just spec parsing.
"""

from __future__ import annotations

from mtg_analyzer.game.effect_binder import attach_to_object, bind_from_catalogue, build_replacements
from mtg_analyzer.game.effects import ReplacementRegistry
from mtg_analyzer.game.rules_engine import RulesEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.models.game_state import GameState
from mtg_analyzer.models.player import Player
from mtg_analyzer.parser.oracle.spec import AbilitySpec, EffectSpec


def _state():
    p1, p2 = Player(id="p1", name="Alice", life=20), Player(id="p2", name="Bob", life=20)
    return GameState(players=[p1, p2]), p1, p2


def _creature(name, type_line="Creature — Bear", power=2, toughness=2, colors=None):
    return Card(
        id=name, name=name, type_line=type_line, is_creature=True,
        power=power, toughness=toughness, color_identity=set(colors or []),
    )


def _bf(state, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


# ---------------------------------------------------------------------------
# Phase 0: `_prevent_damage_replacement`'s widened params
# ---------------------------------------------------------------------------


def test_self_shield_prevents_up_to_amount_and_lets_the_rest_through():
    state, p1, p2 = _state()
    shielded = _bf(state, _creature("Shielded Bear"))
    attacker = _bf(state, _creature("Attacker"), controller="p2")
    effect = ReplacementRegistry.create("prevent_damage", {"to": "self", "amount": 2})
    effect.source = shielded
    shielded.replacement_effects.append(effect)
    engine = RulesEngine(state)

    engine.deal_damage(shielded, 3, source=attacker)
    assert shielded.damage_marked == 1  # 3 dealt, 2 prevented


def test_self_shield_fully_prevents_damage_at_or_under_the_amount():
    state, p1, p2 = _state()
    shielded = _bf(state, _creature("Shielded Bear"))
    attacker = _bf(state, _creature("Attacker"), controller="p2")
    effect = ReplacementRegistry.create("prevent_damage", {"to": "self", "amount": 2})
    effect.source = shielded
    shielded.replacement_effects.append(effect)
    engine = RulesEngine(state)

    engine.deal_damage(shielded, 1, source=attacker)
    assert shielded.damage_marked == 0


def test_recipient_filter_scopes_to_matching_subtype_only():
    # Daunting Defender-shaped: "If a source would deal damage to a Cleric
    # creature you control, prevent 1 of that damage."
    state, p1, p2 = _state()
    warden = _bf(state, _creature("Warden"))
    cleric = _bf(state, _creature("Acolyte", type_line="Creature — Human Cleric"))
    non_cleric = _bf(state, _creature("Squire", type_line="Creature — Human Soldier"))
    attacker = _bf(state, _creature("Attacker"), controller="p2")
    effect = ReplacementRegistry.create(
        "prevent_damage",
        {"to": "controlled_permanent", "recipient_filter": {"subtype": "cleric"}, "amount": 1},
    )
    effect.source = warden
    warden.replacement_effects.append(effect)
    engine = RulesEngine(state)

    engine.deal_damage(cleric, 2, source=attacker)
    engine.deal_damage(non_cleric, 2, source=attacker)
    assert cleric.damage_marked == 1  # 1 of 2 prevented
    assert non_cleric.damage_marked == 2  # untouched — not a Cleric


def test_attached_permanent_recipient_shields_only_the_equipped_creature():
    # Shield of the Realm-shaped: "If a source would deal damage to
    # equipped creature, prevent 2 of that damage."
    state, p1, p2 = _state()
    equipped = _bf(state, _creature("Equipped Knight"))
    unequipped = _bf(state, _creature("Bystander Knight"))
    shield = _bf(state, Card(id="Shield of the Realm", name="Shield of the Realm",
                              type_line="Artifact — Equipment"))
    shield.attached_to = equipped.instance_id
    attacker = _bf(state, _creature("Attacker"), controller="p2")
    effect = ReplacementRegistry.create("prevent_damage", {"to": "attached_permanent", "amount": 2})
    effect.source = shield
    shield.replacement_effects.append(effect)
    engine = RulesEngine(state)

    engine.deal_damage(equipped, 3, source=attacker)
    engine.deal_damage(unequipped, 3, source=attacker)
    assert equipped.damage_marked == 1  # 2 of 3 prevented
    assert unequipped.damage_marked == 3  # not the equipped creature


def test_recipient_union_matches_controller_or_a_filtered_permanent():
    # Hyperion, Supreme Hero-shaped: "If a source would deal damage to you
    # or a Hero you control, prevent all but 1 of that damage."
    state, p1, p2 = _state()
    hyperion = _bf(state, _creature("Hyperion", type_line="Legendary Creature — Hero"))
    other_hero = _bf(state, _creature("Sidekick", type_line="Creature — Hero"))
    stranger = _bf(state, _creature("Stranger", type_line="Creature — Bear"))
    attacker = _bf(state, _creature("Attacker"), controller="p2")
    effect = ReplacementRegistry.create(
        "prevent_damage",
        {"recipient_union": ["controller", {"subtype": "hero"}], "amount": {"all_but": 1}},
    )
    effect.source = hyperion
    hyperion.replacement_effects.append(effect)
    engine = RulesEngine(state)

    engine.deal_damage(p1, 5, source=attacker)
    engine.deal_damage(other_hero, 5, source=attacker)
    engine.deal_damage(stranger, 5, source=attacker)
    assert p1.life == 20 - 1  # only 1 got through
    assert other_hero.damage_marked == 1
    assert stranger.damage_marked == 5  # not a Hero, not the controller


def test_source_filter_only_matches_qualifying_source_color():
    # Sphere of Duty-shaped: "If a green source would deal damage to you,
    # prevent 2 of that damage."
    state, p1, p2 = _state()
    warden = _bf(state, _creature("Warden"))
    green_attacker = _bf(state, _creature("Green Attacker", colors=["G"]), controller="p2")
    red_attacker = _bf(state, _creature("Red Attacker", colors=["R"]), controller="p2")
    effect = ReplacementRegistry.create(
        "prevent_damage", {"to": "controller", "amount": 2, "source_filter": {"color": "G"}},
    )
    effect.source = warden
    warden.replacement_effects.append(effect)
    engine = RulesEngine(state)

    engine.deal_damage(p1, 3, source=green_attacker)
    assert p1.life == 20 - 1  # 2 of 3 prevented
    engine.deal_damage(p1, 3, source=red_attacker)
    assert p1.life == 20 - 1 - 3  # unprevented — wrong color


def test_amount_count_selector_reads_a_live_board_count():
    # Shield of the Avatar-shaped: "…prevent X of that damage, where X is
    # the number of creatures you control."
    state, p1, p2 = _state()
    equipped = _bf(state, _creature("Equipped Knight"))
    _bf(state, _creature("Friend One"))
    _bf(state, _creature("Friend Two"))
    shield = _bf(state, Card(id="Shield of the Avatar", name="Shield of the Avatar",
                              type_line="Artifact — Equipment"))
    shield.attached_to = equipped.instance_id
    attacker = _bf(state, _creature("Attacker"), controller="p2")
    effect = ReplacementRegistry.create(
        "prevent_damage",
        {"to": "attached_permanent", "amount_count_selector": "creatures_you_control"},
    )
    effect.source = shield
    shield.replacement_effects.append(effect)
    engine = RulesEngine(state)

    # 3 creatures you control (equipped + 2 friends) => prevent 3.
    engine.deal_damage(equipped, 5, source=attacker)
    assert equipped.damage_marked == 2


def test_rider_fires_off_the_actual_prevented_amount():
    # Swans of Bryn Argoll-shaped: "…prevent that damage. The source's
    # controller draws cards equal to the damage prevented this way."
    # (A fictional card name here, deliberately distinct from the real
    # "Swans of Bryn Argoll" catalogue entry exercised further below — this
    # test is probing the generic replacement primitive in isolation.)
    state, p1, p2 = _state()
    swans = _bf(state, _creature("Fictional Rider Bird"))
    attacker = _bf(state, _creature("Attacker"), controller="p2")
    effect = ReplacementRegistry.create(
        "prevent_damage",
        {"to": "self", "amount": "all", "rider": {"kind": "draw_cards", "recipient": "source_controller"}},
    )
    effect.source = swans
    swans.replacement_effects.append(effect)
    engine = RulesEngine(state)
    for _ in range(5):
        p2.library.append(GameObject(Card(id="Filler", name="Filler", type_line="Land"), owner_id="p2"))

    engine.deal_damage(swans, 3, source=attacker)
    assert swans.damage_marked == 0
    assert len(p2.hand) == 3


# ---------------------------------------------------------------------------
# Phase 0: `active_if` generic gating (`effect_binder.build_replacements`)
# ---------------------------------------------------------------------------


def test_active_if_gates_a_leveler_style_amount_band():
    # Hedron-Field Purists-shaped: two `prevent_damage` specs, each gated to
    # its own level band via `active_if`'s `source_counters` kind.
    # (A fictional card name here, deliberately distinct from the real
    # "Hedron-Field Purists" catalogue entry exercised further below — see
    # `test_hedron_field_purists_catalogue_entry_switches_band_by_level` —
    # this test is probing the generic replacement primitive in isolation,
    # same idiom `test_rider_fires_off_the_actual_prevented_amount` already
    # uses for "Fictional Rider Bird".)
    state, p1, p2 = _state()
    purist = _bf(state, _creature("Fictional Leveler Purist"))
    attacker = _bf(state, _creature("Attacker"), controller="p2")
    low_band = EffectSpec("prevent_damage", {
        "to": "controller", "amount": 1,
        "active_if": {"kind": "source_counters", "counter": "level", "max": 4},
    })
    high_band = EffectSpec("prevent_damage", {
        "to": "controller", "amount": 2,
        "active_if": {"kind": "source_counters", "counter": "level", "min": 5},
    })
    for effect in build_replacements([low_band, high_band], source=purist):
        purist.replacement_effects.append(effect)
    engine = RulesEngine(state)

    engine.deal_damage(p1, 3, source=attacker)
    assert p1.life == 20 - 2  # low band: prevent 1 of 3

    purist.counters["level"] = 5
    engine.deal_damage(p1, 3, source=attacker)
    assert p1.life == 20 - 2 - 1  # high band: prevent 2 of 3


# ---------------------------------------------------------------------------
# RULE 702.64 Absorb — bound structurally in `effect_binder.attach_to_object`
# ---------------------------------------------------------------------------


def test_absorb_keyword_prevents_damage_to_self():
    state, p1, p2 = _state()
    sliver = _bf(state, _creature("Lymph Sliver", type_line="Creature — Sliver"))
    attach_to_object(sliver, [AbilitySpec("keyword", [], keyword={"name": "absorb", "n": 1})])
    attacker = _bf(state, _creature("Attacker"), controller="p2")
    engine = RulesEngine(state)

    engine.deal_damage(sliver, 2, source=attacker)
    assert sliver.damage_marked == 1  # 1 of 2 prevented

    sliver.damage_marked = 0
    engine.deal_damage(sliver, 1, source=attacker)
    assert sliver.damage_marked == 0  # fully prevented


# ---------------------------------------------------------------------------
# Emblem replacement plumbing (Ajani Steadfast) — models.emblem/rules_engine
# ---------------------------------------------------------------------------


def test_emblem_replacement_effect_binds_and_applies():
    state, p1, p2 = _state()
    engine = RulesEngine(state)
    attacker = _bf(state, _creature("Attacker"), controller="p2")
    engine.create_emblem(p1, {
        "ability_kind": "replacement",
        "effects": [{"type": "prevent_damage", "params": {"to": "controller", "amount": {"all_but": 1}}}],
    })

    assert len(p1.emblems) == 1
    assert len(p1.emblems[0].replacement_effects) == 1
    assert p1.emblems[0].replacement_effects[0] in engine._all_replacement_effects()

    engine.deal_damage(p1, 5, source=attacker)
    assert p1.life == 20 - 1  # all but 1 prevented


# ---------------------------------------------------------------------------
# Phase 4: the "a source of your choice" one-shot chooser
# (`RequestPreventDamageSourceEffect` / `request_choose_objects`'s new
# ``"remember_source"`` action)
# ---------------------------------------------------------------------------


def test_chosen_source_shield_protects_only_that_source_this_turn():
    state, p1, p2 = _state()
    circle = _bf(state, Card(id="Circle of Protection: Red", name="Circle of Protection: Red",
                              type_line="Enchantment"))
    red_attacker = _bf(state, _creature("Red Attacker", colors=["R"]), controller="p2")
    other_attacker = _bf(state, _creature("Other Attacker", colors=["U"]), controller="p2")
    engine = RulesEngine(state)

    candidates = [o for o in state.battlefield if "R" in (o.card.color_identity or [])]
    engine.request_choose_objects(
        p1, candidates, "remember_source", count=1, source=circle,
        prevent_shield={
            "recipient_id": p1.id, "recipient_is_player": True, "amount": "all", "rider": None,
        },
    )
    assert state.pending_choice is None  # forced (single candidate) — resolves outright

    engine.deal_damage(p1, 3, source=red_attacker)
    assert p1.life == 20  # the chosen source's damage is prevented

    engine.deal_damage(p1, 3, source=other_attacker)
    assert p1.life == 20 - 3  # a different source is unaffected


def test_chosen_source_shield_is_swept_at_end_of_turn_even_if_unused():
    state, p1, p2 = _state()
    circle = _bf(state, Card(id="Circle of Protection: Red", name="Circle of Protection: Red",
                              type_line="Enchantment"))
    red_attacker = _bf(state, _creature("Red Attacker", colors=["R"]), controller="p2")
    from mtg_analyzer.game.game_engine import GameEngine

    game_engine = GameEngine.new_game([("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0)
    game_engine.state = state
    game_engine.rules = RulesEngine(state)

    engine = game_engine.rules
    engine.request_choose_objects(
        p1, [red_attacker], "remember_source", count=1, source=circle,
        prevent_shield={"recipient_id": p1.id, "recipient_is_player": True, "amount": "all", "rider": None},
    )
    assert any(getattr(e, "damage_prevention_shield", False) for e in p1.player_effects)

    game_engine._step_cleanup()
    assert not any(getattr(e, "damage_prevention_shield", False) for e in p1.player_effects)


# ---------------------------------------------------------------------------
# Real hand-authored catalogue cards (`game/ability_catalogue.py`), bound the
# ordinary way via `bind_from_catalogue` — not hand-built `EffectSpec`s.
# ---------------------------------------------------------------------------


def test_swans_of_bryn_argoll_catalogue_entry():
    state, p1, p2 = _state()
    swans = _bf(state, Card(id="Swans of Bryn Argoll", name="Swans of Bryn Argoll",
                             type_line="Creature — Bird Spirit", is_creature=True, power=3, toughness=4))
    attacker = _bf(state, _creature("Attacker"), controller="p2")
    engine = RulesEngine(state)
    for _ in range(4):
        p2.library.append(GameObject(Card(id="Filler", name="Filler", type_line="Land"), owner_id="p2"))

    engine.deal_damage(swans, 4, source=attacker)
    assert swans.damage_marked == 0
    assert len(p2.hand) == 4


def test_hostility_catalogue_entry():
    state, p1, p2 = _state()
    hostility = _bf(state, _creature("Hostility"))
    spell = _bf(state, Card(id="Fire Spell", name="Fire Spell", type_line="Instant",
                             is_instant=True), controller="p1")
    engine = RulesEngine(state)

    engine.deal_damage(p2, 4, source=spell)
    assert p2.life == 20  # fully prevented
    tokens = [o for o in state.battlefield if o.name == "Elemental Shaman"]
    assert len(tokens) == 4
    assert all(o.power == 3 and o.toughness == 1 for o in tokens)


def _resolve_any_replacement_order_choice(engine):
    """Defensive drain for a genuine RULE 616.1e ordering choice (2+
    replacements *really* simultaneously applicable to the same event) —
    kept as a no-op safety net for tests that don't care about ordering.
    Before the fourth MEC-30 pass this was load-bearing: every `ReplacementEffect`
    factory in `game/effects.py` only ever checked the event *type* in
    `can_replace`, leaving the real recipient/source scoping inside
    `replacement_fn` itself — so e.g. Gisela's two unrelated replacements
    (one opponent-scoped, one self-scoped) both reported "applicable" for
    *every* damage event and opened a pointless ordering choice each time,
    even though only one of them could ever actually change anything. Each
    factory now passes a `condition` callback mirroring its card's real
    printed condition, so `can_replace` reflects genuine applicability and
    this helper's loop body no longer fires for Gisela at all (see
    `test_gisela_blade_of_goldnight_no_spurious_ordering_choice` below)."""
    while engine.state.pending_choice and engine.state.pending_choice.get("kind") == "replacement_order":
        engine.resolve_replacement_order_choice(0)


def test_gisela_blade_of_goldnight_catalogue_entry():
    state, p1, p2 = _state()
    gisela = _bf(state, Card(id="Gisela, Blade of Goldnight", name="Gisela, Blade of Goldnight",
                              type_line="Legendary Creature — Angel", is_creature=True,
                              power=4, toughness=4))
    attacker = _bf(state, _creature("Attacker"), controller="p2")
    engine = RulesEngine(state)

    engine.deal_damage(p1, 4, source=attacker)
    _resolve_any_replacement_order_choice(engine)
    assert p1.life == 20 - 2  # half of 4, rounded up, survives

    # An odd amount is the case an even-only `dealt` can't catch: "rounded
    # up" prevention removes the larger half (ceil(3/2)=2), so only 1
    # survives — not 2 (which would be prevention rounded *down*).
    engine.deal_damage(p1, 3, source=attacker)
    _resolve_any_replacement_order_choice(engine)
    assert p1.life == 20 - 2 - 1  # half of 3, rounded up = 2 prevented, 1 survives

    engine.deal_damage(p2, 3, source=attacker)
    _resolve_any_replacement_order_choice(engine)
    assert p2.life == 20 - 6  # doubled, opponent-scoped


def test_gisela_blade_of_goldnight_no_spurious_ordering_choice():
    """RULE 616.1e (MEC-30 fourth pass): only the genuinely-applicable one
    of Gisela's two replacements should ever register as `can_replace`, so
    neither direction of damage should open a `replacement_order` choice —
    there's nothing real to order. This is the fix `_resolve_any_
    replacement_order_choice` above documents; before it, both directions
    opened a choice even though only one replacement ever changed anything."""
    state, p1, p2 = _state()
    _bf(state, Card(id="Gisela, Blade of Goldnight", name="Gisela, Blade of Goldnight",
                     type_line="Legendary Creature — Angel", is_creature=True,
                     power=4, toughness=4))
    attacker = _bf(state, _creature("Attacker"), controller="p2")
    engine = RulesEngine(state)

    engine.deal_damage(p1, 4, source=attacker)
    assert engine.state.pending_choice is None
    assert p1.life == 20 - 2  # half of 4, rounded up, survives

    engine.deal_damage(p2, 3, source=attacker)
    assert engine.state.pending_choice is None
    assert p2.life == 20 - 6  # doubled, opponent-scoped


def test_circle_of_protection_red_catalogue_entry():
    state, p1, p2 = _state()
    circle = _bf(state, Card(id="Circle of Protection: Red", name="Circle of Protection: Red",
                              type_line="Enchantment"))
    red_attacker = _bf(state, _creature("Red Attacker", colors=["R"]), controller="p2")
    engine = RulesEngine(state)

    (ability,) = circle.activated_abilities
    (effect,) = ability.effects
    from mtg_analyzer.game.effects import GameContext

    effect.source = circle
    effect.apply(GameContext(state, engine))

    engine.deal_damage(p1, 3, source=red_attacker)
    assert p1.life == 20  # the only (red) candidate was auto-picked and shielded


def test_color_any_filter_matches_any_listed_color():
    # Greater Realm of Preservation catalogue entry: "a black or red source".
    # This filter lives on `RequestPreventDamageSourceEffect`'s *candidate*
    # list (`combat.matches_object_filter`) — a different check from
    # `_prevent_damage_replacement`'s own hand-rolled ``source_filter`` DSL
    # (which only understands ``color``, not ``color_any``), so this has to
    # go through the real chooser, not `ReplacementRegistry`.
    state, p1, p2 = _state()
    realm = _bf(state, Card(id="Greater Realm of Preservation", name="Greater Realm of Preservation",
                             type_line="Enchantment"))
    black_attacker = _bf(state, _creature("Black Attacker", colors=["B"]), controller="p2")
    green_attacker = _bf(state, _creature("Green Attacker", colors=["G"]), controller="p2")
    engine = RulesEngine(state)

    (ability,) = realm.activated_abilities
    (effect,) = ability.effects
    from mtg_analyzer.game.effects import GameContext

    effect.source = realm
    effect.apply(GameContext(state, engine))  # only the black attacker qualifies — auto-picked

    engine.deal_damage(p1, 3, source=black_attacker)
    assert p1.life == 20  # black is in the list — fully prevented
    engine.deal_damage(p1, 3, source=green_attacker)
    assert p1.life == 20 - 3  # green isn't — unprevented, and never even offered


def test_color_from_source_filter_reads_the_shielding_objects_own_choice():
    # Story Circle/Prismatic Circle-shaped ETB "choose a color".
    state, p1, p2 = _state()
    circle = _bf(state, Card(id="Story Circle", name="Story Circle", type_line="Enchantment"))
    circle.chosen_color = "U"
    blue_attacker = _bf(state, _creature("Blue Attacker", colors=["U"]), controller="p2")
    black_attacker = _bf(state, _creature("Black Attacker", colors=["B"]), controller="p2")
    engine = RulesEngine(state)

    (ability,) = circle.activated_abilities
    (effect,) = ability.effects
    from mtg_analyzer.game.effects import GameContext

    effect.source = circle
    effect.apply(GameContext(state, engine))  # only one legal (blue) candidate — auto-picked

    engine.deal_damage(p1, 3, source=blue_attacker)
    assert p1.life == 20  # matches the chosen color

    engine.deal_damage(p1, 3, source=black_attacker)
    assert p1.life == 20 - 3  # a different color is unaffected, and never even offered


def test_subtype_from_source_filter_reads_the_shielding_objects_chosen_type():
    # Circle of Solace-shaped ETB "choose a creature type".
    state, p1, p2 = _state()
    circle = _bf(state, Card(id="Circle of Solace", name="Circle of Solace", type_line="Enchantment"))
    circle.chosen_type = "Goblin"
    goblin = _bf(state, _creature("Raider", type_line="Creature — Goblin"), controller="p2")
    non_goblin = _bf(state, _creature("Bystander"), controller="p2")
    engine = RulesEngine(state)

    (ability,) = circle.activated_abilities
    (effect,) = ability.effects
    from mtg_analyzer.game.effects import GameContext

    effect.source = circle
    effect.apply(GameContext(state, engine))  # only the Goblin is a legal candidate

    engine.deal_damage(p1, 3, source=goblin)
    assert p1.life == 20

    engine.deal_damage(p1, 3, source=non_goblin)
    assert p1.life == 20 - 3


def test_list_rider_fires_every_entry_off_the_same_prevented_amount():
    # New Way Forward-shaped: "…deals that much damage to that source's
    # controller and you draw that many cards." — two riders, one shield.
    state, p1, p2 = _state()
    ward = _bf(state, _creature("Warden"))
    attacker = _bf(state, _creature("Attacker"), controller="p2")
    for _ in range(3):
        p1.library.append(GameObject(Card(id="Filler", name="Filler", type_line="Land"), owner_id="p1"))
    effect = ReplacementRegistry.create(
        "prevent_damage",
        {
            "to": "controller", "amount": "all",
            "rider": [
                {"kind": "deal_damage_to_source_controller"},
                {"kind": "draw_cards", "recipient": "you"},
            ],
        },
    )
    effect.source = ward
    ward.replacement_effects.append(effect)
    engine = RulesEngine(state)

    engine.deal_damage(p1, 3, source=attacker)
    assert p1.life == 20  # prevented
    assert p2.life == 20 - 3  # reflected onto the attacker's controller
    assert len(p1.hand) == 3  # and the shield's own controller drew


def test_any_target_chooser_shields_a_targeted_permanent_not_just_you():
    # Circle of Despair/Martyr's Cause/Sanctum Guardian-shaped: "…would deal
    # damage to any target this turn" — the recipient is whatever was
    # targeted, not always this effect's own controller.
    state, p1, p2 = _state()
    victim = _bf(state, _creature("Victim"))
    attacker = _bf(state, _creature("Attacker"), controller="p2")
    engine = RulesEngine(state)

    engine.request_choose_objects(
        p1, [attacker], "remember_source", count=1, source=victim,
        prevent_shield={
            "recipient_id": victim.instance_id, "recipient_is_player": False,
            "amount": "all", "rider": None,
        },
    )
    assert state.pending_choice is None  # single candidate — auto-picked

    engine.deal_damage(victim, 4, source=attacker)
    assert victim.damage_marked == 0


def test_haazda_shield_mate_catalogue_entry_binds_both_abilities():
    state, p1, p2 = _state()
    mate = _bf(state, Card(id="Haazda Shield Mate", name="Haazda Shield Mate",
                            type_line="Creature — Human Soldier", is_creature=True,
                            power=1, toughness=1))
    attacker = _bf(state, _creature("Attacker"), controller="p2")
    engine = RulesEngine(state)

    assert len(mate.triggered_abilities) == 1  # the upkeep sacrifice-unless-pay clause
    (ability,) = mate.activated_abilities
    (effect,) = ability.effects
    from mtg_analyzer.game.effects import GameContext

    effect.source = mate
    effect.apply(GameContext(state, engine))
    # No source_filter, so both battlefield permanents (mate itself and the
    # attacker) are legal candidates — unlike the single-candidate tests
    # above, this really does open an interactive choice; answer it.
    assert state.pending_choice is not None
    engine.resolve_choose_objects_choice(attacker.instance_id)

    engine.deal_damage(p1, 3, source=attacker)
    assert p1.life == 20  # the shield ability itself still works


def test_circle_of_protection_artifacts_catalogue_entry_filters_by_card_type():
    state, p1, p2 = _state()
    circle = _bf(state, Card(id="Circle of Protection: Artifacts", name="Circle of Protection: Artifacts",
                              type_line="Enchantment"))
    artifact_attacker = _bf(
        state, Card(id="Ornithopter", name="Ornithopter", type_line="Artifact Creature — Thopter",
                     is_creature=True, power=0, toughness=2),
        controller="p2",
    )
    non_artifact_attacker = _bf(state, _creature("Bear Attacker"), controller="p2")
    engine = RulesEngine(state)

    (ability,) = circle.activated_abilities
    (effect,) = ability.effects
    from mtg_analyzer.game.effects import GameContext

    effect.source = circle
    effect.apply(GameContext(state, engine))  # only the artifact creature is a legal candidate

    engine.deal_damage(p1, 3, source=artifact_attacker)
    assert p1.life == 20

    engine.deal_damage(p1, 3, source=non_artifact_attacker)
    assert p1.life == 20 - 3


def test_deflecting_palm_catalogue_entry():
    # Deflecting Palm resolves and leaves the stack before its shield ever
    # matters, so — unlike the permanents above — it's deliberately never
    # put on the battlefield here: only its bound `spell_effects` are used,
    # the same "no live source object floating around, don't pretend one
    # exists" shape a resolved instant leaves the board in.
    state, p1, p2 = _state()
    palm_card = Card(id="Deflecting Palm", name="Deflecting Palm", type_line="Instant", is_instant=True)
    palm = GameObject(palm_card, owner_id="p1", zone=Zone.STACK)
    bind_from_catalogue(palm)
    palm.controller_id = "p1"
    attacker = _bf(state, _creature("Attacker"), controller="p2")
    engine = RulesEngine(state)

    (effect,) = palm.spell_effects
    from mtg_analyzer.game.effects import GameContext

    effect.source = palm
    effect.apply(GameContext(state, engine))

    engine.deal_damage(p1, 5, source=attacker)
    assert p1.life == 20  # prevented
    assert p2.life == 20 - 5  # reflected onto the attacker's controller


# ---------------------------------------------------------------------------
# MEC-30 third pass, Phase 1: three cheap Family A catalogue entries
# ---------------------------------------------------------------------------


def test_additional_damage_is_spell_filter_only_matches_a_spell_source():
    # `_additional_damage_replacement`'s new `is_spell` param — the
    # bonus-damage sibling of `_prevent_damage_replacement`'s own check.
    state, p1, p2 = _state()
    warden = _bf(state, _creature("Warden"))
    spell = _bf(state, Card(id="Fire Spell", name="Fire Spell", type_line="Instant",
                             is_instant=True), controller="p2")
    creature_attacker = _bf(state, _creature("Attacker"), controller="p2")
    effect = ReplacementRegistry.create(
        "additional_damage", {"amount": 1, "is_spell": True},
    )
    effect.source = warden
    warden.replacement_effects.append(effect)
    engine = RulesEngine(state)

    engine.deal_damage(p1, 3, source=spell)
    assert p1.life == 20 - 4  # 3 + 1 — a spell source

    engine.deal_damage(p1, 3, source=creature_attacker)
    assert p1.life == 20 - 4 - 3  # unmodified — not a spell


def test_rem_karolus_catalogue_entry():
    state, p1, p2 = _state()
    rem = _bf(state, Card(id="Rem Karolus, Stalwart Slayer", name="Rem Karolus, Stalwart Slayer",
                           type_line="Legendary Creature — Human Knight", is_creature=True,
                           power=2, toughness=3))
    ally = _bf(state, _creature("Ally"))
    foe = _bf(state, _creature("Foe"), controller="p2")
    spell_at_p1 = _bf(state, Card(id="Bolt Alice", name="Bolt Alice", type_line="Instant",
                                   is_instant=True), controller="p2")
    spell_at_p2 = _bf(state, Card(id="Bolt Bob", name="Bolt Bob", type_line="Instant",
                                   is_instant=True), controller="p1")
    creature_attacker = _bf(state, _creature("Non-Spell Attacker"), controller="p2")
    engine = RulesEngine(state)

    # a spell dealing damage to Rem's controller or another permanent they
    # control is prevented outright
    engine.deal_damage(p1, 5, source=spell_at_p1)
    assert p1.life == 20
    engine.deal_damage(ally, 5, source=spell_at_p1)
    assert ally.damage_marked == 0
    # a non-spell source is unaffected by either replacement
    engine.deal_damage(p1, 4, source=creature_attacker)
    assert p1.life == 20 - 4

    # a spell dealing damage to an opponent (or their permanent) instead
    # deals 1 more
    engine.deal_damage(p2, 3, source=spell_at_p2)
    assert p2.life == 20 - 4  # 3 + 1
    engine.deal_damage(foe, 3, source=spell_at_p2)
    assert foe.damage_marked == 4  # 3 + 1


def test_hedron_field_purists_catalogue_entry_switches_band_by_level():
    state, p1, p2 = _state()
    purist = _bf(state, Card(id="Hedron-Field Purists", name="Hedron-Field Purists",
                              type_line="Creature — Human Cleric", is_creature=True,
                              power=0, toughness=3))
    attacker = _bf(state, _creature("Attacker"), controller="p2")
    engine = RulesEngine(state)

    # RULE 711.4b: with no level counters, an unleveled Leveler has its base
    # characteristics only — neither band's ability is active yet. Matches
    # the general parser-driven Leveler pipeline's own convention
    # (`parser/oracle/gate.py`'s `_process_leveler_body`, `min_level=lo`),
    # which always sets a lower bound for a "LEVEL 1-4"-shaped band.
    engine.deal_damage(p1, 3, source=attacker)
    assert p1.life == 20 - 3  # no counters yet: no prevention at all

    purist.counters["level"] = 1
    engine.deal_damage(p1, 3, source=attacker)
    assert p1.life == 20 - 3 - 2  # LEVEL 1-4: prevent 1 of 3

    purist.counters["level"] = 5
    engine.deal_damage(p1, 3, source=attacker)
    assert p1.life == 20 - 3 - 2 - 1  # LEVEL 5+: prevent 2 of 3


def test_battletide_alchemist_catalogue_entry_scales_by_cleric_count():
    # The real printed text is "a source would deal damage to **a player**"
    # — unscoped by who's being hit, only "the number of Clerics **you**
    # control" (Battletide's own controller) scopes the amount.
    state, p1, p2 = _state()
    alchemist = _bf(state, Card(id="Battletide Alchemist", name="Battletide Alchemist",
                                 type_line="Creature — Kithkin Cleric", is_creature=True,
                                 power=3, toughness=4))
    _bf(state, _creature("Other Cleric", type_line="Creature — Human Cleric"))
    attacker = _bf(state, _creature("Attacker"), controller="p2")
    engine = RulesEngine(state)

    # 2 Clerics Battletide's own controller (p1) controls => prevent 2,
    # regardless of which player is actually being damaged.
    engine.deal_damage(p1, 5, source=attacker)
    assert p1.life == 20 - 3  # 5 - 2 prevented
    engine.deal_damage(p2, 5, source=attacker)
    assert p2.life == 20 - 3  # 5 - 2 prevented — still scoped by p1's Clerics


# ---------------------------------------------------------------------------
# MEC-30 third pass, Phase 2: Nine Lives (new `source_counters_at_least`
# trigger-condition key, not a new state-trigger subsystem)
# ---------------------------------------------------------------------------


def _nine_lives_engine():
    from mtg_analyzer.game.game_engine import GameEngine

    return GameEngine.new_game([("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0)


def test_nine_lives_shields_and_accumulates_incarnation_counters():
    game_engine = _nine_lives_engine()
    state = game_engine.state
    p1, p2 = state.player_by_id("p1"), state.player_by_id("p2")
    nine_lives = _bf(state, Card(id="Nine Lives", name="Nine Lives", type_line="Enchantment"))
    attacker = _bf(state, _creature("Attacker"), controller="p2")
    engine = game_engine.rules

    engine.deal_damage(p1, 4, source=attacker)
    assert p1.life == 20  # fully prevented
    assert nine_lives.counters.get("incarnation", 0) == 1
    assert engine.put_triggers_on_stack() == 0  # only 1 counter — below the threshold


def test_nine_lives_exiles_itself_once_incarnation_counters_reach_nine():
    game_engine = _nine_lives_engine()
    state = game_engine.state
    p1, p2 = state.player_by_id("p1"), state.player_by_id("p2")
    nine_lives = _bf(state, Card(id="Nine Lives", name="Nine Lives", type_line="Enchantment"))
    attacker = _bf(state, _creature("Attacker"), controller="p2")
    engine = game_engine.rules

    for _ in range(8):
        engine.deal_damage(p1, 1, source=attacker)
        assert engine.put_triggers_on_stack() == 0  # still under 9
    assert nine_lives.counters.get("incarnation", 0) == 8

    engine.deal_damage(p1, 1, source=attacker)
    assert nine_lives.counters.get("incarnation", 0) == 9
    assert engine.put_triggers_on_stack() == 1  # the exile trigger fires
    engine.resolve_top_of_stack()

    assert nine_lives not in state.battlefield
    assert nine_lives in p1.exile


def test_nine_lives_loses_the_game_when_it_leaves_the_battlefield():
    game_engine = _nine_lives_engine()
    state = game_engine.state
    p1 = state.player_by_id("p1")
    nine_lives = _bf(state, Card(id="Nine Lives", name="Nine Lives", type_line="Enchantment"))
    engine = game_engine.rules

    engine.destroy(nine_lives)
    assert engine.put_triggers_on_stack() == 1
    engine.resolve_top_of_stack()

    assert p1.has_lost


# ---------------------------------------------------------------------------
# MEC-30 third pass, Phase 3: "Damage can't be prevented this turn"
# (Insult // Injury, Isengard Unleashed) — `GameState.damage_prevention_
# disabled` + the new `ReplacementEffect.prevents_damage` marker.
# ---------------------------------------------------------------------------


def test_disable_damage_prevention_blocks_an_existing_standing_shield():
    state, p1, p2 = _state()
    warden = _bf(state, _creature("Warden"))
    attacker = _bf(state, _creature("Attacker"), controller="p2")
    effect = ReplacementRegistry.create("prevent_damage", {"to": "controller", "amount": "all"})
    effect.source = warden
    warden.replacement_effects.append(effect)
    engine = RulesEngine(state)

    engine.deal_damage(p1, 3, source=attacker)
    assert p1.life == 20  # shield works normally

    engine.disable_damage_prevention_this_turn()
    engine.deal_damage(p1, 3, source=attacker)
    assert p1.life == 20 - 3  # the same shield is now ignored


def test_disable_damage_prevention_also_blocks_a_one_shot_shield():
    state, p1, p2 = _state()
    attacker = _bf(state, _creature("Attacker"), controller="p2")
    engine = RulesEngine(state)

    engine.prevent_damage_to_player(p1, "all")
    engine.disable_damage_prevention_this_turn()
    engine.deal_damage(p1, 3, source=attacker)
    assert p1.life == 20 - 3  # the one-shot shield is ignored too


def test_grant_damage_multiplier_this_turn_only_doubles_the_grantors_own_sources():
    state, p1, p2 = _state()
    source_card = Card(id="Insult // Injury", name="Insult // Injury", type_line="Sorcery")
    source = GameObject(source_card, owner_id="p1", zone=Zone.STACK)
    source.controller_id = "p1"
    my_attacker = _bf(state, _creature("My Attacker"), controller="p1")
    their_attacker = _bf(state, _creature("Their Attacker"), controller="p2")
    engine = RulesEngine(state)

    engine.grant_damage_multiplier_this_turn(p1, source, multiplier=2)
    engine.deal_damage(p2, 3, source=my_attacker)
    assert p2.life == 20 - 6  # doubled — a source p1 controls
    engine.deal_damage(p1, 3, source=their_attacker)
    assert p1.life == 20 - 3  # unaffected — not p1's own source


def test_insult_injury_catalogue_entry_disables_prevention_and_doubles():
    state, p1, p2 = _state()
    insult = GameObject(Card(id="Insult // Injury", name="Insult // Injury", type_line="Sorcery"),
                         owner_id="p1", zone=Zone.STACK)
    bind_from_catalogue(insult)
    insult.controller_id = "p1"
    attacker = _bf(state, _creature("Attacker"), controller="p1")
    engine = RulesEngine(state)
    engine.prevent_damage_to_player(p2, "all")  # p2 has a pre-existing shield

    from mtg_analyzer.game.effects import GameContext

    context = GameContext(state, engine)
    for effect in insult.spell_effects:
        effect.source = insult
        effect.apply(context)

    engine.deal_damage(p2, 3, source=attacker)
    assert p2.life == 20 - 6  # shield ignored, damage doubled


def test_isengard_unleashed_catalogue_entry_only_triples_damage_to_opponents():
    state, p1, p2 = _state()
    isengard = GameObject(Card(id="Isengard Unleashed", name="Isengard Unleashed", type_line="Sorcery"),
                           owner_id="p1", zone=Zone.STACK)
    bind_from_catalogue(isengard)
    isengard.controller_id = "p1"
    my_creature = _bf(state, _creature("My Creature"), controller="p1")
    engine = RulesEngine(state)

    from mtg_analyzer.game.effects import GameContext

    context = GameContext(state, engine)
    for effect in isengard.spell_effects:
        effect.source = isengard
        effect.apply(context)

    engine.deal_damage(p2, 2, source=my_creature)
    assert p2.life == 20 - 6  # tripled — an opponent
    engine.deal_damage(p1, 2, source=my_creature)
    assert p1.life == 20 - 2  # unaffected — not an opponent, `to_opponent_only`


def test_damage_prevention_disabled_flag_is_swept_at_cleanup():
    from mtg_analyzer.game.game_engine import GameEngine

    game_engine = GameEngine.new_game([("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0)
    game_engine.rules.disable_damage_prevention_this_turn()
    assert game_engine.state.damage_prevention_disabled is True

    game_engine._step_cleanup()
    assert game_engine.state.damage_prevention_disabled is False


def test_damage_multiplier_grant_is_swept_at_cleanup_even_if_unused():
    from mtg_analyzer.game.game_engine import GameEngine

    game_engine = GameEngine.new_game([("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0)
    p1 = game_engine.state.player_by_id("p1")
    source = GameObject(Card(id="Insult // Injury", name="Insult // Injury", type_line="Sorcery"),
                         owner_id="p1", zone=Zone.STACK)
    source.controller_id = "p1"

    game_engine.rules.grant_damage_multiplier_this_turn(p1, source, multiplier=2)
    assert any(getattr(e, "damage_multiplier_grant", False) for e in p1.player_effects)

    game_engine._step_cleanup()
    assert not any(getattr(e, "damage_multiplier_grant", False) for e in p1.player_effects)


# ---------------------------------------------------------------------------
# MEC-30 third pass, Phase 4: Ajani Steadfast (all three loyalty abilities,
# not just the emblem — the parser claims none of them)
# ---------------------------------------------------------------------------


def _ajani():
    return Card(id="Ajani Steadfast", name="Ajani Steadfast",
                type_line="Legendary Planeswalker — Ajani", loyalty=4)


def test_ajani_steadfast_plus_one_pumps_up_to_one_target_creature():
    state, p1, p2 = _state()
    ajani = _bf(state, _ajani())
    bear = _bf(state, _creature("Bear"))
    engine = RulesEngine(state)

    from mtg_analyzer.game.effects import GameContext

    (plus_one, _minus_two, _minus_seven) = ajani.activated_abilities
    (effect,) = plus_one.effects
    effect.source = ajani
    context = GameContext(state, engine)
    effect.apply(context, targets=[bear])

    context.recompute()
    assert bear.power == 3 and bear.toughness == 3  # 2/2 base +1/+1
    assert "first strike" in bear.granted_keywords
    assert "vigilance" in bear.granted_keywords
    assert "lifelink" in bear.granted_keywords


def test_ajani_steadfast_minus_two_counters_creatures_and_other_planeswalkers():
    state, p1, p2 = _state()
    ajani = _bf(state, _ajani())
    bear = _bf(state, _creature("Bear"))
    other_pw = _bf(state, Card(id="Other Walker", name="Other Walker",
                                type_line="Planeswalker — Other", loyalty=3))
    engine = RulesEngine(state)

    from mtg_analyzer.game.effects import GameContext

    (_plus_one, minus_two, _minus_seven) = ajani.activated_abilities
    context = GameContext(state, engine)
    for effect in minus_two.effects:
        effect.source = ajani
        effect.apply(context)

    assert bear.counters.get("+1/+1", 0) == 1
    assert ajani.counters.get("+1/+1", 0) == 0  # Ajani itself isn't a creature
    assert other_pw.counters.get("loyalty", 0) == 3 + 1  # got a loyalty counter
    assert ajani.counters.get("loyalty", 0) == 4  # unchanged — "each OTHER planeswalker"


def test_ajani_steadfast_minus_seven_emblem_shields_you_and_your_planeswalkers():
    state, p1, p2 = _state()
    ajani = _bf(state, _ajani())
    other_pw = _bf(state, Card(id="Other Walker", name="Other Walker",
                                type_line="Planeswalker — Other", loyalty=3))
    attacker = _bf(state, _creature("Attacker"), controller="p2")
    engine = RulesEngine(state)

    from mtg_analyzer.game.effects import GameContext

    (_plus_one, _minus_two, minus_seven) = ajani.activated_abilities
    (effect,) = minus_seven.effects
    effect.source = ajani
    effect.apply(GameContext(state, engine))

    assert len(p1.emblems) == 1
    engine.deal_damage(p1, 5, source=attacker)
    assert p1.life == 20 - 1  # all but 1 prevented
    engine.deal_damage(other_pw, 5, source=attacker)
    # RULE 306.9: damage to a planeswalker removes that many loyalty
    # counters instead of marking damage — 1 of 5 got through, so only 1
    # loyalty counter came off.
    assert other_pw.counters.get("loyalty", 0) == 3 - 1


# ---------------------------------------------------------------------------
# MEC-30 third pass, Phase 5: Family B chooser extensions (Kithkin Armor,
# Shadowbane, Honorable Passage, Dazzling Reflection, Samite Blessing)
# ---------------------------------------------------------------------------


def test_kithkin_armor_catalogue_entry_shields_the_enchanted_creature():
    state, p1, p2 = _state()
    host = _bf(state, _creature("Host Bear"))
    armor = _bf(state, Card(id="Kithkin Armor", name="Kithkin Armor", type_line="Enchantment — Aura"))
    armor.attached_to = host.instance_id
    attacker = _bf(state, _creature("Attacker"), controller="p2")
    engine = RulesEngine(state)

    from mtg_analyzer.game.effects import GameContext

    (ability,) = armor.activated_abilities
    (effect,) = ability.effects
    effect.source = armor
    effect.apply(GameContext(state, engine))
    # No source_filter, so every battlefield permanent qualifies (host,
    # armor, attacker) — a real choice, not an auto-pick; answer it.
    assert state.pending_choice is not None
    engine.resolve_choose_objects_choice(attacker.instance_id)

    engine.deal_damage(host, 4, source=attacker)
    assert host.damage_marked == 0


def test_shadowbane_catalogue_entry_shields_you_and_your_creatures():
    state, p1, p2 = _state()
    shadowbane = GameObject(Card(id="Shadowbane", name="Shadowbane", type_line="Instant"),
                             owner_id="p1", zone=Zone.STACK)
    bind_from_catalogue(shadowbane)
    shadowbane.controller_id = "p1"
    my_creature = _bf(state, _creature("My Creature"))
    black_attacker = _bf(state, _creature("Black Attacker", colors=["B"]), controller="p2")
    engine = RulesEngine(state)
    for _ in range(5):
        p1.library.append(GameObject(Card(id="Filler", name="Filler", type_line="Land"), owner_id="p1"))

    from mtg_analyzer.game.effects import GameContext

    (effect,) = shadowbane.spell_effects
    effect.source = shadowbane
    effect.apply(GameContext(state, engine))
    # No source_filter, so both battlefield creatures qualify — answer it.
    assert state.pending_choice is not None
    engine.resolve_choose_objects_choice(black_attacker.instance_id)

    # Both the prevention and the rider fire together within one
    # `deal_damage` call — the damage never lands, and (black source) the
    # rider grants that same amount as life in the same step.
    engine.deal_damage(p1, 3, source=black_attacker)
    assert p1.life == 20 + 3  # prevented, and gained life (black source)
    engine.deal_damage(my_creature, 2, source=black_attacker)
    assert my_creature.damage_marked == 0  # a creature you control, also shielded


def test_honorable_passage_catalogue_entry_reflects_red_source_damage():
    state, p1, p2 = _state()
    passage = GameObject(Card(id="Honorable Passage", name="Honorable Passage", type_line="Instant"),
                          owner_id="p1", zone=Zone.STACK)
    bind_from_catalogue(passage)
    passage.controller_id = "p1"
    victim = _bf(state, _creature("Victim"))
    red_attacker = _bf(state, _creature("Red Attacker", colors=["R"]), controller="p2")
    engine = RulesEngine(state)

    from mtg_analyzer.game.effects import GameContext

    (effect,) = passage.spell_effects
    effect.source = passage
    effect.apply(GameContext(state, engine), targets=[victim])
    # No source_filter, so both battlefield creatures qualify — answer it.
    assert state.pending_choice is not None
    engine.resolve_choose_objects_choice(red_attacker.instance_id)

    engine.deal_damage(victim, 4, source=red_attacker)
    assert victim.damage_marked == 0  # prevented
    assert p2.life == 20 - 4  # red source — reflected onto its controller


def test_dazzling_reflection_catalogue_entry_gains_life_and_shields_same_target():
    state, p1, p2 = _state()
    reflection = GameObject(Card(id="Dazzling Reflection", name="Dazzling Reflection", type_line="Instant"),
                             owner_id="p1", zone=Zone.STACK)
    bind_from_catalogue(reflection)
    reflection.controller_id = "p1"
    target_creature = _bf(state, _creature("Big Creature", power=5, toughness=5), controller="p2")
    attacker = _bf(state, _creature("Attacker"), controller="p2")
    engine = RulesEngine(state)

    from mtg_analyzer.game.effects import GameContext

    context = GameContext(state, engine)
    for effect in reflection.spell_effects:
        effect.source = reflection
        effect.apply(context, targets=[target_creature])

    assert p1.life == 20 + 5  # gained life equal to the target's power
    engine.deal_damage(p1, 3, source=target_creature)
    assert p1.life == 20 + 5  # that creature's own damage is prevented
    engine.deal_damage(p1, 3, source=attacker)
    assert p1.life == 20 + 5 - 3  # a different source is unaffected


def test_samite_blessing_catalogue_entry_grants_a_chooser_ability_to_the_host():
    state, p1, p2 = _state()
    host = _bf(state, _creature("Host Bear"))
    blessing = _bf(state, Card(id="Samite Blessing", name="Samite Blessing", type_line="Enchantment — Aura"))
    blessing.attached_to = host.instance_id
    victim = _bf(state, _creature("Victim"))
    attacker = _bf(state, _creature("Attacker"), controller="p2")
    engine = RulesEngine(state)
    from mtg_analyzer.game import continuous

    continuous.recompute(state)

    granted = host.granted_activated_abilities
    assert len(granted) == 1
    (ability,) = granted
    (effect,) = ability.effects
    from mtg_analyzer.game.effects import GameContext

    effect.source = host
    effect.apply(GameContext(state, engine), targets=[victim])
    # No source_filter, so every battlefield permanent qualifies — answer it.
    assert state.pending_choice is not None
    engine.resolve_choose_objects_choice(attacker.instance_id)

    engine.deal_damage(victim, 4, source=attacker)
    assert victim.damage_marked == 0


# ---------------------------------------------------------------------------
# MEC-30 third pass, Phase 6: Opal-Eye, Konda's Yojimbo (RULE 616.1c
# redirection, not prevention — a genuinely new primitive)
# ---------------------------------------------------------------------------


def test_redirect_damage_from_source_rewrites_the_recipient():
    state, p1, p2 = _state()
    opal_eye = _bf(state, Card(id="Opal-Eye, Konda's Yojimbo", name="Opal-Eye, Konda's Yojimbo",
                                type_line="Legendary Creature — Fox Samurai", is_creature=True,
                                power=1, toughness=4))
    attacker = _bf(state, _creature("Attacker"), controller="p2")
    engine = RulesEngine(state)

    engine.redirect_damage_from_source(attacker, opal_eye, "all")
    engine.deal_damage(p1, 5, source=attacker)
    assert p1.life == 20  # never landed on p1...
    assert opal_eye.damage_marked == 5  # ...it went to Opal-Eye instead

    # a different source is unaffected
    other_attacker = _bf(state, _creature("Other Attacker"), controller="p2")
    engine.deal_damage(p1, 3, source=other_attacker)
    assert p1.life == 20 - 3


def test_redirect_damage_from_source_caps_at_a_finite_budget():
    """No real card prints a finite redirect amount today (both cards wired
    to `redirect_damage_from_source` always pass "all"), but the primitive
    itself must honour one: only the shield's own remaining budget gets
    redirected, and the un-redirected remainder still lands on the original
    recipient as ordinary damage — mirroring how a partially-exhausted
    `prevent_damage_*` shield splits `dealt` into a survives/prevented
    portion instead of silently dropping or over-redirecting it."""
    state, p1, p2 = _state()
    opal_eye = _bf(state, Card(id="Opal-Eye, Konda's Yojimbo", name="Opal-Eye, Konda's Yojimbo",
                                type_line="Legendary Creature — Fox Samurai", is_creature=True,
                                power=1, toughness=4))
    attacker = _bf(state, _creature("Attacker"), controller="p2")
    engine = RulesEngine(state)

    engine.redirect_damage_from_source(attacker, opal_eye, 2)
    engine.deal_damage(p1, 5, source=attacker)
    assert opal_eye.damage_marked == 2  # only the shield's own budget redirected
    assert p1.life == 20 - 3  # the un-redirected remainder still hits p1

    # the shield is now exhausted — a second hit is unaffected
    opal_eye.damage_marked = 0
    engine.deal_damage(p1, 4, source=attacker)
    assert opal_eye.damage_marked == 0
    assert p1.life == 20 - 3 - 4


def test_redirect_damage_from_source_is_not_blocked_by_disable_prevention():
    # A redirect isn't a prevention (RULE 615 doesn't apply to it), so
    # `disable_damage_prevention_this_turn` must leave it working.
    state, p1, p2 = _state()
    opal_eye = _bf(state, Card(id="Opal-Eye, Konda's Yojimbo", name="Opal-Eye, Konda's Yojimbo",
                                type_line="Legendary Creature — Fox Samurai", is_creature=True,
                                power=1, toughness=4))
    attacker = _bf(state, _creature("Attacker"), controller="p2")
    engine = RulesEngine(state)

    engine.redirect_damage_from_source(attacker, opal_eye, "all")
    engine.disable_damage_prevention_this_turn()
    engine.deal_damage(p1, 5, source=attacker)
    assert p1.life == 20
    assert opal_eye.damage_marked == 5


def test_opal_eye_catalogue_entry_redirects_the_chosen_source():
    state, p1, p2 = _state()
    opal_eye = _bf(state, Card(id="Opal-Eye, Konda's Yojimbo", name="Opal-Eye, Konda's Yojimbo",
                                type_line="Legendary Creature — Fox Samurai", is_creature=True,
                                power=1, toughness=4))
    attacker = _bf(state, _creature("Attacker"), controller="p2")
    engine = RulesEngine(state)

    from mtg_analyzer.game.effects import GameContext

    (redirect_ability, _prevent_ability) = opal_eye.activated_abilities
    (effect,) = redirect_ability.effects
    effect.source = opal_eye
    effect.apply(GameContext(state, engine))
    # Only one battlefield permanent besides Opal-Eye itself — but Opal-Eye
    # is also a candidate (no source_filter), so this is a real choice.
    assert state.pending_choice is not None
    engine.resolve_choose_objects_choice(attacker.instance_id)

    engine.deal_damage(p1, 5, source=attacker)
    assert p1.life == 20
    assert opal_eye.damage_marked == 5


def test_opal_eye_catalogue_entry_second_ability_shields_only_itself():
    state, p1, p2 = _state()
    opal_eye = _bf(state, Card(id="Opal-Eye, Konda's Yojimbo", name="Opal-Eye, Konda's Yojimbo",
                                type_line="Legendary Creature — Fox Samurai", is_creature=True,
                                power=1, toughness=4))
    attacker = _bf(state, _creature("Attacker"), controller="p2")
    engine = RulesEngine(state)

    from mtg_analyzer.game.effects import GameContext

    (_redirect_ability, prevent_ability) = opal_eye.activated_abilities
    (effect,) = prevent_ability.effects
    effect.source = opal_eye
    effect.apply(GameContext(state, engine))

    engine.deal_damage(opal_eye, 3, source=attacker)
    assert opal_eye.damage_marked == 2  # 1 of 3 prevented
    engine.deal_damage(p1, 3, source=attacker)
    assert p1.life == 20 - 3  # the controller isn't shielded — only Opal-Eye itself


# ---------------------------------------------------------------------------
# Phase 8 (MEC-30): Penance, Seasoned Tactician, Bone Mask — three new
# non-mana cost/rider shapes
# ---------------------------------------------------------------------------


def test_penance_catalogue_entry_prevents_regardless_of_recipient():
    """Penance's own printed text has no "to you" at all — the shield must
    protect whoever the chosen source hits, not just Penance's controller
    (`RequestPreventDamageSourceEffect`'s new ``recipient="any"``)."""
    state, p1, p2 = _state()
    penance = _bf(state, Card(id="Penance", name="Penance", type_line="Enchantment"))
    attacker = _bf(state, _creature("Attacker", colors=["R"]), controller="p2")
    engine = RulesEngine(state)

    from mtg_analyzer.game.effects import GameContext

    (ability,) = penance.activated_abilities
    (effect,) = ability.effects
    effect.source = penance
    effect.apply(GameContext(state, engine))
    assert state.pending_choice is None  # single red/black candidate — auto-picked

    # p2, not Penance's own controller (p1), is who gets hit — proving the
    # shield isn't scoped to "you" at all.
    engine.deal_damage(p2, 5, source=attacker)
    assert p2.life == 20


def test_penance_cost_puts_the_chosen_hand_card_on_top_of_library():
    """RULE 602.1: "put a card from your hand on top of your library" is a
    genuine cost *choice* — `ActivationMixin._resolve_put_hand_card_cost`,
    `RulesEngine.put_hand_card_on_top_of_library`."""
    from mtg_analyzer.game.game_engine import GameEngine

    state, p1, _p2 = _state()
    penance = _bf(state, Card(id="Penance", name="Penance", type_line="Enchantment"))
    engine = GameEngine(state)

    keep = GameObject(_creature("Keep"), owner_id="p1", zone=Zone.HAND)
    spend = GameObject(_creature("Spend"), owner_id="p1", zone=Zone.HAND)
    p1.hand.extend([keep, spend])
    library_size = len(p1.library)

    engine.activate_ability(p1, penance, hand_card_choices=[spend.instance_id])

    assert spend not in p1.hand
    assert keep in p1.hand
    assert p1.library and p1.library[-1] is spend  # top of deck is the list end
    assert len(p1.library) == library_size + 1


def test_penance_hand_card_choice_reachable_via_game_session():
    """The raw-engine test above proves `activate_ability`'s own
    `hand_card_choices` param works; this proves the choice actually
    reaches it through `GameSession.apply_action` (`_dispatch_activate_
    ability`) — the real path any UI/API caller uses, which previously
    dropped `hand_card_choices`/`discard_choices` on the floor entirely."""
    from mtg_analyzer.game.game_engine import GameEngine
    from mtg_analyzer.services.game_session import GameSession

    state, p1, _p2 = _state()
    penance = _bf(state, Card(id="Penance", name="Penance", type_line="Enchantment"))
    engine = GameEngine(state)
    session = GameSession(engine)

    keep = GameObject(_creature("Keep"), owner_id="p1", zone=Zone.HAND)
    spend = GameObject(_creature("Spend"), owner_id="p1", zone=Zone.HAND)
    p1.hand.extend([keep, spend])
    library_size = len(p1.library)

    session.apply_action({
        "type": "activate_ability", "instance_id": penance.instance_id,
        "ability_index": 0, "hand_card_choices": [spend.instance_id],
    })

    assert spend not in p1.hand
    assert keep in p1.hand
    assert p1.library and p1.library[-1] is spend
    assert len(p1.library) == library_size + 1


def test_penance_cost_not_payable_with_an_empty_hand():
    from mtg_analyzer.game.game_engine import GameEngine

    state, p1, _p2 = _state()
    penance = _bf(state, Card(id="Penance", name="Penance", type_line="Enchantment"))
    engine = GameEngine(state)

    assert not engine.can_activate(p1, penance, penance.activated_abilities[0])


def test_seasoned_tactician_catalogue_entry_shields_the_controller():
    state, p1, p2 = _state()
    tactician = _bf(state, Card(id="Seasoned Tactician", name="Seasoned Tactician",
                                 type_line="Creature — Human Advisor", is_creature=True,
                                 power=1, toughness=3))
    attacker = _bf(state, _creature("Attacker"), controller="p2")
    engine = RulesEngine(state)

    from mtg_analyzer.game.effects import GameContext

    (ability,) = tactician.activated_abilities
    (effect,) = ability.effects
    effect.source = tactician
    effect.apply(GameContext(state, engine))
    # No source_filter — Seasoned Tactician and Attacker are both
    # candidates, so this is a real choice.
    assert state.pending_choice is not None
    engine.resolve_choose_objects_choice(attacker.instance_id)

    engine.deal_damage(p1, 5, source=attacker)
    assert p1.life == 20


def test_seasoned_tactician_cost_exiles_exactly_four_cards():
    """`costs.exile_top_of_library` widened from a bare bool (Thought Lash's
    always-exactly-one) to a real printed count — regression-checked
    against Thought Lash separately (`test_thought_lash_catalogue_entry`,
    unchanged) so this doesn't silently break the original card."""
    from mtg_analyzer.game.game_engine import GameEngine

    state, p1, _p2 = _state()
    tactician = _bf(state, Card(id="Seasoned Tactician", name="Seasoned Tactician",
                                 type_line="Creature — Human Advisor", is_creature=True,
                                 power=1, toughness=3))
    engine = GameEngine(state)
    p1.mana_pool.add("C", 3)
    p1.library.extend(
        GameObject(_creature(f"Library Card {i}"), owner_id="p1", zone=Zone.LIBRARY)
        for i in range(6)
    )
    library_size = len(p1.library)

    engine.activate_ability(p1, tactician)

    assert len(p1.library) == library_size - 4
    assert len(p1.exile) == 4


def test_seasoned_tactician_cost_not_payable_with_fewer_than_four_library_cards():
    from mtg_analyzer.game.game_engine import GameEngine

    state, p1, _p2 = _state()
    tactician = _bf(state, Card(id="Seasoned Tactician", name="Seasoned Tactician",
                                 type_line="Creature — Human Advisor", is_creature=True,
                                 power=1, toughness=3))
    engine = GameEngine(state)
    p1.mana_pool.add("C", 3)  # mana itself is payable — only the library count should block this
    p1.library.extend(
        GameObject(_creature(f"Library Card {i}"), owner_id="p1", zone=Zone.LIBRARY)
        for i in range(3)
    )

    assert not engine.can_activate(p1, tactician, tactician.activated_abilities[0])


def test_thought_lash_catalogue_entry_still_exiles_exactly_one_card():
    """Regression check for `_EXILE_TOP_LIBRARY_RE`'s widened count grammar
    — a bare "exile the top card" (no number) must still parse to exactly
    1, not 0 or "all"."""
    from mtg_analyzer.game.game_engine import GameEngine

    state, p1, _p2 = _state()
    thought_lash = _bf(state, Card(id="Thought Lash", name="Thought Lash", type_line="Enchantment"))
    engine = GameEngine(state)
    p1.library.extend(
        GameObject(_creature(f"Library Card {i}"), owner_id="p1", zone=Zone.LIBRARY)
        for i in range(3)
    )
    library_size = len(p1.library)

    engine.activate_ability(p1, thought_lash)

    assert len(p1.library) == library_size - 1
    assert len(p1.exile) == 1


def test_bone_mask_catalogue_entry_exiles_top_of_library_equal_to_prevented():
    """Bone Mask's own rider — `RulesEngine.apply_prevent_rider`'s new
    ``"exile_top_of_library_scaled"`` kind, `mill`'s exile-instead-of-
    graveyard sibling."""
    state, p1, p2 = _state()
    mask = _bf(state, Card(id="Bone Mask", name="Bone Mask", type_line="Artifact"))
    attacker = _bf(state, _creature("Attacker"), controller="p2")
    engine = RulesEngine(state)
    p1.library.extend(
        GameObject(_creature(f"Library Card {i}"), owner_id="p1", zone=Zone.LIBRARY)
        for i in range(6)
    )
    library_size = len(p1.library)

    from mtg_analyzer.game.effects import GameContext

    (ability,) = mask.activated_abilities
    (effect,) = ability.effects
    effect.source = mask
    effect.apply(GameContext(state, engine))
    # No source_filter — Bone Mask and Attacker are both candidates, so
    # this is a real choice.
    assert state.pending_choice is not None
    engine.resolve_choose_objects_choice(attacker.instance_id)

    engine.deal_damage(p1, 5, source=attacker)
    assert p1.life == 20  # fully prevented
    assert len(p1.library) == library_size - 5
    assert len(p1.exile) == 5


# ---------------------------------------------------------------------------
# Phase 7 (MEC-30): Mercenaries — "Any player may activate this ability"
# ---------------------------------------------------------------------------


def test_mercenaries_ability_is_activatable_by_a_non_controller():
    from mtg_analyzer.game.game_engine import GameEngine

    state, p1, p2 = _state()
    mercenaries = _bf(state, Card(id="Mercenaries", name="Mercenaries",
                                   type_line="Creature — Human Mercenary", is_creature=True,
                                   power=3, toughness=3))
    engine = GameEngine(state)
    p2.mana_pool.add("C", 3)

    ability = mercenaries.activated_abilities[0]
    assert engine.can_activate(p2, mercenaries, ability)  # p2 doesn't control Mercenaries


def test_mercenaries_shield_protects_whoever_activates_it_not_the_controller():
    """RULE 602.2b: the activator, not Mercenaries' own controller (p1), is
    who "you" resolves to — `GameContext.resolving_controller_id`."""
    from mtg_analyzer.game.game_engine import GameEngine

    state, p1, p2 = _state()
    mercenaries = _bf(state, Card(id="Mercenaries", name="Mercenaries",
                                   type_line="Creature — Human Mercenary", is_creature=True,
                                   power=3, toughness=3))
    engine = GameEngine(state)
    p2.mana_pool.add("C", 3)

    engine.activate_ability(p2, mercenaries)  # p2 activates, though p1 controls it
    engine.rules.resolve_top_of_stack()

    # p2 (the activator) is shielded from Mercenaries' own damage…
    engine.rules.deal_damage(p2, 4, source=mercenaries)
    assert p2.life == 20
    # …but p1 (Mercenaries' actual controller) is not.
    engine.rules.deal_damage(p1, 4, source=mercenaries)
    assert p1.life == 20 - 4


def test_mercenaries_shield_only_watches_its_own_damage():
    from mtg_analyzer.game.game_engine import GameEngine

    state, p1, p2 = _state()
    mercenaries = _bf(state, Card(id="Mercenaries", name="Mercenaries",
                                   type_line="Creature — Human Mercenary", is_creature=True,
                                   power=3, toughness=3))
    other_attacker = _bf(state, _creature("Other Attacker"), controller="p1")
    engine = GameEngine(state)
    p2.mana_pool.add("C", 3)

    engine.activate_ability(p2, mercenaries)
    engine.rules.resolve_top_of_stack()

    engine.rules.deal_damage(p2, 4, source=other_attacker)
    assert p2.life == 20 - 4  # a different source isn't watched by this shield


def test_mercenaries_ability_is_offered_via_legal_actions_to_a_non_controller():
    """RULE 602.2b: `can_activate`/`activate_ability` accepting a
    non-controller isn't enough by itself — `legal_actions()` is the single
    source of truth the UI/bots actually consult (docs R4.3), so the
    activated-ability enumeration must offer this ability to p2 too, not
    just to p1 (Mercenaries' own controller)."""
    from mtg_analyzer.game.game_engine import GameEngine

    state, p1, p2 = _state()
    mercenaries = _bf(state, Card(id="Mercenaries", name="Mercenaries",
                                   type_line="Creature — Human Mercenary", is_creature=True,
                                   power=3, toughness=3))
    engine = GameEngine(state)
    p2.mana_pool.add("C", 3)

    offers = [
        a for a in engine.legal_actions(p2)
        if a.get("type") == "activate_ability" and a.get("instance_id") == mercenaries.instance_id
    ]
    assert offers, "Mercenaries should offer its ability to a non-controller via legal_actions()"

    # An ordinary (non-"any player may activate") ability on someone else's
    # permanent must still not be offered — this isn't a blanket "offer
    # everything on the battlefield" widening. Bone Mask (already used
    # above) has a real, ordinary activated ability bound via `_bf`'s own
    # `bind_from_catalogue` call.
    other = _bf(state, Card(id="Bone Mask", name="Bone Mask", type_line="Artifact"), controller="p1")
    stray = [
        a for a in engine.legal_actions(p2)
        if a.get("type") == "activate_ability" and a.get("instance_id") == other.instance_id
    ]
    assert not stray, "an ordinary ability on someone else's permanent must stay hidden from a non-controller"


# ---------------------------------------------------------------------------
# Phase 7 (MEC-30): Rhystic Circle — "Any player may pay {1}. If no one
# does, <effect>." (a genuine multi-player, aggregate-outcome tax)
# ---------------------------------------------------------------------------


def test_rhystic_circle_shield_grants_when_every_player_declines():
    from mtg_analyzer.game.game_engine import GameEngine

    state, p1, p2 = _state()
    circle = _bf(state, Card(id="Rhystic Circle", name="Rhystic Circle", type_line="Enchantment"))
    attacker = _bf(state, _creature("Attacker"), controller="p2")
    engine = GameEngine(state)
    p1.mana_pool.add("C", 2)  # {1} for the ability itself, {1} more to survive the tax poll
    p2.mana_pool.add("C", 1)  # can afford the tax poll too, but will decline

    engine.activate_ability(p1, circle)
    engine.rules.resolve_top_of_stack()

    # Active-player-first turn order: p1, then p2 — both explicitly decline.
    assert state.pending_choice is not None
    assert state.pending_choice["kind"] == "all_decline_or"
    engine.rules.resolve_all_decline_or_choice("decline")
    assert state.pending_choice is not None
    assert state.pending_choice["kind"] == "all_decline_or"
    engine.rules.resolve_all_decline_or_choice("decline")

    # Everyone declined — the shield's own "choose a source" chooser opens.
    assert state.pending_choice is not None
    assert state.pending_choice["kind"] == "choose_objects"
    engine.rules.resolve_choose_objects_choice(attacker.instance_id)

    engine.rules.deal_damage(p1, 5, source=attacker)
    assert p1.life == 20
    assert p1.mana_pool.total() == 1  # spent {1} on the ability, kept {1} — declined the tax
    assert p2.mana_pool.total() == 1  # never paid either


def test_rhystic_circle_sweep_is_cancelled_the_moment_someone_pays():
    from mtg_analyzer.game.game_engine import GameEngine

    state, p1, p2 = _state()
    circle = _bf(state, Card(id="Rhystic Circle", name="Rhystic Circle", type_line="Enchantment"))
    attacker = _bf(state, _creature("Attacker"), controller="p2")
    engine = GameEngine(state)
    p1.mana_pool.add("C", 2)
    p2.mana_pool.add("C", 1)

    engine.activate_ability(p1, circle)
    engine.rules.resolve_top_of_stack()

    # p1 (asked first) pays — cancels the whole sweep immediately, no
    # shield at all, and p2 is never even asked.
    assert state.pending_choice is not None
    engine.rules.resolve_all_decline_or_choice("pay")
    assert state.pending_choice is None
    assert p1.mana_pool.total() == 0
    assert p2.mana_pool.total() == 1  # untouched — never asked

    engine.rules.deal_damage(p1, 5, source=attacker)
    assert p1.life == 20 - 5  # nobody's shielded — someone paid to stop it


def test_rhystic_circle_sweep_auto_skips_a_player_who_cannot_pay():
    from mtg_analyzer.game.game_engine import GameEngine

    state, p1, p2 = _state()
    circle = _bf(state, Card(id="Rhystic Circle", name="Rhystic Circle", type_line="Enchantment"))
    attacker = _bf(state, _creature("Attacker"), controller="p2")
    engine = GameEngine(state)
    p1.mana_pool.add("C", 1)  # just enough for the {1} activation cost, none left for the tax
    # p2 has no mana at all — can't pay either.

    engine.activate_ability(p1, circle)
    engine.rules.resolve_top_of_stack()

    # Neither player can afford the {1} tax — both auto-skipped (the same
    # "don't stall on a choice nobody can act on" shortcut ward/pay_cost_
    # then already take), straight to the shield's own "choose a source"
    # chooser with no `all_decline_or` pending_choice in between.
    assert state.pending_choice is not None
    assert state.pending_choice["kind"] == "choose_objects"
    engine.rules.resolve_choose_objects_choice(attacker.instance_id)

    engine.rules.deal_damage(p1, 5, source=attacker)
    assert p1.life == 20


# ---------------------------------------------------------------------------
# Desperate Gambit (MEC-30, last card of the family)
# ---------------------------------------------------------------------------


def test_desperate_gambit_win_doubles_the_chosen_sources_damage():
    state, p1, p2 = _state()
    gambit_card = Card(id="Desperate Gambit", name="Desperate Gambit", type_line="Instant", is_instant=True)
    gambit = GameObject(gambit_card, owner_id="p1", zone=Zone.STACK)
    bind_from_catalogue(gambit)
    gambit.controller_id = "p1"
    my_creature = _bf(state, _creature("My Creature"), controller="p1")
    engine = RulesEngine(state)
    state.rng_seed = 2  # a "win" (heads) on the first flip at this seed
    state.rng_counter = 0

    from mtg_analyzer.game.effects import GameContext

    (effect,) = gambit.spell_effects
    effect.source = gambit
    effect.apply(GameContext(state, engine))
    # Only one legal candidate — Desperate Gambit is on the stack, not the
    # battlefield, so only My Creature is "a source you control" — auto-picked.
    assert state.pending_choice is None

    engine.deal_damage(p1, 3, source=my_creature)
    assert p1.life == 20 - 6  # doubled


def test_desperate_gambit_lose_prevents_the_chosen_sources_damage():
    state, p1, p2 = _state()
    gambit_card = Card(id="Desperate Gambit", name="Desperate Gambit", type_line="Instant", is_instant=True)
    gambit = GameObject(gambit_card, owner_id="p1", zone=Zone.STACK)
    bind_from_catalogue(gambit)
    gambit.controller_id = "p1"
    my_creature = _bf(state, _creature("My Creature"), controller="p1")
    engine = RulesEngine(state)
    state.rng_seed = 0  # a "loss" (tails) on the first flip at this seed
    state.rng_counter = 0

    from mtg_analyzer.game.effects import GameContext

    (effect,) = gambit.spell_effects
    effect.source = gambit
    effect.apply(GameContext(state, engine))
    assert state.pending_choice is None

    engine.deal_damage(p1, 3, source=my_creature)
    assert p1.life == 20  # fully prevented


def test_desperate_gambit_only_offers_sources_the_caster_controls():
    state, p1, p2 = _state()
    gambit_card = Card(id="Desperate Gambit", name="Desperate Gambit", type_line="Instant", is_instant=True)
    gambit = GameObject(gambit_card, owner_id="p1", zone=Zone.STACK)
    bind_from_catalogue(gambit)
    gambit.controller_id = "p1"
    _bf(state, _creature("My Creature"), controller="p1")
    opponents_creature = _bf(state, _creature("Opponent's Creature"), controller="p2")
    engine = RulesEngine(state)

    from mtg_analyzer.game.effects import GameContext

    (effect,) = gambit.spell_effects
    effect.source = gambit
    effect.apply(GameContext(state, engine))
    # Two permanents exist, but only My Creature is "a source you control"
    # — still a forced auto-pick, not a real choice.
    assert state.pending_choice is None

    engine.deal_damage(p2, 3, source=opponents_creature)
    assert p2.life == 20 - 3  # untouched — the opponent's creature was never a candidate
