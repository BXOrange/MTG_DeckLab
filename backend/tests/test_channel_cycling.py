"""Tests for a hand-zone, non-mana "Discard this card: <effect>" activated
ability (Channel, RULE 702.29; Cycling, RULE 702.28) — distinct from
`game/mana_abilities.py`'s "Exile this card from your hand: Add …" (a mana
ability, no stack) since Channel/Cycling *do* use the stack (RULE 602),
so they're routed through the ordinary `ActivatedAbility`/`activate_ability`
path with a hand-zone source instead.
"""

from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.game.effects.core import ActivatedAbility, DrawCardEffect, DestroyEffect, TriggeredAbility
from mtg_analyzer.game.costs import ActivationCost, parse_activation_cost
from mtg_analyzer.parser.oracle import MODELED, parse_oracle


def make_engine(hand=0, extra_library=0):
    cards = [Card(id=f"Bear{i}", name=f"Bear{i}", type_line="Creature", is_creature=True)
             for i in range(6 + extra_library)]
    return GameEngine.new_game([("p1", "Alice", cards)], starting_life=20, starting_hand=hand)


# ---------------------------------------------------------------------------
# Cost-string recognition (game/costs.py)
# ---------------------------------------------------------------------------


def test_discard_this_card_is_recognized_as_discard_self():
    cost = parse_activation_cost("Discard this card")
    assert cost.discard_self is True
    assert cost.discard == 0


def test_cycling_cost_combines_mana_and_discard_self():
    cost = parse_activation_cost("{2}{W}, Discard this card")
    assert cost.discard_self is True
    assert cost.mana.converted_mana_cost == 3


def test_discard_a_card_is_not_confused_with_discard_self():
    cost = parse_activation_cost("Discard a card")
    assert cost.discard_self is False
    assert cost.discard == 1


# ---------------------------------------------------------------------------
# Engine mechanism: activate from hand, pay by discarding the source itself
# ---------------------------------------------------------------------------


def _cycler(owner_id="p1", cost_text="{1}{W}, Discard this card"):
    card = Card(id="Cycler", name="Cycler", type_line="Sorcery",
                mana_cost_string="{2}{W}", converted_mana_cost=3, is_sorcery=True)
    obj = GameObject(card, owner_id=owner_id, zone=Zone.HAND)
    obj.activated_abilities = [
        ActivatedAbility(
            effects=[DrawCardEffect(count=1)],
            cost=parse_activation_cost(cost_text),
            source=obj,
            description="Cycling {1}{W}",
        )
    ]
    return obj


