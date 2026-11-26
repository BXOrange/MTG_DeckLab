"""PAR-285: the graveyard pick's quality and mana-value-bound slots (RULE 115.1, 202.3, 205.4a, 105.2c).

"target multicolored card", "target blue instant card", "target noncreature artifact card with mana value 1 or less",
"legendary or Rat card", and the bounds "mana value X" / "less than ~'s power" / "less than or equal to ~'s power" /
"mana value 1". Tests run parser -> binder -> `legal_targets` -> effect on the real cards' text, with matching and
non-matching candidates; each slot fails when its wiring (parser key, `ExileEffect.exact_mana_value`, the strict
power sentinel, the quality filter) is removed."""

from __future__ import annotations

import pytest

from tests.support.cards import strip_inert_keywords
from mtg_analyzer.config import DB_PATH
from mtg_analyzer.game.binding.core import build_effects
from mtg_analyzer.game.effects.core import GameContext
from mtg_analyzer.game.targeting import legal_targets
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import Zone
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.services.card_database import CardDatabase
from tests.test_mec118_opponent_choice import _engine, _put

#: Newly MODELED by this slot (full-pool spec diff vs v984).
NEWLY_COVERED = [
    "Abiding Grace", "Narset, Enlightened Exile", "Nashi, Moon's Legacy", "Nucklavee",
    "Obscura Charm", "Reborn Hope", "Salvaging Station", "Scrivener", "Sequence Engine", "The Mirari Conjecture",
    "Toshiro Umezawa",
]
PICK_TYPES = ("exile", "return_from_graveyard", "grant_flashback_to_target")


def _real(name: str):
    card = CardDatabase(DB_PATH).get_card(name)
    if card is None:
        pytest.skip("card cache not available")
    return strip_inert_keywords(card)  # BUG-75: Prototype has no engine behaviour; the rest of the text is under test


def _picks(name: str):
    result = parse_oracle(_real(name))
    assert result.modeled is True, name
    return [e for ab in result.specs for e in (ab.effects or []) if e.type in PICK_TYPES]


def _gy(name, type_line, cost="", mv=0, **kw) -> Card:
    return Card(id=name, name=name, type_line=type_line, mana_cost_string=cost, converted_mana_cost=mv,
                is_creature="Creature" in type_line, is_instant="Instant" in type_line,
                is_sorcery="Sorcery" in type_line, is_land="Land" in type_line, **kw)


def _offered(eng, effect, who="p1") -> set:
    return {o["instance_id"] for o in legal_targets(eng.state, who, effect.target_spec, source=effect.source)}


@pytest.mark.parametrize("name", NEWLY_COVERED)
def test_real_cards_are_modeled(name):
    assert parse_oracle(_real(name)).modeled is True


def test_parse_shapes():
    (multi,) = match_clause("return target multicolored card from your graveyard to your hand")
    assert multi.params["creature_filter"] == {"multicolored": True}
    (blue,) = match_clause("return target blue instant card from your graveyard to your hand")
    assert blue.params["target_kind"] == "graveyard_instant" and blue.params["colors"] == ["U"]
    (art,) = match_clause("return target noncreature artifact card with mana value 1 or less from your graveyard to the battlefield")
    assert art.params["target_kind"] == "graveyard_noncreature_artifact" and art.params["max_mana_value"] == 1
    (exact,) = match_clause("return target creature card with mana value 1 from your graveyard to the battlefield")
    assert exact.params["exact_mana_value"] == 1
    (x_exile,) = match_clause("exile target creature card with mana value x from a graveyard")
    assert x_exile.params["exact_mana_value"] == "x"
    (x_le,) = match_clause("exile target creature card with mana value x or less from a graveyard")
    assert x_le.params["max_mana_value"] == "x"
    (lt,) = match_clause("exile target noncreature, nonland card with mana value less than ~'s power from a graveyard")
    assert lt.params["max_mana_value"] == "source_power_less_than"
    (le,) = match_clause("exile target instant or sorcery card with mana value less than or equal to ~'s power from your graveyard")
    assert le.params["max_mana_value"] == "source_power"
    (union,) = match_clause("exile up to 1 target legendary or rat card from your graveyard")
    assert union.params["creature_filter"] == {"any_of": [{"legendary": True}, {"subtype": "Rat"}]}
    (black,) = match_clause("exile up to 1 target black card from your graveyard")
    assert black.params["colors"] == ["B"]
    # adversarial: a stray word is no subtype, a union with a colour is not this slot, "multicolored" takes no union
    assert match_clause("exile up to 1 target legendary or frobnicate card from your graveyard") is None
    assert match_clause("return target multicolored or rat card from your graveyard to your hand") is None
    assert match_clause("return target white or black card from your graveyard to your hand") is None


