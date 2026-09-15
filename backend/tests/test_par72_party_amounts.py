"""PAR-72: Party (RULE 700.8/702.129) generalized into a resolve-time
amount, widening the already-shipped `continuous.count_selector`'s
`"creatures_in_your_party"` branch (PAR-53 — previously wired only into a
cost-reduction "per" and the `"you have a full party"` boolean condition)
into the general `amount_from_count_selector`/`count_selector` family
(PAR-32/36/43 &c.) already shared by most one-shot effects and two static
forms (an anthem's "for each X", a CDA's "equal to the number of X").

One handler per distinct effect-verb template, this codebase's established
convention — the fixed phrase "for each creature in your party"/"the number
of creatures in your party" appears on ten genuinely different effect verbs
across the traced cards, each needing its own regex + builder.

Three primitives were extended (all pure widening, no new engine concept):
`GainLifeEffect.count_selector_multiplier` (a per-unit multiplier — every
prior `count_selector` gain_life shape printed exactly 1 life per unit;
Shepherd of Heroes prints 2), `ScryEffect.count_from_count_selector`,
`InspectTopChooseEffect.count_from_count_selector`/``count_plus`` (Skyclave
Plunder's "X is 3 plus the number of..."), `CounterSpellEffect.
unless_pays_extra_selector` (Concerted Defense's dynamic "unless its
controller pays {1} plus an additional {1} for each...") and a trailing-
sentence peel in `segmenter.py` folding "This ability costs {N} less to
activate for each..." into the *already-existing* hand-authored-only
`ActivationCost.dynamic_reduction` (Eiganjo, Seat of the Empire's own
shape) — Seafloor Stalker is the oracle-text route to that same primitive.

One real, previously-latent bug was found and fixed while building
Synchronized Spellcraft's "and X damage to that creature's controller"
half: `DealDamageEffect`'s `recipient_subject` resolution path read raw
`self.amount` instead of `_amount_for` (the method that actually applies
`amount_from_count_selector`/`amount_from_trigger_event`/
`amount_if_target_color`), so combining `recipient_subject` with any of
those three silently dropped them — no shipped card had combined them
before now.

Acquisitions Expert ("target opponent reveals a number of cards from their
hand equal to the number of creatures in your party. You choose one of
those cards...") was deliberately left UNCLAIMED: unlike every other card
in this batch, the revealed subset is chosen by the *hand's owner*, not the
caster — a genuinely different two-step interactive shape (existing
`RevealHandChooseDiscardEffect` always offers the chooser the *whole* hand)
that needs a new pending-choice primitive, out of this ticket's "generalize
an existing amount" scope.

Reference: docs/implementation-state/Done_Backend.md's "Oracle-Text Parser
Front-End" PAR-72 entry.
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.catalogue.static_handlers import static_effect_specs
from mtg_analyzer.parser.oracle.gate import parse_oracle
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


def _hand(player, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.HAND)
    bind_from_catalogue(obj)
    player.add_to_zone(obj, Zone.HAND)
    return obj


def _engine():
    eng = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )
    eng.begin_turn()
    eng.state.current_step = "main1"
    return eng, eng.state, eng.state.players[0], eng.state.players[1]


def _party_of_two(state, controller="p1"):
    """Two creatures covering two distinct party roles for ``controller``."""
    _bf(state, _card("Test Cleric", "Creature — Human Cleric"), controller=controller)
    _bf(state, _card("Test Rogue", "Creature — Human Rogue"), controller=controller)


# ---------------------------------------------------------------------------
# PARSER
# ---------------------------------------------------------------------------


def test_add_mana_from_party():
    assert match_clause("add {r} for each creature in your party") == [
        EffectSpec("add_mana", {"color": "R", "amount_selector": "creatures_in_your_party"})
    ]


def test_counter_unless_pays_extra_from_party():
    assert match_clause(
        "counter target noncreature spell unless its controller pays {1} "
        "plus an additional {1} for each creature in your party"
    ) == [EffectSpec("counter", {
        "noncreature": True, "unless_pays": "{1}",
        "unless_pays_extra_selector": "creatures_in_your_party",
    })]


def test_add_counters_self_from_party():
    assert match_clause("put a +1/+1 counter on it for each creature in your party") == [
        EffectSpec("add_counters", {"amount_from_count_selector": "creatures_in_your_party"})
    ]


def test_choose_target_add_counters_from_party():
    assert match_clause(
        "choose target creature you control. put a +1/+1 counter on it for each creature in your party"
    ) == [EffectSpec("add_counters", {
        "target_kind": "creature_you_control",
        "amount_from_count_selector": "creatures_in_your_party",
    })]


def test_pump_self_power_from_party():
    assert match_clause("it gets +1/+0 until end of turn for each creature in your party") == [
        EffectSpec("pump", {
            "amount_from_count_selector": "creatures_in_your_party",
            "amount_from_count_selector_axis": "power",
        })
    ]


def test_pump_target_both_from_party():
    assert match_clause(
        "target creature gets +1/+1 until end of turn for each creature in your party"
    ) == [EffectSpec("pump", {
        "target_kind": "creature", "amount_from_count_selector": "creatures_in_your_party",
    })]


def test_pump_up_to_two_from_party():
    assert match_clause(
        "up to 2 target creatures each get +x/+x until end of turn, "
        "where x is the number of creatures in your party"
    ) == [EffectSpec("pump", {
        "target_kind": "creature", "target_count": 2, "optional": True,
        "amount_from_count_selector": "creatures_in_your_party",
    })]


def test_pump_target_opponent_negative_from_party():
    assert match_clause(
        "target creature an opponent controls gets -x/-x until end of turn, "
        "where x is the number of creatures in your party"
    ) == [EffectSpec("pump", {
        "target_kind": "creature_you_dont_control",
        "amount_from_count_selector": "creatures_in_your_party",
        "amount_from_count_selector_negative": True,
    })]


def test_pump_unblockable_self_form():
    # Widened `_PUMP_UNBLOCKABLE_RE` (Seafloor Stalker's own effect body,
    # sans the trailing cost-reduction sentence the segmenter peels off
    # separately) — previously target-only.
    assert match_clause(
        "~ gets +1/+0 until end of turn and can't be blocked this turn"
    ) == [EffectSpec("pump", {"power": 1, "toughness": 0, "unblockable": True})]


def test_gain_life_multiplier_from_party():
    assert match_clause("you gain 2 life for each creature in your party") == [
        EffectSpec("gain_life", {
            "count_selector": "creatures_in_your_party", "count_selector_multiplier": 2,
        })
    ]


def test_create_token_from_party():
    assert match_clause(
        "create a 1/1 white kor warrior creature token for each creature in your party"
    ) == [EffectSpec("create_token", {
        "power": 1, "toughness": 1, "colors": ["W"], "subtypes": ["Kor", "Warrior"],
        "count_selector": "creatures_in_your_party",
    })]


def test_scry_from_party():
    assert match_clause("scry x, where x is the number of creatures in your party") == [
        EffectSpec("scry", {"count_from_count_selector": "creatures_in_your_party"})
    ]


def test_lose_life_and_gain_life_from_party():
    assert match_clause(
        "each opponent loses x life and you gain x life, "
        "where x is the number of creatures in your party"
    ) == [
        EffectSpec("lose_life", {
            "amount_from_count_selector": "creatures_in_your_party", "selector": "each_opponent",
        }),
        EffectSpec("gain_life", {"count_selector": "creatures_in_your_party"}),
    ]


def test_damage_attacking_or_blocking_twice_party():
    assert match_clause(
        "choose target attacking or blocking creature. ~ deals damage to that creature "
        "equal to twice the number of creatures in your party"
    ) == [EffectSpec("damage", {
        "target_kind": "attacking_or_blocking_creature",
        "amount_from_count_selector": "creatures_in_your_party", "amount_multiplier": 2,
    })]


def test_look_top_put_three_from_party():
    assert match_clause(
        "look at the top x cards of your library, where x is 3 plus the number of "
        "creatures in your party. put 3 of those cards into your hand and the rest "
        "on the bottom of your library in a random order"
    ) == [EffectSpec("inspect_top_choose", {
        "count_from_count_selector": "creatures_in_your_party", "count_plus": 3,
        "action": "library_to_hand", "max_picks": 3, "rest_destination": "library_bottom_random",
    })]


def test_damage_target_and_controller_from_party():
    assert match_clause(
        "~ deals 4 damage to target creature and x damage to that creature's controller, "
        "where x is the number of creatures in your party"
    ) == [
        EffectSpec("damage", {"amount": 4, "target_kind": "creature"}),
        EffectSpec("damage", {
            "recipient_subject": "previous_subject_controller",
            "amount_from_count_selector": "creatures_in_your_party",
        }),
    ]


def test_damage_target_from_party():
    assert match_clause(
        "it deals x damage to target creature or planeswalker, "
        "where x is the number of creatures in your party"
    ) == [EffectSpec("damage", {
        "target_kind": "creature", "amount_from_count_selector": "creatures_in_your_party",
    })]


def test_burakos_attack_from_party():
    assert match_clause(
        "defending player loses x life and you create x treasure tokens, "
        "where x is the number of creatures in your party"
    ) == [
        EffectSpec("lose_life", {
            "selector": "defending_player", "amount_from_count_selector": "creatures_in_your_party",
        }),
        EffectSpec("create_token", {
            "token_name": "Treasure", "count_selector": "creatures_in_your_party",
        }),
    ]


def test_burakos_self_types_is_a_static_not_an_effect_body():
    # This is a plain declarative line with no trigger/cost wrapper, so it
    # must be classified as a `static` ability (`static_effect_specs`), not
    # matched through the effect-body table `match_clause` drives.
    assert static_effect_specs("~ is also a cleric, rogue, warrior, and wizard") == [
        EffectSpec("type_change", {
            "affects": "self", "add_subtypes": ["Cleric", "Rogue", "Warrior", "Wizard"],
        })
    ]


def test_pt_cda_from_party():
    assert static_effect_specs("~'s power is equal to the number of creatures in your party") == [
        EffectSpec("pt_cda", {"affects": "self", "power_count": "creatures_in_your_party"})
    ]


def test_attached_anthem_from_party_with_keyword():
    assert static_effect_specs(
        "equipped creature gets +1/+0 for each creature in your party and has menace"
    ) == [
        EffectSpec("anthem", {
            "affects": "attached_permanent", "power": 1, "toughness": 0,
            "power_count": "creatures_in_your_party", "toughness_count": "creatures_in_your_party",
        }),
        EffectSpec("grant_keyword", {"keywords": ["menace"], "affects": "attached_permanent"}),
    ]


def test_acquisitions_expert_shaped_reveal_stays_unmodeled():
    # The defender (not the caster) chooses *which* N cards get revealed —
    # a genuinely different two-step interactive shape from
    # `RevealHandChooseDiscardEffect`'s "reveal your whole hand" template.
    assert match_clause(
        "target opponent reveals a number of cards from their hand equal to the number "
        "of creatures in your party. you choose 1 of those cards. that player discards that card"
    ) is None


# ---------------------------------------------------------------------------
# EXECUTE
# ---------------------------------------------------------------------------


def test_shepherd_of_heroes_shaped_gain_life_scales_by_two_per_party_member():
    eng, state, p1, p2 = _engine()
    _party_of_two(state)
    shepherd = _hand(p1, _card(
        "Test Shepherd of Heroes",
        oracle_text="When this creature enters, you gain 2 life for each creature in your party.",
    ))
    obj = GameObject(shepherd.card, owner_id="p1", zone=Zone.BATTLEFIELD)
    bind_from_catalogue(obj)
    # RULE 603.6a: fire ENTERS_BATTLEFIELD while the object is genuinely on
    # the battlefield, mirroring `GameState.add_to_battlefield`'s own
    # append-then-fire ordering.
    state.add_to_battlefield(obj)
    state.fire_event(GameEvent(
        EventType.ENTERS_BATTLEFIELD, controller_id="p1", instance_id=obj.instance_id,
        object_types=sorted(obj.type_words),
    ))
    eng.rules.put_triggers_on_stack()
    eng.resolve_until_stable()
    # Two party members present (Cleric, Rogue) -> 2 * 2 = 4 life.
    assert p1.life == 20 + 4


def test_synchronized_spellcraft_shaped_damage_reads_party_scaled_controller_damage():
    eng, state, p1, p2 = _engine()
    _party_of_two(state)
    victim = _bf(state, _card("Test Victim", is_creature=True, power=3, toughness=10), controller="p2")
    spell = _hand(p1, _card(
        "Test Synchronized Spellcraft", "Instant", cost="{2}{R}", cmc=3,
        oracle_text=(
            "Test Synchronized Spellcraft deals 4 damage to target creature and X damage "
            "to that creature's controller, where X is the number of creatures in your party."
        ),
    ))
    p1.mana_pool.add_many({"C": 2, "R": 1})
    eng.rules.cast_spell(p1, spell, targets=[victim])
    eng.resolve_until_stable()
    assert victim.damage_marked == 4
    # 2 party members -> 2 damage to the victim's controller (p2), not 0
    # (the bug this ticket found and fixed: `recipient_subject` silently
    # ignored `amount_from_count_selector` before this batch).
    assert p2.life == 20 - 2


def test_concerted_defense_shaped_counter_tax_scales_with_party():
    eng, state, p1, p2 = _engine()
    _party_of_two(state, controller="p1")
    countered = _hand(p2, _card("Test Countered Spell", "Sorcery", cost="{2}", cmc=2), controller="p2")
    counter_spell = _hand(p1, _card(
        "Test Concerted Defense", "Instant", cost="{1}{U}",
        oracle_text=(
            "Counter target noncreature spell unless its controller pays {1} "
            "plus an additional {1} for each creature in your party."
        ),
    ))
    p2.mana_pool.add_many({"C": 5})  # 2 to cast + 3 left over to actually afford the tax
    eng.rules.cast_spell(p2, countered)
    p1.mana_pool.add_many({"C": 1, "U": 1})
    countered_stack_item = state.stack[-1]
    eng.rules.cast_spell(p1, counter_spell, targets=[countered_stack_item])
    eng.resolve_until_stable()
    choice = state.pending_choice
    assert choice is not None and choice["kind"] == "counter_unless_pays"
    # base {1} + 2 party members * {1} each = {3}.
    assert "3" in choice["prompt"]


def test_skyclave_plunder_shaped_inspect_reads_three_plus_party():
    eng, state, p1, p2 = _engine()
    _party_of_two(state)
    for i in range(8):
        p1.library.append(GameObject(_card(f"Filler {i}"), owner_id="p1", zone=Zone.LIBRARY))
    spell = _hand(p1, _card(
        "Test Skyclave Plunder", "Sorcery", cost="{2}{U}", cmc=3,
        oracle_text=(
            "Look at the top X cards of your library, where X is 3 plus the number of "
            "creatures in your party. Put 3 of those cards into your hand and the rest "
            "on the bottom of your library in a random order."
        ),
    ))
    p1.mana_pool.add_many({"C": 2, "U": 1})
    eng.rules.cast_spell(p1, spell)  # removes the spell itself from hand
    eng.resolve_until_stable()
    # 3 base + 2 party members = 5 cards inspected; forced pick of 3, one at
    # a time (`_request_choose_objects`'s own "offered one object at a
    # time" shape).
    picked = 0
    while state.pending_choice is not None:
        options = state.pending_choice["options"]
        assert len(options) == 5 - picked
        eng.rules.resolve_choice(options[0]["instance_id"])
        picked += 1
        eng.resolve_until_stable()
    assert picked == 3
    assert len(p1.hand) == 3
    assert len(p1.library) == 8 - 3  # the 2 unchosen of the 5 inspected return to the library
