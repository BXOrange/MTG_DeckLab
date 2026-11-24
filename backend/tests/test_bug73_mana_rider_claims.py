"""BUG-73 (RULE 605.1a, 605.3a, 602.5d): a sentence after a mana ability's Add clause is claimed only when the engine
carries it out.

The segmenter used to claim any ``<cost>: Add <mana>. <anything>`` line whole, so a rider the mana-ability builder never
reads (a delayed draw, a life gain, "Activate only as a sorcery") was dropped silently on a MODELED card. The riders
below are the ones `parser/oracle/mana_riders.py` re-claims, each checked against the real `ManaAbility` the engine
builds and, where it changes play, against `tap_for_mana`.
"""
import re

import pytest

from mtg_analyzer.game.mana_abilities import parse_mana_abilities
from mtg_analyzer.parser.oracle import MODELED, PARSER_VERSION, parse_oracle
from mtg_analyzer.parser.oracle.mana_riders import is_executed_rider, mana_riders_executed
from mtg_analyzer.parser.oracle.segmenter import segment_line
from mtg_analyzer.parser.oracle.spec import ParserProvenance
from mtg_analyzer.config import DB_PATH
from mtg_analyzer.services.card_database import CardDatabase
from tests.support.deck_batch import card, game

ADD = "{t}: add {g}."
_PROVENANCE = ParserProvenance(version=PARSER_VERSION, source="test")


def _claimed(line: str) -> bool:
    return segment_line(line, allow_spell_effect=True, provenance=_PROVENANCE).claimed


def _real(name):
    return CardDatabase(DB_PATH).get_card(name)


# --- the unknown rider fails closed ------------------------------------------------------------------------------


def test_an_unknown_sentence_after_the_add_clause_leaves_the_line_unclaimed():
    assert not _claimed("{4}, {t}: add {w}{u}{b}{r}{g}. zorble the frobnicator.")
    assert _claimed("{4}, {t}: add {w}{u}{b}{r}{g}.")


@pytest.mark.parametrize("rider", [
    "draw a card.",                                     # Chromatic Sphere: the builder has no draw
    "you gain 1 life.",                                 # Pristine Talisman
    "draw a card at the beginning of the next turn's upkeep.",   # Astrolabe
    "if you control another mutant, you gain 1 life.",  # Black Tom Cassidy
    "when you next cast an instant or sorcery spell this turn, copy that spell.",   # Ether
    "activate only as a sorcery.",                      # a real timing limit with no flag on the cost
    "if there are no depletion counters on ~, sacrifice it.",
    "spend this mana only to cast a spell with devoid.",           # outside the restriction vocabulary
    "spend this mana only to cast a legendary spell, and that spell can't be countered.",   # half is unread
    "if you control a creature with power 4 or greater, add {g}{g} instead.",
])
def test_riders_the_builder_does_not_read_are_not_claimed(rider):
    assert not is_executed_rider(rider)
    assert not _claimed(f"{ADD} {rider}")


@pytest.mark.parametrize("name", [
    "Codie, Vociferous Codex", "Brass Infiniscope", "Astrolabe", "Barbed Sextant", "Avid Reclaimer",
    "Black Tom Cassidy", "Ether", "Foraging Wickermaw", "Chromatic Sphere", "Pristine Talisman",
])
def test_cards_whose_rider_the_builder_never_reads_are_no_longer_modeled(name):
    card_ = _real(name)
    if card_ is None:
        pytest.skip(f"{name} is not in this cache")
    assert parse_oracle(card_).coverage != MODELED


@pytest.mark.parametrize("name", ["Chocobo Camp", "Exploding Barrel", "Chandra, Bold Pyromancer"])
def test_cards_whose_rider_is_executed_or_not_a_mana_line_stay_modeled(name):
    # Chocobo Camp / Exploding Barrel carry a rider the builder reads (a next-cast counter, a source counter);
    # Chandra's "+1: Add {R}{R}. ... target player" is a loyalty ability (RULE 605.1a: it targets), not a mana line.
    assert parse_oracle(_real(name)).coverage == MODELED


# --- the executed riders stay claimed, and the engine applies them -----------------------------------------------