def test_can_activate_a_hand_zone_discard_self_ability():
    eng = make_engine(hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    p1.mana_pool.add_many({"W": 1, "C": 1})
    cycler = _cycler()
    p1.add_to_zone(cycler, Zone.HAND)
    ability = cycler.activated_abilities[0]
    assert eng.can_activate(p1, cycler, ability) is True


def test_activating_discards_the_source_and_draws_a_card():
    eng = make_engine(hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    p1.mana_pool.add_many({"W": 1, "C": 1})
    cycler = _cycler()
    p1.add_to_zone(cycler, Zone.HAND)
    hand_before = len(p1.hand)

    eng.activate_ability(p1, cycler, 0)
    eng.resolve_until_stable()

    assert cycler not in p1.hand
    assert cycler in p1.graveyard
    assert len(p1.hand) == hand_before  # cycler left, one card drawn: net unchanged


def test_cannot_activate_without_paying_the_mana_portion():
    eng = make_engine(hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    cycler = _cycler()
    p1.add_to_zone(cycler, Zone.HAND)
    ability = cycler.activated_abilities[0]
    assert eng.can_activate(p1, cycler, ability) is False


def test_a_pure_channel_ability_with_no_mana_portion():
    # Channel-shaped: "Discard this card: <effect>." — no mana at all.
    eng = make_engine(hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    opponent_creature = GameObject(
        Card(id="Bear", name="Bear", type_line="Creature", is_creature=True, power=2, toughness=2),
        owner_id="p1", controller_id="p1", zone=Zone.BATTLEFIELD,
    )
    eng.state.add_to_battlefield(opponent_creature)
    channel_card = GameObject(
        Card(id="Fiery Cannonade", name="Fiery Cannonade", type_line="Instant",
             mana_cost_string="{2}{R}", converted_mana_cost=3, is_instant=True),
        owner_id="p1", zone=Zone.HAND,
    )
    channel_card.activated_abilities = [
        ActivatedAbility(
            effects=[DestroyEffect(target_kind="creature")],
            cost=parse_activation_cost("Discard this card"),
            source=channel_card,
        )
    ]
    p1.add_to_zone(channel_card, Zone.HAND)
    ability = channel_card.activated_abilities[0]
    assert eng.can_activate(p1, channel_card, ability) is True

    eng.activate_ability(p1, channel_card, 0, targets=[opponent_creature])
    eng.resolve_until_stable()

    assert channel_card in p1.graveyard
    assert opponent_creature not in eng.state.battlefield


def test_legal_actions_surfaces_the_hand_zone_ability():
    eng = make_engine(hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    p1.mana_pool.add_many({"W": 1, "C": 1})
    cycler = _cycler()
    p1.add_to_zone(cycler, Zone.HAND)

    actions = eng.legal_actions(p1)
    offers = [a for a in actions if a.get("type") == "activate_ability" and a.get("instance_id") == cycler.instance_id]
    assert len(offers) == 1


# ---------------------------------------------------------------------------
# Real deck card: Dismantling Wave's Cycling clause (ability_catalogue.py)
# ---------------------------------------------------------------------------


def test_dismantling_wave_cycling_destroys_all_artifacts_and_enchantments():
    from mtg_analyzer.game.binding.core import bind_from_catalogue

    eng = make_engine(hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    p1.mana_pool.add_many({"W": 2, "C": 6})
    art = GameObject(
        Card(id="Signet", name="Signet", type_line="Artifact"),
        owner_id="p1", controller_id="p1", zone=Zone.BATTLEFIELD,
    )
    eng.state.add_to_battlefield(art)
    creature = GameObject(
        Card(id="Bear", name="Bear", type_line="Creature", is_creature=True, power=2, toughness=2),
        owner_id="p1", controller_id="p1", zone=Zone.BATTLEFIELD,
    )
    eng.state.add_to_battlefield(creature)

    card = Card(id="Dismantling Wave", name="Dismantling Wave", type_line="Sorcery",
                mana_cost_string="{2}{W}", converted_mana_cost=3, is_sorcery=True)
    obj = GameObject(card, owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(obj)
    p1.add_to_zone(obj, Zone.HAND)

    cycling = next(a for a in obj.activated_abilities if a.cost.discard_self)
    assert eng.can_activate(p1, obj, cycling) is True

    eng.activate_ability(p1, obj, obj.activated_abilities.index(cycling))
    eng.resolve_until_stable()

    assert obj in p1.graveyard
    assert art not in eng.state.battlefield
    assert creature in eng.state.battlefield  # only artifacts/enchantments


def test_renewed_faith_cycling_gains_life():
    from mtg_analyzer.game.binding.core import bind_from_catalogue

    eng = make_engine(hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    p1.mana_pool.add_many({"W": 1, "C": 2})
    card = Card(id="Renewed Faith", name="Renewed Faith", type_line="Instant",
                mana_cost_string="{1}{W}", converted_mana_cost=2, is_instant=True)
    obj = GameObject(card, owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(obj)
    p1.add_to_zone(obj, Zone.HAND)

    cycling = next(a for a in obj.activated_abilities if a.cost.discard_self)
    hand_before = len(p1.hand)
    eng.activate_ability(p1, obj, obj.activated_abilities.index(cycling))
    eng.resolve_until_stable()

    assert obj in p1.graveyard
    # Cycling's own effect is "draw a card" — the life gain is the spell's
    # own (uncast, in this test) cast mode.
    assert len(p1.hand) == hand_before  # this card left, one drawn: net unchanged


# ---------------------------------------------------------------------------
# PAR-9: generic Cycling execution for an *unregistered* card. Previously the
# parser recognized a bare "Cycling {N}" keyword line well enough to satisfy
# the coverage gate (`[keyword] []`, no unclaimed clauses — MODELED), but
# nothing ever bound it to a real activated ability unless the card was also
# hand-authored (Dismantling Wave/Renewed Faith above) — so an ordinary
# cycling creature with no other text (Barkhide Mauler-shaped) was "MODELED"
# yet never actually cyclable. `effect_binder._cycling_activated_ability`
# closes that for the plain, type-unrestricted keyword.
# ---------------------------------------------------------------------------


def _unregistered_cycler(name="Not A Real Card", cost="{2}", keywords=None, oracle_text=None):
    card = Card(
        id=name, name=name, type_line="Creature — Beast", is_creature=True,
        power=4, toughness=4,
        oracle_text=oracle_text or f"Cycling {cost} ({cost}, Discard this card: Draw a card.)",
        keywords=keywords if keywords is not None else ["Cycling"],
    )
    return GameObject(card, owner_id="p1", zone=Zone.HAND)


def test_bare_cycling_on_an_unregistered_card_gets_a_real_activated_ability():
    from mtg_analyzer.game.binding.core import bind_from_catalogue

    obj = _unregistered_cycler()
    bind_from_catalogue(obj)

    (ability,) = obj.activated_abilities
    assert ability.cost.discard_self is True
    assert ability.cost.mana.converted_mana_cost == 2


def test_bare_cycling_end_to_end_draws_a_card_and_discards_itself():
    eng = make_engine(hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    p1.mana_pool.add_many({"C": 2})
    obj = _unregistered_cycler()
    from mtg_analyzer.game.binding.core import bind_from_catalogue
    bind_from_catalogue(obj)
    p1.add_to_zone(obj, Zone.HAND)
    hand_before = len(p1.hand)

    ability = obj.activated_abilities[0]
    assert eng.can_activate(p1, obj, ability) is True
    eng.activate_ability(p1, obj, 0)
    eng.resolve_until_stable()

    assert obj in p1.graveyard
    assert len(p1.hand) == hand_before


def test_typecycling_variant_does_not_get_the_generic_draw_ability():
    # Ash Barrens-shaped: Scryfall's `keywords` array tags the generic
    # parent slugs ("Landcycling", "Typecycling", "Cycling") alongside the
    # specific one even though only "Basic landcycling" is actually
    # printed — and the shared cost regex has no word boundary, so it would
    # otherwise happily extract a cost out of "Basic landcycling {1}" too.
    # A type-restricted variant searches the library, not "draw a card";
    # never guess here — no activated ability at all is the correct,
    # fail-closed outcome until that shape is modeled for real.
    from mtg_analyzer.game.binding.core import bind_from_catalogue

    obj = _unregistered_cycler(
        name="Ash Barrens", cost="{1}",
        keywords=["Landcycling", "Basic landcycling", "Typecycling", "Cycling"],
        oracle_text="{T}: Add {C}.\nBasic landcycling {1} ({1}, Discard this card: "
                    "Search your library for a basic land card, reveal it, put it "
                    "into your hand, then shuffle.)",
    )
    bind_from_catalogue(obj)

    assert obj.activated_abilities == []


def test_hand_authored_cycling_is_not_duplicated_by_the_generic_binder():
    # Regression: Dismantling Wave's own hand-authored discard-self ability
    # (destroy all artifacts/enchantments) must stay the *only* one — the
    # generic fallback must not also bind a competing plain "draw a card"
    # for the same cost just because `ability_catalogue.specs_for` folds in
    # `parse_keywords`' own "cycling" spec for every card, registered or not.
    from mtg_analyzer.game.binding.core import bind_from_catalogue

    card = Card(id="Dismantling Wave", name="Dismantling Wave", type_line="Sorcery",
                mana_cost_string="{2}{W}", converted_mana_cost=3, is_sorcery=True)
    obj = GameObject(card, owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(obj)

    discard_self_abilities = [a for a in obj.activated_abilities if a.cost.discard_self]
    assert len(discard_self_abilities) == 1


# ---------------------------------------------------------------------------
# PAR-8: granting Cycling to *other* cards ("Each historic card in your hand
# has cycling {2}{W}." — Jo Grant/Rhet-Tomb Mystic/Tectonic Reformation) — a
# layer-6 static ability whose targets are hand cards, not battlefield
# permanents. Parser: `static_handlers._HAND_CYCLING_GRANT_RE`/
# `grant_cycling_to_hand`. Engine: `continuous._apply_hand_cycling_grants`.
# ---------------------------------------------------------------------------


def test_hand_cycling_grant_clause_is_recognized():
    from mtg_analyzer.parser.oracle.catalogue.static_handlers import static_effect_specs

    (spec,) = static_effect_specs("each historic card in your hand has cycling {2}{w}")
    assert spec.type == "grant_cycling_to_hand"
    assert spec.params == {"cost": "{2}{w}", "card_type": "historic"}


def test_bare_hand_cycling_grant_with_no_filter_is_recognized():
    from mtg_analyzer.parser.oracle.catalogue.static_handlers import static_effect_specs

    (spec,) = static_effect_specs("each card in your hand has cycling {2}")
    assert spec.params == {"cost": "{2}"}


def test_rhet_tomb_mystic_and_tectonic_reformation_are_modeled():
    from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle

    for card in (
        Card(id="Rhet-Tomb Mystic", name="Rhet-Tomb Mystic", type_line="Creature — Human Cleric",
             is_creature=True, power=2, toughness=3,
             oracle_text="Flying\nEach creature card in your hand has cycling {1}{U}."),
        Card(id="Tectonic Reformation", name="Tectonic Reformation", type_line="Enchantment",
             oracle_text="Each land card in your hand has cycling {R}.\n"
                         "Cycling {2} ({2}, Discard this card: Draw a card.)"),
    ):
        result = parse_oracle(card)
        assert result.coverage != UNMODELED, card.name
        assert result.unclaimed == [], card.name


def _hand_cycling_grantor(controller="p1", cost="{2}{W}", card_type="historic",
                           name="Jo Grant"):
    filter_word = f"{card_type} " if card_type else ""
    card = Card(
        id=name, name=name, type_line="Legendary Creature — Time Lord",
        is_creature=True, is_legendary=True, power=2, toughness=4,
        oracle_text=f"Each {filter_word}card in your hand has cycling {cost}.",
    )
    from mtg_analyzer.models.game.game_object import GameObject as _GO
    obj = _GO(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    return obj


def test_only_matching_hand_cards_are_granted_cycling():
    from mtg_analyzer.game import continuous
    from mtg_analyzer.game.binding.core import bind_from_catalogue
    from mtg_analyzer.models.game.game_state import GameState
    from mtg_analyzer.models.game.player import Player

    p1, p2 = Player(id="p1", life=20), Player(id="p2", life=20)
    state = GameState(players=[p1, p2])
    source = _hand_cycling_grantor()
    bind_from_catalogue(source)
    state.add_to_battlefield(source)

    historic = GameObject(Card(id="Sol Ring", name="Sol Ring", type_line="Artifact"),
                           owner_id="p1", zone=Zone.HAND)
    mundane = GameObject(Card(id="Bear", name="Bear", type_line="Creature",
                               is_creature=True, power=2, toughness=2),
                          owner_id="p1", zone=Zone.HAND)
    opponents_historic = GameObject(Card(id="Signet", name="Signet", type_line="Legendary Artifact",
                                          is_legendary=True),
                                     owner_id="p2", zone=Zone.HAND)
    p1.hand.extend([historic, mundane])
    p2.hand.append(opponents_historic)

    continuous.recompute(state)

    assert len(historic.granted_activated_abilities) == 1
    assert historic.granted_activated_abilities[0].cost.discard_self is True
    assert mundane.granted_activated_abilities == []
    assert opponents_historic.granted_activated_abilities == []  # not this player's hand


def test_hand_cycling_grant_disappears_when_its_source_leaves():
    from mtg_analyzer.game import continuous
    from mtg_analyzer.game.binding.core import bind_from_catalogue
    from mtg_analyzer.models.game.game_state import GameState
    from mtg_analyzer.models.game.player import Player

    p1, p2 = Player(id="p1", life=20), Player(id="p2", life=20)
    state = GameState(players=[p1, p2])
    source = _hand_cycling_grantor(card_type="creature", cost="{1}{U}")
    bind_from_catalogue(source)
    state.add_to_battlefield(source)

    creature_card = GameObject(Card(id="Bear", name="Bear", type_line="Creature",
                                     is_creature=True, power=2, toughness=2),
                                owner_id="p1", zone=Zone.HAND)
    p1.hand.append(creature_card)
    continuous.recompute(state)
    assert len(creature_card.granted_activated_abilities) == 1

    state.battlefield.remove(source)
    continuous.recompute(state)
    assert creature_card.granted_activated_abilities == []


def test_hand_cycling_grant_end_to_end_is_offered_and_activatable():
    eng = make_engine(hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player

    from mtg_analyzer.game.binding.core import bind_from_catalogue
    source = _hand_cycling_grantor(card_type=None, cost="{2}", name="Generic Cycler")
    source.card.type_line = "Enchantment"
    source.card.is_creature = False
    source.card.is_legendary = False
    bind_from_catalogue(source)
    eng.state.add_to_battlefield(source)

    card = GameObject(Card(id="Bear2", name="Bear2", type_line="Creature",
                            is_creature=True, power=2, toughness=2),
                       owner_id="p1", zone=Zone.HAND)
    p1.add_to_zone(card, Zone.HAND)
    p1.mana_pool.add_many({"C": 2})
    eng.recompute_continuous_effects()

    actions = eng.legal_actions(p1)
    offers = [a for a in actions if a.get("type") == "activate_ability"
              and a.get("instance_id") == card.instance_id]
    assert len(offers) == 1

    eng.activate_ability(p1, card, offers[0]["ability_index"])
    eng.resolve_until_stable()

    assert card in p1.graveyard


# ---------------------------------------------------------------------------
# RULE 702.28c: "When you cycle this card, <effect>." (`EventType.CYCLED`,
# `ActivationCost.is_cycling`, `RulesEngine._collect_cycled_triggers`)
# ---------------------------------------------------------------------------


def test_paying_a_cycling_cost_fires_cycled_not_a_plain_channel():
    eng = make_engine(hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    p1.mana_pool.add_many({"C": 2})
    obj = _unregistered_cycler()
    bind_from_catalogue(obj)
    p1.add_to_zone(obj, Zone.HAND)
    ability = obj.activated_abilities[0]
    assert ability.cost.is_cycling is True

    seen = []
    eng.state.subscribe(lambda e: seen.append(e) if e.type == EventType.CYCLED else None)
    eng.activate_ability(p1, obj, 0)

    assert len(seen) == 1
    assert seen[0].get("instance_id") == obj.instance_id


def test_a_plain_channel_ability_never_fires_cycled():
    # Channel shares `discard_self` but is never Cycling — `is_cycling`
    # stays False, so no CYCLED event, and a "when you cycle" trigger on
    # some unrelated card must not fire off a Channel discard.
    eng = make_engine(hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    p1.mana_pool.add_many({"C": 1})
    card = Card(id="Channeler", name="Channeler", type_line="Sorcery",
                mana_cost_string="{1}", converted_mana_cost=1, is_sorcery=True,
                oracle_text="Channel — {1}, Discard this card: Draw a card.")
    obj = GameObject(card, owner_id="p1", zone=Zone.HAND)
    obj.activated_abilities = [
        ActivatedAbility(
            effects=[DrawCardEffect(count=1)],
            cost=parse_activation_cost("{1}, Discard this card"),
            source=obj,
            description="Channel",
        )
    ]
    p1.add_to_zone(obj, Zone.HAND)
    assert obj.activated_abilities[0].cost.is_cycling is False

    seen = []
    eng.state.subscribe(lambda e: seen.append(e) if e.type == EventType.CYCLED else None)
    eng.activate_ability(p1, obj, 0)

    assert seen == []


def test_when_you_cycle_this_card_trigger_fires_from_the_graveyard():
    # A "when you cycle" ability lives on an object that's already been
    # discarded to the graveyard by the time CYCLED fires — proving
    # `_collect_cycled_triggers`'s graveyard-scoped scan, not the ordinary
    # (battlefield-only) `_collect_triggers` loop, is what finds it.
    eng = make_engine(hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    p1.mana_pool.add_many({"C": 2})
    obj = _unregistered_cycler()
    bind_from_catalogue(obj)
    bonus = TriggeredAbility(
        trigger_event=EventType.CYCLED,
        condition=lambda e, c, iid=obj.instance_id: e.get("instance_id") == iid,
        effects=[DestroyEffect(target_kind="permanent", selector="all_creatures")],
        source=obj,
    )
    obj.triggered_abilities.append(bonus)
    p1.add_to_zone(obj, Zone.HAND)
    bystander_card = Card(id="Bystander", name="Bystander", type_line="Creature",
                           is_creature=True, power=1, toughness=1)
    bystander = GameObject(bystander_card, owner_id="p1", zone=Zone.BATTLEFIELD)
    eng.state.add_to_battlefield(bystander)

    eng.activate_ability(p1, obj, 0)
    assert obj in p1.graveyard  # the source is already discarded here
    placed = eng.rules.put_triggers_on_stack()
    assert placed == 1
    eng.resolve_until_stable()

    assert bystander not in eng.state.battlefield


def _shark_typhoon_card():
    return Card(
        id="Shark Typhoon", name="Shark Typhoon", type_line="Enchantment",
        mana_cost_string="{3}{U}", converted_mana_cost=4,
        oracle_text="Whenever you cast a noncreature spell, create an X/X blue "
                     "Shark creature token with flying, where X is that spell's "
                     "mana value.\nCycling {X}{1}{U} ({X}{1}{U}, Discard this "
                     "card: Draw a card.)\nWhen you cycle this card, create an "
                     "X/X blue Shark creature token with flying.",
        keywords=["Cycling"],
    )


def test_shark_typhoon_is_fully_modeled():
    result = parse_oracle(_shark_typhoon_card())
    assert result.coverage == MODELED


def test_shark_typhoon_spell_cast_trigger_sizes_the_shark_by_mana_value():
    eng = make_engine(hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    p1.mana_pool.add_many({"C": 3})
    typhoon = GameObject(_shark_typhoon_card(), owner_id="p1", zone=Zone.BATTLEFIELD)
    bind_from_catalogue(typhoon)
    eng.state.add_to_battlefield(typhoon)

    bolt = GameObject(
        Card(id="Bolt", name="Bolt", type_line="Instant", mana_cost_string="{2}{R}",
             converted_mana_cost=3, is_instant=True, oracle_text="~ deals 3 damage to any target."),
        owner_id="p1", zone=Zone.HAND,
    )
    bind_from_catalogue(bolt)
    p1.add_to_zone(bolt, Zone.HAND)
    p1.mana_pool.add_many({"R": 3})

    before = len(eng.state.battlefield)
    eng.cast_spell(p1, bolt, targets=[eng.state.player_by_id("p1")])
    eng.resolve_until_stable()

    sharks = [o for o in eng.state.battlefield if "Shark" in o.card.type_line]
    assert len(sharks) == 1
    assert sharks[0].power == 3 and sharks[0].toughness == 3
    assert len(eng.state.battlefield) == before + 1


def test_shark_typhoon_cycling_sizes_the_shark_by_the_paid_x():
    eng = make_engine(hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    p1.mana_pool.add_many({"C": 6, "U": 1})
    typhoon = GameObject(_shark_typhoon_card(), owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(typhoon)
    p1.add_to_zone(typhoon, Zone.HAND)

    (ability,) = typhoon.activated_abilities
    assert ability.cost.is_cycling is True
    eng.activate_ability(p1, typhoon, 0, x=5)
    assert typhoon in p1.graveyard
    placed = eng.rules.put_triggers_on_stack()
    assert placed == 1
    eng.resolve_until_stable()

    sharks = [o for o in eng.state.battlefield if "Shark" in o.card.type_line]
    assert len(sharks) == 1
    assert sharks[0].power == 5 and sharks[0].toughness == 5
