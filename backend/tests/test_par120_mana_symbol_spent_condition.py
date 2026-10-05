"""PAR-120 — "if `<mana symbol[s]>` was spent to cast it/this spell" as a
standing condition (RULE 601.2h/603.4), the printed-mana-symbol sibling of
Adamant's own word-form "if at least N `<color>` mana was spent to cast it"
(PAR-95, `_ADAMANT_MANA_SPENT_IF_RE`).

No new engine primitive: `GameObject.mana_by_color_spent_to_cast` (Adamant's
own per-colour cast-payment diff) and the `mana_color_spent_to_cast_at_least`
condition kind both already existed — the whole gap was a second regex
recognizing "{w}{w} was spent to cast it" the same way the first recognizes
"if at least 2 white mana was spent to cast it". One or two repeated pips of
the *same* symbol (a backreference enforces the colours match — a mixed pair
like "{r}{g}" is a different, unclaimed shape, left open).

`parser_probe.py diff`: +17, 0 regressed.
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.static_handlers import static_condition
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.services.card_database import CardDatabase, DEFAULT_DB_PATH


def _db():
    return CardDatabase(DEFAULT_DB_PATH)


# ---------------------------------------------------------------------------
# PARSER: the condition itself
# ---------------------------------------------------------------------------


def test_single_symbol():
    assert static_condition("{r} was spent to cast this spell") == {
        "kind": "mana_color_spent_to_cast_at_least", "color": "R", "amount": 1,
    }


def test_doubled_symbol():
    assert static_condition("{g}{g} was spent to cast it") == {
        "kind": "mana_color_spent_to_cast_at_least", "color": "G", "amount": 2,
    }


def test_colorless_symbol():
    assert static_condition("{c} was spent to cast it") == {
        "kind": "mana_color_spent_to_cast_at_least", "color": "C", "amount": 1,
    }


def test_mixed_pair_is_a_different_shape_and_fails_closed():
    # Same-colour backreference means "{r}{g}" (Mythos of Illuna-shaped)
    # deliberately doesn't match this row — a real, separately-scoped gap.
    assert static_condition("{r}{g} was spent to cast this spell") is None


# ---------------------------------------------------------------------------
# PARSER: end-to-end, real cards
# ---------------------------------------------------------------------------


def test_real_cards_become_modeled():
    for name in (
        "Catharsis", "Deceit", "Emptiness", "Gruul Scrapper", "Ogre Savant",
        "Shrieking Grotesque", "Steamcore Weird", "Tin Street Hooligan",
    ):
        card = _db().get_card(name)
        result = parse_oracle(card)
        assert result.modeled, f"{name}: {result.unclaimed}"


# ---------------------------------------------------------------------------
# ENGINE: end-to-end, real board
# ---------------------------------------------------------------------------


def test_gruul_scrapper_gains_haste_only_if_red_mana_paid_for_it():
    eng = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )
    eng.begin_turn()
    state = eng.state

    obj = GameObject(_db().get_card("Gruul Scrapper"), owner_id="p1", zone=Zone.BATTLEFIELD)
    obj.controller_id = "p1"
    obj.mana_by_color_spent_to_cast = {"G": 1}  # no red paid
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)

    from mtg_analyzer.models.game.events import EventType, GameEvent

    def _fire_enters():
        state.fire_event(GameEvent(
            EventType.ENTERS_BATTLEFIELD, instance_id=obj.instance_id,
            controller_id="p1", object_types=sorted(obj.type_words),
        ))

    _fire_enters()
    # RULE 603.4: an intervening "if" is checked as the trigger event occurs — no red was spent, so it never triggers
    placed = eng.rules.put_triggers_on_stack()
    assert placed == 0
    eng.recompute_continuous_effects()
    assert not combat_has_haste(obj)

    obj.mana_by_color_spent_to_cast = {"G": 1, "R": 1}  # red paid the generic pip
    _fire_enters()
    placed = eng.rules.put_triggers_on_stack()
    assert placed == 1
    eng.rules.resolve_top_of_stack()
    eng.recompute_continuous_effects()
    assert combat_has_haste(obj)


def combat_has_haste(obj) -> bool:
    from mtg_analyzer.game import combat
    return combat.has(obj, "haste")
