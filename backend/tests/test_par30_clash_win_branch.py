"""PAR-30 — Clash (RULE 701.30) win-branch residue, batch 1.

The `if you win, <effect>` / `whenever you win a clash, <effect>` bodies each
need ordinary effect grammar; this batch closes a cohesive first slice:

- "Whenever you **clash and win**, …" as a WON_CLASH trigger phrasing
  (Sylvan Echoes) alongside the existing "you win a clash".
- `_FREE_CAST_FROM_HAND_RE` accepts "…spell **from your hand** with mana
  value N or less…" word order (Marvo, Deep Operative) as well as the
  Expertise-cycle "…with mana value N or less from your hand…".
- `return_self_to_hand` accepts "return **this card** to its owner's hand"
  (Ringskipper — a "when ~ dies" clash-win body, source in the graveyard).
- The connector-split loop treats a bare `clash` spec as a
  **referent-transparent** interstitial, so "create 2 tokens. clash with an
  opponent. if you win, **those creatures** gain deathtouch …" (Gilt-Leaf
  Ambush) keeps its pronoun chain across the clash sentence.
- `_PUMP_PREV_SINGULAR_PT_RE` accepts "gets **an additional** +N/+N"
  (Fistful of Force).
"""

from __future__ import annotations

from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body


def _sorcery(name: str, text: str) -> Card:
    return Card(id=name[:6], name=name, type_line="Sorcery", is_sorcery=True,
                oracle_text=text)


def test_clash_and_win_trigger_phrasing():
    c = Card(id="SYLE", name="Sylvan Echoes", type_line="Enchantment",
             oracle_text="Whenever you clash and win, you may draw a card.")
    r = parse_oracle(c)
    assert r.coverage != UNMODELED, r.unclaimed
    assert r.specs[0].trigger["event"] == "WON_CLASH"


def test_free_cast_from_hand_both_word_orders():
    a = match_clause(
        "cast a spell with mana value 8 or less from your hand without paying its mana cost"
    )
    b = match_clause(
        "cast a spell from your hand with mana value 8 or less without paying its mana cost"
    )
    assert a == b == [
        __import__("mtg_analyzer.parser.oracle.spec", fromlist=["EffectSpec"]).EffectSpec(
            "free_cast_from_hand", {"max_mana_value": 8}
        )
    ]


def test_return_this_card_to_its_owners_hand():
    got = match_clause("return this card to its owner's hand")
    assert got is not None and got[0].type == "return_to_hand"
    assert got[0].params.get("target_kind") is None


def test_clash_is_referent_transparent_in_connector_split():
    specs = parse_effect_body(
        "create 2 1/1 green elf warrior creature tokens. clash with an "
        "opponent. if you win, those creatures gain deathtouch until end of turn."
    )
    assert specs is not None
    kinds = [s.type for s in specs]
    assert kinds == ["create_token", "clash", "pump"]
    assert specs[2].params.get("previous_subject") is True
    assert specs[2].params.get("keywords") == ["deathtouch"]
    assert specs[2].condition == {"kind": "clash_won"}


def test_pump_prev_singular_accepts_an_additional():
    got = match_clause(
        "that creature gets an additional +2/+2 and gains trample until end of turn",
        previous_subject=True,
    )
    assert got is not None and got[0].type == "pump"
    assert got[0].params["power"] == 2 and got[0].params["toughness"] == 2
    assert "trample" in got[0].params.get("keywords", [])


def test_destroy_all_opponents_enchantments():
    got = match_clause("destroy all enchantments your opponents control")
    assert got == [__import__(
        "mtg_analyzer.parser.oracle.spec", fromlist=["EffectSpec"]
    ).EffectSpec("destroy", {"selector": "opponents_enchantments"})]
    # a scope on a noun with no named opponent-scoped selector reads as a structured group
    # (PAR-128 `DestroyEffect.group`) instead of failing closed
    [land] = match_clause("destroy all lands your opponents control")
    assert land.params == {"group": {"zone": "battlefield", "of": "opponents", "filter": {"card_type": "land"}}}


def test_real_clash_cards_modeled():
    for name, tl, text in [
        ("Sylvan Echoes", "Enchantment",
         "Whenever you clash and win, you may draw a card."),
        ("Spring Cleaning", "Sorcery",
         "Destroy target enchantment. Clash with an opponent. If you win, "
         "destroy all enchantments your opponents control."),
        ("Ringskipper", "Creature — Merfolk Rogue",
         "When Ringskipper dies, clash with an opponent. If you win, return "
         "this card to its owner's hand."),
        ("Gilt-Leaf Ambush", "Instant",
         "Create two 1/1 green Elf Warrior creature tokens. Clash with an "
         "opponent. If you win, those creatures gain deathtouch until end of turn."),
        ("Fistful of Force", "Instant",
         "Target creature gets +2/+2 until end of turn. Clash with an opponent. "
         "If you win, that creature gets an additional +2/+2 and gains trample "
         "until end of turn."),
        ("Marvo, Deep Operative", "Legendary Creature — Merfolk",
         "Whenever Marvo attacks, clash with defending player.\nWhenever you "
         "win a clash, draw a card. Then you may cast a spell from your hand "
         "with mana value 8 or less without paying its mana cost."),
    ]:
        c = Card(id=name[:5], name=name, type_line=tl,
                 is_creature="Creature" in tl, is_instant=tl == "Instant",
                 is_sorcery=tl == "Sorcery", mana_cost_string="{2}{W}",
                 power=1 if "Creature" in tl else None,
                 toughness=1 if "Creature" in tl else None,
                 oracle_text=text)
        assert parse_oracle(c).coverage != UNMODELED, (name, parse_oracle(c).unclaimed)
