"""Batch 8 (docs/implementation-state/BACKLOG.md):
"permission / 'you may' statics" — extra land drops, no maximum hand size,
and an optional "may choose not to untap" toggle. None of these are about a
permanent's own characteristics (RULE 613), so unlike most static families
they're consulted by per-*player*/per-*object* helpers in `game/continuous.py`
rather than the layer engine proper — the same treatment `cast_limit`/
`draw_limit`/`no_untap` already got.

Three new "static" layers (`extra_land_drop`, `no_max_hand_size`,
`no_untap_optional` — all plain `StaticAbility` instances, no new `GameEffect`
classes needed) plus one new one-shot `GameEffect`/`EffectSpec`
(`ExtraLandPlayEffect`/``extra_land_play``, the one-turn resolve-time sibling
of the standing `extra_land_drop` static, Explore/Escape to the Wilds-shaped).

"May choose not to untap" needed one real engine primitive: since
`GameEngine._step_untap` has no mid-untap-step pause to ask the controller
fresh every turn, the choice is a standing toggle instead (`GameObject.
skip_untap`, `GameEngine.set_skip_untap`) — sticky until changed again, only
honoured while the object actually carries the `"no_untap_optional"` grant.

Investigation note: sampling the real "choose not to untap" backlog (Batson
Monolith-style artifacts, Rubinia Soulsinger/Hivis of the Scale-shaped
creatures) found every single one *also* has a second unclaimed clause (an
Aura/Equipment-shaped "for as long as ~ remains tapped" targeted lock, or a
storage-counter upkeep trigger) — so this family's real yield is 0 cards
today under the all-or-nothing coverage gate, same "upper bound overcounts"
pattern every previous batch's progress-log entry already flags. It's still
worth having: it'll flip the moment either sibling family is built, and any
future card with a *plain* "you may choose not to untap ~..." clause and
nothing else claims it immediately.

Reference: mtg_analyzer/parser/oracle/catalogue/{static_handlers,handlers}.py,
mtg_analyzer/game/{effects,continuous,game_engine}.py,
mtg_analyzer/models/{player,game_object}.py.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game import continuous
from mtg_analyzer.game.binding.core import attach_to_object, bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.models.game.game_state import GameState
from mtg_analyzer.models.game.player import Player
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle


def _permanent(name, oracle_text, type_line="Artifact"):
    return Card(id=name, name=name, type_line=type_line, oracle_text=oracle_text)


def _land(name="Forest"):
    return Card(id=name, name=name, type_line="Basic Land — Forest", is_land=True)


def _engine():
    p1 = Player(id="p1", name="Alice", life=20)
    p2 = Player(id="p2", name="Bob", life=20)
    state = GameState(players=[p1, p2])
    engine = GameEngine(state)
    return engine, state, p1, p2


def _bf(state, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


def _in_hand(player, card):
    obj = GameObject(card, owner_id=player.id, zone=Zone.HAND)
    player.hand.append(obj)
    return obj


# ---------------------------------------------------------------------------
# Parse-side coverage
# ---------------------------------------------------------------------------


def test_exploration_shaped_extra_land_drop_is_modeled():
    card = _permanent(
        "Exploration", "You may play an additional land on each of your turns.", type_line="Enchantment"
    )
    result = parse_oracle(card)
    assert result.unclaimed == []
    static = next(s for s in result.specs if s.ability_kind == "static")
    assert static.effects[0].type == "extra_land_drop"
    assert static.effects[0].params == {"affects": "you", "count": 1}


def test_azusa_shaped_two_additional_lands_is_modeled():
    card = _permanent(
        "Azusa Shaped", "You may play two additional lands on each of your turns.",
        type_line="Creature — Human Shaman",
    )
    result = parse_oracle(card)
    assert result.unclaimed == []
    static = next(s for s in result.specs if s.ability_kind == "static")
    assert static.effects[0].params == {"affects": "you", "count": 2}


def test_each_player_extra_land_drop_is_modeled():
    card = _permanent(
        "Rites of Flourishing Shaped",
        "Each player may play an additional land on each of their turns.",
        type_line="Enchantment",
    )
    result = parse_oracle(card)
    assert result.unclaimed == []
    static = next(s for s in result.specs if s.ability_kind == "static")
    assert static.effects[0].params == {"affects": "each_player", "count": 1}


def test_no_maximum_hand_size_is_modeled():
    card = _permanent("Reliquary Tower Shaped", "You have no maximum hand size.", type_line="Land")
    result = parse_oracle(card)
    assert result.unclaimed == []
    static = next(s for s in result.specs if s.ability_kind == "static")
    assert static.effects[0].type == "no_max_hand_size"
    assert static.effects[0].params == {"affects": "you"}


def test_players_have_no_maximum_hand_size_is_modeled():
    card = _permanent("Anvil of Bogardan Shaped", "Players have no maximum hand size.")
    result = parse_oracle(card)
    assert result.unclaimed == []
    static = next(s for s in result.specs if s.ability_kind == "static")
    assert static.effects[0].params == {"affects": "each_player"}


def test_durational_no_max_hand_size_stays_unclaimed():
    # Fail-closed: the resolve-time "for the rest of the game" variant is a
    # different shape (not a standing permanent's static) and isn't claimed.
    card = _permanent(
        "Choice of Fortunes Shaped", "You have no maximum hand size for the rest of the game.",
        type_line="Sorcery",
    )
    card.is_sorcery = True
    assert parse_oracle(card).coverage == UNMODELED


def test_may_choose_not_to_untap_is_modeled():
    card = _permanent(
        "Rubinia Soulsinger Shaped",
        "You may choose not to untap this creature during your untap step.",
        type_line="Creature — Human Wizard",
    )
    result = parse_oracle(card)
    assert result.unclaimed == []
    static = next(s for s in result.specs if s.ability_kind == "static")
    assert static.effects[0].type == "no_untap_optional"


def test_may_choose_not_to_untap_with_trailing_clause_stays_unclaimed():
    # Fail-closed regression (Grand Marshal Macie-shaped): the "if you do, …"
    # tail is a different, unmodeled compound effect — don't half-claim it.
    card = _permanent(
        "Grand Marshal Macie Shaped",
        "You may choose not to untap ~ during your untap step. If you do, put a "
        "pause counter on it, then you lose 1 life for each pause counter on it.",
        type_line="Creature — Human Soldier",
    )
    assert parse_oracle(card).coverage == UNMODELED


def test_extra_land_play_one_shot_is_modeled():
    card = Card(
        id="Explore Shaped", name="Explore Shaped", type_line="Sorcery",
        oracle_text="Draw a card. You may play an additional land this turn.",
        mana_cost_string="{1}{G}", converted_mana_cost=2, is_sorcery=True,
    )
    result = parse_oracle(card)
    assert result.unclaimed == []
    spell = next(s for s in result.specs if s.ability_kind == "spell_effect")
    kinds = [e.type for e in spell.effects]
    assert kinds == ["draw", "extra_land_play"]
    assert spell.effects[1].params == {"count": 1}


def test_extra_land_play_up_to_n_is_modeled():
    card = Card(
        id="Summer Bloom Shaped", name="Summer Bloom Shaped", type_line="Sorcery",
        oracle_text="You may play up to three additional lands this turn.",
        mana_cost_string="{G}", converted_mana_cost=1, is_sorcery=True,
    )
    result = parse_oracle(card)
    assert result.unclaimed == []
    spell = next(s for s in result.specs if s.ability_kind == "spell_effect")
    assert spell.effects[0].params == {"count": 3}


# ---------------------------------------------------------------------------
# Execute-side
# ---------------------------------------------------------------------------


def test_extra_land_drop_static_lets_controller_play_two_lands():
    engine, state, p1, p2 = _engine()
    _bf(state, _permanent(
        "Exploration", "You may play an additional land on each of your turns.", type_line="Enchantment"
    ))
    state.current_step = "main1"
    first = _in_hand(p1, _land("Forest"))
    second = _in_hand(p1, _land("Island"))

    assert engine.can_play_land(p1, first)
    engine.play_land(p1, first)
    assert engine.can_play_land(p1, second)  # the extra drop, not the base one
    engine.play_land(p1, second)
    assert p1.lands_played_this_turn == 2


def test_extra_land_drop_affects_you_by_default_not_the_opponent():
    engine, state, p1, p2 = _engine()
    _bf(state, _permanent(
        "Exploration", "You may play an additional land on each of your turns.", type_line="Enchantment"
    ), controller="p1")
    assert continuous.extra_land_plays_for(state, p1) == 1
    assert continuous.extra_land_plays_for(state, p2) == 0


def test_each_player_extra_land_drop_applies_regardless_of_controller():
    engine, state, p1, p2 = _engine()
    _bf(state, _permanent(
        "Rites of Flourishing Shaped",
        "Each player may play an additional land on each of their turns.",
        type_line="Enchantment",
    ), controller="p1")
    assert continuous.extra_land_plays_for(state, p1) == 1
    assert continuous.extra_land_plays_for(state, p2) == 1


def test_extra_land_play_one_shot_lets_you_play_extra_land_this_turn_only():
    engine, state, p1, p2 = _engine()
    engine.begin_turn()
    state.current_step = "main1"
    a, b = _in_hand(p1, _land("Forest")), _in_hand(p1, _land("Island"))

    assert engine.can_play_land(p1, a)
    engine.play_land(p1, a)
    assert not engine.can_play_land(p1, b)  # no grant yet

    card = Card(
        id="Explore Shaped", name="Explore Shaped", type_line="Sorcery",
        oracle_text="You may play an additional land this turn.",
        mana_cost_string="{G}", converted_mana_cost=1, is_sorcery=True,
    )
    result = parse_oracle(card)
    assert result.modeled
    spell_obj = GameObject(card, owner_id="p1", zone=Zone.HAND)
    attach_to_object(spell_obj, result.specs)
    p1.hand.append(spell_obj)
    p1.mana_pool.add_many({"G": 5})

    engine.cast_spell(p1, spell_obj)
    engine.resolve_until_stable()

    assert p1.extra_land_plays_this_turn == 1
    assert engine.can_play_land(p1, b)
    engine.play_land(p1, b)

    # The grant lapses once it's p1's own next turn (RULE 305.2 — "this
    # turn" only) — `begin_turn` only resets the *new* active player's
    # counter each call (matching `lands_played_this_turn`'s own reset), so
    # this needs a full round trip: p1 -> p2 -> p1 again.
    engine.begin_turn()
    engine.begin_turn()
    assert state.active_player is p1
    assert p1.extra_land_plays_this_turn == 0


def test_no_max_hand_size_static_skips_cleanup_discard():
    engine, state, p1, p2 = _engine()
    _bf(state, _permanent("Reliquary Tower Shaped", "You have no maximum hand size.", type_line="Land"))
    for i in range(10):
        _in_hand(p1, Card(id=f"Filler {i}", name=f"Filler {i}", type_line="Instant", is_instant=True))

    engine._step_cleanup()
    assert len(p1.hand) == 10


def test_without_the_static_cleanup_discards_down_to_seven():
    engine, state, p1, p2 = _engine()
    for i in range(10):
        _in_hand(p1, Card(id=f"Filler {i}", name=f"Filler {i}", type_line="Instant", is_instant=True))

    engine._step_cleanup()
    assert len(p1.hand) == 7


def test_no_untap_optional_default_untaps_normally():
    engine, state, p1, p2 = _engine()
    obj = _bf(state, _permanent(
        "Rubinia Soulsinger Shaped",
        "You may choose not to untap this creature during your untap step.",
        type_line="Creature — Human Wizard",
    ))
    obj.tapped = True
    assert obj.skip_untap is False
    engine._step_untap()
    assert obj.tapped is False


def test_no_untap_optional_toggled_on_keeps_it_tapped():
    engine, state, p1, p2 = _engine()
    obj = _bf(state, _permanent(
        "Rubinia Soulsinger Shaped",
        "You may choose not to untap this creature during your untap step.",
        type_line="Creature — Human Wizard",
    ))
    obj.tapped = True
    engine.set_skip_untap(p1, obj, True)
    engine._step_untap()
    assert obj.tapped is True

    # Toggling back off restores normal untapping next untap step.
    engine.set_skip_untap(p1, obj, False)
    engine._step_untap()
    assert obj.tapped is False


def test_set_skip_untap_rejects_object_without_the_permission():
    engine, state, p1, p2 = _engine()
    obj = _bf(state, _permanent("Plain Bear", "", type_line="Creature — Bear"))
    with pytest.raises(ValueError):
        engine.set_skip_untap(p1, obj, True)


def test_set_skip_untap_rejects_the_wrong_controller():
    engine, state, p1, p2 = _engine()
    obj = _bf(state, _permanent(
        "Rubinia Soulsinger Shaped",
        "You may choose not to untap this creature during your untap step.",
        type_line="Creature — Human Wizard",
    ), controller="p2")
    with pytest.raises(ValueError):
        engine.set_skip_untap(p1, obj, True)


def test_legal_actions_offers_set_skip_untap_only_with_the_permission():
    engine, state, p1, p2 = _engine()
    obj = _bf(state, _permanent(
        "Rubinia Soulsinger Shaped",
        "You may choose not to untap this creature during your untap step.",
        type_line="Creature — Human Wizard",
    ))
    plain = _bf(state, _permanent("Plain Bear", "", type_line="Creature — Bear"))

    actions = engine.legal_actions(p1)
    offer = next(
        (a for a in actions if a["type"] == "set_skip_untap" and a["instance_id"] == obj.instance_id), None
    )
    assert offer is not None
    assert offer["skip_untap"] is False
    assert not any(
        a["type"] == "set_skip_untap" and a["instance_id"] == plain.instance_id for a in actions
    )

    engine.set_skip_untap(p1, obj, True)
    offer_after = next(
        a for a in engine.legal_actions(p1) if a["type"] == "set_skip_untap" and a["instance_id"] == obj.instance_id
    )
    assert offer_after["skip_untap"] is True
