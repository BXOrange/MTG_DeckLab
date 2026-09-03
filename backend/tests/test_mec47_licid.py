"""MEC-47 — the Tempest Licid cycle (first pass: the keyword-grant Licids).

"{cost}, {T}: This creature loses this ability and becomes an Aura
enchantment with enchant creature. Attach it to target creature. You may
pay {cost} to end this effect." + "Enchanted creature has <keyword>."

`LicidBecomeAuraEffect` / `LicidRevertEffect` + `GameObject.is_licid_aura`:
- attach the Licid, flag it, park a `for_as_long_as` `type_change` static
  that strips Creature / adds Enchantment—Aura while the flag holds;
- `is_licid_aura` / `not_licid_aura` `static_conditions` gate the two
  activated abilities so the transform is offered only as a creature and
  the "pay to end" only as an Aura.
"""

from __future__ import annotations

from mtg_analyzer.game import ability_catalogue as ac
from mtg_analyzer.game.effect_binder import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone


def _engine():
    eng = GameEngine.new_game(
        [("p1", "A", []), ("p2", "B", [])], starting_life=20, starting_hand=0
    )
    eng.begin_turn()
    eng.state.current_step = "main1"
    return eng, eng.state


def _put(st, card, pid="p1"):
    o = GameObject(card, owner_id=pid, zone=Zone.BATTLEFIELD)
    o.controller_id = pid
    st.add_to_battlefield(o)
    return o


def _gliding_licid(st, pid="p1"):
    o = _put(st, Card(
        id="GL", name="Gliding Licid", type_line="Creature — Licid",
        is_creature=True, power=2, toughness=2, mana_cost_string="{2}{U}",
        oracle_text=(
            "{U}, {T}: This creature loses this ability and becomes an Aura "
            "enchantment with enchant creature. Attach it to target creature. "
            "You may pay {U} to end this effect.\n"
            "Enchanted creature has flying."
        ),
    ), pid)
    o.summoning_sick = False   # its transform ability has a {T} cost
    bind_from_catalogue(o)
    return o


def _bear(st, name, pid="p2"):
    return _put(st, Card(id=name[:6], name=name, type_line="Creature — Bear",
                         is_creature=True, power=2, toughness=2), pid)


# --- registration -----------------------------------------------------


_ALL_LICIDS = (
    "Gliding Licid", "Enraging Licid", "Quickening Licid", "Corrupting Licid",
    "Calming Licid", "Convulsing Licid", "Tempting Licid", "Dominating Licid",
    "Transmogrifying Licid",
)


def test_licids_registered_with_two_activated_and_a_static():
    for n in _ALL_LICIDS:
        card = Card(id=n[:6], name=n, type_line="Creature — Licid",
                    is_creature=True, power=1, toughness=1)
        specs = ac.specs_for(card)
        kinds = sorted(s.ability_kind for s in specs)
        assert kinds[:2] == ["activated", "activated"] and "static" in kinds, n
        # fresh objects each call
        assert ac.specs_for(card) is not specs


def _licid_on_battlefield(st, name, granted_text, pid="p1"):
    o = _put(st, Card(
        id=name[:6], name=name, type_line="Creature — Licid",
        is_creature=True, power=1, toughness=1,
        oracle_text=(
            "{X}, {T}: This creature loses this ability and becomes an Aura "
            "enchantment with enchant creature. Attach it to target creature. "
            "You may pay {X} to end this effect.\n" + granted_text
        ),
    ), pid)
    o.summoning_sick = False
    bind_from_catalogue(o)
    return o


