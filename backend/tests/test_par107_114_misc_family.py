"""PAR-107…114 residue batches, part 2 — miscellaneous shapes (mana triggers, counters, edicts, blink, tallies …).

New axes (each measured over the whole card cache, 0 regressed):

* "whenever enchanted land is tapped for mana, its controller adds an additional {G}{G}" — `is tapped for mana`
  as a trigger verb, the "an additional" mana wording, and "2 mana in any combination of colors" as two single picks;
* "counter target spell, activated ability, or triggered ability" — `counter` with ``target_kind=spell_or_ability``;
  "counter target spell with mana value X";
* "look at target player's hand" — an informational pending choice (`look_at_hand`);
* "you win the game" after an intervening "if you have 40 or more life";
* "where x is the number of cards in your hand minus 4" (floored), "-X/-X … where X is …" (negated bind);
* "the greatest mana value among your commanders" and the "where x is the greatest …" amount family;
* "target opponent sacrifices/exiles a creature or planeswalker with the greatest mana value …";
* "exile up to 2 target creatures you control, then return those cards …" — plural / tapped / owner blink;
* "for each creature destroyed this way" — the resolution's own destroyed/exiled tallies;
* "target player mills half their library, rounded down";
* "you may shuffle" after "look at the top N cards, then put them back in any order";
* a played-from-exile turn tally ("if you didn't play a card from exile this turn").

Reference: parser/oracle/catalogue/handlers.py, segmenter.py, count_phrase.py, history_phrase.py; game/effects/*.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.normalize import normalize
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body


def _card(name, type_line="Creature — Bear", oracle_text="", **kw):
    kw.setdefault("converted_mana_cost", 2)
    creature = "Creature" in type_line
    kw.setdefault("power", 2 if creature else None)
    kw.setdefault("toughness", 2 if creature else None)
    return Card(
        id=name, name=name, type_line=type_line, oracle_text=oracle_text, is_creature=creature,
        is_instant="Instant" in type_line, is_sorcery="Sorcery" in type_line,
        is_land="Land" in type_line, **kw,
    )


def _engine():
    eng = GameEngine.new_game([("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    return eng


def _put(eng, card, controller="p1", zone=Zone.BATTLEFIELD):
    obj = GameObject(card, owner_id=controller, zone=zone)
    obj.controller_id = controller
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    player = eng.state.player_by_id(controller)
    if zone == Zone.BATTLEFIELD:
        eng.state.add_to_battlefield(obj)
    else:
        player.add_to_zone(obj, zone)
    return obj


def _parse(text):
    return parse_effect_body(normalize(text))


def _cast(eng, name, type_line, text, targets=None, controller="p1", cmc=0):
    player = eng.state.player_by_id(controller)
    spell = GameObject(_card(name, type_line, text, converted_mana_cost=cmc), owner_id=controller, zone=Zone.HAND)
    bind_from_catalogue(spell)
    player.add_to_zone(spell, Zone.HAND)
    eng.cast_spell(player, spell, targets=targets or [])
    return spell


# --- triggered mana off an enchanted land ---------------------------------------------------------------


@pytest.mark.parametrize("text, expected_colors", [
    ("Enchant land\nWhenever enchanted land is tapped for mana, its controller adds an additional {G}.", ["G"]),
    ("Enchant land\nWhenever enchanted land is tapped for mana, its controller adds an additional {G}{G}.", ["G", "G"]),
])
def test_wild_growth_family_adds_extra_mana_for_the_lands_controller(text, expected_colors):
    aura_card = _card("Growth Test", "Enchantment — Aura", text)
    result = parse_oracle(aura_card)
    assert result.modeled, result.unclaimed
    trig = next(s for s in result.specs if s.ability_kind == "triggered")
    assert trig.trigger["event"] == "TAPPED_FOR_MANA" and trig.trigger.get("mana_ability") is True
    assert [e.type for e in trig.effects] == ["add_mana"]
    assert trig.effects[0].params["recipient"] == "event_controller"

    eng = _engine()
    land = _put(eng, _card("Forest", "Basic Land — Forest", converted_mana_cost=0))
    aura = _put(eng, aura_card)
    aura.attached_to = land.instance_id
    p1 = eng.state.player_by_id("p1")
    eng.tap_for_mana(p1, land)
    eng.resolve_until_stable()
    # the land's own {G} plus the Aura's bonus
    assert p1.mana_pool.total() == 1 + len(expected_colors)


def test_two_any_colour_mana_is_two_independent_picks():
    # the bare phrase names no tapper to credit — only the enchanted-land referent claims it
    assert not _parse("Add an additional 2 mana in any combination of colors.")
    trig = parse_oracle(_card(
        "Dawn Test", "Enchantment — Aura",
        "Enchant land\nWhenever enchanted land is tapped for mana, its controller adds an additional 2 mana in "
        "any combination of colors.")).specs
    effects = next(s for s in trig if s.ability_kind == "triggered").effects
    assert [e.params["colors"] for e in effects] == [["any"], ["any"]]


def test_badgermole_style_creature_tap_adds_on_top():
    [spec] = _parse("Add an additional {g}.")
    assert spec.type == "add_mana" and spec.params == {"colors": ["G"]}
    card = _card("Cub Test", "Creature — Badger", "Whenever you tap a creature for mana, add an additional {G}.")
    assert parse_oracle(card).modeled


# --- counter target spell, activated ability, or triggered ability ----------------------------------------


def test_counter_spell_or_ability_parses_with_the_union_kind():
    [spec] = _parse("Counter target spell, activated ability, or triggered ability.")
    assert spec.type == "counter" and spec.params == {"target_kind": "spell_or_ability"}


def test_disallow_counters_a_spell_and_an_ability():
    text = "Counter target spell, activated ability, or triggered ability."
    eng = _engine()
    p2 = eng.state.player_by_id("p2")
    # a spell on the stack
    bolt = GameObject(_card("Bolt", "Instant", "~ deals 3 damage to any target.", converted_mana_cost=0),
                      owner_id="p2", zone=Zone.HAND)
    bind_from_catalogue(bolt)
    p2.add_to_zone(bolt, Zone.HAND)
    eng.state.active_player_index = eng.state.players.index(p2)
    eng.cast_spell(p2, bolt, targets=[eng.state.player_by_id("p1")])
    assert any(item.obj is bolt for item in eng.state.stack)
    eng.state.active_player_index = 0
    disallow = _put(eng, _card("Disallow", "Instant", text, converted_mana_cost=0), zone=Zone.HAND)
    p1 = eng.state.player_by_id("p1")
    eng.cast_spell(p1, disallow, targets=[bolt])
    eng.resolve_until_stable()
    assert bolt.zone == Zone.GRAVEYARD and p1.life == 20  # countered, never resolved


def test_spell_blast_names_the_announced_x_as_the_mana_value():
    text = "Counter target spell with mana value X."
    [spec] = _parse(text)
    assert spec.type == "counter" and spec.params["mana_value"] == "x"
    from mtg_analyzer.game import targeting

    eng = _engine()
    p2 = eng.state.player_by_id("p2")
    p2.mana_pool.add_many({"C": 8})
    for name, cmc in (("Cheap", 1), ("Dear", 3)):
        spell = GameObject(_card(name, "Instant", converted_mana_cost=cmc, mana_cost_string="{%d}" % cmc),
                           owner_id="p2", zone=Zone.HAND)
        bind_from_catalogue(spell)
        p2.add_to_zone(spell, Zone.HAND)
        eng.state.active_player_index = eng.state.players.index(p2)
        eng.cast_spell(p2, spell)
    eng.state.active_player_index = 0
    source = GameObject(_card("Spell Blast", "Instant", text, converted_mana_cost=1), owner_id="p1", zone=Zone.HAND)
    source.x_paid = 3
    spec_obj = targeting.TargetSpec(kind="spell", spell_filter={"mana_value": "x"})
    offered = targeting.legal_targets(eng.state, "p1", spec_obj, source=source)
    assert [o["name"] for o in offered] == ["Dear"]
    source.x_paid = 1
    assert [o["name"] for o in targeting.legal_targets(eng.state, "p1", spec_obj, source=source)] == ["Cheap"]


# --- look at target player's hand -------------------------------------------------------------------------


def test_look_at_hand_shows_the_hand_to_the_looker_only():
    [spec] = _parse("Look at target player's hand.")
    assert spec.type == "look_at_hand"
    eng = _engine()
    p1, p2 = eng.state.player_by_id("p1"), eng.state.player_by_id("p2")
    held = [_put(eng, _card(f"Secret{i}", "Instant"), controller="p2", zone=Zone.HAND) for i in range(2)]
    glasses = _put(eng, _card("Glasses Test", "Artifact", "{T}: Look at target player's hand."))
    eng.activate_ability(p1, glasses, 0, targets=[p2])
    eng.resolve_until_stable()
    choice = eng.state.pending_choice
    assert choice["kind"] == "look_hand" and choice["player_id"] == "p1" and choice["owner_id"] == "p2"
    assert sorted(o["label"] for o in choice["options"] if "instance_id" in o) == ["Secret0", "Secret1"]
    eng.resolve_pending_choice("decline")
    assert eng.state.pending_choice is None
    assert all(card in p2.hand for card in held)  # nothing moved


def test_looking_at_an_empty_hand_opens_nothing():
    eng = _engine()
    p1, p2 = eng.state.player_by_id("p1"), eng.state.player_by_id("p2")
    eng.rules.look_at_hand(p1, p2)
    assert eng.state.pending_choice is None


# --- you win the game ------------------------------------------------------------------------------------


def test_felidar_sovereign_wins_at_forty_life_only():
    text = "At the beginning of your upkeep, if you have 40 or more life, you win the game."
    assert parse_oracle(_card("Sovereign Test", "Creature — Cat Beast", text)).modeled
    [spec] = _parse("You win the game.")
    assert spec.type == "win_game"
    spec = next(s for s in parse_oracle(_card("Sovereign Test", "Creature — Cat Beast", text)).specs
                if s.ability_kind == "triggered")
    assert spec.effects[0].condition == {"kind": "life_at_least", "amount": 40}


# --- amounts -------------------------------------------------------------------------------------------


def test_minus_is_floored_at_zero():
    [spec] = _parse("You gain X life, where X is the number of cards in your hand minus 4.")
    assert spec.params["amount"]["minus"] == 4 and spec.params["amount"]["minimum"] == 0
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    for i in range(3):
        _put(eng, _card(f"H{i}", "Instant"), zone=Zone.HAND)
    tower = _put(eng, _card("Tower Test", "Artifact",
                            "At the beginning of your upkeep, you gain X life, where X is the number of cards in "
                            "your hand minus 4."))
    life = p1.life
    from mtg_analyzer.game.effects.core import EffectRegistry, GameContext

    effect = EffectRegistry.create("bind", dict(spec.params))
    effect.source = tower
    effect.apply(GameContext(eng.state, eng.rules))
    assert p1.life == life  # 3 cards in hand: -1 counts as 0
    for i in range(3):
        _put(eng, _card(f"I{i}", "Instant"), zone=Zone.HAND)
    effect.apply(GameContext(eng.state, eng.rules))
    assert p1.life == life + 2  # 6 cards in hand


def test_negative_x_pump_binds_the_negated_measurement():
    [spec] = _parse("Target creature gets -X/-X until end of turn, where X is the number of cards in your hand.")
    inner = spec.params["effects"][0]["params"]
    assert inner["power"] == "-$n" and inner["toughness"] == "-$n"
    eng = _engine()
    victim = _put(eng, _card("Victim", "Creature — Bear", power=5, toughness=5), controller="p2")
    for i in range(3):
        _put(eng, _card(f"H{i}", "Instant"), zone=Zone.HAND)
    _cast(eng, "Nightmarish End", "Instant",
          "Target creature gets -X/-X until end of turn, where X is the number of cards in your hand.",
          targets=[victim])
    eng.resolve_until_stable()
    assert victim.power == 2 and victim.toughness == 2


def test_greatest_commander_mana_value_counts_both_zones():
    from mtg_analyzer.game import continuous

    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    on_field = _put(eng, _card("Cmdr A", "Legendary Creature — Elf", converted_mana_cost=4))
    on_field.is_commander = True
    in_zone = _put(eng, _card("Cmdr B", "Legendary Creature — Elf", converted_mana_cost=6), zone=Zone.COMMAND)
    in_zone.is_commander = True
    assert continuous.count_selector(eng.state, "p1", "greatest_commander_mana_value") == 6
    assert continuous.count_selector(eng.state, "p2", "greatest_commander_mana_value") == 0
    assert p1 is not None


@pytest.mark.parametrize("text", [
    "All creatures get -X/-X until end of turn, where X is the greatest mana value of a commander you own on the "
    "battlefield or in the command zone.",
    "Scry X, where X is the greatest mana value among permanents you control, then draw three cards.",
    "Look at the top X cards of your library, where X is the number of cards in your hand, then put them back in any "
    "order.",
])
def test_where_x_amount_phrases_claim(text):
    assert _parse(text)


# --- edicts by greatest mana value ---------------------------------------------------------------------------


def test_edict_by_mana_value_parses_as_sacrifice_or_exile():
    [spec] = _parse("Each opponent sacrifices a creature or planeswalker with the greatest mana value among "
                    "creatures and planeswalkers they control.")
    assert spec.params == {"what": "creature_or_planeswalker", "count": 1, "greatest": "mana_value",
                           "selector": "each_opponent"}
    [spec] = _parse("Target opponent exiles a creature or planeswalker they control with the greatest mana value "
                    "among creatures and planeswalkers they control.")
    assert spec.params["action"] == "exile" and spec.params["target_kind"] == "player"
    # a pool that is not the picked type is another card
    assert not _parse("Each opponent sacrifices a creature with the greatest mana value among creatures and "
                      "planeswalkers they control.")


def test_flare_of_malice_takes_the_dearest_and_asks_on_a_tie():
    text = ("Each opponent sacrifices a creature or planeswalker with the greatest mana value among creatures "
            "and planeswalkers they control.")
    eng = _engine()
    cheap = _put(eng, _card("Cheap", converted_mana_cost=1), controller="p2")
    dear = _put(eng, _card("Dear", converted_mana_cost=5), controller="p2")
    _cast(eng, "Flare Test", "Sorcery", text)
    eng.resolve_until_stable()
    assert dear.zone == Zone.GRAVEYARD and cheap in eng.state.battlefield
    # a tie is the opponent's choice among the tied
    a = _put(eng, _card("Tie A", converted_mana_cost=4), controller="p2")
    b = _put(eng, _card("Tie B", converted_mana_cost=4), controller="p2")
    _cast(eng, "Flare Test 2", "Sorcery", text)
    eng.resolve_until_stable()
    choice = eng.state.pending_choice
    assert choice is not None and choice["player_id"] == "p2"
    eng.resolve_pending_choice(b.instance_id)
    assert b.zone == Zone.GRAVEYARD and a in eng.state.battlefield and cheap in eng.state.battlefield


def test_blot_out_exiles_instead():
    text = ("Target opponent exiles a creature or planeswalker they control with the greatest mana value "
            "among creatures and planeswalkers they control.")
    eng = _engine()
    p2 = eng.state.player_by_id("p2")
    dear = _put(eng, _card("Dear", converted_mana_cost=5), controller="p2")
    _cast(eng, "Blot Test", "Instant", text, targets=[p2])
    eng.resolve_until_stable()
    assert dear in p2.exile


# --- blink, plural --------------------------------------------------------------------------------------


def test_displace_blinks_up_to_two_and_gandalf_returns_lands_tapped():
    [spec] = _parse("Exile up to 2 target creatures you control, then return those cards to the battlefield under "
                    "their owner's control.")
    assert spec.type == "blink" and spec.params == {
        "target_kind": "creature_you_control", "optional": True, "target_count_max": 2}
    [spec] = _parse("Exile up to 3 target lands you control, then return them to the battlefield tapped under "
                    "their owner's control.")
    assert spec.params["tapped"] is True and spec.params["target_kind"] == "land_you_control"

    eng = _engine()
    a = _put(eng, _card("Alpha"))
    b = _put(eng, _card("Beta"))
    a.counters["+1/+1"] = 2
    _cast(eng, "Displace Test", "Sorcery",
          "Exile up to 2 target creatures you control, then return those cards to the battlefield under their "
          "owner's control.", targets=[a, b])
    eng.resolve_until_stable()
    assert a in eng.state.battlefield and b in eng.state.battlefield
    assert not a.counters  # RULE 400.7: a new object remembers nothing


def test_blinked_lands_come_back_tapped():
    eng = _engine()
    land = _put(eng, _card("Forest", "Basic Land — Forest", converted_mana_cost=0))
    eng.rules.blink(land, tapped=True)
    assert land in eng.state.battlefield and land.tapped


# --- "…destroyed this way" tallies --------------------------------------------------------------------------


def test_fumigate_gains_one_life_per_creature_destroyed():
    text = "Destroy all creatures. You gain 1 life for each creature destroyed this way."
    assert parse_oracle(_card("Fumigate Test", "Sorcery", text)).modeled
    eng = _engine()
    for i in range(3):
        _put(eng, _card(f"Mine{i}"))
    for i in range(2):
        _put(eng, _card(f"Theirs{i}"), controller="p2")
    p1 = eng.state.player_by_id("p1")
    life = p1.life
    _cast(eng, "Fumigate Test", "Sorcery", text)
    eng.resolve_until_stable()
    assert not [o for o in eng.state.battlefield if o.is_creature]
    assert p1.life == life + 5


def test_a_narrower_this_way_noun_stays_unclaimed():
    assert not _parse("Destroy all creatures. For each nontoken creature destroyed this way, you create a tapped "
                      "Treasure token.")


# --- mill half ----------------------------------------------------------------------------------------------


@pytest.mark.parametrize("direction, library, milled", [("down", 7, 3), ("up", 7, 4), ("down", 0, 0)])
def test_mill_half_their_library(direction, library, milled):
    text = f"Target player mills half their library, rounded {direction}."
    [spec] = _parse(text)
    assert spec.params == {"target_kind": "player", "half": direction}
    eng = _engine()
    p2 = eng.state.player_by_id("p2")
    for i in range(library):
        p2.library.append(GameObject(_card(f"L{i}", "Instant"), owner_id="p2", zone=Zone.LIBRARY))
    _cast(eng, "Cut Test", "Sorcery", text, targets=[p2])
    eng.resolve_until_stable()
    assert len(p2.graveyard) == milled and len(p2.library) == library - milled


# --- look at the top N, "you may shuffle" -------------------------------------------------------------------


def test_may_shuffle_is_offered_after_the_order_is_set():
    text = "Look at the top 3 cards of your library, then put them back in any order. You may shuffle."
    [spec] = _parse(text)
    assert spec.params == {"count": 3, "may_shuffle": True}
    # "have that player shuffle" belongs to the target form only, and vice versa
    assert not _parse("Look at the top 3 cards of your library, then put them back in any order. You may have "
                      "that player shuffle.")
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    cards = [GameObject(_card(f"L{i}", "Instant"), owner_id="p1", zone=Zone.LIBRARY) for i in range(5)]
    p1.library.extend(cards)
    eng.rules.look_reorder_top(p1, 3, may_shuffle=True)
    assert eng.state.pending_choice["kind"] == "reorder_top"
    eng.resolve_pending_choice(None)  # keep the order
    offer = eng.state.pending_choice
    assert offer["kind"] == "shuffle_offer" and offer["library_owner_id"] == "p1"
    before = list(p1.library)
    eng.resolve_pending_choice("decline")
    assert eng.state.pending_choice is None and p1.library == before
    eng.rules.look_reorder_top(p1, 3, may_shuffle=True)
    eng.resolve_pending_choice(None)
    eng.resolve_pending_choice("do")
    assert eng.state.pending_choice is None and sorted(o.instance_id for o in p1.library) == sorted(
        o.instance_id for o in before)


# --- cards played from exile ---------------------------------------------------------------------------------


def test_played_from_exile_tally_counts_spells_and_lands():
    from mtg_analyzer.parser.oracle.catalogue.history_phrase import parse_history_condition

    assert parse_history_condition("you didn't play a card from exile this turn") == {
        "kind": "cards_played_from_exile_this_turn", "max": 0}
    assert parse_history_condition("you played a card from exile this turn") == {
        "kind": "cards_played_from_exile_this_turn", "min": 1}
    eng = _engine()
    assert eng.state.cards_played_from_exile_this_turn.get("p1", 0) == 0
    eng.state.fire_event(GameEvent(EventType.SPELL_CAST, player_id="p1", from_exile=True))
    eng.state.fire_event(GameEvent(EventType.LAND_PLAYED, player_id="p1", from_exile=True))
    eng.state.fire_event(GameEvent(EventType.LAND_PLAYED, player_id="p1", from_exile=False))
    eng.state.fire_event(GameEvent(EventType.SPELL_CAST, player_id="p2", from_exile=False))
    assert eng.state.cards_played_from_exile_this_turn["p1"] == 2
    assert eng.state.cards_played_from_exile_this_turn.get("p2", 0) == 0

    from mtg_analyzer.game import static_conditions

    didnt_play = {"kind": "cards_played_from_exile_this_turn", "max": 0}
    assert static_conditions.condition_holds(didnt_play, eng.state, controller_id="p2")
    assert not static_conditions.condition_holds(didnt_play, eng.state, controller_id="p1")


def test_deny_the_witch_counters_an_ability_and_its_controller_loses_life():
    from mtg_analyzer.models.game.game_state import StackItem
    from mtg_analyzer.game.effects.core import DealDamageEffect

    text = ("Counter target spell, activated ability, or triggered ability. Its controller loses life equal to the "
            "number of creatures you control.")
    assert parse_oracle(_card("Deny Test", "Instant", text)).modeled
    eng = _engine()
    p1, p2 = eng.state.player_by_id("p1"), eng.state.player_by_id("p2")
    for i in range(3):
        _put(eng, _card(f"Mine{i}"))
    source = _put(eng, _card("Pinger", "Artifact"), controller="p2")
    victim = _put(eng, _card("Victim", toughness=5))
    ability = StackItem(kind="ability", controller_id="p2", source=source, description="Pinger's ability",
                        effects=[DealDamageEffect(3, target_kind="creature")], targets=[victim])
    eng.state.stack.append(ability)
    deny = GameObject(_card("Deny Test", "Instant", text, converted_mana_cost=0), owner_id="p1", zone=Zone.STACK)
    deny.controller_id = "p1"
    bind_from_catalogue(deny)
    for e in deny.spell_effects:
        e.source = deny
    eng.state.stack.append(StackItem(
        kind="spell", controller_id="p1", obj=deny, description="Deny Test",
        effects=deny.spell_effects, targets=[ability]))
    life = p2.life
    eng.resolve_until_stable()
    assert ability not in eng.state.stack and victim.damage_marked == 0
    # p1 controls its three creatures and the victim: the ability's controller (p2) loses 4
    assert p2.life == life - 4 and p1.life == 20


def test_a_spell_that_puts_itself_on_the_bottom_of_its_library_does_so_instead_of_the_graveyard():
    text = "You gain twice X life. Put ~ on the bottom of its owner's library."
    assert parse_oracle(_card("Sacrament Test", "Sorcery", text)).modeled
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    for i in range(3):
        p1.library.append(GameObject(_card(f"L{i}", "Instant"), owner_id="p1", zone=Zone.LIBRARY))
    spell = _cast(eng, "Sacrament Test", "Sorcery", text)
    eng.resolve_until_stable()
    assert spell.zone == Zone.LIBRARY and p1.library[0] is spell and spell not in p1.graveyard


def test_terminus_puts_every_creature_on_the_bottom_of_its_owners_library():
    text = "Put all creatures on the bottom of their owners' libraries."
    [spec] = _parse(text)
    assert spec.type == "return_to_library" and spec.params["position"] == "bottom" and "group" in spec.params
    eng = _engine()
    mine = _put(eng, _card("Mine"))
    theirs = _put(eng, _card("Theirs"), controller="p2")
    land = _put(eng, _card("Forest", "Basic Land — Forest", converted_mana_cost=0))
    _cast(eng, "Terminus Test", "Sorcery", text)
    eng.resolve_until_stable()
    assert mine.zone == Zone.LIBRARY and theirs.zone == Zone.LIBRARY and land in eng.state.battlefield
    assert eng.state.player_by_id("p1").library[0] is mine and eng.state.player_by_id("p2").library[0] is theirs


def test_geyser_drake_discounts_only_on_other_players_turns():
    text = "During turns other than yours, spells you cast cost {1} less to cast."
    card = _card("Drake Test", "Creature — Drake", text)
    assert parse_oracle(card).modeled
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    _put(eng, card)
    spell = _put(eng, _card("Spell", "Instant", converted_mana_cost=3, mana_cost_string="{2}{R}"), zone=Zone.HAND)
    assert eng.effective_cast_cost(p1, spell).converted_mana_cost == 3  # my turn
    eng.state.active_player_index = 1
    assert eng.effective_cast_cost(p1, spell).converted_mana_cost == 2  # an opponent's turn


def test_sakiko_adds_mana_equal_to_the_damage_and_keeps_it():
    from mtg_analyzer.models.mana.mana_pool import KEEP_UNTIL_END_OF_TURN

    text = ("Whenever a creature you control deals combat damage to a player, add that much {G}. Until end of turn, "
            "you don't lose this mana as steps and phases end.")
    card = _card("Sakiko Test", "Legendary Creature — Spirit", text)
    assert parse_oracle(card).modeled
    spec = next(s for s in parse_oracle(card).specs if s.ability_kind == "triggered")
    assert spec.effects[0].params == {
        "color": "G", "amount_from_trigger_event": "amount", "keep_until": KEEP_UNTIL_END_OF_TURN}