def test_reborn_hope_offers_only_your_multicolored_cards():
    eng = _engine()
    hope = _put(eng, _real("Reborn Hope"), "p1", Zone.HAND)
    multi = _put(eng, _gy("Gold", "Creature — Elf", "{W}{B}", 2), "p1", Zone.GRAVEYARD)
    _put(eng, _gy("Mono", "Creature — Elf", "{W}", 1), "p1", Zone.GRAVEYARD)
    _put(eng, _gy("Theirs", "Creature — Elf", "{W}{B}", 2), "p2", Zone.GRAVEYARD)
    (effect,) = build_effects(_picks("Reborn Hope"), hope)
    assert _offered(eng, effect) == {multi.instance_id}
    effect.apply(GameContext(eng.state, eng.rules), [multi])
    assert multi.zone == Zone.HAND


def test_salvaging_station_noncreature_artifact_mana_value_bound():
    eng = _engine()
    station = _put(eng, _real("Salvaging Station"), "p1")
    ok = _put(eng, _gy("Cheap Rock", "Artifact", "{1}", 1), "p1", Zone.GRAVEYARD)
    _put(eng, _gy("Dear Rock", "Artifact", "{2}", 2), "p1", Zone.GRAVEYARD)
    _put(eng, _gy("Cheap Golem", "Artifact Creature — Golem", "{1}", 1), "p1", Zone.GRAVEYARD)
    _put(eng, _gy("Cheap Spell", "Instant", "{U}", 1), "p1", Zone.GRAVEYARD)
    (effect,) = build_effects(_picks("Salvaging Station"), station)
    assert _offered(eng, effect) == {ok.instance_id}
    effect.apply(GameContext(eng.state, eng.rules), [ok])
    eng.resolve_until_stable()
    assert ok.zone == Zone.BATTLEFIELD


def test_nucklavee_blue_instant_only():
    eng = _engine()
    nuck = _put(eng, _real("Nucklavee"), "p1")
    blue = _put(eng, _gy("Blue Instant", "Instant", "{U}", 1), "p1", Zone.GRAVEYARD)
    _put(eng, _gy("Red Instant", "Instant", "{R}", 1), "p1", Zone.GRAVEYARD)
    _put(eng, _gy("Blue Sorcery", "Sorcery", "{U}", 1), "p1", Zone.GRAVEYARD)
    _, blue_effect = build_effects(_picks("Nucklavee"), nuck)
    assert _offered(eng, blue_effect) == {blue.instance_id}


def test_narset_strict_power_bound_across_every_graveyard():
    eng = _engine()
    narset = _put(eng, _real("Narset, Enlightened Exile"), "p1")  # printed 3/3
    assert narset.power == 3
    cheap = _put(eng, _gy("Cheap Spell", "Instant", "{1}{U}", 2), "p2", Zone.GRAVEYARD)
    _put(eng, _gy("Equal Spell", "Instant", "{2}{U}", 3), "p1", Zone.GRAVEYARD)
    _put(eng, _gy("Cheap Land", "Land", "", 0), "p1", Zone.GRAVEYARD)
    _put(eng, _gy("Cheap Bear", "Creature — Bear", "{1}{G}", 2), "p1", Zone.GRAVEYARD)
    exile = build_effects(_picks("Narset, Enlightened Exile"), narset)[0]
    assert _offered(eng, exile) == {cheap.instance_id}


def test_arcane_proxy_non_strict_power_bound():
    eng = _engine()
    proxy = _put(eng, _real("Arcane Proxy"), "p1")
    power = proxy.power  # whatever the permanent's power is: the bound reads it live (RULE 208.1)
    at_bound = _put(eng, _gy("Bound Spell", "Instant", "", power), "p1", Zone.GRAVEYARD)
    _put(eng, _gy("Over Spell", "Instant", "", power + 1), "p1", Zone.GRAVEYARD)
    _put(eng, _gy("Creature", "Creature — Bear", "", 0), "p1", Zone.GRAVEYARD)
    exile = build_effects(_picks("Arcane Proxy"), proxy)[0]
    assert _offered(eng, exile) == {at_bound.instance_id}


