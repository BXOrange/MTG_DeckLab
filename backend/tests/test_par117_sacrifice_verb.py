"""PAR-117 (sacrifice-verb residue) — two independent small closures on the
"its controller sacrifices …"/"its controller sacrifices it at end step"
family, named in `BACKLOG.md`'s PAR-117 entry as needing "its own referent
plumbing" beyond the group-subject/attached-permanent increments.

1. **"Its controller sacrifices it at the beginning of the next end step."**
   (Celestial Sword/Goblin Ski Patrol) is *not* a new referent at all: RULE
   701.17a already makes "sacrifice" inherently self-directed — a permanent
   is always sacrificed by its own controller, never chosen by another
   player — so `SacrificeSpecificEffect.apply` never reads a player, only
   the captured object. "Its controller sacrifices it…" and a bare
   "sacrifice it…" (`handlers._DELAYED_SAC_EXILE_TAIL_RE`, PAR-30) therefore
   compile to the *identical* spec; this closes on recognizing the extra
   subject/verb-conjugation, not a new primitive.

2. **"Its controller sacrifices `<N>` [nontoken] `<what>`[ or `<what2>`] of
   their choice."** (Funeral March — attached-permanent referent; Tainted
   Aether — group-subject referent) *is* a real widening:
   `SacrificeEffect.player` never read the `{"of": …, "as": "controller"}`
   operand `GainLifeEffect`/`LoseLifeEffect`/`DrawCardEffect`/`DiscardEffect`/
   `MillEffect` already do (PAR-115/PAR-117) — it fell straight to
   `targets[0] if targets else None`. Widened via `GameEffect._operand_player`
   like its siblings; RULE 601.2c's interactive edict itself needed no
   different plumbing, just the operand. Also adds `"creature_or_land"` to
   `damage_death_mixin._matches_permanent_type` (Tainted Aether's own
   "creature or land" choice — a new two-word combination, not a new
   predicate shape).

`parser_probe.py diff` against the pre-change tree (PARSER_VERSION 416):
+3 (Celestial Sword, Funeral March, Tainted Aether), 0 regressed. Goblin Ski
Patrol stays UNMODELED — its own remaining clause ("Activate only once and
only if you control a snow Mountain.") is a genuine singleton (confirmed via
`parser_probe.py blocked`, 1 SOLO/0 also-blocked) needing a reversed
"only once and only if" word order *and* a "snow `<land type>`" control-count
selector neither of which any other cached card needs — left for
`singletons.md`, not attempted here. Fade Away/Killing Wave's own "for each
creature, its controller sacrifices …" (a leading, not trailing, "for each"
prefix over every creature regardless of controller) and Torment of Venom's
compound "unless they sacrifice `<X>` of their choice or discard a card"
are separately-shaped residue, deliberately not attempted this pass.
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue, build_effects
from mtg_analyzer.game.effects.core import GameContext, _apply_effects_partitioned
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.gate import parse_oracle, UNMODELED
from mtg_analyzer.parser.oracle.spec import EffectSpec
from mtg_analyzer.services.card_database import CardDatabase, DEFAULT_DB_PATH

_ATTACHED_CONTROLLER = {"of": "attached", "as": "controller"}
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


def _creature(name, power=2, toughness=2, controller="p2"):
    obj = GameObject(
        Card(id=name, name=name, type_line="Creature — Bear", is_creature=True,
             power=power, toughness=toughness),
        owner_id=controller, zone=Zone.BATTLEFIELD,
    )
    obj.controller_id = controller
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    return obj


def _aura(name, host, controller="p1"):
    obj = GameObject(
        Card(id=name, name=name, type_line="Enchantment — Aura"),
        owner_id=controller, zone=Zone.BATTLEFIELD,
    )
    obj.controller_id = controller
    obj.attached_to = host.instance_id
    return obj


# ---------------------------------------------------------------------------
# 1. "its controller sacrifices it at the beginning of the next end step" —
#    same spec as the bare "sacrifice it" form, no new referent.
# ---------------------------------------------------------------------------


def test_bare_and_its_controller_forms_compile_identically():
    bare = match_clause("sacrifice it at the beginning of the next end step")
    prefixed = match_clause("its controller sacrifices it at the beginning of the next end step")
    assert bare == prefixed == [
        EffectSpec("create_delayed_trigger", {
            "step": "end", "scope": "any", "capture": "previous_or_self",
            "effects": [{"type": "sacrifice_specific", "params": {}}],
        })
    ]


def test_its_controller_exiles_and_destroys_variants():
    assert match_clause("its controller exiles it at the beginning of the next end step") == [
        EffectSpec("create_delayed_trigger", {
            "step": "end", "scope": "any", "capture": "previous_or_self",
            "effects": [{"type": "exile_specific", "params": {}}],
        })
    ]
    assert match_clause("its controller destroys it at the beginning of the next end step") == [
        EffectSpec("create_delayed_trigger", {
            "step": "end", "scope": "any", "capture": "previous_or_self",
            "effects": [{"type": "destroy_specific", "params": {}}],
        })
    ]


def test_celestial_sword_is_modeled():
    card = _db().get_card("Celestial Sword")
    result = parse_oracle(card)
    assert result.coverage != UNMODELED, result.unclaimed


# ---------------------------------------------------------------------------
# 2. "its controller sacrifices <N> [nontoken] <what>[ or <what2>] of their
#    choice" — a real referent widening on SacrificeEffect.player.
# ---------------------------------------------------------------------------


def test_sacrifices_gated_on_attached_subject():
    assert match_clause("its controller sacrifices a creature of their choice", attached_subject=True) == [
        EffectSpec("sacrifice", {"what": "creature", "count": 1, "player": _ATTACHED_CONTROLLER})
    ]
    # Ungated — no attached-permanent trigger condition offered this
    # pronoun a referent — stays unclaimed rather than guessing.
    assert match_clause("its controller sacrifices a creature of their choice") is None


def test_sacrifices_gated_on_group_subject():
    assert match_clause(
        "its controller sacrifices a creature or land of their choice", group_subject=True,
    ) == [
        EffectSpec("sacrifice", {"what": "creature_or_land", "count": 1, "player": _ENTERING_CONTROLLER})
    ]


def test_sacrifices_nontoken_creature():
    assert match_clause(
        "its controller sacrifices a nontoken creature of their choice", attached_subject=True,
    ) == [
        EffectSpec("sacrifice", {"what": "nontoken_creature", "count": 1, "player": _ATTACHED_CONTROLLER})
    ]


def test_sacrifices_unwhitelisted_combo_fails_closed():
    # "artifact or land" has no shipped card and no whitelisted
    # `_SACRIFICE_WHAT_OR_COMBOS` entry — fail closed rather than guess a
    # `_matches_permanent_type` string the engine would silently accept-all on.
    assert match_clause(
        "its controller sacrifices a artifact or land of their choice", attached_subject=True,
    ) is None


def test_funeral_march_is_modeled():
    card = _db().get_card("Funeral March")
    result = parse_oracle(card)
    assert result.coverage != UNMODELED, result.unclaimed


def test_tainted_aether_is_modeled():
    card = _db().get_card("Tainted Aether")
    result = parse_oracle(card)
    assert result.coverage != UNMODELED, result.unclaimed


def test_direct_apply_sacrifice_hits_the_attached_hosts_controller():
    eng, state, p1, p2 = _engine()
    # p2's only creature is the enchanted host itself — exactly one
    # matching candidate → `_request_choose_objects` auto-picks it, no
    # pending choice to answer. p1 (the Aura's own controller) has a
    # second creature that must stay untouched.
    host = _creature("Ox", controller="p2")
    state.add_to_battlefield(host)
    decoy = _creature("Decoy", controller="p1")
    state.add_to_battlefield(decoy)
    aura = _aura("Funeral March", host, controller="p1")
    state.add_to_battlefield(aura)

    ctx = eng.rules.context
    effs = build_effects(
        [EffectSpec("sacrifice", {"what": "creature", "count": 1, "player": _ATTACHED_CONTROLLER})],
        aura,
    )
    _apply_effects_partitioned(effs, ctx, None, None, source=aura)

    assert host not in state.battlefield
    assert host in p2.graveyard
    # Nothing of p1's (the Aura's own controller) was touched.
    assert decoy in state.battlefield


def test_direct_apply_sacrifice_hits_the_entering_creatures_controller():
    eng, state, p1, p2 = _engine()
    victim = _creature("Goat", controller="p2")
    state.add_to_battlefield(victim)
    src = GameObject(
        Card(id="src3", name="Src3", type_line="Enchantment"), owner_id="p1", zone=Zone.BATTLEFIELD,
    )
    src.controller_id = "p1"
    ctx = eng.rules.context
    ctx.trigger_event = {"instance_id": victim.instance_id, "controller_id": "p2"}
    effs = build_effects(
        [EffectSpec("sacrifice", {"what": "creature_or_land", "count": 1, "player": _ENTERING_CONTROLLER})],
        src,
    )
    _apply_effects_partitioned(effs, ctx, None, None, source=src)
    ctx.trigger_event = None

    assert victim not in state.battlefield
    assert victim in p2.graveyard
