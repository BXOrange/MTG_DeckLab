"""MEC-34 — Animate Dead, the first RULE 303.4f "Enchant creature card in
a graveyard" reanimator Aura this engine models. The target isn't a
permanent at all, so `RulesEngine._resolve_permanent_spell`'s ordinary
"attach or send to the graveyard" branch would otherwise misfire on it —
fixed by recognizing a graveyard-zone attach target and leaving the Aura
on the battlefield unattached until its own "when this enters" ability
reanimates the stashed target (`GameObject.reanimate_target_id`) and
attaches itself to the result. `targeting.legal_targets` also gained a
graveyard-wide branch for the "creature card in a graveyard" quality,
since the pre-existing "enchant" branch only ever searched the battlefield.

Reference: docs/implementation-state/Done_Backend.md "MEC-34" entry.
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.models.game_object import GameObject, Zone

from tests.test_game_engine import creature, make_engine


def _named(name):
    from mtg_analyzer.config import DB_PATH
    from mtg_analyzer.services.card_database import CardDatabase

    return CardDatabase(DB_PATH).get_card(name)


def _graveyard_creature(state, card, controller):
    obj = GameObject(card, owner_id=controller, zone=Zone.GRAVEYARD)
    state.player_by_id(controller).graveyard.append(obj)
    return obj


def _cast_animate_dead(hand=1):
    eng = make_engine([_named("Animate Dead")], [_named("Animate Dead")], hand=hand)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    p1.mana_pool.add_many({"B": 2})  # {1}{B}
    return eng, p1


def test_animate_dead_offers_a_graveyard_creature_as_its_legal_target():
    eng, p1 = _cast_animate_dead()
    bear = _graveyard_creature(eng.state, creature("Bear", power=2, toughness=2), controller="p2")

    animate_dead = p1.hand[0]
    bind_from_catalogue(animate_dead)
    eng.recompute_continuous_effects()

    assert eng.can_cast(p1, animate_dead, targets=[bear])


def test_animate_dead_reanimates_under_the_casters_control_and_attaches():
    eng, p1 = _cast_animate_dead()
    bear = _graveyard_creature(eng.state, creature("Bear", power=2, toughness=2), controller="p2")

    animate_dead = p1.hand[0]
    bind_from_catalogue(animate_dead)
    eng.cast_spell(p1, animate_dead, targets=[bear])
    eng.resolve_until_stable()

    reanimated = next(
        (o for o in eng.state.battlefield if o.card.name == "Bear"), None
    )
    assert reanimated is not None
    assert reanimated.controller_id == "p1"  # under YOUR control, not the owner's
    assert reanimated.owner_id == "p2"
    assert animate_dead.attached_to == reanimated.instance_id

    eng.recompute_continuous_effects()
    assert reanimated.power == 1  # printed 2, Animate Dead's own -1/-0
    assert reanimated.toughness == 2


def test_animate_dead_leaving_sacrifices_the_reanimated_creature():
    eng, p1 = _cast_animate_dead()
    bear = _graveyard_creature(eng.state, creature("Bear", power=2, toughness=2), controller="p1")

    animate_dead = p1.hand[0]
    bind_from_catalogue(animate_dead)
    eng.cast_spell(p1, animate_dead, targets=[bear])
    eng.resolve_until_stable()

    reanimated = next(o for o in eng.state.battlefield if o.card.name == "Bear")

    eng.rules.put_into_graveyard(animate_dead)
    eng.resolve_until_stable()

    assert animate_dead not in eng.state.battlefield
    assert reanimated not in eng.state.battlefield
    assert reanimated in p1.graveyard
