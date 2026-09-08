"""PAR-30 — "tapped and attacking **that player / that opponent**" trailing
defender ref (RULE 508.1 / 508.4).

The put-from-hand (`_PUT_FROM_HAND_RE`), look-top
(`_LOOK_TOP_PUT_ATTACKING_RE`), inline-create-token (`_TOKEN_TAPPED_
ATTACKING`) and "the token enters …" (`_CREATED_ENTERS_ATTACKING_RE`)
routes all gained an optional trailing "that player"/"that opponent". The
named defender is the one the source is already attacking, which
`RulesEngine.put_onto_battlefield_attacking` derives from the other
attackers, so the phrase is consumed rather than re-modeled. Alongside it,
`_SELF_SUBJECT_RE` and the `PLAYER_ATTACKED` row accept "~ attacks a
player"/"an opponent" and "you attack a player" — the defender kind refines
nothing the bare event doesn't already carry.
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue, build_effects
from mtg_analyzer.game.effects.core import GameContext
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle
from mtg_analyzer.parser.oracle.spec import EffectSpec


def _engine():
    eng = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )
    return eng, eng.state


# --- parse: the defender-ref suffix is consumed, not modeled ---------------


def test_inline_token_defender_suffix_consumed():
    with_suffix = match_clause(
        "create a 1/1 white glimmer enchantment creature token "
        "that's tapped and attacking that player"
    )
    without = match_clause(
        "create a 1/1 white glimmer enchantment creature token "
        "that's tapped and attacking"
    )
    assert with_suffix == without
    assert with_suffix is not None
    assert with_suffix[0].params["tapped"] is True
    assert with_suffix[0].params["attacking"] is True


def test_put_from_hand_defender_suffix_consumed():
    with_suffix = match_clause(
        "you may put an angel, demon, or dragon creature card from your hand "
        "onto the battlefield tapped and attacking that opponent"
    )
    without = match_clause(
        "you may put an angel, demon, or dragon creature card from your hand "
        "onto the battlefield tapped and attacking"
    )
    assert with_suffix == without
    assert with_suffix is not None
    assert with_suffix[0].params["attacking"] is True


def test_plain_put_from_hand_without_attacking_still_bare():
    # a "that player" without "tapped and attacking" is not a defender ref —
    # the suffix only rides on the attacking form.
    assert match_clause(
        "put a creature card from your hand onto the battlefield"
    ) == [EffectSpec("put_from_hand_onto_battlefield",
                     {"criteria": {"type": "creature"}, "count": 1})]


# --- parse: real cards ----------------------------------------------------


def test_soaring_lightbringer_modeled():
    c = Card(
        id="sl", name="Soaring Lightbringer",
        type_line="Enchantment Creature — Glimmer",
        is_creature=True, keywords=["Flying"],
        oracle_text=(
            "Flying\n"
            "Other enchantment creatures you control have flying.\n"
            "Whenever you attack a player, create a 1/1 white Glimmer "
            "enchantment creature token that's tapped and attacking that player."
        ),
    )
    res = parse_oracle(c)
    assert res.coverage != UNMODELED, res.unclaimed
    tok = [s for s in res.specs if s.ability_kind == "triggered"][0]
    inner = tok.effects[0]
    assert inner.params["tapped"] is True and inner.params["attacking"] is True


def _segment(text: str):
    from mtg_analyzer.parser.oracle.segmenter import segment_line
    from mtg_analyzer.parser.oracle.spec import ParserProvenance

    return segment_line(
        text, allow_spell_effect=False, provenance=ParserProvenance.from_dict({})
    )


def test_you_attack_a_player_is_player_attacked_trigger():
    seg = _segment(
        "whenever you attack a player, create a 1/1 white soldier creature "
        "token that's tapped and attacking that player"
    )
    assert seg.claimed
    assert seg.spec.trigger["event"] == "PLAYER_ATTACKED"


def test_self_attacks_an_opponent_is_attacks_trigger():
    seg = _segment("whenever ~ attacks an opponent, put a +1/+1 counter on ~")
    assert seg.claimed
    assert seg.spec.trigger["event"] == "ATTACKS"


# --- execute: the created thing really joins combat attacking -------------


def test_created_token_enters_attacking_via_auto_defender():
    eng, state = _engine()
    src = GameObject(
        Card(id="s", name="Src", type_line="Creature — Soldier",
             is_creature=True, power=2, toughness=2),
        owner_id="p1", zone=Zone.BATTLEFIELD,
    )
    src.controller_id = "p1"
    state.add_to_battlefield(src)
    # src is attacking p2 — the auto-defender source for the new token.
    src.attacking = True
    src.combat_defender = {"kind": "player", "id": "p2", "label": "Bob"}

    effects = build_effects(
        [EffectSpec("create_token", {
            "count": 1, "power": 1, "toughness": 1, "colors": ["W"],
            "subtypes": ["Soldier"], "keywords": [],
            "tapped": True, "attacking": True,
        })],
        src,
    )
    ctx = GameContext(state, eng.rules)
    for eff in effects:
        eff.apply(ctx, [])

    made = [o for o in state.battlefield if o.name == "Soldier"]
    assert len(made) == 1
    tok = made[0]
    assert tok.tapped is True
    assert getattr(tok, "attacking", False) is True
    assert (tok.combat_defender or {}).get("id") == "p2"