def test_sequence_engine_exact_x_from_any_graveyard():
    eng = _engine()
    engine_card = _put(eng, _real("Sequence Engine"), "p1")
    engine_card.x_paid = 3
    mine = _put(eng, _gy("Three Drop", "Creature — Bear", "{2}{G}", 3), "p1", Zone.GRAVEYARD)
    theirs = _put(eng, _gy("Their Three", "Creature — Bear", "{2}{G}", 3), "p2", Zone.GRAVEYARD)
    _put(eng, _gy("Two Drop", "Creature — Bear", "{1}{G}", 2), "p1", Zone.GRAVEYARD)
    _put(eng, _gy("Four Drop", "Creature — Bear", "{3}{G}", 4), "p2", Zone.GRAVEYARD)
    _put(eng, _gy("Three Spell", "Instant", "{2}{U}", 3), "p1", Zone.GRAVEYARD)
    exile = build_effects(_picks("Sequence Engine"), engine_card)[0]
    assert _offered(eng, exile) == {mine.instance_id, theirs.instance_id}
    exile.apply(GameContext(eng.state, eng.rules), [theirs])
    assert theirs.zone == Zone.EXILE


def test_nashi_legendary_or_rat_union():
    eng = _engine()
    nashi = _put(eng, _real("Nashi, Moon's Legacy"), "p1")
    legend = _put(eng, _gy("Legend", "Legendary Creature — Elf", "{1}{G}", 2, is_legendary=True), "p1", Zone.GRAVEYARD)
    rat = _put(eng, _gy("Rat", "Creature — Rat", "{B}", 1), "p1", Zone.GRAVEYARD)
    _put(eng, _gy("Elf", "Creature — Elf", "{G}", 1), "p1", Zone.GRAVEYARD)
    _put(eng, _gy("Theirs", "Legendary Creature — Rat", "{B}", 1, is_legendary=True), "p2", Zone.GRAVEYARD)
    exile = build_effects(_picks("Nashi, Moon's Legacy"), nashi)[0]
    assert _offered(eng, exile) == {legend.instance_id, rat.instance_id}


def test_abiding_grace_exact_literal_mana_value():
    eng = _engine()
    grace = _put(eng, _real("Abiding Grace"), "p1")
    one = _put(eng, _gy("One Drop", "Creature — Elf", "{G}", 1), "p1", Zone.GRAVEYARD)
    _put(eng, _gy("Two Drop", "Creature — Elf", "{1}{G}", 2), "p1", Zone.GRAVEYARD)
    _put(eng, _gy("Free", "Creature — Elf", "", 0), "p1", Zone.GRAVEYARD)
    (effect,) = [e for e in build_effects(_returns_in_modes("Abiding Grace"), grace)]
    assert _offered(eng, effect) == {one.instance_id}


def _returns_in_modes(name):
    result = parse_oracle(_real(name))
    assert result.modeled is True
    return [e for ab in result.specs if ab.modes
            for option in ab.modes["options"] for e in option if e.type == "return_from_graveyard"]


def test_toshiro_casts_only_instant_cards():
    eng = _engine()
    toshiro = _put(eng, _real("Toshiro Umezawa"), "p1")
    instant = _put(eng, _gy("Spell", "Instant", "{U}", 1), "p1", Zone.GRAVEYARD)
    _put(eng, _gy("Sorcery", "Sorcery", "{U}", 1), "p1", Zone.GRAVEYARD)
    effect = build_effects(_picks("Toshiro Umezawa"), toshiro)[0]
    assert _offered(eng, effect) == {instant.instance_id}


def test_obscura_charm_multicolored_permanent_with_bound():
    eng = _engine()
    charm = _put(eng, _real("Obscura Charm"), "p1", Zone.HAND)
    good = _put(eng, _gy("Gold Rock", "Artifact", "{W}{B}", 2), "p1", Zone.GRAVEYARD)
    _put(eng, _gy("Dear Gold", "Creature — Elf", "{2}{W}{B}", 4), "p1", Zone.GRAVEYARD)
    _put(eng, _gy("Mono Rock", "Artifact", "{1}", 1), "p1", Zone.GRAVEYARD)
    _put(eng, _gy("Gold Spell", "Instant", "{W}{B}", 2), "p1", Zone.GRAVEYARD)
    (effect,) = build_effects(_returns_in_modes("Obscura Charm"), charm)
    assert _offered(eng, effect) == {good.instance_id}
