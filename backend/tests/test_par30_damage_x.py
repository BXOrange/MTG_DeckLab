"""PAR-30 — "{X}-scaled damage" effect-body handler.

`_damage_x` claims "~ deals X damage to <target>" (digit-free, so no overlap
with the `NUMBER`-based `damage` row) and emits `EffectSpec("damage",
{"amount": "x"})` — the `"x"` sentinel `RulesEngine._substitute_x` already
rewrites off the spell/ability's announced {X} at resolution. Closes ~20
classic X-burn spells and activated abilities (Blaze, Devil's Play, Fanning
the Flames, Volcanic Geyser, Cinder Elemental, Heat Ray, Pain Kami, …) plus
Titan's Revenge (a clash card blocked on its pre-clash "~ deals X damage to
any target" clause).
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import build_effects
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle
from mtg_analyzer.parser.oracle.spec import EffectSpec


def test_damage_x_clause_forms():
    assert match_clause("~ deals x damage to any target") == [
        EffectSpec("damage", {"amount": "x", "target_kind": "any"})
    ]
    assert match_clause("it deals x damage to target creature") == [
        EffectSpec("damage", {"amount": "x", "target_kind": "creature"})
    ]
    # a plain digit still routes through the ordinary `damage` row
    assert match_clause("~ deals 3 damage to any target")[0].params["amount"] == 3


def test_real_x_burn_cards_modeled():
    for name, tl, text in [
        ("Blaze", "Sorcery", "Blaze deals X damage to any target."),
        ("Heat Ray", "Instant", "Heat Ray deals X damage to target creature."),
        ("Cinder Elemental", "Creature — Elemental",
         "{X}{R}, {T}, Sacrifice Cinder Elemental: It deals X damage to any target."),
        ("Titan's Revenge", "Sorcery",
         "Titan's Revenge deals X damage to any target. Clash with an opponent. "
         "If you win, return Titan's Revenge to its owner's hand."),
    ]:
        c = Card(id=name[:4], name=name, type_line=tl,
                 is_sorcery=tl == "Sorcery", is_instant=tl == "Instant",
                 is_creature="Creature" in tl,
                 power=2 if "Creature" in tl else None,
                 toughness=2 if "Creature" in tl else None,
                 oracle_text=text)
        assert parse_oracle(c).coverage != UNMODELED, (name, parse_oracle(c).unclaimed)


def test_damage_x_resolves_against_announced_x():
    eng = GameEngine.new_game(
        [("p1", "A", []), ("p2", "B", [])], starting_life=20, starting_hand=0
    )
    st = eng.state
    ox = GameObject(
        Card(id="OX", name="Ox", type_line="Creature — Ox", is_creature=True,
             power=3, toughness=3),
        owner_id="p2", zone=Zone.BATTLEFIELD,
    )
    ox.controller_id = "p2"
    st.add_to_battlefield(ox)
    src = GameObject(Card(id="BLZ", name="Blaze", type_line="Sorcery", is_sorcery=True),
                     owner_id="p1", zone=Zone.STACK)
    src.controller_id = "p1"

    eff = build_effects(
        [EffectSpec("damage", {"amount": "x", "target_kind": "any"})], src
    )[0]
    eng.rules._substitute_x([eff], 4)
    assert eff.amount == 4
    eff.apply(eng.rules.context, [ox])
    eng.rules.check_state_based_actions()
    assert ox not in st.battlefield  # 4 >= 3 toughness

    # a player target
    p2 = st.player_by_id("p2")
    eff2 = build_effects(
        [EffectSpec("damage", {"amount": "x", "target_kind": "any"})], src
    )[0]
    eng.rules._substitute_x([eff2], 5)
    eff2.apply(eng.rules.context, [p2])
    assert p2.life == 15