def test_dominating_licid_steals_control_of_the_enchanted_creature():
    eng, st = _engine()
    licid = _licid_on_battlefield(st, "Dominating Licid", "You control enchanted creature.")
    host = _bear(st, "Victim", pid="p2")
    st.player_by_id("p1").mana_pool.add_many({"U": 6})

    eng.activate_ability(st.player_by_id("p1"), licid, 0, targets=[host])
    eng.resolve_until_stable()
    eng.recompute_continuous_effects()

    assert host.controller_id == "p1", "you control enchanted creature"

    eng.activate_ability(st.player_by_id("p1"), licid, 1)  # end it
    eng.resolve_until_stable()
    eng.recompute_continuous_effects()
    assert host.controller_id == "p2", "control returns when the Licid detaches"


def test_transmogrifying_licid_pumps_and_adds_artifact():
    eng, st = _engine()
    licid = _licid_on_battlefield(
        st, "Transmogrifying Licid",
        "Enchanted creature gets +1/+1 and is an artifact in addition to its other types.",
    )
    host = _bear(st, "Host")
    st.player_by_id("p1").mana_pool.add_many({"C": 3})

    eng.activate_ability(st.player_by_id("p1"), licid, 0, targets=[host])
    eng.resolve_until_stable()
    eng.recompute_continuous_effects()

    assert (host.power, host.toughness) == (3, 3)
    assert "artifact" in {t.lower() for t in host.type_words}


# --- transform ------------------------------------------------------


def test_transform_makes_it_an_aura_and_grants_the_host_flying():
    eng, st = _engine()
    licid = _gliding_licid(st)
    host = _bear(st, "Host")
    st.player_by_id("p1").mana_pool.add_many({"U": 1})

    assert eng.can_activate(st.player_by_id("p1"), licid, licid.activated_abilities[0])
    eng.activate_ability(st.player_by_id("p1"), licid, 0, targets=[host])
    eng.resolve_until_stable()
    eng.recompute_continuous_effects()

    assert licid.is_licid_aura is True
    assert licid.attached_to == host.instance_id
    assert not licid.is_creature, "the Licid stops being a creature (layer 4)"
    assert "enchantment" in {t.lower() for t in licid.type_words}
    assert "flying" in host.granted_keywords


def test_transform_ability_gone_while_aura_revert_ability_present():
    eng, st = _engine()
    licid = _gliding_licid(st)
    host = _bear(st, "Host")
    p1 = st.player_by_id("p1")
    p1.mana_pool.add_many({"U": 2})
    eng.activate_ability(p1, licid, 0, targets=[host])
    eng.resolve_until_stable()

    # ability 0 (transform, gated not_licid_aura) is no longer activatable;
    # ability 1 (revert, gated is_licid_aura) is.
    assert not eng.can_activate(p1, licid, licid.activated_abilities[0])
    assert eng.can_activate(p1, licid, licid.activated_abilities[1])


def test_pay_to_end_reverts_to_a_creature_and_host_loses_flying():
    eng, st = _engine()
    licid = _gliding_licid(st)
    host = _bear(st, "Host")
    p1 = st.player_by_id("p1")
    p1.mana_pool.add_many({"U": 2})

    eng.activate_ability(p1, licid, 0, targets=[host])
    eng.resolve_until_stable()
    eng.recompute_continuous_effects()
    assert "flying" in host.granted_keywords

    eng.activate_ability(p1, licid, 1)   # pay {U} to end
    eng.resolve_until_stable()
    eng.recompute_continuous_effects()

    assert licid.is_licid_aura is False
    assert licid.attached_to is None
    assert licid.is_creature is True
    assert "flying" not in host.granted_keywords
    # the parked type-change floating static self-swept
    assert all(
        getattr(fs, "object_ids", None) != [licid.instance_id]
        for fs in st.floating_statics
    )


def test_leaving_the_battlefield_resets_the_licid_flag():
    eng, st = _engine()
    licid = _gliding_licid(st)
    host = _bear(st, "Host")
    st.player_by_id("p1").mana_pool.add_many({"U": 1})
    eng.activate_ability(st.player_by_id("p1"), licid, 0, targets=[host])
    eng.resolve_until_stable()
    assert licid.is_licid_aura is True

    licid.reset_as_new_object()
    assert licid.is_licid_aura is False
