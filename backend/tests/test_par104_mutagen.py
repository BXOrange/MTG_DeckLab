"""PAR-104: the TMNT Mutagen token ("create a Mutagen token") and the clauses the cards around it needed —
the token itself (`data/tokens.json` + `handlers._NAMED_TOKEN_WORDS`), a comma list of card types in a cast trigger
("an artifact, instant, or sorcery spell"), the Donatello replacement ("those tokens plus a Mutagen token are created
instead"), "a Mutagen token for each +1/+1 counter on it" under a leaving trigger (The Ooze), and the shared target pool
"artifact, enchantment, or creature with flying / power 4 or greater" (Mutant Chain Reaction and 12 more).
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.game.targeting import TargetSpec, legal_targets
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.replacements import replacement_clause_specs as replacement_specs
from mtg_analyzer.parser.oracle.catalogue.subgrammars import resolve_target_kind
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.services.token_database import default_token_database


def _card(name, type_line="Creature — Bear", oracle="", power=2, toughness=2, **flags):
    creature = "Creature" in type_line
    return Card(id=name, name=name, type_line=type_line, oracle_text=oracle, is_creature=creature,
                is_land="Land" in type_line, is_sorcery="Sorcery" in type_line, is_instant="Instant" in type_line,
                power=power if creature else None,
                toughness=toughness if creature else None, converted_mana_cost=0, **flags)


def _engine():
    return GameEngine.new_game([("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0)


def _put(eng, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, controller_id=controller, zone=Zone.BATTLEFIELD)
    bind_from_catalogue(obj)
    eng.state.add_to_battlefield(obj)
    return obj


def _mutagens(eng, controller="p1"):
    return [o for o in eng.state.battlefield if o.name == "Mutagen" and o.controller_id == controller]


# --- the token --------------------------------------------------------------


def test_the_curated_token_has_its_real_ability():
    token = default_token_database().get_token("Mutagen")
    assert token is not None
    assert "Put a +1/+1 counter on target creature" in token.oracle_text
    assert "Activate only as a sorcery" in token.oracle_text


def test_creating_a_mutagen_token_gives_a_working_artifact():
    eng = _engine()
    maker = "When this creature enters, create a Mutagen token."
    assert parse_oracle(_card("Crustacean Commando", "Creature — Crab Mutant Soldier", maker)).modeled
    bear = _put(eng, _card("Bear"))
    _put(eng, _card("Crustacean Commando", "Creature — Crab Mutant Soldier", maker))
    # an ETB put onto the battlefield directly does not trigger; fire the effect the way a resolving ETB does
    from mtg_analyzer.game.effects.core import EffectRegistry
    from mtg_analyzer.game.effects.core import GameContext
    effect = EffectRegistry.create("create_token", {"count": 1, "token_name": "Mutagen"})
    effect.source = bear
    effect.apply(GameContext(eng.state, eng.rules), [])
    token = _mutagens(eng)[0]
    assert token.is_token and token.card.is_artifact
    p1 = eng.state.player_by_id("p1")
    p1.mana_pool.add_many({"G": 1})
    token.tapped = False
    eng.state.current_step = "combat_damage"
    assert not eng.can_activate(p1, token, token.activated_abilities[0])   # "Activate only as a sorcery"
    eng.state.current_step = "main1"
    eng.activate_ability(p1, token, 0, targets=[bear])
    eng.resolve_until_stable()
    assert bear.counters.get("+1/+1") == 1
    assert token not in eng.state.battlefield  # sacrificed as a cost


# --- cast trigger over a comma list of types -------------------------------

APRIL = "Whenever a player casts an artifact, instant, or sorcery spell, you create a Mutagen token."


def test_the_comma_list_cast_trigger_is_modeled_with_its_type_filter():
    result = parse_oracle(_card("April O'Neil, Human Element", "Legendary Creature — Human", APRIL))
    assert result.modeled, result.unclaimed
    trigger = next(s.trigger for s in result.specs if s.ability_kind == "triggered")
    assert trigger["event"] == "SPELL_CAST"
    assert trigger["spell_filter"] == {"card_type_any": ["artifact", "instant", "sorcery"]}


@pytest.mark.parametrize("text", [
    "Whenever a player casts an artifact, instant, or frobnicator spell, you create a Mutagen token.",
])
def test_an_unknown_word_in_the_type_list_is_not_claimed(text):
    assert not parse_oracle(_card("April", "Legendary Creature — Human", text)).modeled


# --- Donatello's replacement ----------------------------------------------


def test_donatello_adds_a_mutagen_to_every_token_creation():
    from mtg_analyzer.parser.oracle.spec import EffectSpec
    clause = "if 1 or more tokens would be created under your control, those tokens plus a mutagen token are created instead"
    assert replacement_specs(clause) == [EffectSpec("additional_named_token", {"token_name": "Mutagen"})]
    assert replacement_specs(clause.replace("mutagen", "frobnicator")) is None
    donatello = _card("Donatello, the Brains", "Legendary Creature — Mutant Ninja Turtle",
                      "If one or more tokens would be created under your control, those tokens plus a Mutagen token "
                      "are created instead.")
    assert parse_oracle(donatello).modeled


def test_donatello_executes_for_its_controller_only():
    eng = _engine()
    text = ("If one or more tokens would be created under your control, those tokens plus a Mutagen token "
            "are created instead.")
    donatello = _put(eng, _card("Donatello, the Brains", "Legendary Creature — Mutant Ninja Turtle", text))
    from mtg_analyzer.game.effects.core import EffectRegistry, GameContext
    ctx = GameContext(eng.state, eng.rules)
    for who in ("p1", "p2"):
        maker = _put(eng, _card(f"Maker {who}"), controller=who)
        effect = EffectRegistry.create("create_token", {"count": 1, "token_name": "Clue"})
        effect.source = maker
        effect.apply(ctx, [])
    assert len(_mutagens(eng, "p1")) == 1   # Donatello's controller got the extra token
    assert len(_mutagens(eng, "p2")) == 0
    assert donatello in eng.state.battlefield


# --- The Ooze: a token for each +1/+1 counter on the leaving creature -------

OOZE = ("Whenever a creature you control with a +1/+1 counter on it leaves the battlefield, "
        "create a Mutagen token for each +1/+1 counter on it.")


def test_the_ooze_is_modeled():
    assert parse_oracle(_card("The Ooze", "Legendary Creature — Ooze", OOZE)).modeled


def test_the_leaving_creatures_counters_set_the_token_count():
    eng = _engine()
    _put(eng, _card("The Ooze", "Legendary Creature — Ooze", OOZE))
    grower = _put(eng, _card("Grower"))
    plain = _put(eng, _card("Plain"))
    eng.rules.add_counters(grower, 3, "+1/+1")
    eng.rules.put_into_graveyard(grower)
    eng.resolve_until_stable()
    assert len(_mutagens(eng)) == 3
    eng.rules.put_into_graveyard(plain)   # no counter: not the printed trigger
    eng.resolve_until_stable()
    assert len(_mutagens(eng)) == 3


def test_a_per_counter_count_is_only_claimed_under_a_group_trigger():
    # "it" with no firing creature to read would count nothing
    assert not parse_oracle(_card("Spell", "Instant", "Create a Mutagen token for each +1/+1 counter on it.")).modeled


# --- "target artifact, enchantment, or creature with flying" ----------------


def test_the_three_type_pool_is_the_dedicated_kind_in_any_order():
    for phrase in ("target artifact, enchantment, or creature", "target artifact, creature, or enchantment",
                   "target creature, artifact, or enchantment", "target enchantment, creature, or artifact"):
        assert resolve_target_kind(phrase) == "artifact_creature_or_enchantment", phrase
    # a different union keeps its own, broader reading
    assert resolve_target_kind("target artifact, enchantment, or land") == "permanent"


MUTANT = "Destroy up to one target artifact, enchantment, or creature with flying. Create a Mutagen token."


@pytest.mark.parametrize("name, text", [
    ("Mutant Chain Reaction", MUTANT),
    ("Return to the Earth", "Destroy target artifact, enchantment, or creature with flying."),
    ("Exorcise", "Exile target artifact, enchantment, or creature with power 4 or greater."),
])
def test_the_cards_are_modeled(name, text):
    assert parse_oracle(_card(name, "Sorcery", text)).modeled


def test_the_quality_narrows_only_the_creatures_of_the_pool():
    eng = _engine()
    flier = _put(eng, _card("Flier", "Creature — Bird", keywords=["Flying"]))
    walker = _put(eng, _card("Walker"))
    rock = _put(eng, _card("Rock", "Artifact"))
    aura = _put(eng, _card("Aura", "Enchantment"))
    land = _put(eng, _card("Forest", "Basic Land — Forest"))
    p2 = _put(eng, _card("Big Wall", "Creature — Wall", power=0, toughness=8), controller="p2")
    eng.recompute_continuous_effects()
    spec = TargetSpec(kind="artifact_creature_or_enchantment", creature_filter={"keyword": "flying"})
    names = {d["name"] for d in legal_targets(eng.state, "p1", spec)}
    assert names == {"Flier", "Rock", "Aura"}
    assert "Walker" not in names and "Forest" not in names and "Big Wall" not in names
    big = TargetSpec(kind="artifact_creature_or_enchantment", creature_filter={"min_power": 4})
    assert {d["name"] for d in legal_targets(eng.state, "p1", big)} == {"Rock", "Aura"}
    assert flier and walker and rock and aura and land and p2  # silence unused


def test_the_opponent_scoped_three_type_pool_excludes_your_own_permanents():
    eng = _engine()
    _put(eng, _card("My Bear"))
    _put(eng, _card("My Rock", "Artifact"))
    _put(eng, _card("Their Aura", "Enchantment"), controller="p2")
    _put(eng, _card("Their Bear"), controller="p2")
    _put(eng, _card("Their Forest", "Basic Land — Forest"), controller="p2")
    kind = resolve_target_kind("target artifact, creature, or enchantment an opponent controls")
    assert kind == "artifact_creature_or_enchantment_you_dont_control"
    names = {d["name"] for d in legal_targets(eng.state, "p1", TargetSpec(kind=kind))}
    assert names == {"Their Aura", "Their Bear"}


def test_the_library_put_and_exile_until_leaves_rows_still_claim_the_three_type_phrase():
    assert parse_oracle(_card("Banishing Stroke", "Sorcery",
                              "Put target artifact, creature, or enchantment on the bottom of its owner's library.")).modeled


# --- Case of the Pilfered Proof: a Solved-gated replacement, and a two-event subject trigger --------------

CASE = (
    "Whenever a Detective you control enters or is turned face up, put a +1/+1 counter on it.\n"
    "To solve — You control three or more Detectives. (If unsolved, solve at the beginning of your end step.)\n"
    "Solved — If one or more tokens would be created under your control, those tokens plus a Clue token are created "
    "instead. (It's an artifact with \"{2}, Sacrifice this token: Draw a card.\")"
)


def test_a_two_event_group_trigger_binds():
    # "enters or is turned face up" names two events; binding it used to hash the list (a TypeError at deck load)
    eng = _engine()
    case = _put(eng, _card("Case of the Pilfered Proof", "Enchantment — Case", CASE))
    assert len(case.triggered_abilities) >= 2


def test_the_solved_replacement_adds_its_clue_only_once_solved():
    from mtg_analyzer.game.effects.core import EffectRegistry, GameContext
    results = {}
    for solved in (False, True):
        eng = _engine()
        case = _put(eng, _card("Case of the Pilfered Proof", "Enchantment — Case", CASE))
        case.is_solved = solved
        maker = _put(eng, _card("Maker"))
        effect = EffectRegistry.create("create_token", {"count": 1, "token_name": "Food"})
        effect.source = maker
        effect.apply(GameContext(eng.state, eng.rules), [])
        results[solved] = sorted(o.name for o in eng.state.battlefield if o.name in ("Clue", "Food"))
    assert results == {False: ["Food"], True: ["Clue", "Food"]}
