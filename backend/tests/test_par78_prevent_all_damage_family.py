"""PAR-78: "Prevent all damage that would be dealt to `<target>`" — broad
recognition (in progress). `PreventDamageEffect`/`"prevent_damage_shield"`
already supported an unlimited ("all") shield; the real gap turned out to
be several: no `source_filter` ("by creatures"/"by sources you don't
control"/…) on any prevention primitive at all, no board-wide "creatures[
you control]" recipient shield (`_prevent_damage_to_creatures`), and —
found the hard way — a bare *permanent's own* un-triggered "Prevent all
damage that would be dealt to `<X>`." line is a STANDING replacement
effect (RULE 613), not a one-shot resolve-time grant: `segment_line`'s own
``allow_spell_effect`` gate correctly leaves such a line unclaimed for the
one-shot `EffectRegistry` family, and the real primitive for it was
already-shipped `ReplacementRegistry`'s ``"prevent_damage"`` factory
(MEC-30) — only its own parser recognition (`static_handlers.py`) and a
matching `source_filter` vocabulary extension were missing.

Two parallel `source_filter` vocabularies now exist by design, not
oversight: `catalogue.handlers._PREVENT_SOURCE_FILTER_PHRASES` (one-shot,
`{"creature": bool, "artifact": bool, ...}`) and `catalogue.
static_handlers._STATIC_PREVENT_SOURCE_FILTER_PHRASES` (standing, the
pre-existing `{"card_type": str, "is_creature": bool, ...}` shape
`_prevent_damage_replacement` already used) — different effect kinds with
no shared class to unify them through.

Reference: docs/implementation-state/Done_Backend.md's "Oracle-Text Parser
Front-End" PAR-78 entry (once closed).
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
from mtg_analyzer.parser.oracle.spec import EffectSpec


def _card(name, type_line="Creature — Bear", cost="{1}{G}", cmc=2, **kw):
    lowered = type_line.lower()
    for flag in ("instant", "sorcery", "land", "creature"):
        kw.setdefault(f"is_{flag}", flag in lowered)
    if kw.get("is_creature"):
        kw.setdefault("power", 2)
        kw.setdefault("toughness", 2)
    return Card(id=name, name=name, type_line=type_line, mana_cost_string=cost,
                converted_mana_cost=cmc, **kw)


def _bf(state, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


def _engine():
    return GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )


# ---------------------------------------------------------------------------
# Real cards: full MODELED verdict, a sample across the closed shapes
# ---------------------------------------------------------------------------


def test_sample_real_cards_now_modeled():
    for entry in [
        ("Cho-Manno, Revolutionary", "Creature — Human Soldier",
         "Prevent all damage that would be dealt to ~."),
        ("Argothian Pixies", "Creature — Faerie",
         "Prevent all damage that would be dealt to ~ by artifact creatures."),
        ("Solitary Confinement", "Enchantment",
         "Prevent all damage that would be dealt to you.\n"
         "Skip your draw step.\nAt the beginning of your upkeep, sacrifice "
         "~ unless you pay 1 life."),
        ("Bubble Matrix", "Artifact",
         "Prevent all damage that would be dealt to creatures."),
        ("Inner Sanctum", "Enchantment",
         "Prevent all damage that would be dealt to creatures you control."),
        ("Indestructible Aura", "Instant",
         "Prevent all damage that would be dealt to target creature this turn."),
        ("Inviolability", "Enchantment — Aura",
         "Enchant creature\nPrevent all damage that would be dealt to "
         "enchanted creature."),
        ("Djeru's Resolve", "Instant",
         "Untap target creature. Prevent all damage that would be dealt "
         "to it this turn."),
        ("Favored Hoplite", "Creature — Human Soldier",
         "Heroic — Whenever you cast a spell that targets this creature, "
         "put a +1/+1 counter on this creature and prevent all damage "
         "that would be dealt to it this turn.", ["Heroic"]),
        ("Kitsune Healer", "Creature — Fox Cleric",
         "{T}: Prevent all damage that would be dealt to target "
         "legendary creature this turn."),
    ]:
        name, type_line, text = entry[0], entry[1], entry[2]
        keywords = entry[3] if len(entry) > 3 else []
        card = _card(name, type_line=type_line, oracle_text=text, keywords=keywords)
        result = parse_oracle(card)
        assert result.modeled, f"{name} stayed UNMODELED: {result.unclaimed}"


# ---------------------------------------------------------------------------
# Parse-level: one-shot family (trigger/activated/spell contexts)
# ---------------------------------------------------------------------------


def test_self_only_with_source_filter_parses():
    assert parse_effect_body(
        "prevent all damage that would be dealt to ~ by artifact creatures", self_subject=True,
    ) == [EffectSpec("prevent_damage_shield", {
        "amount": "all", "self_only": True,
        "source_filter": {"creature": True, "artifact": True},
    })]


def test_you_and_permanents_you_control_parses():
    assert parse_effect_body(
        "prevent all damage that would be dealt to you and permanents you "
        "control this turn"
    ) == [EffectSpec("prevent_damage_shield", {
        "amount": "all", "recipient_scope": "permanents",
    })]


def test_mass_creatures_you_control_with_attacking_filter_parses():
    assert parse_effect_body(
        "prevent all damage that would be dealt to attacking creatures you control"
    ) == [EffectSpec("prevent_damage_shield", {
        "amount": "all", "recipient_creatures_scope": "you_control",
        "recipient_filter": {"attacking": True},
    })]


def test_target_creature_with_min_power_and_filter_parses():
    assert parse_effect_body(
        "prevent all damage that would be dealt to target creature with "
        "power 5 or greater this turn"
    ) == [EffectSpec("prevent_damage_shield", {
        "amount": "all", "target_kind": "creature",
        "creature_filter": {"min_power": 5},
    })]


def test_previous_subject_pronoun_parses():
    assert parse_effect_body(
        "untap target creature. prevent all damage that would be dealt to it this turn"
    ) == [
        EffectSpec("tap", {"target_kind": "creature", "untap": True}),
        EffectSpec("prevent_damage_shield", {"amount": "all", "previous_subject": True}),
    ]


# ---------------------------------------------------------------------------
# Parse-level: standing (static, no wrapper) family
# ---------------------------------------------------------------------------


def test_static_self_is_a_replacement_ability_not_one_shot():
    # A bare permanent imperative with no trigger/cost wrapper is a
    # standing RULE 613/616 replacement effect, not a one-shot
    # `spell_effect` grant — `segment_line` must tag it `ability_kind=
    # "replacement"` (routed through `ReplacementRegistry` at bind time),
    # not `"static"`/`"spell_effect"`.
    from mtg_analyzer.parser.oracle.segmenter import segment_line
    from mtg_analyzer.parser.oracle.spec import ParserProvenance

    prov = ParserProvenance(source="test", version=1)
    seg = segment_line(
        "prevent all damage that would be dealt to ~.", allow_spell_effect=False, provenance=prov,
    )
    assert seg.claimed and seg.spec.ability_kind == "replacement"


def test_standing_self_parses():
    from mtg_analyzer.parser.oracle.catalogue.replacements import replacement_clause_specs

    assert replacement_clause_specs("prevent all damage that would be dealt to ~") == [
        EffectSpec("prevent_damage", {"to": "self", "amount": "all"})
    ]


def test_standing_creatures_you_control_with_source_filter_parses():
    from mtg_analyzer.parser.oracle.catalogue.replacements import replacement_clause_specs

    assert replacement_clause_specs(
        "prevent all damage that would be dealt to creatures you control by sources you control"
    ) == [EffectSpec("prevent_damage", {
        "to": "creatures_you_control", "amount": "all",
        "source_filter": {"controller": "you"},
    })]


def test_standing_during_your_turn_wrapper_still_works():
    from mtg_analyzer.parser.oracle.catalogue.static_handlers import static_effect_specs

    specs = static_effect_specs("during your turn, prevent all damage that would be dealt to ~")
    assert specs is not None
    assert specs[0].type == "prevent_damage"
    assert specs[0].params.get("active_if") == {"kind": "your_turn"}


# ---------------------------------------------------------------------------
# Execute: the one-shot source_filter primitive
# ---------------------------------------------------------------------------


def test_source_filter_only_blocks_matching_sources():
    eng = _engine()
    state = eng.state
    p1, p2 = state.players
    target = _bf(state, _card("Target"), controller="p1")
    artifact_src = _bf(state, _card("ArtSrc", type_line="Artifact Creature"), controller="p2")
    nonartifact_src = _bf(state, _card("NonArtSrc"), controller="p2")

    eng.rules.prevent_damage_to_target(
        target, "all", source_filter={"creature": True, "artifact": True},
    )
    eng.rules.deal_damage(target, 2, source=artifact_src)
    assert target.damage_marked == 0
    eng.rules.deal_damage(target, 3, source=nonartifact_src)
    assert target.damage_marked == 3


# ---------------------------------------------------------------------------
# Execute: the board-wide "creatures[ you control]" shield
# ---------------------------------------------------------------------------


def test_mass_creature_shield_only_protects_the_controllers_own():
    eng = _engine()
    state = eng.state
    p1, p2 = state.players
    mine = _bf(state, _card("Mine"), controller="p1")
    theirs = _bf(state, _card("Theirs"), controller="p2")

    eng.rules._prevent_damage_to_creatures(p1, recipient_scope="you_control")
    eng.rules.deal_damage(mine, 3, source=None)
    eng.rules.deal_damage(theirs, 3, source=None)

    assert mine.damage_marked == 0
    assert theirs.damage_marked == 3


# ---------------------------------------------------------------------------
# Execute: the standing (static) shield via a real card
# ---------------------------------------------------------------------------


def test_standing_self_shield_survives_across_turns_no_expiry():
    eng = _engine()
    state = eng.state
    p1 = state.players[0]
    guardian = _bf(state, _card(
        "Test Cho-Manno", is_creature=True,
        oracle_text="Prevent all damage that would be dealt to ~.",
    ))
    attacker = _bf(state, _card("Test Attacker"), controller="p2")

    eng.rules.deal_damage(guardian, 5, source=attacker)
    assert guardian.damage_marked == 0
    # A standing replacement, unlike the one-shot "this turn" shield, must
    # still apply after a cleanup step — sweep once and re-check.
    for effect in list(state.permanents()):
        effect.damage_marked = 0
    eng.rules.deal_damage(guardian, 5, source=attacker)
    assert guardian.damage_marked == 0


# ---------------------------------------------------------------------------
# Execute: the remaining SOLO cards, hand-authored (`game/card_registry/
# damage_prevention.py`) — the "sources of the color of your choice" chooser
# family (genuinely different from "a source of your choice": it shields
# against every matching source, not one permanent) and a few other
# bespoke shapes. Real cards, real oracle text, via `CardDatabase`.
# ---------------------------------------------------------------------------


def _real(name):
    from mtg_analyzer.config import DB_PATH
    from mtg_analyzer.services.card_database import CardDatabase

    return CardDatabase(DB_PATH).get_card(name)


def _real_bf(state, name, controller="p1", sick=False):
    obj = GameObject(_real(name), owner_id=controller, zone=Zone.BATTLEFIELD)
    bind_from_catalogue(obj)
    obj.summoning_sick = sick
    state.add_to_battlefield(obj)
    return obj


def test_avacyn_chosen_color_shield_resolves_the_picked_colors_sources_only():
    eng = _engine()
    state = eng.state
    p1, p2 = state.players
    avacyn = _real_bf(state, "Avacyn, Guardian Angel")
    target = _bf(state, _card("Target", is_creature=True), controller="p2")
    red_src = _bf(state, _card("RedSrc", is_creature=True, color_identity={"R"}), controller="p2")
    blue_src = _bf(state, _card("BlueSrc", is_creature=True, color_identity={"U"}), controller="p2")

    p1.mana_pool.add_many({"W": 1, "C": 1})
    eng.activate_ability(p1, avacyn, ability_index=0, targets=[target])
    eng.resolve_until_stable()
    assert state.pending_choice["kind"] == "prevent_damage_chosen_color"
    eng.resolve_pending_choice("R")
    eng.resolve_until_stable()

    eng.rules.deal_damage(target, 3, source=red_src)
    assert target.damage_marked == 0
    eng.rules.deal_damage(target, 3, source=blue_src)
    assert target.damage_marked == 3


def test_protective_sphere_reads_the_color_of_mana_actually_spent():
    eng = _engine()
    state = eng.state
    p1, p2 = state.players
    sphere = _real_bf(state, "Protective Sphere")
    red_src = _bf(state, _card("RedSrc", is_creature=True, color_identity={"R"}), controller="p2")
    blue_src = _bf(state, _card("BlueSrc", is_creature=True, color_identity={"U"}), controller="p2")

    p1.mana_pool.add_many({"R": 1})
    eng.activate_ability(p1, sphere, ability_index=0)
    eng.resolve_until_stable()
    assert sphere.noted_mana_color == "R"
    assert p1.life == 19  # the 1-life cost

    eng.rules.deal_damage(p1, 3, source=red_src)
    assert p1.life == 19
    eng.rules.deal_damage(p1, 3, source=blue_src)
    assert p1.life == 16


def test_samite_ministration_gains_life_only_off_a_black_or_red_source():
    eng = _engine()
    state = eng.state
    p1, p2 = state.players
    spell = GameObject(_real("Samite Ministration"), owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(spell)
    p1.hand.append(spell)
    black_src = _bf(state, _card("BlackSrc", is_creature=True, color_identity={"B"}), controller="p2")
    blue_src = _bf(state, _card("BlueSrc", is_creature=True, color_identity={"U"}), controller="p2")

    p1.mana_pool.add_many({"W": 1, "C": 1})
    eng.cast_spell(p1, spell)
    eng.resolve_until_stable()
    assert state.pending_choice["kind"] == "choose_objects"  # 2 candidates: a real choice
    eng.resolve_pending_choice(str(black_src.instance_id))
    eng.resolve_until_stable()

    eng.rules.deal_damage(p1, 4, source=black_src)
    assert p1.life == 24  # 4 prevented + 4 gained off the rider


def test_shieldmage_advocate_returns_and_shields_off_one_activation():
    eng = _engine()
    state = eng.state
    p1, p2 = state.players
    advocate = _real_bf(state, "Shieldmage Advocate", sick=False)
    gy_card = GameObject(_card("GYCard", type_line="Instant"), owner_id="p2", zone=Zone.GRAVEYARD)
    p2.graveyard.append(gy_card)

    creature = _bf(state, _card("Protected Creature", is_creature=True))
    eng.activate_ability(p1, advocate, ability_index=0, targets=[gy_card, creature])
    eng.resolve_until_stable()
    assert gy_card in p2.hand and gy_card not in p2.graveyard


def test_consulate_surveillance_shield_is_paid_with_energy_not_mana():
    eng = _engine()
    state = eng.state
    p1, p2 = state.players
    consulate = _real_bf(state, "Consulate Surveillance")
    p1.counters["energy"] = 4

    eng.activate_ability(p1, consulate, ability_index=0)
    eng.resolve_until_stable()
    assert p1.counters.get("energy") == 2


def test_prismatic_ward_shields_only_from_the_chosen_colors_sources():
    eng = _engine()
    state = eng.state
    p1, p2 = state.players
    host = _bf(state, _card("Host", is_creature=True))
    ward = GameObject(_real("Prismatic Ward"), owner_id="p1", zone=Zone.BATTLEFIELD)
    ward.attached_to = host.instance_id
    ward.chosen_color = "R"
    bind_from_catalogue(ward)
    state.add_to_battlefield(ward)
    red_src = _bf(state, _card("RedSrc", is_creature=True, color_identity={"R"}), controller="p2")
    blue_src = _bf(state, _card("BlueSrc", is_creature=True, color_identity={"U"}), controller="p2")

    eng.rules.deal_damage(host, 3, source=red_src)
    assert host.damage_marked == 0
    eng.rules.deal_damage(host, 3, source=blue_src)
    assert host.damage_marked == 3


# ---------------------------------------------------------------------------
# Parse-level: three more real-card widenings found while closing out the
# SOLO list — "him"/"her" as the self-subject pronoun, a two-word subtype-OR
# creature_filter on the RULE 115 target shape, and a devotion-shaped
# five-colour static condition.
# ---------------------------------------------------------------------------


def test_self_subject_pronoun_accepts_him_and_her():
    for pronoun in ("it", "him", "her"):
        assert parse_effect_body(
            f"prevent all damage that would be dealt to {pronoun} this turn", self_subject=True,
        ) == [EffectSpec("prevent_damage_shield", {"amount": "all", "self_only": True})]


def test_target_creature_two_word_subtype_or_filter_parses():
    assert parse_effect_body(
        "prevent all damage that would be dealt to target tapped merfolk or "
        "kithkin creature this turn"
    ) == [EffectSpec("prevent_damage_shield", {
        "amount": "all", "target_kind": "creature",
        "creature_filter": {"tapped": True, "subtype_any": ["Merfolk", "Kithkin"]},
    })]


def test_target_creature_unknown_subtype_word_stays_unclaimed():
    # "attacking" isn't in the closed subtype vocabulary — must fail closed
    # rather than guessing a subtype filter for a qualifier word.
    assert parse_effect_body(
        "prevent all damage that would be dealt to target attacking creature this turn"
    ) is None


def test_control_permanent_of_each_color_condition():
    from mtg_analyzer.parser.oracle.catalogue.static_handlers import static_condition, static_effect_specs

    assert static_condition("you control a permanent of each color") == {
        "kind": "control_permanent_of_each_color",
    }
    specs = static_effect_specs(
        "as long as you control a permanent of each color, prevent all damage that would be dealt to you"
    )
    assert specs == [EffectSpec("prevent_damage", {
        "to": "controller", "amount": "all",
        "active_if": {"kind": "control_permanent_of_each_color"},
    })]


def test_control_permanent_of_each_color_execute():
    from mtg_analyzer.game.static_conditions import condition_holds

    eng = _engine()
    state = eng.state

    def _add(color):
        return _bf(state, _card(f"{color}Src", is_creature=True, color_identity={color}))

    for color in ("W", "U", "B", "R"):
        _add(color)
    cond = {"kind": "control_permanent_of_each_color"}
    assert condition_holds(cond, state, controller_id="p1") is False
    _add("G")
    assert condition_holds(cond, state, controller_id="p1") is True
