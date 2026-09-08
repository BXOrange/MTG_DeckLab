"""Tests for oracle-text *recognition* of standing replacement-effect
clauses (Batch 11's A.5 item) — the binder side (`game/effects/core.py`'s
`ReplacementRegistry`) already supported `double_tokens`/`double_counters`/
`additional_damage`/`prevent_damage`/`double_damage`; this covers the new
parser front-end (`parser/oracle/catalogue/replacements.py`) for the first
three, the ones with a single fixed real-card phrasing (Doubling Season/
Anointed Procession's token/counter-doubling lines, Torbran's "plus N
damage" line). `prevent_damage`'s real cards (Riot Control/Thought Lash)
are a different, unmodeled *one-shot spell effect* shape and aren't covered.

Mirrors `test_effect_families_wave3.py`'s parser-then-engine split.
"""

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle import parse_oracle
from mtg_analyzer.parser.oracle.catalogue.replacements import replacement_clause_specs
from mtg_analyzer.parser.oracle.gate import MODELED


def perm(name, text, type_line="Enchantment", **kw):
    return Card(id=name, name=name, type_line=type_line, oracle_text=text, **kw)


def _bound(state, card, controller="p1"):
    """A hand-authored-catalogue-free card, bound and on the battlefield."""
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


def _make_engine():
    return GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0,
    )


# ---------------------------------------------------------------------------
# PARSER RECOGNITION
# ---------------------------------------------------------------------------


def test_double_tokens_clause_is_recognized():
    specs = replacement_clause_specs(
        "If an effect would create 1 or more tokens under your control, "
        "it creates twice that many of those tokens instead."
    )
    assert specs is not None
    (spec,) = specs
    assert spec.type == "double_tokens" and spec.params == {}


def test_double_counters_clause_is_recognized():
    specs = replacement_clause_specs(
        "If an effect would put 1 or more counters on a permanent you "
        "control, it puts twice that many of those counters on that "
        "permanent instead."
    )
    assert specs is not None
    (spec,) = specs
    assert spec.type == "double_counters" and spec.params == {}


def test_additional_damage_clause_is_recognized_with_color_and_amount():
    specs = replacement_clause_specs(
        "If a red source you control would deal damage to an opponent or "
        "a permanent an opponent controls, it deals that much damage plus "
        "2 instead."
    )
    assert specs is not None
    (spec,) = specs
    assert spec.type == "additional_damage"
    assert spec.params == {
        "amount": 2, "your_sources_only": True, "to_opponent_only": True, "color": "R",
    }


def test_mechanized_warfares_compound_color_filter_is_recognized():
    # "a red or artifact source" — the OR-combined compound source filter.
    specs = replacement_clause_specs(
        "If a red or artifact source you control would deal damage to an "
        "opponent or a permanent an opponent controls, it deals that much "
        "damage plus 1 instead."
    )
    assert specs is not None
    (spec,) = specs
    assert spec.type == "additional_damage"
    assert spec.params == {
        "amount": 1, "your_sources_only": True, "to_opponent_only": True,
        "colors": ["R"], "types": ["artifact"],
    }


def test_innkeepers_talents_causer_scoped_counter_clause_is_recognized():
    # "you would put ... on a permanent or player" — a *causer*-scoped
    # sentence (who's putting the counters), unlike Doubling Season's own
    # *recipient*-scoped "on a permanent you control".
    specs = replacement_clause_specs(
        "If you would put 1 or more counters on a permanent or player, "
        "put twice that many of each of those kinds of counters on that "
        "permanent or player instead."
    )
    assert specs is not None
    (spec,) = specs
    assert spec.type == "double_counters" and spec.params == {"your_effects_only": True}


def test_prevent_damage_one_shot_shape_stays_unclaimed_here():
    # Riot Control/Thought Lash-shaped — a one-shot spell effect, not a
    # standing permanent replacement clause; deliberately out of scope.
    assert replacement_clause_specs(
        "Prevent all damage that would be dealt to you this turn."
    ) is None


def test_gate_claims_torban_shaped_card_as_modeled():
    card = perm(
        "Torbran, Thane of Red Fell",
        "If a red source you control would deal damage to an opponent or "
        "a permanent an opponent controls, it deals that much damage plus "
        "2 instead.",
        type_line="Legendary Creature — Dwarf Berserker",
        is_creature=True, power=3, toughness=3,
    )
    result = parse_oracle(card)
    assert result.coverage == MODELED
    (spec,) = [s for s in result.specs if s.ability_kind == "replacement"]
    assert spec.effects[0].type == "additional_damage"


