"""PAR-102 — a pump that also grants a quoted ability in one sentence.

"[Until end of turn, ]target creature gets +2/+0 and gains [<keywords> and ]"<quoted ability>"[ until end
of turn]." parses to a `pump` (P/T + flag keywords, which picks the recipient) followed by a `grant_until`
over the quoted ability that replays the same recipient (`previous_subject`; a group subject re-states its
selector and **locks** it, RULE 611.2c; a self subject grants its own source).

Reference: parser/oracle/catalogue/handlers.py (`_pump_and_quoted_grant`), game/effects/counters_tokens.py
(`GrantUntilEffect.lock_group`).
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game import continuous
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body

ABNORMAL = (
    'Until end of turn, target creature gets +2/+0 and gains "When this creature dies, return it to the '
    "battlefield tapped under its owner's control.\""
)
ROOT = 'Until end of turn, creatures you control get +2/+2 and gain menace and "Whenever this creature attacks, you gain 1 life."'


def _card(name, type_line="Creature — Bear", oracle_text="", **kw):
    kw.setdefault("converted_mana_cost", 2)
    creature = "Creature" in type_line
    kw.setdefault("power", 2 if creature else None)
    kw.setdefault("toughness", 2 if creature else None)
    return Card(id=name, name=name, type_line=type_line, oracle_text=oracle_text, is_creature=creature,
                is_instant="Instant" in type_line, **kw)


def _engine():
    eng = GameEngine.new_game([("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    return eng


def _bf(eng, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.controller_id = controller
    bind_from_catalogue(obj)
    eng.state.add_to_battlefield(obj)
    return obj


def _cast(eng, text, targets=None):
    p1 = eng.state.player_by_id("p1")
    spell = GameObject(_card("Trick", "Instant", text, converted_mana_cost=0), owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(spell)
    p1.add_to_zone(spell, Zone.HAND)
    eng.cast_spell(p1, spell, targets=targets or [])
    eng.resolve_until_stable()
    return spell


# --- parse ---------------------------------------------------------------------------------------


def test_targeted_form_emits_pump_then_a_previous_subject_grant():
    from mtg_analyzer.parser.oracle.normalize import normalize

    specs = parse_effect_body(normalize(ABNORMAL))
    assert [s.type for s in specs] == ["pump", "grant_until"]
    assert specs[0].params == {"power": 2, "toughness": 0, "target_kind": "creature"}
    grant = specs[1].params
    assert grant["previous_subject"] is True and grant["duration"] == "end_of_turn"
    assert grant["static"]["type"] == "grant_triggered_ability"


def test_group_form_locks_its_selector_and_keeps_the_keyword_on_the_pump():
    from mtg_analyzer.parser.oracle.normalize import normalize

    pump, grant = parse_effect_body(normalize(ROOT))
    assert pump.params["keywords"] == ["menace"] and "selector" in pump.params
    assert grant.params["lock_group"] is True and "previous_subject" not in grant.params


@pytest.mark.parametrize("text", [
    # No duration at all: a permanent grant is a different card.
    'Target creature gets +2/+0 and gains "When this creature dies, draw a card."',
    # An attached subject is a standing static, not a resolving effect.
    'Enchanted creature gets +2/+2 and has "Whenever this creature attacks, you gain 1 life."',
    # An unparseable quoted ability stays unclaimed rather than being dropped.
    'Until end of turn, target creature gets +2/+0 and gains "When this creature dies, frobnicate the quux."',
])
def test_adversarial_shapes_are_not_claimed(text):
    from mtg_analyzer.parser.oracle.normalize import normalize

    specs = parse_effect_body(normalize(text))
    assert "grant_until" not in [s.type for s in (specs or [])]


@pytest.mark.parametrize("name", [
    "Abnormal Endurance", "Supernatural Stamina", "Hunter's Prowess", "Dreadmaw's Ire", "Tower Above",
    "Full Steam Ahead", "Greater Stone Spirit", "Dead Before Sunrise", "Root Manipulation",
])
def test_real_cards_are_modeled(name):
    from mtg_analyzer.services.card_database import DEFAULT_DB_PATH, CardDatabase

    if not DEFAULT_DB_PATH.exists():
        pytest.skip("card cache not present in this environment")
    card = CardDatabase(DEFAULT_DB_PATH).get_card(name)
    if card is None:
        pytest.skip(f"{name!r} not in the local card cache")
    assert parse_oracle(card).modeled


# --- execute -------------------------------------------------------------------------------------


def test_targeted_pump_and_dies_trigger_come_back_the_creature_tapped():
    eng = _engine()
    bear = _bf(eng, _card("Bear"))
    _cast(eng, ABNORMAL, [bear])
    assert (bear.power, bear.toughness) == (4, 2)
    foe = _bf(eng, _card("Zapper", "Creature — Wizard"), controller="p2")
    eng.rules.deal_damage(bear, 5, source=foe)
    eng.resolve_until_stable()
    back = [o for o in eng.state.battlefield if o.card.name == "Bear"]
    assert len(back) == 1 and back[0].tapped is True


def test_group_grant_is_fixed_when_the_spell_resolves():
    eng = _engine()
    bear = _bf(eng, _card("Bear"))
    _cast(eng, ROOT)
    assert bear.power == 4 and "menace" in bear.granted_keywords
    late = _bf(eng, _card("Late Bear"))
    eng.recompute_continuous_effects()
    # RULE 611.2c: a creature that arrives afterwards is in neither the pump nor the grant.
    assert late.power == 2 and "menace" not in late.granted_keywords
    [floating] = eng.state.floating_statics
    assert {o.instance_id for o in continuous.affected_objects(eng.state, floating)} == {bear.instance_id}


# --- the sibling rows of the same ticket ----------------------------------------------------------


def test_a_granted_toxic_poisons_on_combat_damage_only_this_turn():
    eng = _engine()
    bear = _bf(eng, _card("Bear"))
    _cast(eng, "Until end of turn, target creature gets +1/+3 and gains flying and toxic 1.", [bear])
    assert (bear.power, bear.toughness) == (3, 5) and "flying" in bear.granted_keywords
    p2 = eng.state.player_by_id("p2")
    eng.rules.deal_damage(p2, 3, source=bear, combat=True)
    assert p2.life == 17 and p2.poison == 1
    eng.rules.deal_damage(p2, 3, source=bear, combat=False)
    assert p2.poison == 1  # RULE 702.164c: combat damage only


def test_all_creature_types_is_granted_to_the_chosen_set_only():
    eng = _engine()
    bear = _bf(eng, _card("Bear"))
    _cast(eng, "Until end of turn, creatures you control get +2/+0 and gain all creature types.")
    assert bear.power == 4 and continuous.has_subtype(bear, "Elf")
    late = _bf(eng, _card("Late Bear"))
    eng.recompute_continuous_effects()
    assert not continuous.has_subtype(late, "Elf")


WHILE_TAPPED = "Target Elf creature gets +2/+2 and has trample for as long as ~ remains tapped."


def test_while_tapped_grant_parses_and_ends_when_the_source_untaps():
    from mtg_analyzer.parser.oracle.normalize import normalize

    [spec] = parse_effect_body(normalize(WHILE_TAPPED))
    assert spec.type == "grant_until" and spec.params["creature_filter"] == {"subtype": "Elf"}
    assert spec.params["duration"] == "for_as_long_as" and spec.params["condition"] == {"kind": "source_tapped"}

    eng = _engine()
    courier = _bf(eng, _card("Courier", "Creature — Elf", f"{{T}}: {WHILE_TAPPED}"))
    courier.summoning_sick = False
    elf = _bf(eng, _card("Elf", "Creature — Elf"))
    bear = _bf(eng, _card("Bear"))
    p1 = eng.state.player_by_id("p1")
    eng.activate_ability(p1, courier, 0, target_groups=[[elf]])
    eng.resolve_until_stable()
    assert courier.tapped
    assert (elf.power, elf.toughness) == (4, 4) and "trample" in elf.granted_keywords
    assert bear.power == 2  # only the chosen creature
    courier.tapped = False  # RULE 611.2b: the effect ends for good once the source is untapped
    eng.recompute_continuous_effects()
    assert (elf.power, elf.toughness) == (2, 2)
    courier.tapped = True
    eng.recompute_continuous_effects()
    assert (elf.power, elf.toughness) == (2, 2)  # …and doesn't come back when it taps again


# --- "gains your choice of …" ---------------------------------------------------------------------

CHOICE = "Target creature gets +1/+1 and gains your choice of deathtouch or lifelink until end of turn."


def test_keyword_choice_parses_to_one_pump_with_options_and_rejects_non_flags():
    from mtg_analyzer.parser.oracle.normalize import normalize

    [spec] = parse_effect_body(normalize(CHOICE))
    assert spec.type == "pump" and spec.params["keyword_options"] == ["deathtouch", "lifelink"]
    assert (spec.params["power"], spec.params["toughness"]) == (1, 1)
    # A quality option can't be a flag: the clause stays unclaimed instead of dropping a choice.
    quality = "target creature gains your choice of flying or protection from red until end of turn."
    assert not any(s.type == "pump" for s in (parse_effect_body(normalize(quality)) or []))
    # No duration → a permanent grant, which is another card.
    permanent = "target creature gains your choice of flying or haste."
    assert not parse_effect_body(normalize(permanent))


@pytest.mark.parametrize("answer, kept, dropped", [("1", "lifelink", "deathtouch"), (None, "deathtouch", "lifelink")])
def test_the_controller_picks_one_keyword_at_resolution(answer, kept, dropped):
    eng = _engine()
    bear = _bf(eng, _card("Bear"))
    _cast(eng, CHOICE, [bear])
    assert eng.state.pending_choice and eng.state.pending_choice["kind"] == "keyword_choice"
    assert [o["label"] for o in eng.state.pending_choice["options"]] == ["deathtouch", "lifelink"]
    eng.resolve_pending_choice(answer)
    assert (bear.power, bear.toughness) == (3, 3)
    assert kept in bear.granted_keywords and dropped not in bear.granted_keywords


def test_a_self_ability_asks_too():
    eng = _engine()
    avenger = _bf(eng, _card("Avenger", "Creature — Soldier", "{1}: Until end of turn, ~ gets -1/-1 and gains your choice of flying or haste."))
    avenger.summoning_sick = False
    eng.state.player_by_id("p1").mana_pool.add_many({"C": 1})
    eng.activate_ability(eng.state.player_by_id("p1"), avenger, 0)
    eng.resolve_until_stable()
    assert eng.state.pending_choice["kind"] == "keyword_choice"
    eng.resolve_pending_choice("1")
    assert "haste" in avenger.granted_keywords and avenger.power == 1


# --- "When that creature dies this turn, …" ---------------------------------------------------------

DIES = "Target creature gets +2/+0 until end of turn. When that creature dies this turn, you gain 3 life."


def test_that_creature_dies_this_turn_needs_a_preceding_clause_that_chose_it():
    from mtg_analyzer.parser.oracle.normalize import normalize

    specs = parse_effect_body(normalize(DIES))
    assert [s.type for s in specs] == ["pump", "create_turn_trigger"]
    trigger = specs[1].params
    assert trigger["previous_subject"] is True and trigger["trigger"]["event"] == "DIES"
    # With nothing before it, "that creature" names nobody — the clause must stay unclaimed.
    assert not parse_effect_body(normalize("When that creature dies this turn, you gain 3 life."))


def test_only_the_chosen_creatures_death_triggers_it():
    eng = _engine()
    chosen = _bf(eng, _card("Chosen"))
    other = _bf(eng, _card("Other"))
    foe = _bf(eng, _card("Zapper", "Creature — Wizard"), controller="p2")
    p1 = eng.state.player_by_id("p1")
    _cast(eng, DIES, [chosen])
    eng.rules.deal_damage(other, 9, source=foe)
    eng.resolve_until_stable()
    assert p1.life == 20  # an unrelated death gains nothing
    eng.rules.deal_damage(chosen, 9, source=foe)
    eng.resolve_until_stable()
    assert p1.life == 23