@pytest.mark.parametrize("rider", [
    "~ deals 1 damage to you.",
    "activate only once each turn.",
    "activate only during your turn.",
    "activate only during your turn and only once each turn.",
    "activate only during your turn, before attackers are declared.",
    "spend this mana only to cast a creature spell.",
    "spend this mana only to cast artifact spells or activate abilities of artifacts.",
    "spend this mana only on costs that contain {x}.",
    "this mana can't be spent to cast a nonartifact spell.",
    "put a depletion counter on ~.",
    "you get a poison counter.",
    "you get two rad counters.",
    "~ doesn't untap during your next untap step.",
    "if that mana is spent to cast a creature spell, that creature enters with an additional +1/+1 counter on it.",
    "when you next cast a creature spell this turn, that creature enters with 2 additional +1/+1 counters on it.",
])
def test_riders_the_engine_executes_are_claimed(rider):
    assert is_executed_rider(rider)
    assert _claimed(f"{ADD} {rider}")


def test_activate_only_if_is_claimed_only_for_a_condition_the_vocabulary_reads():
    assert mana_riders_executed("add {b}. activate only if you control a swamp.")
    assert not mana_riders_executed("add {b}. activate only if the moon is full.")


def test_the_x_scaled_life_rider_is_still_claimed_whole():
    assert _claimed("{t}, sacrifice x goats: add x mana of any one color. you gain x life.")


def _tap(name, **kw):
    eng = game()
    land = card(eng, name)
    eng.tap_for_mana(eng.state.player_by_id("p1"), land, **kw)
    return eng, land


def test_a_pain_land_rider_damages_its_controller_when_tapped_for_that_mana():
    eng, _ = _tap("Adarkar Wastes", ability_index=1)
    assert eng.state.player_by_id("p1").life == 19
    eng, _ = _tap("Adarkar Wastes", ability_index=0)  # the {C} line has no rider
    assert eng.state.player_by_id("p1").life == 20
    eng, _ = _tap("Talisman of Conviction", ability_index=1)  # "This artifact deals 1 damage to you."
    assert eng.state.player_by_id("p1").life == 19


def test_a_karoo_style_land_does_not_untap_during_its_next_untap_step():
    # RULE 611.2a / 502.3: the rider is a one-shot effect of the ability (Cinder Marsh).
    _, plain = _tap("Cinder Marsh", ability_index=0)
    assert plain.tapped and not plain.skip_next_untap
    eng, land = _tap("Cinder Marsh", ability_index=1)
    assert land.tapped and land.skip_next_untap
    eng._step_untap()  # the flagged land stays tapped this once, then untaps
    assert land.tapped and not land.skip_next_untap
    eng._step_untap()
    assert not land.tapped


def test_a_counter_rider_is_put_on_the_source_as_the_ability_resolves():
    eng, land = _tap("Land Cap")
    assert land.counters.get("depletion") == 1
    eng, bayou = _tap("Exploding Barrel")
    assert bayou.counters.get("pressure") == 1


def test_a_poison_counter_rider_is_given_to_the_controller():
    eng, _ = _tap("Noxious Bayou")
    assert eng.state.player_by_id("p1").poison == 1


def test_an_only_once_each_turn_limit_is_enforced_on_the_mana_ability():
    eng = game()
    devotee = card(eng, "Abzan Devotee")
    player = eng.state.player_by_id("p1")
    player.mana_pool.add_many({"C": 2})
    eng.tap_for_mana(player, devotee)
    with pytest.raises(ValueError, match="already been activated"):
        eng.tap_for_mana(player, devotee)


def test_an_only_if_rider_gates_the_ability_on_the_board():
    eng = game()
    field = card(eng, "Tainted Field")
    player = eng.state.player_by_id("p1")
    with pytest.raises(ValueError):
        eng.tap_for_mana(player, field, ability_index=1)
    card(eng, "Swamp")
    eng.tap_for_mana(player, field, ability_index=1)
    assert field.tapped


def test_a_spend_restriction_rider_tags_the_produced_mana():
    ability = parse_mana_abilities(_real("Ancient Ziggurat"))[0]
    assert ability.restriction == {"kind": "creature_spell", "allow_ability": False}
    eng, _ = _tap("Ancient Ziggurat")
    assert [lot["restriction"]["kind"] for lot in eng.state.player_by_id("p1").mana_pool.restricted] == ["creature_spell"]