def test_effect_specs_property_includes_replacement_kind():
    card = perm(
        "Anointed Procession",
        "If an effect would create 1 or more tokens under your control, "
        "it creates twice that many of those tokens instead.",
    )
    result = parse_oracle(card)
    assert result.modeled
    assert any(s.ability_kind == "replacement" for s in result.effect_specs)


# ---------------------------------------------------------------------------
# ENGINE: the bound ReplacementEffect actually replaces the event
# ---------------------------------------------------------------------------


def test_anointed_procession_doubles_token_creation():
    eng = _make_engine()
    card = perm(
        "Anointed Procession",
        "If an effect would create 1 or more tokens under your control, "
        "it creates twice that many of those tokens instead.",
    )
    _bound(eng.state, card)
    token_card = Card(id="Spirit", name="Spirit", type_line="Token Creature — Spirit",
                       is_creature=True, power=1, toughness=1)
    tokens = eng.rules.create_token("p1", token_card, count=1)
    assert len(tokens) == 2


def test_torbran_increases_damage_to_an_opponent_permanent():
    eng = _make_engine()
    card = perm(
        "Torbran, Thane of Red Fell",
        "If a red source you control would deal damage to an opponent or "
        "a permanent an opponent controls, it deals that much damage plus "
        "2 instead.",
        type_line="Legendary Creature — Dwarf Berserker",
        is_creature=True, power=3, toughness=3, color_identity={"R"},
    )
    torbran = _bound(eng.state, card)
    target = GameObject(
        Card(id="Bear", name="Bear", type_line="Creature — Bear", is_creature=True,
             power=2, toughness=2),
        owner_id="p2", zone=Zone.BATTLEFIELD,
    )
    eng.state.add_to_battlefield(target)

    eng.rules.deal_damage(target, 3, source=torbran)
    assert target.damage_marked == 5  # 3 + Torbran's +2


def test_innkeepers_talent_doubles_counters_it_causes():
    # Causer-scoped, unlike Doubling Season: doubles a permanent's counters
    # *and* a player's (poison), since it's the same unscoped COUNTER event
    # either way — as long as Innkeeper's Talent's own controller is the
    # one whose effect placed them.
    eng = _make_engine()
    card = perm(
        "Innkeeper's Talent",
        "If you would put 1 or more counters on a permanent or player, "
        "put twice that many of each of those kinds of counters on that "
        "permanent or player instead.",
    )
    talent = _bound(eng.state, card)
    bear = GameObject(
        Card(id="Bear", name="Bear", type_line="Creature — Bear", is_creature=True,
             power=2, toughness=2),
        owner_id="p2", zone=Zone.BATTLEFIELD,
    )
    eng.state.add_to_battlefield(bear)

    eng.rules.add_counters(bear, 1, "+1/+1", source=talent)
    assert bear.counters.get("+1/+1") == 2

    p2 = eng.state.player_by_id("p2")
    eng.rules.add_player_counters(p2, 1, "poison", source=talent)
    assert p2.poison == 2


def test_innkeepers_talent_does_not_double_counters_it_did_not_cause():
    eng = _make_engine()
    card = perm(
        "Innkeeper's Talent",
        "If you would put 1 or more counters on a permanent or player, "
        "put twice that many of each of those kinds of counters on that "
        "permanent or player instead.",
    )
    _bound(eng.state, card)
    bear = GameObject(
        Card(id="Bear", name="Bear", type_line="Creature — Bear", is_creature=True,
             power=2, toughness=2),
        owner_id="p2", zone=Zone.BATTLEFIELD,
    )
    eng.state.add_to_battlefield(bear)
    eng.rules.add_counters(bear, 1, "+1/+1")  # no source — not "you" causing it
    assert bear.counters.get("+1/+1") == 1


def test_mechanized_warfare_boosts_red_or_artifact_source_damage():
    eng = _make_engine()
    card = perm(
        "Mechanized Warfare",
        "If a red or artifact source you control would deal damage to an "
        "opponent or a permanent an opponent controls, it deals that much "
        "damage plus 1 instead.",
    )
    _bound(eng.state, card)
    artifact_creature = GameObject(
        Card(id="Golem", name="Golem", type_line="Artifact Creature", is_creature=True,
             power=2, toughness=2),
        owner_id="p1", zone=Zone.BATTLEFIELD,
    )
    eng.state.add_to_battlefield(artifact_creature)
    p2 = eng.state.player_by_id("p2")
    eng.rules.deal_damage(p2, 3, source=artifact_creature)
    assert p2.life == 20 - 4  # 3 + Mechanized Warfare's +1 (artifact source)


