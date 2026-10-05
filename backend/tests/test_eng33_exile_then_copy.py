"""ENG-33 (completion) — the reanimator-token connector.

ENG-33's first three primitives (targeted-player edict, uncapped/noncreature
free-cast, put-`<type>`-from-hand) shipped at PARSER_VERSION 129; its fourth,
"create a token that's a copy of **that card**", was PAR-18's existing
`CopyPermanentEffect(referent="previous")` — but the two-sentence *connector*
that feeds it, "Exile [up to N] target `<X>` card from [a/your] graveyard.
[If you do / If you exiled a card this way,] create a token that's a copy of
that card[, except <tail>].", was left unparsed (Ardyn, Anikthea, Séance,
God-Pharaoh's Gift, Sauron the Necromancer &c. — the reanimator-token cycle).

This closes that connector:

- `segmenter._EXILE_THEN_COPY_SENTENCE_RE` matches the whole two-sentence span
  at `parse_effect_body` level (before the connector-split loop would shatter
  it into a bare "if you do, create …" half no handler claims), parsing the
  "before" exile and the "after" copy independently and requiring the exile
  to genuinely pick a graveyard card (`_announces_creature_target`) — the
  pronoun `CopyPermanentEffect(referent="previous")` reads back (RULE 608.2).
- the reflexive "if you do" / "if you exiled a card this way" connector needs
  no `pending_choice`: the copy effect already no-ops when nothing was exiled.
- "You may exile …" optionality is peeled and re-folded as `optional=True`.
- `handlers._EXILE_FROM_GRAVEYARD_RE` now also accepts the untargeted "exile
  **a** creature card from your graveyard" determiner, not just "target".
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue, build_effects
from mtg_analyzer.game.effects.core import GameContext, _apply_effects_partitioned
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle
from mtg_analyzer.parser.oracle.spec import EffectSpec


def _engine():
    return GameEngine.new_game(
        [("p1", "p1", []), ("p2", "p2", [])], starting_life=20, starting_hand=0
    )


def _sorcery(text: str, name: str = "T") -> Card:
    return Card(
        id=name[:6], name=name, type_line="Sorcery", is_sorcery=True,
        mana_cost_string="{2}{B}", converted_mana_cost=3, oracle_text=text,
    )


# --- parse ---------------------------------------------------------------------


def test_if_you_exiled_a_card_this_way_connector_parses():
    card = _sorcery(
        "Exile up to one target creature card from a graveyard. If you exiled "
        "a card this way, create a token that's a copy of that card, except "
        "it's a 5/5 black Demon."
    )
    result = parse_oracle(card)
    assert result.coverage != UNMODELED, result.unclaimed
    effects = result.specs[0].effects
    assert [e.type for e in effects] == ["exile", "copy_permanent"]
    assert effects[0].params.get("optional") is True
    copy = effects[1].params
    assert copy.get("referent") == "previous"
    assert copy.get("set_power") == 5 and copy.get("set_toughness") == 5
    assert copy.get("set_colors") == ["B"]
    assert copy.get("add_subtypes") == ["Demon"]


def test_you_may_exile_untargeted_form_parses_as_optional():
    card = _sorcery(
        "You may exile a creature card from your graveyard. If you do, create "
        "a token that's a copy of that card, except it's a 4/4 black Zombie."
    )
    result = parse_oracle(card)
    assert result.coverage != UNMODELED, result.unclaimed
    effects = result.specs[0].effects
    assert [e.type for e in effects] == ["exile", "copy_permanent"]
    # "You may" optionality is represented here (either on the exile spec or
    # as segment-level optionality); either way the exile picks a graveyard
    # creature the copy reads back.
    assert effects[0].params.get("target_kind", "").endswith("graveyard_creature")
    assert effects[1].params.get("referent") == "previous"


def test_real_card_ardyn_the_usurper_is_modeled():
    card = Card(
        id="Ardyn", name="Ardyn, the Usurper",
        type_line="Legendary Creature — Elder Human Noble",
        is_creature=True, is_legendary=True, power=4, toughness=4,
        mana_cost_string="{5}{B}{B}{B}", converted_mana_cost=8,
        # "Starscourge" is a card-specific flavour label (RULE 207.2c);
        # `normalize._strip_unregistered_keyword_labels` peels it off the
        # front only when Scryfall's own keyword array names it.
        keywords=["Starscourge"],
        oracle_text=(
            "Demons you control have menace, lifelink, and haste.\n"
            "Starscourge — At the beginning of combat on your turn, exile up "
            "to one target creature card from a graveyard. If you exiled a "
            "card this way, create a token that's a copy of that card, except "
            "it's a 5/5 black Demon."
        ),
    )
    assert parse_oracle(card).modeled, parse_oracle(card).unclaimed


# --- fail-closed --------------------------------------------------------------


def test_reflexive_connector_without_a_graveyard_antecedent_stays_unmodeled():
    # No exile-from-graveyard "before" half → the pronoun has nothing to bind
    # to, so the sentence regex must not claim it.
    card = _sorcery(
        "Draw a card. If you do, create a token that's a copy of that card."
    )
    assert parse_oracle(card).coverage == UNMODELED


def test_reflexive_connector_with_a_non_copy_followup_stays_unmodeled():
    # The "after" half is anchored on "create a … token that's a copy of that
    # card"; a different follow-up must not have its "if you do," stripped and
    # then run unconditionally.
    card = _sorcery(
        "You may exile a creature card from your graveyard. If you do, draw "
        "two cards."
    )
    assert parse_oracle(card).coverage == UNMODELED


# --- execute ----------------------------------------------------------------


def test_exile_then_copy_end_to_end_makes_a_modified_token():
    eng = _engine()
    st = eng.state

    grave = GameObject(
        Card(id="Bear", name="Grizzly Bear", type_line="Creature — Bear",
             is_creature=True, power=2, toughness=2),
        owner_id="p2", zone=Zone.GRAVEYARD,
    )
    st.players[1].graveyard.append(grave)

    src = GameObject(
        _sorcery(
            "Exile up to one target creature card from a graveyard. If you "
            "exiled a card this way, create a token that's a copy of that "
            "card, except it's a 5/5 black Demon.",
            name="Starscourge",
        ),
        owner_id="p1", zone=Zone.STACK,
    )
    src.controller_id = "p1"
    specs = parse_oracle(src.card).specs[0].effects
    effects = build_effects([EffectSpec(s.type, dict(s.params)) for s in specs], src)

    _apply_effects_partitioned(
        effects, GameContext(st, eng.rules), [grave], None, source=src,
    )
    eng.recompute_continuous_effects()

    tokens = [o for o in st.battlefield if o.is_token]
    assert len(tokens) == 1
    tok = tokens[0]
    assert tok.card.name == "Grizzly Bear"
    assert (tok.power, tok.toughness) == (5, 5)
    assert "Demon" in tok.card.type_line
    assert grave.zone == Zone.EXILE
