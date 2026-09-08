"""Incubate (RULE 701.53) residue — the plain "incubate N" cache cards that
were blocked on *unrelated* surrounding grammar, not on incubate itself.
Three parser rows close them (PAR-30), all reusable well beyond Incubate:

- **Assimilate Essence** — "counter target creature or battle spell unless
  its controller pays {4}. **If they do**, you incubate 2.": a reflexive
  follow-up on the pay branch of an "unless … pays" counter
  (`CounterSpellEffect.on_pay_effect_specs`, threaded through
  `RulesEngine.counter_unless_pays` / `resolve_counter_unless_pays_choice`),
  plus "battle" as a counter-target spell type. Also unlocks
  **Don't Make a Sound** ("… If they do, surveil 2.").
- **Searing Barb** — "~ deals 2 damage to any target. **If it's a
  creature**, it can't block this turn.": the "any target" damage clause
  can land on a player/planeswalker/battle, so the can't-block rider is
  gated on the previous clause's target being a creature
  (`CantBlockEffect.previous_subject` + a `previous_target_is_creature`
  `ConditionalEffect` gate).
- **Tiller of Flesh** — "Whenever you cast a spell that targets one or more
  permanents, incubate 2.": a RULE 608.2b targeting filter on the cast
  trigger (`SPELL_CAST`'s new ``targets_a_permanent`` flag +
  ``requires_spell_targets_permanent`` predicate).
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import build_effects
from mtg_analyzer.game.effects.core import _apply_effects_partitioned
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.models.game_state import StackItem
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle
from mtg_analyzer.parser.oracle.spec import EffectSpec
from mtg_analyzer.services.card_database import CardDatabase, DEFAULT_DB_PATH


def _db():
    return CardDatabase(DEFAULT_DB_PATH)


# --- parse -----------------------------------------------------------------


def test_counter_reflexive_if_they_do_clause():
    specs = match_clause(
        "counter target creature or battle spell unless its controller pays {4}. "
        "if they do, you incubate 2",
        self_subject=True,
    )
    assert specs is not None and specs[0].type == "counter"
    p = specs[0].params
    assert p["card_types"] == ["creature", "battle"]
    assert p["unless_pays"] == "{4}"
    assert p["on_pay_effect_specs"] == [
        {"type": "create_token", "params": {
            "count": 1, "token_name": "Incubator",
            "extra_counters": {"kind": "+1/+1", "count": 2},
        }},
    ]
    # a bare "counter … unless pays" (no reflexive) still parses, no on_pay
    bare = match_clause("counter target spell unless its controller pays {3}", self_subject=True)
    assert bare is not None and "on_pay_effect_specs" not in bare[0].params


def test_if_prev_creature_cant_block_clause():
    specs = match_clause("if it's a creature, it can't block this turn")
    assert specs == [EffectSpec(
        "cant_block_this_turn", {"previous_subject": True},
        condition={"previous_target_is_creature": True},
    )]


def test_cast_spell_targets_permanent_trigger_parses():
    card = Card(
        id="tof", name="Tiller of Flesh", type_line="Creature — Zombie",
        is_creature=True, power=2, toughness=2,
        oracle_text="Whenever you cast a spell that targets one or more permanents, "
                    "incubate 2.",
    )
    r = parse_oracle(card)
    assert r.coverage != UNMODELED, r.unclaimed
    spec = r.specs[0]
    assert spec.trigger["event"] == "SPELL_CAST"
    assert spec.trigger.get("requires_spell_targets_permanent") is True
    assert spec.effects[0].type == "create_token"


def test_real_cards_modeled():
    db = _db()
    for name in ("Assimilate Essence", "Searing Barb", "Tiller of Flesh", "Don't Make a Sound"):
        card = db.get_card(name)
        assert card is not None, name
        assert parse_oracle(card).coverage != UNMODELED, (name, parse_oracle(card).unclaimed)


# --- execute -------------------------------------------------------------------


def _engine():
    eng = GameEngine.new_game(
        [("p1", "p1", []), ("p2", "p2", [])], starting_life=20, starting_hand=0
    )
    eng.begin_turn()
    eng.state.current_step = "main1"
    return eng


def _push_spell(eng, player_id, card):
    """A bare spell on the stack (bypassing casting/payment — the effect
    under test is the counter, not casting)."""
    obj = GameObject(card, owner_id=player_id, zone=Zone.STACK)
    obj.controller_id = player_id
    eng.state.stack.append(StackItem(
        kind="spell", controller_id=player_id, obj=obj,
        description=card.name, effects=[],
    ))
    return obj


def test_searing_barb_cant_block_only_bites_a_creature_target():
    eng = _engine()
    st = eng.state
    p1, p2 = st.players
    src = GameObject(_db().get_card("Searing Barb"), owner_id="p1", zone=Zone.STACK)
    src.controller_id = "p1"
    blocker = GameObject(Card(id="wall", name="Wall", type_line="Creature — Wall",
                              is_creature=True, power=0, toughness=4),
                         owner_id="p2", zone=Zone.BATTLEFIELD)
    blocker.controller_id = "p2"
    blocker.summoning_sick = False
    st.add_to_battlefield(blocker)

    effs = build_effects(parse_oracle(src.card).specs[0].effects, src)
    _apply_effects_partitioned(effs, eng.rules.context, [blocker], None, source=src)

    assert blocker.damage_marked == 2
    assert getattr(blocker, "temp_cant_block", False) is True
    toks = [o for o in st.battlefield if getattr(o, "is_token", False)]
    assert len(toks) == 1 and toks[0].name == "Incubator"


def test_searing_barb_cant_block_rider_is_inert_on_a_player_target():
    eng = _engine()
    st = eng.state
    p1, p2 = st.players
    src = GameObject(_db().get_card("Searing Barb"), owner_id="p1", zone=Zone.STACK)
    src.controller_id = "p1"

    effs = build_effects(parse_oracle(src.card).specs[0].effects, src)
    # "any target" resolves onto a player — the can't-block clause must
    # no-op rather than crash, and the incubate still happens
    _apply_effects_partitioned(effs, eng.rules.context, [p2], None, source=src)

    assert p2.life == 18
    assert [o for o in st.battlefield if getattr(o, "is_token", False)]


def test_assimilate_essence_incubates_only_when_the_controller_pays():
    eng = _engine()
    st = eng.state
    p1, p2 = st.players
    src = GameObject(_db().get_card("Assimilate Essence"), owner_id="p1", zone=Zone.STACK)
    src.controller_id = "p1"
    target = _push_spell(eng, "p2", Card(id="bear", name="Bear",
                                         type_line="Creature — Bear", is_creature=True,
                                         power=2, toughness=2))
    p2.mana_pool.add("C", 4)  # p2 *can* pay, so the choice opens

    effs = build_effects(parse_oracle(src.card).specs[0].effects, src)
    effs[0].apply(eng.rules.context, [target])

    choice = st.pending_choice
    assert choice is not None and choice["kind"] == "counter_unless_pays"
    eng.rules.resolve_counter_unless_pays_choice("pay")

    assert target in [i.obj for i in st.stack]  # paid → not countered
    toks = [o for o in st.battlefield if getattr(o, "is_token", False)]
    assert len(toks) == 1 and toks[0].name == "Incubator"
    assert toks[0].counters.get("+1/+1") == 2


def test_assimilate_essence_no_incubate_on_the_counter_branch():
    eng = _engine()
    st = eng.state
    p1, p2 = st.players
    src = GameObject(_db().get_card("Assimilate Essence"), owner_id="p1", zone=Zone.STACK)
    src.controller_id = "p1"
    target = _push_spell(eng, "p2", Card(id="bear", name="Bear",
                                         type_line="Creature — Bear", is_creature=True,
                                         power=2, toughness=2))
    p2.mana_pool.add("C", 4)  # p2 could pay, but will decline

    effs = build_effects(parse_oracle(src.card).specs[0].effects, src)
    effs[0].apply(eng.rules.context, [target])
    assert st.pending_choice is not None
    eng.rules.resolve_counter_unless_pays_choice(None)  # decline → countered

    assert not [o for o in st.battlefield if getattr(o, "is_token", False)]
    assert target not in [i.obj for i in st.stack]
