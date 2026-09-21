"""PAR-98 — the small verified residue batch #2 (parse + execute): two-color cast
triggers, Meanders Guide's reflexive tap-then-return, the "except by creatures
with haste" family, "when you sacrifice a Clue", the last-time-counter trigger and
the noncreature-spell activation gate."""

from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle
from mtg_analyzer.services.card_database import CardDatabase, DEFAULT_DB_PATH


def test_two_color_mimic_triggers_parse_with_an_and_color_filter():
    db = CardDatabase(DEFAULT_DB_PATH)
    for name, colors in (
        ("Battlegate Mimic", ["R", "W"]),
        ("Nightsky Mimic", ["W", "B"]),
        ("Riverfall Mimic", ["U", "R"]),
    ):
        parsed = parse_oracle(db.get_card(name))
        assert parsed.coverage != UNMODELED
        trigger = next(spec.trigger for spec in parsed.specs if spec.trigger.get("event") == "SPELL_CAST")
        assert trigger["cast_of_all_colors"] == colors


# --- Meanders Guide: an optional tap, then a RULE 603.12 reflexive trigger ----

from mtg_analyzer.game.binding.core import bind_from_catalogue, build_effects
from mtg_analyzer.game.effects.core import _apply_effects_partitioned
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone


def _meanders_table(*, merfolk_tapped: bool):
    eng = GameEngine.new_game([("p1", "p1", []), ("p2", "p2", [])], starting_life=20, starting_hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.players[0]
    guide = GameObject(CardDatabase(DEFAULT_DB_PATH).get_card("Meanders Guide"), owner_id="p1", zone=Zone.BATTLEFIELD)
    guide.controller_id = "p1"
    guide.summoning_sick = False
    bind_from_catalogue(guide)
    eng.state.add_to_battlefield(guide)
    ally = GameObject(Card(id="mer", name="Ally Merfolk", type_line="Creature — Merfolk",
                           is_creature=True, power=1, toughness=1), owner_id="p1", zone=Zone.BATTLEFIELD)
    ally.controller_id = "p1"
    ally.tapped = merfolk_tapped
    eng.state.add_to_battlefield(ally)
    cheap = GameObject(Card(id="cheap", name="Cheap Bear", type_line="Creature — Bear", is_creature=True,
                            power=1, toughness=1, converted_mana_cost=3), owner_id="p1", zone=Zone.GRAVEYARD)
    dear = GameObject(Card(id="dear", name="Dear Bear", type_line="Creature — Bear", is_creature=True,
                           power=4, toughness=4, converted_mana_cost=4), owner_id="p1", zone=Zone.GRAVEYARD)
    p1.graveyard.extend([cheap, dear])
    return eng, guide, ally, cheap, dear


def _resolve_guide_attack_body(eng, guide):
    trig = next(s for s in parse_oracle(guide.card).specs if s.ability_kind == "triggered")
    _apply_effects_partitioned(build_effects(trig.effects, guide), eng.rules.context, None, None, source=guide)
    eng.resolve_until_stable()


def test_meanders_guide_tap_then_reflexive_return_executes():
    eng, guide, ally, cheap, dear = _meanders_table(merfolk_tapped=False)
    _resolve_guide_attack_body(eng, guide)
    assert ally.tapped
    choice = eng.state.pending_choice
    assert choice is not None and choice["kind"] == "trigger_target"
    offered = {o["instance_id"] for o in choice["options"] if "instance_id" in o}
    assert cheap.instance_id in offered and dear.instance_id not in offered  # mana value 3 or less
    eng.rules.resolve_choice(cheap.instance_id)
    eng.resolve_until_stable()
    assert cheap.zone == Zone.BATTLEFIELD and dear.zone == Zone.GRAVEYARD


def test_meanders_guide_without_an_untapped_merfolk_returns_nothing():
    eng, guide, ally, cheap, dear = _meanders_table(merfolk_tapped=True)
    _resolve_guide_attack_body(eng, guide)
    assert eng.state.pending_choice is None
    assert cheap.zone == Zone.GRAVEYARD


# --- "…can't be blocked this turn except by creatures with haste" -----------

from mtg_analyzer.game import combat
from mtg_analyzer.game.effects.core import _apply_effects_partitioned as _apply_partitioned


def _bear(eng, pid, name, *, keywords=""):
    obj = GameObject(Card(id=name[:6], name=name, type_line="Creature — Bear", is_creature=True,
                          power=2, toughness=2, oracle_text=keywords), owner_id=pid, zone=Zone.BATTLEFIELD)
    obj.controller_id = pid
    eng.state.add_to_battlefield(obj)
    return obj


def _fresh_engine():
    eng = GameEngine.new_game([("p1", "p1", []), ("p2", "p2", [])], starting_life=20, starting_hand=0)
    eng.begin_turn()
    return eng


def test_evasion_exception_haste_cards_parse():
    db = CardDatabase(DEFAULT_DB_PATH)
    for name in ("Agility Bobblehead", "Run for Your Life", "Speed, Young Avenger"):
        parsed = parse_oracle(db.get_card(name))
        assert parsed.coverage != UNMODELED, (name, parsed.unclaimed)


def test_run_for_your_life_restricts_every_chosen_creature():
    eng = _fresh_engine()
    a, b = _bear(eng, "p1", "Alpha"), _bear(eng, "p1", "Beta")
    slow, fast = _bear(eng, "p2", "Slow"), _bear(eng, "p2", "Fast")
    fast.temp_keywords.add("haste")
    spell = parse_oracle(CardDatabase(DEFAULT_DB_PATH).get_card("Run for Your Life"))
    body = next(s for s in spell.specs if s.ability_kind == "spell_effect")
    _apply_partitioned(build_effects(body.effects, a), eng.rules.context, [a, b], None, source=a)
    eng.recompute_continuous_effects()
    for attacker in (a, b):
        assert "haste" in attacker.granted_keywords or "haste" in attacker.temp_keywords
        assert combat.blocker_allowed(attacker, slow) is False
        assert combat.blocker_allowed(attacker, fast) is True


def test_speed_young_avenger_needs_a_hasty_target_and_grants_the_restriction():
    parsed = parse_oracle(CardDatabase(DEFAULT_DB_PATH).get_card("Speed, Young Avenger"))
    trig = next(s for s in parsed.specs if s.ability_kind == "triggered")
    inner = trig.effects[0].params["then_trigger"][0]["params"]
    assert inner["creature_filter"] == {"keyword": "haste"}
    assert inner["restriction"] == {"kind": "only_blocked_by", "filter": {"keyword": "haste"}}


def test_agility_bobblehead_target_count_reads_the_bobbleheads_you_control():
    from mtg_analyzer.game.continuous import count_selector

    eng = _fresh_engine()
    for i in range(2):
        bobble = GameObject(Card(id=f"bob{i}", name=f"Bobblehead {i}", type_line="Artifact — Bobblehead"),
                            owner_id="p1", zone=Zone.BATTLEFIELD)
        bobble.controller_id = "p1"
        eng.state.add_to_battlefield(bobble)
    opposing = GameObject(Card(id="bobx", name="Their Bobblehead", type_line="Artifact — Bobblehead"),
                          owner_id="p2", zone=Zone.BATTLEFIELD)
    opposing.controller_id = "p2"
    eng.state.add_to_battlefield(opposing)
    assert count_selector(eng.state, "p1", "permanents_you_control_of_type_bobblehead") == 2


# --- "When(ever) you sacrifice a Clue, …" ----------------------------------


def _clue(eng):
    clue = GameObject(Card(id="Clue", name="Clue", type_line="Artifact — Clue"), owner_id="p1", zone=Zone.BATTLEFIELD)
    clue.controller_id = "p1"
    eng.state.add_to_battlefield(clue)
    return clue


def _bound(eng, name, zone):
    obj = GameObject(CardDatabase(DEFAULT_DB_PATH).get_card(name), owner_id="p1", zone=zone)
    obj.controller_id = "p1"
    bind_from_catalogue(obj)
    if zone == Zone.BATTLEFIELD:
        obj.summoning_sick = False
        eng.state.add_to_battlefield(obj)
    else:
        eng.state.players[0].graveyard.append(obj)
    return obj


def test_sacrifice_clue_bare_when_cards_parse():
    db = CardDatabase(DEFAULT_DB_PATH)
    for name in ("Curious Cadaver", "Daring Sleuth // Bearer of Overwhelming Truths", "Persuasive Interrogators"):
        parsed = parse_oracle(db.get_card(name))
        assert parsed.coverage != UNMODELED, (name, parsed.unclaimed)


def test_curious_cadaver_returns_from_the_graveyard_when_a_clue_is_sacrificed():
    eng = _fresh_engine()
    cadaver = _bound(eng, "Curious Cadaver", Zone.GRAVEYARD)
    eng.rules.put_into_graveyard(_clue(eng))
    assert eng.rules.put_triggers_on_stack() == 1
    eng.rules.resolve_top_of_stack()
    assert cadaver in eng.state.players[0].hand


def test_persuasive_interrogators_gives_the_targeted_opponent_two_poison():
    eng = _fresh_engine()
    _bound(eng, "Persuasive Interrogators", Zone.BATTLEFIELD)
    eng.rules.put_into_graveyard(_clue(eng))
    eng.rules.put_triggers_on_stack()
    if eng.state.pending_choice is not None:
        eng.rules.resolve_choice("p2")
    eng.resolve_until_stable()
    assert eng.state.players[1].poison == 2 and eng.state.players[0].poison == 0


# --- "When the last time counter is removed from this card while it's exiled" ---

from mtg_analyzer.models.game.events import EventType, GameEvent


def _suspended(eng, name, counters):
    obj = GameObject(CardDatabase(DEFAULT_DB_PATH).get_card(name), owner_id="p1", zone=Zone.EXILE)
    obj.controller_id = "p1"
    bind_from_catalogue(obj)
    obj.add_counters("time", counters)
    eng.state.players[0].exile.append(obj)
    return obj


def test_last_time_counter_cards_parse():
    db = CardDatabase(DEFAULT_DB_PATH)
    for name in ("Veiling Oddity", "Riftmarked Knight"):
        parsed = parse_oracle(db.get_card(name))
        assert parsed.coverage != UNMODELED, (name, parsed.unclaimed)


def test_veiling_oddity_trigger_fires_only_when_the_last_counter_comes_off():
    eng = _fresh_engine()
    odd = _suspended(eng, "Veiling Oddity", 2)
    mine, theirs = _bear(eng, "p1", "Mine"), _bear(eng, "p2", "Theirs")

    eng.rules.remove_suspend_time_counter(odd)
    assert odd.counters["time"] == 1 and eng.rules.put_triggers_on_stack() == 0

    eng.rules.remove_suspend_time_counter(odd)
    assert eng.rules.put_triggers_on_stack() == 1
    eng.rules.resolve_top_of_stack()
    assert mine.temp_unblockable and theirs.temp_unblockable


def test_veiling_oddity_trigger_through_the_real_upkeep_removal():
    eng = _fresh_engine()
    odd = _suspended(eng, "Veiling Oddity", 1)
    mine = _bear(eng, "p1", "Mine")
    eng.state.fire_event(GameEvent(EventType.STEP_BEGIN, step="upkeep"))
    eng.resolve_until_stable()
    assert odd.counters.get("time", 0) == 0
    assert mine.temp_unblockable


def test_riftmarked_knight_makes_a_knight_with_protection_from_white_when_suspend_ends():
    from mtg_analyzer.game.combat import protections_of

    eng = _fresh_engine()
    knight = _suspended(eng, "Riftmarked Knight", 1)
    eng.rules.remove_suspend_time_counter(knight)
    assert eng.rules.put_triggers_on_stack() == 1
    eng.rules.resolve_top_of_stack()
    tokens = [o for o in eng.state.battlefield if o.controller_id == "p1" and o.is_token]
    assert len(tokens) == 1
    token = tokens[0]
    assert (token.power, token.toughness) == (2, 2)
    assert "W" in protections_of(token.card)
    assert "flanking" in [k.lower() for k in token.card.keywords]
    assert "haste" in [k.lower() for k in token.card.keywords]


# --- "Activate only if you've cast a noncreature spell this turn" ---------------


def test_seeker_of_insight_activation_needs_a_noncreature_spell_cast_this_turn():
    db = CardDatabase(DEFAULT_DB_PATH)
    for name in ("Seeker of Insight", "Tapestry of the Ages"):
        assert parse_oracle(db.get_card(name)).coverage != UNMODELED, name
    eng = _fresh_engine()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    seeker = _bound(eng, "Seeker of Insight", Zone.BATTLEFIELD)
    ability = seeker.activated_abilities[-1]
    assert eng.can_activate(p1, seeker, ability) is False
    eng.state.noncreature_spells_cast_this_turn[p1.id] = 1
    assert eng.can_activate(p1, seeker, ability) is True