def test_a_next_cast_rider_arms_for_the_matching_spell():
    ability = parse_mana_abilities(_real("Chocobo Camp"))[0]
    assert ability.next_cast_rider == {"kind": "entry_counters", "count": 1, "creature": True, "subtype": "Bird"}


def test_a_talisman_and_the_x_life_rider_are_read():
    assert any(a.self_damage == 1 for a in parse_mana_abilities(_real("Talisman of Conviction")))
    assert any(a.gain_life_x for a in parse_mana_abilities(_real("Springjack Pasture")))


def test_an_only_if_rider_naming_its_own_source_gates_the_ability():
    # "Activate only if this land entered this turn." (Mirrex) -- the builder reads "this land" as the normalizer's "~".
    assert any(a.cost.activation_condition for a in parse_mana_abilities(_real("Mirrex")))
    assert any(a.cost.activation_condition for a in parse_mana_abilities(_real("Flywheel Racer")))


# --- parity: every claimed rider is in the ManaAbility the engine builds (full cache) ------------------------------


def _carried_by(abilities, sentence):
    """Whether some `ManaAbility` of the card carries ``sentence``'s effect -- the field the engine applies."""
    from mtg_analyzer.parser.oracle import mana_riders as R

    text = sentence.strip()
    if text.lower().startswith("spend this mana only") or R._CANT_CAST_NONARTIFACT_RE.fullmatch(text):
        return any(a.restriction for a in abilities)
    if R._SELF_DAMAGE_SENTENCE_RE.fullmatch(text):
        return any(a.self_damage for a in abilities)
    if R._RAD_SENTENCE_RE.fullmatch(text):
        return any(a.self_rad_counters for a in abilities)
    if R.SOURCE_COUNTER_RIDER_RE.fullmatch(text):
        return any(a.source_counters for a in abilities)
    if R.PLAYER_COUNTER_RIDER_RE.fullmatch(text):
        return any(a.player_counters for a in abilities)
    if R.SKIP_NEXT_UNTAP_RIDER_RE.fullmatch(text):
        return any(a.skips_next_untap for a in abilities)
    if R._MANA_ACTIVATION_LIMIT_RE.fullmatch(text) or R._ACTIVATE_ONLY_IF_RE.fullmatch(text):
        return any(
            a.cost.once_per_turn or a.cost.only_during_your_turn or a.cost.only_before_attackers
            or a.cost.activation_condition for a in abilities
        )
    if re.fullmatch(r"you gain x life\.", text, re.IGNORECASE):
        return any(a.gain_life_x for a in abilities)  # the announced-X rider (Springjack Pasture)
    return any(a.spend_rider or a.next_cast_rider for a in abilities)


@pytest.mark.full_cache
def test_every_claimed_mana_rider_is_carried_by_the_engines_mana_ability(full_cache_parse):
    from mtg_analyzer.game.card_registry import is_registered
    from mtg_analyzer.parser.oracle.mana_riders import split_sentences
    from mtg_analyzer.parser.oracle.normalize import normalize
    from mtg_analyzer.parser.oracle.segmenter.activation_clauses import LOYALTY_LINE_RE, MANA_EFFECT_RE

    missing = []
    for card_ in full_cache_parse.cards:
        if is_registered(card_.name) or parse_oracle(card_).coverage != MODELED:
            continue
        riders = []
        for line in normalize(card_.oracle_text or "", card_.name).split("\n"):
            cost, sep, effect = line.partition(":")
            # A loyalty ability (+1: Add {R}{R}. ...) is an ordinary stack ability, not a mana line (RULE 605.1a).
            if sep and '"' not in line and MANA_EFFECT_RE.match(effect.strip()) and not LOYALTY_LINE_RE.match(line):
                riders += split_sentences(effect)[1:]
        if not riders:
            continue
        abilities = parse_mana_abilities(card_)
        missing += [(card_.name, r) for r in riders if not _carried_by(abilities, r)]
    assert not missing, missing[:40]

