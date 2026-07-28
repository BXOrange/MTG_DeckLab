"""Serialize a game to a portable "replay" descriptor and back (UC: Replay/Puzzle).

Reference: docs/requirements/02_MVP_USECASES_REVISED.md UC3 (Goldfisch) — Replay mode is
its sibling: instead of playing a legal deck from turn 1, the user *builds an
arbitrary board* (or loads one saved from a goldfish game) and plays from there.

The models expose ``to_dict`` (a wire *view*) but no ``from_dict`` — there is no
way to rebuild a live `GameState` from a serialized view. So save/load uses a
**re-resolvable descriptor**: every card is stored by Scryfall id + name and
rebuilt from the card cache on load (`LazyCardLoader`), never a raw object dump.
Tokens — which have no cache entry — carry a self-describing block so they
survive the round-trip without one.

The descriptor is plain JSON (the format the frontend downloads/uploads):

    {"format": "mtg-replay", "version": 1,
     "turn_number": 1, "active_player_index": 0,
     "current_phase": "precombat_main", "current_step": "main1",
     "players": [{"id","name","life","poison","counters","is_dummy",
                  "commander_damage",
                  "zones": {"library","hand","graveyard","exile","command": [inst...]}}],
     "battlefield": [inst...]}     # each inst adds owner_id/controller_id

An ``inst`` records ``card_id``/``name`` (+ a ``token`` block when it is a token)
and the per-instance state the editor can set (tapped, transformed, counters, …).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

from mtg_analyzer.game import continuous
from mtg_analyzer.game.effect_binder import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.game.phases import default_turn_sequence
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.models.game_state import GameState
from mtg_analyzer.models.player import Player

if TYPE_CHECKING:
    from mtg_analyzer.services.lazy_card_loader import LazyCardLoader

FORMAT = "mtg-replay"
VERSION = 1

#: Personal zones the editor exposes, in display order (the battlefield is a
#: shared top-level list; the stack isn't editable).
ZONE_NAMES = ["library", "hand", "graveyard", "exile", "command"]

#: Flat (phase, step) order of a default turn — used to position the engine's
#: step cursor when a replay names a `current_step` (so "Nächster Schritt"
#: continues from the right place).
_STEP_ORDER: list[tuple[str, str]] = [
    (phase.name, step.name) for phase, step in default_turn_sequence().iter_steps()
]
_STEP_INDEX = {step: i for i, (_phase, step) in enumerate(_STEP_ORDER)}


# -- Serialize -------------------------------------------------------------


def _serialize_object(obj: GameObject) -> dict[str, Any]:
    """One game object → a re-resolvable instance descriptor.

    Card identity is the *front* face (``_front_card``) plus a ``transformed``
    flag, so a flipped DFC round-trips by resolving the front and re-applying
    the flip. A token also carries a self-describing block (it has no cache
    entry to re-resolve from)."""
    front = getattr(obj, "_front_card", obj.card)
    inst: dict[str, Any] = {
        "card_id": front.id,
        "name": front.name,
        "tapped": obj.tapped,
        "transformed": obj.transformed,
        "summoning_sick": obj.summoning_sick,
        "damage_marked": obj.damage_marked,
        "counters": dict(obj.counters),
        "is_token": obj.is_token,
        "is_commander": obj.is_commander,
        "attached_to": obj.attached_to,
        # RULE 310.8: a battle's protector is per-object state chosen as it
        # entered, not derivable from the card — without it a re-opened board
        # would have RULE 310.10's SBA silently pick a new one. ``None`` for
        # every non-battle, which is the overwhelming majority.
        "protector_id": obj.protector_id,
        # RULE 708.2: a face-down permanent (morph/disguise/manifest/cloak).
        # The *identity* above already round-trips — `_front_card` is the real
        # card, untouched by the face swap — so only the face-down status and
        # which rule caused it need carrying, and a re-opened board can put
        # the synthetic 2/2 face back on.
        "face_down": obj.face_down,
        "face_down_kind": obj.face_down_kind,
    }
    if obj.is_token:
        card = obj.card
        inst["token"] = {
            "name": card.name,
            "type_line": card.type_line,
            "power": card.power,
            "toughness": card.toughness,
            "colors": sorted(card.color_identity),
            "oracle_text": card.oracle_text,
            "loyalty": card.loyalty,
        }
    return inst


def _serialize_player(state: GameState, player: Player) -> dict[str, Any]:
    zones = {
        name: [_serialize_object(o) for o in player.zones[Zone(name)]]
        for name in ZONE_NAMES
    }
    return {
        "id": player.id,
        "name": player.name,
        "life": player.life,
        "poison": player.poison,
        "counters": dict(player.counters),
        "is_dummy": player.is_dummy,
        "commander_damage": {str(k): v for k, v in player.commander_damage.items()},
        "zones": zones,
    }


def serialize_replay(state: GameState) -> dict[str, Any]:
    """Snapshot a live game as a portable, re-resolvable descriptor."""
    battlefield = []
    for obj in state.battlefield:
        inst = _serialize_object(obj)
        inst["owner_id"] = obj.owner_id
        inst["controller_id"] = obj.controller_id
        battlefield.append(inst)
    return {
        "format": FORMAT,
        "version": VERSION,
        "turn_number": state.turn_number,
        "active_player_index": state.active_player_index,
        "current_phase": state.current_phase or "precombat_main",
        "current_step": state.current_step or "main1",
        "players": [_serialize_player(state, p) for p in state.players],
        "battlefield": battlefield,
    }


# -- Build -----------------------------------------------------------------


def _token_card(token: dict[str, Any]) -> Card:
    """An ad-hoc `Card` for a token block (RULE 111). ``type_line`` is forced
    to start with "Token" so `Card.is_token` holds; P/T only on creatures."""
    type_line = (token.get("type_line") or "Token Creature").strip()
    if not type_line.lower().startswith("token"):
        type_line = f"Token {type_line}"
    is_creature = "creature" in type_line.lower()
    power = token.get("power")
    toughness = token.get("toughness")
    return Card(
        id=f"token:{token.get('name', 'Token')}:{type_line}",
        name=token.get("name") or "Token",
        type_line=type_line,
        color_identity=set(token.get("colors") or []),
        is_creature=is_creature,
        power=power if is_creature else None,
        toughness=toughness if is_creature else None,
        oracle_text=token.get("oracle_text") or "",
        loyalty=token.get("loyalty"),
    )


def build_object(
    inst: dict[str, Any],
    owner_id: str,
    cards_by_name: dict[str, Card],
    controller_id: Optional[str] = None,
) -> Optional[GameObject]:
    """Rebuild one `GameObject` from an instance descriptor, binding its
    card text to live abilities (bind-on-load, like `build_goldfish_engine`).

    Returns None when a non-token card can't be resolved from the cache, so an
    unresolvable card is skipped rather than aborting the whole load."""
    is_token = bool(inst.get("is_token"))
    token = inst.get("token")
    if is_token and token:
        card: Optional[Card] = _token_card(token)
    else:
        card = cards_by_name.get(inst.get("name", ""))
    if card is None:
        return None

    obj = GameObject(
        card,
        owner_id=owner_id,
        controller_id=controller_id,
        is_commander=bool(inst.get("is_commander")),
        is_token=is_token or None,
    )
    obj.tapped = bool(inst.get("tapped"))
    obj.summoning_sick = bool(inst.get("summoning_sick", True))
    obj.damage_marked = int(inst.get("damage_marked", 0) or 0)
    obj.counters = {k: int(v) for k, v in (inst.get("counters") or {}).items()}
    obj.attached_to = inst.get("attached_to")
    obj.protector_id = inst.get("protector_id")  # RULE 310.8, see the descriptor
    # Transform *before* binding (not after) so catalogue-derived abilities/
    # keywords are bound against whichever face is actually current — the
    # same ordering `RulesEngine.transform_permanent` enforces for a live
    # transform, just inlined here since this builds a bare `GameObject` with
    # no `RulesEngine` yet to call it on.
    if inst.get("transformed"):
        obj.transform()
    bind_from_catalogue(obj)  # card text → live abilities
    if inst.get("face_down"):
        # RULE 708.2, applied *after* binding: `turn_face_down` stashes the
        # face-up bundle it finds, so the abilities have to exist first —
        # otherwise turning it back face up later would restore an empty one.
        from mtg_analyzer.game.face_down import face_down_card

        kind = inst.get("face_down_kind") or "morph"
        obj.turn_face_down(face_down_card(kind), kind)
        if kind in ("disguise", "cloak"):
            obj.intrinsic_keywords = {"ward"}          # RULE 702.168a/701.58a
            obj.parametric_keywords = {"ward": {"cost": "{2}"}}
    return obj


def _resolve_names(descriptor: dict[str, Any], loader: "LazyCardLoader") -> dict[str, Card]:
    """Batch-resolve every non-token card name in a descriptor (one round trip)."""
    names: list[str] = []

    def collect(inst: dict[str, Any]) -> None:
        if not inst.get("is_token") and inst.get("name"):
            names.append(inst["name"])

    for pd in descriptor.get("players", []):
        for zone_insts in (pd.get("zones") or {}).values():
            for inst in zone_insts:
                collect(inst)
    for inst in descriptor.get("battlefield", []):
        collect(inst)
    if not names:
        return {}
    return loader.load_cards(names).cards


def cursor_after(step: str) -> int:
    """Engine step cursor positioned *after* ``step`` (the next advance runs the
    following step), mirroring how a stepped goldfish sits between steps."""
    index = _STEP_INDEX.get(step, _STEP_INDEX["main1"])
    return index + 1


def phase_for_step(step: str, default: str = "precombat_main") -> str:
    """The phase a step belongs to (RULE 500), for `edit_set_turn`."""
    for phase, name in _STEP_ORDER:
        if name == step:
            return phase
    return default


def build_replay_engine(
    descriptor: dict[str, Any], loader: "LazyCardLoader"
) -> GameEngine:
    """Build a live `GameEngine` from a replay descriptor.

    No `engine.start()` — the board is given, so we position the turn/step
    cursor directly instead of dealing an opening hand and beginning turn 1."""
    cards_by_name = _resolve_names(descriptor, loader)

    players: list[Player] = []
    for pd in descriptor.get("players", []):
        player = Player(
            id=pd["id"],
            name=pd.get("name", ""),
            life=int(pd.get("life", 40)),
            is_dummy=bool(pd.get("is_dummy")),
        )
        player.poison = int(pd.get("poison", 0) or 0)
        player.counters = {k: int(v) for k, v in (pd.get("counters") or {}).items()}
        player.commander_damage = {
            int(k): v for k, v in (pd.get("commander_damage") or {}).items()
        }
        for name in ZONE_NAMES:
            for inst in (pd.get("zones") or {}).get(name, []):
                obj = build_object(inst, owner_id=player.id, cards_by_name=cards_by_name)
                if obj is not None:
                    player.add_to_zone(obj, Zone(name))
        players.append(player)

    if not players:  # a descriptor with no players still needs one live player
        players.append(Player(id="p1", name="Du", life=40))

    state = GameState(players=players)
    for inst in descriptor.get("battlefield", []):
        obj = build_object(
            inst,
            owner_id=inst.get("owner_id", players[0].id),
            cards_by_name=cards_by_name,
            controller_id=inst.get("controller_id"),
        )
        if obj is not None:
            state.add_to_battlefield(obj)

    state.turn_number = int(descriptor.get("turn_number", 1) or 1)
    idx = int(descriptor.get("active_player_index", 0) or 0)
    state.active_player_index = idx if 0 <= idx < len(players) else 0
    state.current_phase = descriptor.get("current_phase") or "precombat_main"
    state.current_step = descriptor.get("current_step") or "main1"
    # A position that was assembled rather than played has no turn history,
    # so the display-only round counter is derived from the turn number.
    state.sync_round_number()

    engine = GameEngine(state)
    engine.resume_at(cursor_after(state.current_step))
    continuous.recompute(state)
    return engine


def blank_replay(num_players: int = 1) -> dict[str, Any]:
    """An empty descriptor: 1 player (solo puzzle) or 2 (with an opponent)."""
    num = max(1, min(2, num_players))
    names = ["Du", "Gegner"]
    players = [
        {
            "id": f"p{i + 1}",
            "name": names[i],
            "life": 40,
            "poison": 0,
            "counters": {},
            "is_dummy": False,
            "commander_damage": {},
            "zones": {name: [] for name in ZONE_NAMES},
        }
        for i in range(num)
    ]
    return {
        "format": FORMAT,
        "version": VERSION,
        "turn_number": 1,
        "active_player_index": 0,
        "current_phase": "precombat_main",
        "current_step": "main1",
        "players": players,
        "battlefield": [],
    }