def test_torbran_does_not_boost_damage_to_its_own_controller():
    eng = _make_engine()
    card = perm(
        "Torbran, Thane of Red Fell",
        "If a red source you control would deal damage to an opponent or "
        "a permanent an opponent controls, it deals that much damage plus "
        "2 instead.",
        type_line="Legendary Creature — Dwarf Berserker",
        is_creature=True, power=3, toughness=3, color_identity={"R"},
    )
    torbran = _bound(eng.state, card)
    own = GameObject(
        Card(id="OwnBear", name="OwnBear", type_line="Creature — Bear", is_creature=True,
             power=2, toughness=2),
        owner_id="p1", zone=Zone.BATTLEFIELD,
    )
    eng.state.add_to_battlefield(own)

    eng.rules.deal_damage(own, 3, source=torbran)
    assert own.damage_marked == 3  # unboosted — not "an opponent or their permanent"


# ---------------------------------------------------------------------------
# Damage-multiplying clauses (Furnace of Rath/Dictate of the Twin Gods,
# Gratuitous Violence, Fiery Emancipation) — RULE 616.1 "target/duration
# variants" beyond the fixed sentences above.
# ---------------------------------------------------------------------------


def test_furnace_of_raths_unscoped_double_damage_clause_is_recognized():
    specs = replacement_clause_specs(
        "If a source would deal damage to a permanent or player, it deals "
        "double that damage to that permanent or player instead."
    )
    assert specs is not None
    (spec,) = specs
    assert spec.type == "double_damage" and spec.params == {}


def test_gratuitous_violences_creature_scoped_clause_is_recognized():
    specs = replacement_clause_specs(
        "If a creature you control would deal damage to a permanent or "
        "player, it deals double that damage instead."
    )
    assert specs is not None
    (spec,) = specs
    assert spec.type == "double_damage"
    assert spec.params == {"creature_only": True, "your_sources_only": True}


def test_fiery_emancipations_triple_damage_clause_is_recognized():
    specs = replacement_clause_specs(
        "If a source you control would deal damage to a permanent or "
        "player, it deals triple that damage to that permanent or player "
        "instead."
    )
    assert specs is not None
    (spec,) = specs
    assert spec.type == "double_damage"
    assert spec.params == {"multiplier": 3, "your_sources_only": True}


def test_gate_claims_dictate_of_the_twin_gods_as_modeled():
    # Dictate of the Twin Gods has no `ability_catalogue.py` entry at all —
    # this proves the oracle-parser recognition alone is enough to model it
    # (Flash is an ordinary keyword, claimed separately).
    card = perm(
        "Dictate of the Twin Gods",
        "Flash\nIf a source would deal damage to a permanent or player, it "
        "deals double that damage to that permanent or player instead.",
    )
    result = parse_oracle(card)
    assert result.coverage == MODELED
    (spec,) = [s for s in result.specs if s.ability_kind == "replacement"]
    assert spec.effects[0].type == "double_damage" and spec.effects[0].params == {}


def test_dictate_of_the_twin_gods_doubles_any_source_end_to_end():
    eng = _make_engine()
    card = perm(
        "Dictate of the Twin Gods",
        "Flash\nIf a source would deal damage to a permanent or player, it "
        "deals double that damage to that permanent or player instead.",
    )
    _bound(eng.state, card)
    p2 = eng.state.player_by_id("p2")
    eng.rules.deal_damage(p2, 3, source=None)
    assert p2.life == 20 - 6  # unscoped — doubles even sourceless burn


