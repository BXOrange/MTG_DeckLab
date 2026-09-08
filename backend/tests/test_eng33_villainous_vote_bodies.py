"""ENG-33 — villainous-choice / vote option-body primitives.

The `face_villainous_choice` (RULE 701.55) and `vote` (RULE 701.38) parsers
only claim a card when *every* option/outcome body is modelable. ENG-33 adds
three general handlers — each of which also unlocks a large family of
ordinary spells:

1. **target-player edict** — "target player/opponent sacrifices [N]
   [nontoken] <what> [of their choice]" → `sacrifice` with the new
   `SacrificeEffect.target_kind="player"` RULE 115 player target (Diabolic
   Edict / Chainer's Edict, and the villainous/vote *other* option).
2. **uncapped free-cast** — "you may cast a[ noncreature] spell from your
   hand without paying its mana cost" with the mana-value cap now optional
   (`FreeCastFromHandEffect.noncreature_only`) — Great Intelligence's Plan.
3. **put a `<type>` card from hand onto the battlefield** → the existing
   `PutFromHandOntoBattlefieldEffect` (Dr. Eggman, plus Elvish Piper /
   Quicksilver Amulet / Growth Spiral / Sakura-Tribe Scout …).

Reference: game/effects/core.py (`SacrificeEffect.target_kind`,
`FreeCastFromHandEffect.noncreature_only`), parser/oracle/catalogue/
handlers.py (`_target_player_edict`, `_free_cast_from_hand`, `_put_from_hand`).
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.spec import EffectSpec


# --- parse -----------------------------------------------------------------


def test_target_player_edict_parses():
    assert match_clause("target player sacrifices a creature of their choice") == [
        EffectSpec("sacrifice", {"target_kind": "player", "what": "creature", "count": 1})
    ]
    assert match_clause(
        "target opponent sacrifices 2 nontoken creatures of their choice"
    ) == [EffectSpec("sacrifice", {
        "target_kind": "player", "what": "nontoken_creature", "count": 2,
    })]


def test_uncapped_free_cast_parses():
    assert match_clause(
        "you may cast a spell from your hand without paying its mana cost"
    ) == [EffectSpec("free_cast_from_hand", {})]
    assert match_clause(
        "you may cast a noncreature spell from your hand without paying its mana cost"
    ) == [EffectSpec("free_cast_from_hand", {"noncreature_only": True})]
    # the capped MEC-20 "Expertise" form still parses unchanged
    assert match_clause(
        "cast a spell with mana value 3 or less from your hand without paying its mana cost"
    ) == [EffectSpec("free_cast_from_hand", {"max_mana_value": 3})]


def test_put_type_from_hand_parses_and_fails_closed():
    assert match_clause(
        "you may put a construct, robot, or vehicle card from your hand onto the battlefield"
    ) == [EffectSpec("put_from_hand_onto_battlefield", {
        "criteria": {"type": ["construct", "robot", "vehicle"]}, "count": 1,
    })]
    assert match_clause(
        "put a land card from your hand onto the battlefield"
    ) == [EffectSpec("put_from_hand_onto_battlefield", {
        "criteria": {"type": "land"}, "count": 1,
    })]
    # an unrecognised type word → fail-closed
    assert match_clause(
        "you may put a bogus card from your hand onto the battlefield"
    ) is None


def test_villainous_option_bodies_now_claim_cards():
    assert parse_oracle(Card(
        id="GIP", name="Great Intelligence's Plan", type_line="Sorcery",
        is_sorcery=True, mana_cost_string="{4}{U}",
        oracle_text="Draw three cards. Then target opponent faces a villainous "
                    "choice — They discard three cards, or you may cast a spell "
                    "from your hand without paying its mana cost.",
    )).modeled


def test_copy_of_referenced_card_body_still_fail_closed():
    # PAR-30 — "create a token that's a copy of that card" needs the
    # "except it's a 3/3 …" modifier grammar + a preceding clause that
    # populates `previous_targets`.
    assert match_clause(
        "target opponent faces a villainous choice — they discard 3 cards, or "
        "you create a token that's a copy of that card"
    ) is None


# --- execute -------------------------------------------------------------------


def _engine():
    eng = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )
    return eng, eng.state


def _creature(state, pid, name):
    o = GameObject(Card(id=name, name=name, type_line="Creature — Bear",
                        is_creature=True, power=2, toughness=2),
                   owner_id=pid, zone=Zone.BATTLEFIELD)
    o.controller_id = pid
    state.add_to_battlefield(o)
    return o


def test_diabolic_edict_targets_a_player_and_they_pick():
    eng, st = _engine()
    p2 = st.player_by_id("p2")
    keep = _creature(st, "p2", "Keeper")
    doomed = _creature(st, "p2", "Doomed")

    spell = GameObject(
        Card(id="DE", name="Diabolic Edict", type_line="Instant", is_instant=True,
             mana_cost_string="{1}{B}",
             oracle_text="Target player sacrifices a creature of their choice."),
        owner_id="p1", zone=Zone.STACK,
    )
    spell.controller_id = "p1"
    bind_from_catalogue(spell)
    assert spell.spell_effects[0].target_spec.kind == "player"

    for e in spell.spell_effects:
        e.apply(eng.rules.context, [p2])
    assert st.pending_choice["kind"] == "choose_objects"
    assert st.pending_choice["player_id"] == "p2"
    pick = next(o["id"] for o in st.pending_choice["options"] if o.get("label") == "Doomed")
    eng.resolve_pending_choice(pick)

    assert doomed not in st.battlefield
    assert keep in st.battlefield


def test_uncapped_free_cast_offers_every_nonland_hand_card():
    eng, st = _engine()
    p1 = st.player_by_id("p1")
    for i, (name, tl, is_creature) in enumerate([
        ("Bolt", "Instant", False), ("Ogre", "Creature — Ogre", True),
    ]):
        o = GameObject(Card(id=f"h{i}", name=name, type_line=tl,
                            is_creature=is_creature, is_instant=not is_creature,
                            mana_cost_string="{9}{R}"),
                       owner_id="p1", zone=Zone.HAND)
        o.controller_id = "p1"
        p1.hand.append(o)
    land = GameObject(Card(id="L", name="Wastes", type_line="Land", is_land=True),
                      owner_id="p1", zone=Zone.HAND)
    land.controller_id = "p1"
    p1.hand.append(land)

    src = GameObject(Card(id="s", name="Src", type_line="Enchantment"),
                     owner_id="p1", zone=Zone.BATTLEFIELD)
    src.controller_id = "p1"
    st.add_to_battlefield(src)
    eff = EffectSpec("free_cast_from_hand", {})
    from mtg_analyzer.game.binding.core import build_effects

    build_effects([eff], src)[0].apply(eng.rules.context, None)
    assert st.pending_choice["kind"] == "choose_objects"
    labels = {o["label"] for o in st.pending_choice["options"] if o.get("label") != "Nichts wählen"}
    assert labels == {"Bolt", "Ogre"}  # both nonland cards, no cap; land excluded


def test_put_type_from_hand_only_offers_matching_cards():
    eng, st = _engine()
    p1 = st.player_by_id("p1")
    art = GameObject(Card(id="a", name="Widget", type_line="Artifact"),
                     owner_id="p1", zone=Zone.HAND)
    art.controller_id = "p1"
    p1.hand.append(art)
    crt = GameObject(Card(id="c", name="Beast", type_line="Creature — Beast",
                          is_creature=True, power=3, toughness=3),
                     owner_id="p1", zone=Zone.HAND)
    crt.controller_id = "p1"
    p1.hand.append(crt)

    src = GameObject(Card(id="s", name="Src", type_line="Enchantment"),
                     owner_id="p1", zone=Zone.BATTLEFIELD)
    src.controller_id = "p1"
    st.add_to_battlefield(src)
    from mtg_analyzer.game.binding.core import build_effects

    build_effects(
        [EffectSpec("put_from_hand_onto_battlefield", {"criteria": {"type": "artifact"}, "count": 1})],
        src,
    )[0].apply(eng.rules.context, None)

    opts = [o for o in st.pending_choice["options"] if o.get("label") != "Nichts wählen"]
    assert [o["label"] for o in opts] == ["Widget"]
    eng.resolve_pending_choice(opts[0]["id"])
    assert art in st.battlefield
    assert crt not in st.battlefield
