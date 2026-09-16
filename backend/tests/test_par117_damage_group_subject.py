"""PAR-117 (group-subject residue): a RULE 603.1 group-subject condition on
a `DAMAGE`-shaped trigger — "whenever a `<type/subtype>` [you control] deals
[combat ]damage[ to `<recipient>`], its controller `<verb>`" (Edric,
Spymaster of Trest; the Sliver "combat damage to a player" triggered-ability
cycle: Essence/Brood/Synapse Sliver).

Two independent gaps closed together, both scoped to `_DAMAGE_TRIGGER_RE`'s
own dispatch (`segmenter.py`) rather than the already-correct shared
group-subject machinery (MEC-28/PAR-115/PAR-117's own earlier increments):

1. The dispatch never passed `group_subject=True` at all, so none of the
   PAR-115/117 `group_its_controller_*` rows (already shipped for every
   other RULE 603.1 event) were reachable for `DAMAGE`.
2. `_DAMAGE_TRIGGER_RE`'s group-subject branch only ever recognized
   `_GROUP_TYPE_WORDS`'s closed main-type vocabulary ("creature"/
   "artifact"/…) — a creature *subtype* ("a Sliver deals damage") has no
   route in at all, unlike the ENTERS/DIES/ATTACKS/BLOCKS family's own
   `_GROUP_SUBTYPE_SUBJECT_RE` sibling.

A third gap surfaced diagnosing Edric/Synapse Sliver specifically: "its
controller **may** `<effect>`" (RULE 601.2b's "you may", asked of a referent
rather than "you") had no composition at all — `_MID_BODY_OPTIONAL_RE` only
ever peels a *leading* "you may", so `OptionalEffect.player` gained a
referent-dict mode (the same `{"of": …, "as": "controller"}` vocabulary
`GainLifeEffect`/`DrawCardEffect` already read) alongside its existing
"you"/"target" strings.

Proving these end to end surfaced a real correctness trap, not just a
recognition gap: Rakish Heir/Stensia Masquerade's bare "put a +1/+1 counter
on **it**" collides, at the `AddCountersEffect` spec level, with an
unrelated card naming *itself* under the identical group condition (Malakir
Cullblade: "…dies, put a +1/+1 counter on Malakir Cullblade.", folded to
"~") — both compile to the same untargeted `add_counters` spec, so a
binder-side rewrite that can't see which literal word the clause used would
retarget the wrong one. Split into its own `group_subject_only`-gated row
(`_add_counters_group_subject_it`, matching only the literal "it") tried
*before* the generic self/"~" row, so both readings stay correct — see that
handler's own docstring.

A second correctness trap: "…deals combat damage to **a creature**,
destroy **that creature**…" (Sosuke, Son of Seshiro) needs the *damage
recipient*, a third referent this project doesn't model yet — distinct from
both the group subject (the dealer) and a same-resolution `previous_target`.
`delayed_sac_exile_tail`'s own generic ``previous_or_self`` capture has no
way to tell that apart and would silently fall back to this ability's own
source. Left unclaimed on purpose (`_DELAYED_SAC_EXILE_TAIL_RE`'s own
ambiguous-``obj`` branch pre-checked and refused) rather than guessed —
confirmed via `parser_probe.py diff` staying 0 regressed against the full
cache while this file's own family closed.
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.gate import parse_oracle, UNMODELED
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
from mtg_analyzer.parser.oracle.spec import EffectSpec
from mtg_analyzer.services.card_database import CardDatabase, DEFAULT_DB_PATH

_ENTERING_CONTROLLER = {"of": "entering", "as": "controller"}


def _db():
    return CardDatabase(DEFAULT_DB_PATH)


def _engine():
    eng = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )
    eng.begin_turn()
    eng.state.current_step = "main1"
    return eng, eng.state, eng.state.players[0], eng.state.players[1]


def _put(engine, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.controller_id = controller
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    engine.state.add_to_battlefield(obj)
    return obj


def _creature(name, power=2, toughness=2, type_line="Creature — Bear"):
    return Card(
        id=name, name=name, type_line=type_line, is_creature=True,
        power=power, toughness=toughness, mana_cost_string="{1}{G}", converted_mana_cost=2,
    )


# ---------------------------------------------------------------------------
# PARSER: group_subject unlocked for DAMAGE, incl. a subtype acting object
# ---------------------------------------------------------------------------


def test_its_controller_draws_gated_on_group_subject():
    assert match_clause("its controller draws a card", group_subject=True) == [
        EffectSpec("draw", {"count": 1, "player": _ENTERING_CONTROLLER})
    ]


def test_its_controller_gains_that_much_life_gated_on_group_subject():
    assert match_clause(
        "its controller gains that much life", group_subject=True,
    ) == [
        EffectSpec("gain_life", {
            "amount_from_trigger_event": "amount", "player": _ENTERING_CONTROLLER,
        })
    ]
    # Ungated — no referent offered this pronoun a meaning.
    assert match_clause("its controller gains that much life") is None


def test_its_controller_may_draw_composes_optional_with_the_referent():
    # The "its controller may `<effect>`" composition lives one level up
    # from `match_clause`'s HANDLERS table — `parse_effect_body`'s own
    # `_MID_BODY_ITS_CONTROLLER_MAY_RE` dispatch, mirroring the shape
    # `_MID_BODY_OPTIONAL_RE`'s plain "you may" already uses. The inner
    # ``draw`` spec also carries the same referent as its own ``player`` —
    # RULE 603.1's "its controller" both asks *and* draws, so the body must
    # not fall back to Edric's own controller once the pause is answered
    # (`_rewrite_optional_referent_actor`).
    assert parse_effect_body("its controller may draw a card.", group_subject=True) == [
        EffectSpec("optional", {
            "effects": [{
                "type": "draw", "params": {"count": 1, "player": _ENTERING_CONTROLLER},
            }],
            "player": _ENTERING_CONTROLLER,
        })
    ]
    # Ungated — no active pronoun referent to name a chooser with.
    assert parse_effect_body("its controller may draw a card.") is None


def test_its_controller_may_create_token_composes_optional():
    specs = parse_effect_body(
        "its controller may create a 1/1 colorless sliver creature token.",
        group_subject=True,
    )
    assert specs is not None
    assert specs[0].type == "optional"
    assert specs[0].params["player"] == _ENTERING_CONTROLLER
    inner = specs[0].params["effects"][0]
    assert inner["type"] == "create_token"
    # The token's own creator must be the same referent, not "you" (this
    # ability's own controller) — Brood Sliver's Sliver-controller, not
    # Brood Sliver's own controller.
    assert inner["params"]["creators"] == "trigger_subject_controller"


def test_add_counters_on_it_is_gated_and_uses_the_sentinel():
    # Only offered under group_subject — a bare "it" stays the generic
    # self-buff reading otherwise (unchanged for every pre-existing card).
    assert match_clause("put a +1/+1 counter on it") == [
        EffectSpec("add_counters", {"count": 1, "kind": "+1/+1"})
    ]
    assert match_clause("put a +1/+1 counter on it", group_subject=True) == [
        EffectSpec("add_counters", {
            "count": 1, "kind": "+1/+1", "trigger_subject_key": "__group_subject__",
        })
    ]


def test_add_counters_on_explicit_self_name_is_unaffected_by_group_subject():
    # "~"/a card's own name is never ambiguous — it must keep claiming the
    # generic self-buff row even when a group condition is in scope
    # (Malakir Cullblade: "…dies, put a +1/+1 counter on Malakir
    # Cullblade.", folded to "~" by normalize()).
    assert match_clause("put a +1/+1 counter on ~", group_subject=True) == [
        EffectSpec("add_counters", {"count": 1, "kind": "+1/+1"})
    ]


# ---------------------------------------------------------------------------
# END TO END: the real cards
# ---------------------------------------------------------------------------


def test_essence_sliver_brood_sliver_synapse_sliver_edric_are_modeled():
    for name in (
        "Essence Sliver", "Brood Sliver", "Synapse Sliver", "Edric, Spymaster of Trest",
    ):
        result = parse_oracle(_db().get_card(name))
        assert result.coverage != UNMODELED, (name, result.unclaimed)


def test_rakish_heir_and_stensia_masquerade_are_modeled():
    for name in ("Rakish Heir", "Stensia Masquerade"):
        result = parse_oracle(_db().get_card(name))
        assert result.coverage != UNMODELED, (name, result.unclaimed)


def test_sosuke_son_of_seshiro_stays_unmodeled_on_the_damage_recipient_referent():
    # "…deals combat damage to a creature, destroy that creature at end of
    # combat." needs a damage-*recipient* referent this project doesn't
    # have yet (distinct from the group subject, the dealer) — refused
    # rather than silently destroying Sosuke's own controller's board.
    result = parse_oracle(_db().get_card("Sosuke, Son of Seshiro"))
    assert result.coverage == UNMODELED


def test_quest_for_the_gemblades_keeps_working():
    # A creature-recipient DAMAGE trigger whose body is an explicit "~"
    # self-reference (no pronoun ambiguity at all) must not be caught by
    # the Sosuke-shaped refusal above.
    result = parse_oracle(_db().get_card("Quest for the Gemblades"))
    assert result.coverage != UNMODELED, result.unclaimed


# ---------------------------------------------------------------------------
# EXECUTE: the referent actually resolves to the right object/player,
# fired as a synthetic DAMAGE event (mirroring `test_par117_group_subject_
# controller.py`'s own ENTERS_BATTLEFIELD precedent) rather than driving a
# full combat — the engine doesn't otherwise enforce "one of your
# opponents"/"you control" as a hard filter (documented simplification, see
# `_DAMAGE_TRIGGER_RE`'s own comments), so the synthetic event is exactly as
# faithful as a real attack while staying independent of turn/priority
# plumbing this file isn't testing.
# ---------------------------------------------------------------------------


def _damage_event(source, target_id, *, amount=3, is_player=True, combat=True):
    return GameEvent(
        EventType.DAMAGE, amount=amount, is_player=is_player, combat=combat,
        target_id=target_id, source_id=source.instance_id,
        source_controller_id=source.controller_id,
    )


def test_edric_asks_the_damaged_creatures_controller_not_edrics_own():
    eng, state, p1, p2 = _engine()
    edric = _put(eng, _db().get_card("Edric, Spymaster of Trest"), controller="p1")
    # A creature controlled by p2 deals the damage — Edric (p1's own
    # permanent) must ask *p2*, the attacker's own controller, not p1.
    raider = _put(eng, _creature("Raider"), controller="p2")
    p2.library.append(GameObject(
        Card(id="L", name="L", type_line="Plains", is_land=True),
        owner_id="p2", zone=Zone.LIBRARY,
    ))

    state.fire_event(_damage_event(raider, target_id="p1"))
    placed = eng.rules.put_triggers_on_stack()
    assert placed == 1
    eng.rules.resolve_top_of_stack()

    assert state.pending_choice is not None
    assert state.pending_choice["player_id"] == "p2"
    eng.rules.resolve_choice("yes")  # "composite_optional"'s ANSWER_FLAG accept id
    eng.resolve_until_stable()

    assert len(p2.hand) == 1
    assert edric.controller_id == "p1"  # Edric itself never drew


def test_essence_sliver_gains_life_equal_to_the_damage_dealt():
    eng, state, p1, p2 = _engine()
    _put(eng, _db().get_card("Essence Sliver"), controller="p1")
    sliver = _put(
        eng, _creature("Test Sliver", power=3, toughness=3, type_line="Creature — Sliver"),
        controller="p1",
    )
    p1.life = 20

    state.fire_event(_damage_event(sliver, target_id="p2", amount=3))
    placed = eng.rules.put_triggers_on_stack()
    assert placed == 1
    eng.rules.resolve_top_of_stack()

    assert p1.life == 23  # gained exactly the 3 damage dealt


def test_rakish_heir_counter_lands_on_the_vampire_not_on_rakish_heir():
    eng, state, p1, p2 = _engine()
    heir = _put(eng, _db().get_card("Rakish Heir"), controller="p1")
    vampire = _put(
        eng, _creature("Test Vampire", type_line="Creature — Vampire"), controller="p1",
    )

    state.fire_event(_damage_event(vampire, target_id="p2", amount=2))
    placed = eng.rules.put_triggers_on_stack()
    assert placed == 1
    eng.rules.resolve_top_of_stack()

    assert vampire.counters.get("+1/+1", 0) == 1
    assert heir.counters.get("+1/+1", 0) == 0