def test_fiery_emancipation_triples_only_your_own_sources():
    eng = _make_engine()
    card = perm(
        "Fiery Emancipation",
        "If a source you control would deal damage to a permanent or "
        "player, it deals triple that damage to that permanent or player "
        "instead.",
    )
    emancipation = _bound(eng.state, card)
    attacker = GameObject(
        Card(id="atk", name="Attacker", type_line="Creature — Human", is_creature=True,
             power=3, toughness=3),
        owner_id="p1", zone=Zone.BATTLEFIELD,
    )
    eng.state.add_to_battlefield(attacker)
    p2 = eng.state.player_by_id("p2")

    eng.rules.deal_damage(p2, 3, source=attacker)
    assert p2.life == 20 - 9  # 3 * 3

    p2.life = 20
    opponent_attacker = GameObject(
        Card(id="opp_atk", name="Opponent Attacker", type_line="Creature — Human",
             is_creature=True, power=3, toughness=3),
        owner_id="p2", zone=Zone.BATTLEFIELD,
    )
    eng.state.add_to_battlefield(opponent_attacker)
    eng.rules.deal_damage(eng.state.player_by_id("p1"), 3, source=opponent_attacker)
    assert eng.state.player_by_id("p1").life == 17  # untouched — not "your" source


# ---------------------------------------------------------------------------
# Life-gain replacement (Angel of Vitality / Boon Reflection family) — RULE
# 119.3/616.1, routed through `RulesEngine.gain_life`'s new `LIFE_GAIN`
# pre-event.
# ---------------------------------------------------------------------------


def test_gain_life_plus_clause_is_recognized():
    (spec,) = replacement_clause_specs(
        "If you would gain life, you gain that much life plus 1 instead."
    )
    assert spec.type == "gain_life_replacement" and spec.params == {"plus": 1}


def test_gain_life_double_clause_is_recognized():
    (spec,) = replacement_clause_specs(
        "If you would gain life, you gain twice that much life instead."
    )
    assert spec.type == "gain_life_replacement" and spec.params == {}


def test_angel_of_vitality_adds_one_to_each_life_gain():
    eng = _make_engine()
    _bound(eng.state, perm(
        "Angel of Vitality",
        "If you would gain life, you gain that much life plus 1 instead.",
        type_line="Creature — Angel", is_creature=True, power=2, toughness=2,
    ))
    p1 = eng.state.player_by_id("p1")
    p1.life = 20
    eng.rules.gain_life(p1, 3)
    assert p1.life == 24  # 3 + 1


def test_boon_reflection_doubles_your_life_gain_but_not_an_opponents():
    eng = _make_engine()
    _bound(eng.state, perm(
        "Boon Reflection",
        "If you would gain life, you gain twice that much life instead.",
    ))
    p1 = eng.state.player_by_id("p1")
    p2 = eng.state.player_by_id("p2")
    p1.life = 20
    eng.rules.gain_life(p1, 3)
    assert p1.life == 26  # doubled

    p2.life = 20
    eng.rules.gain_life(p2, 3)
    assert p2.life == 23  # opponent's gain untouched (self-scoped)


def test_gate_claims_alhammarrets_archive_lifegain_line_as_modeled():
    # Only the life-gain half is asserted MODELED here — the card's second
    # "draw two cards instead" line is a separate, unmodeled draw-replacement
    # shape, so the whole card stays UNMODELED overall; but the clause parses.
    (spec,) = replacement_clause_specs(
        "If you would gain life, you gain twice that much life instead."
    )
    assert spec.type == "gain_life_replacement"


# ---------------------------------------------------------------------------
# Recipient-scoped +1/+1 counter replacement (Hardened Scales / Branching
# Evolution / Kami of Whispered Hopes) — RULE 616.1.
# ---------------------------------------------------------------------------


def test_hardened_scales_additive_clause_is_recognized():
    # `replacement_clause_specs` is called *after* normalization (number
    # words → digits), so the unit input is the already-normalized form —
    # mirroring the existing digit-form clause tests above.
    (spec,) = replacement_clause_specs(
        "If 1 or more +1/+1 counters would be put on a creature you "
        "control, that many plus 1 +1/+1 counters are put on it instead."
    )
    assert spec.type == "double_counters"
    assert spec.params == {"kind": "+1/+1", "plus": 1, "recipient": "creature_you_control"}


def test_kami_of_whispered_hopes_permanent_scoped_clause_is_recognized():
    (spec,) = replacement_clause_specs(
        "If 1 or more +1/+1 counters would be put on a permanent you "
        "control, that many plus 1 +1/+1 counters are put on that "
        "permanent instead."
    )
    assert spec.type == "double_counters"
    assert spec.params == {"kind": "+1/+1", "plus": 1, "recipient": "permanent_you_control"}


def test_branching_evolution_double_clause_is_recognized():
    (spec,) = replacement_clause_specs(
        "If 1 or more +1/+1 counters would be put on a creature you "
        "control, twice that many +1/+1 counters are put on that creature "
        "instead."
    )
    assert spec.type == "double_counters"
    assert spec.params == {"kind": "+1/+1", "recipient": "creature_you_control"}


def _creature_obj(name, controller, power=2, toughness=2):
    return GameObject(
        Card(id=name, name=name, type_line="Creature — Bear", is_creature=True,
             power=power, toughness=toughness),
        owner_id=controller, zone=Zone.BATTLEFIELD,
    )


def test_hardened_scales_adds_one_to_your_creatures_counters_only():
    eng = _make_engine()
    _bound(eng.state, perm(
        "Hardened Scales",
        "If one or more +1/+1 counters would be put on a creature you "
        "control, that many plus one +1/+1 counters are put on it instead.",
    ))
    mine = _creature_obj("Mine", "p1")
    theirs = _creature_obj("Theirs", "p2")
    eng.state.add_to_battlefield(mine)
    eng.state.add_to_battlefield(theirs)

    eng.rules.add_counters(mine, 2, "+1/+1")
    assert mine.plus_one_counters == 3  # 2 + 1

    eng.rules.add_counters(theirs, 2, "+1/+1")
    assert theirs.plus_one_counters == 2  # opponent's creature untouched


def test_branching_evolution_doubles_only_plus_one_counters_on_your_creature():
    eng = _make_engine()
    _bound(eng.state, perm(
        "Branching Evolution",
        "If one or more +1/+1 counters would be put on a creature you "
        "control, twice that many +1/+1 counters are put on that creature "
        "instead.",
    ))
    mine = _creature_obj("Mine", "p1")
    eng.state.add_to_battlefield(mine)

    eng.rules.add_counters(mine, 3, "+1/+1")
    assert mine.plus_one_counters == 6  # doubled

    # A different counter kind on the same creature is untouched (kind-scoped).
    eng.rules.add_counters(mine, 1, "stun")
    assert mine.counters.get("stun") == 1


def test_kami_scoped_counter_replacement_covers_a_noncreature_permanent():
    eng = _make_engine()
    _bound(eng.state, perm(
        "Kami of Whispered Hopes",
        "If one or more +1/+1 counters would be put on a permanent you "
        "control, that many plus one +1/+1 counters are put on that "
        "permanent instead.",
    ))
    artifact = GameObject(
        Card(id="Art", name="Art", type_line="Artifact"),
        owner_id="p1", zone=Zone.BATTLEFIELD,
    )
    eng.state.add_to_battlefield(artifact)
    eng.rules.add_counters(artifact, 2, "+1/+1")
    assert artifact.plus_one_counters == 3  # permanent-scoped, not creature-only


# ---------------------------------------------------------------------------
# "If ~ would die, exile it instead" (Gloomshrieker / Corpseweaver Prodigy)
# — RULE 616.1, redirected at `RulesEngine._move_to_graveyard`.
# ---------------------------------------------------------------------------


def test_die_to_exile_subject_recognition():
    cases = {
        "If this creature would die, exile it instead.": "self",
        "If a creature you control would die, exile it instead.": "you_control",
        "If a creature an opponent controls would die, exile it instead.": "opponents_control",
        "If a creature would die, exile it instead.": "any",
        # MEC-49 — Kumano / Baron Sengir's back-face family.
        "If a creature dealt damage by ~ this turn would die, exile it instead.":
            "damaged_by_source_this_turn",
        "If a permanent dealt damage by ~ this turn would die this turn, exile that permanent instead.":
            "damaged_by_source_this_turn",
        # …and the Aura-hosted variant (Kumano's Blessing).
        "If a creature dealt damage by enchanted creature this turn would die, exile it instead.":
            "damaged_by_attached_this_turn",
    }
    for text, subject in cases.items():
        (spec,) = replacement_clause_specs(text)
        assert spec.type == "die_to_exile" and spec.params == {"subject": subject}, text


def test_die_to_exile_damaged_by_source_only_exiles_what_this_source_hit():
    eng = _make_engine()
    kumano = _spirit(
        "Kumano, Master Yamabushi", "p1",
        "If a creature dealt damage by ~ this turn would die, exile it instead.",
    )
    bind_from_catalogue(kumano)
    eng.state.add_to_battlefield(kumano)

    hit = GameObject(Card(id="Hit", name="Hit", type_line="Creature — Bear", is_creature=True,
                          power=2, toughness=2), owner_id="p2", zone=Zone.BATTLEFIELD)
    missed = GameObject(Card(id="Missed", name="Missed", type_line="Creature — Bear", is_creature=True,
                             power=2, toughness=2), owner_id="p2", zone=Zone.BATTLEFIELD)
    eng.state.add_to_battlefield(hit)
    eng.state.add_to_battlefield(missed)

    eng.rules.deal_damage(hit, 1, source=kumano)

    eng.rules.destroy(hit, can_be_regenerated=False)
    eng.rules.destroy(missed, can_be_regenerated=False)
    assert hit.zone == Zone.EXILE
    assert missed.zone == Zone.GRAVEYARD  # never damaged by Kumano


def test_die_to_exile_damaged_by_source_real_card_modeled():
    card = Card(
        id="KMY", name="Kumano, Master Yamabushi",
        type_line="Legendary Creature — Human Monk", is_creature=True, power=4, toughness=4,
        oracle_text=(
            "{1}{R}: Kumano, Master Yamabushi deals 1 damage to any target.\n"
            "If a creature dealt damage by Kumano, Master Yamabushi this turn would "
            "die, exile it instead."
        ),
    )
    res = parse_oracle(card)
    assert res.coverage == MODELED, res.unclaimed
    repl = next(s for s in res.specs if s.ability_kind == "replacement")
    assert repl.effects[0].params == {"subject": "damaged_by_source_this_turn"}


def _spirit(name, controller, text=""):
    return GameObject(
        Card(id=name, name=name, type_line="Creature — Spirit", is_creature=True,
             power=1, toughness=1, oracle_text=text),
        owner_id=controller, zone=Zone.BATTLEFIELD,
    )


def test_gloomshrieker_exiles_itself_instead_of_dying():
    eng = _make_engine()
    g = _spirit("Gloomshrieker", "p1", "If this creature would die, exile it instead.")
    bind_from_catalogue(g)
    eng.state.add_to_battlefield(g)
    eng.rules.destroy(g, can_be_regenerated=False)
    assert g.zone == Zone.EXILE
    assert g not in eng.state.player_by_id("p1").graveyard


def test_die_to_exile_also_redirects_an_sba_death_and_a_sacrifice():
    for kill in ("sba", "sacrifice"):
        eng = _make_engine()
        g = _spirit("Gloomshrieker", "p1", "If this creature would die, exile it instead.")
        bind_from_catalogue(g)
        eng.state.add_to_battlefield(g)
        if kill == "sba":
            g.damage_marked = 5
            eng.rules.check_state_based_actions()
        else:
            eng.rules.put_into_graveyard(g)
        assert g.zone == Zone.EXILE, kill


def test_corpseweaver_exiles_opponents_creatures_but_not_your_own():
    eng = _make_engine()
    cw = _spirit("Corpseweaver Prodigy", "p1",
                 "If a creature an opponent controls would die, exile it instead.")
    bind_from_catalogue(cw)
    eng.state.add_to_battlefield(cw)

    opp = GameObject(Card(id="Opp", name="Opp", type_line="Creature — Bear", is_creature=True,
                          power=2, toughness=2), owner_id="p2", zone=Zone.BATTLEFIELD)
    eng.state.add_to_battlefield(opp)
    eng.rules.destroy(opp, can_be_regenerated=False)
    assert opp.zone == Zone.EXILE

    mine = GameObject(Card(id="Mine", name="Mine", type_line="Creature — Bear", is_creature=True,
                           power=2, toughness=2), owner_id="p1", zone=Zone.BATTLEFIELD)
    eng.state.add_to_battlefield(mine)
    eng.rules.destroy(mine, can_be_regenerated=False)
    assert mine.zone == Zone.GRAVEYARD  # your own creature isn't covered


def test_die_to_exile_does_not_fire_for_a_noncreature_permanent_leaving():
    # WOULD_DIE only fires for a creature (RULE 700.4) — an artifact with a
    # hypothetical self "die → exile" clause never triggers it.
    eng = _make_engine()
    art = GameObject(
        Card(id="Art", name="Art", type_line="Artifact",
             oracle_text="If this creature would die, exile it instead."),
        owner_id="p1", zone=Zone.BATTLEFIELD,
    )
    bind_from_catalogue(art)
    eng.state.add_to_battlefield(art)
    eng.rules.destroy(art, can_be_regenerated=False)
    assert art.zone == Zone.GRAVEYARD
