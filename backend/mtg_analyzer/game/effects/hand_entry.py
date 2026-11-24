"""Per-player hand choices and their battlefield-entry instructions."""
from __future__ import annotations

from ...models.cards.card_query import is_permanent_card, matches
from ...models.game.game_object import Zone
from .. import continuations
from .battlefield_batches import start_battlefield_batch
from .core import GameEffect, _apply_effects_partitioned, _controller_of


class GroupHandEntryEffect(GameEffect):
    def __init__(self, criteria, scope, *, any_number=False, repeat=False, draw_if_missed=False,
                 before=None, after=None, source=None):
        super().__init__(source)
        self.criteria = criteria
        self.scope = scope
        self.any_number = any_number
        self.repeat = repeat
        self.draw_if_missed = draw_if_missed
        self.before = before
        self.after = after

    def apply(self, context, targets=None):
        controller = _controller_of(self.source, context)
        if controller is None or controller.has_lost:
            return
        players = context.state.living_players_apnap()
        if self.repeat:
            # RULE 608.2c: "starting with you" overrides APNAP for these sequential entries.
            start = players.index(controller)
            players = players[start:] + players[:start]
        elif self.scope == "opponents":
            players = [p for p in players if p.id != controller.id]
        frame = {
            "players": [p.id for p in players], "cursor": 0, "selected": [], "entered": [],
            "controller_id": controller.id, "source_id": getattr(self.source, "instance_id", None),
            "source_incarnation": (context.resolving_source_incarnation if context.resolving_source_incarnation is not None
                                   else getattr(self.source, "zone_incarnation", None)),
            "criteria": self.criteria, "any_number": self.any_number, "repeat": self.repeat,
            "draw_if_missed": self.draw_if_missed, "after": self.after,
        }
        _prepare(context.engine, frame, self.before)


def _advance(rules, frame):
    # RULE 101.4/101.4a: select in APNAP order, holding the exact hidden
    # visits in hand until the entire non-repeating group has chosen.
    while frame["cursor"] < len(frame["players"]):
        player = rules.state.player_by_id(frame["players"][frame["cursor"]])
        if not player.has_lost:
            selected = {iid for _, iid, _ in frame["selected"]}
            unselected = [obj for obj in player.hand if obj.instance_id not in selected]
            # Offer the same private prompt for a nonempty hand even if
            # nothing matches. Other seats learn only that the player passed.
            if unselected:
                candidates = [obj for obj in unselected if is_permanent_card(obj.card)
                              and matches(obj.card, frame["criteria"])]
                options = [{"id": str(obj.instance_id), "label": obj.name, "instance_id": obj.instance_id}
                           for obj in candidates]
                options.append({"id": "decline", "label": "Auswahl abschließen" if frame["any_number"]
                                else "Nichts wählen"})
                rules.open_choice({
                    "kind": "group_hand_entry", "player_id": player.id, "optional": True,
                    "prompt": "Lege eine Karte aus deiner Hand ins Spiel",
                    "source_id": frame["source_id"], "options": options,
                    "group_hand_entry": frame,
                    "hand_entry_visits": {obj.instance_id: obj.zone_incarnation for obj in candidates},
                })
                return
        frame["cursor"] += 1
    if not frame["repeat"]:
        _move_selected(rules, frame)
    elif frame["entered"]:
        frame["entered"] = []
        frame["cursor"] = 0
        _advance(rules, frame)
    else:
        _finish(rules, frame, [])


@continuations.choice("group_hand_entry", answer=continuations.ANSWER_INT, rule="101.4")
def _resume_hand_entry(rules, choice, answer):
    frame = choice["group_hand_entry"]
    if answer is not None:
        obj = rules.state.find_object(answer)
        if (obj is None or obj.zone != Zone.HAND
                or obj.zone_incarnation != choice["hand_entry_visits"].get(answer)):
            rules.open_choice(choice)
            raise ValueError("Choose an offered card in your hand")
        frame["selected"].append((choice["player_id"], answer, obj.zone_incarnation))
    if answer is None or not frame["any_number"]:
        frame["cursor"] += 1
    if frame["repeat"] and answer is not None:
        _move_selected(rules, frame)
    else:
        _advance(rules, frame)


def _move_selected(rules, frame):
    selected, frame["selected"] = frame["selected"], []
    cards = []
    for player_id, instance_id, incarnation in selected:
        player = rules.state.player_by_id(player_id)
        obj = rules.state.find_object(instance_id)
        if not player.has_lost and obj in player.hand and obj.zone_incarnation == incarnation:
            cards.append((obj, player_id))
    if cards:
        # RULE 110.2a: each chooser controls their own entrants.
        start_battlefield_batch(rules, [obj for obj, _ in cards], frame["controller_id"],
                                controllers={obj.instance_id: pid for obj, pid in cards},
                                source=rules.state.find_object(frame["source_id"]),
                                hand_entry=frame)
    else:
        finish_hand_entry(rules, frame, [])


def finish_hand_entry(rules, frame, entered):
    if frame["repeat"]:
        frame["entered"].extend(entered)
        _advance(rules, frame)
    else:
        _finish(rules, frame, entered)


def _prepare(rules, frame, before):
    if before == "exile_creatures":
        visits = []
        with rules.state.simultaneous():
            for obj in rules.state.permanents():
                if obj.is_creature:
                    rules.exile(obj)
                    if obj.zone == Zone.EXILE:
                        visits.append((obj.instance_id, obj.zone_incarnation))
        frame["exiled_visits"] = visits
    if before == "shuffle_hand_and_owned_permanents":
        state = rules.state
        frame["shuffle_visits"] = [
            (obj.instance_id, obj.zone_incarnation) for player in state.living_players_apnap()
            for obj in [*player.hand, *(o for o in state.permanents() if o.owner_id == player.id)]
        ]
        frame["commanders"] = [iid for iid, _ in frame["shuffle_visits"] if state.find_object(iid).is_commander]
        frame["send_to_command"] = []
        _choose_shuffle_replacements(rules, frame)
        return
    _advance(rules, frame)


def _choose_shuffle_replacements(rules, frame):
    # RULE 903.9b: take replacement choices before shuffling any cards.
    while frame["commanders"]:
        obj = rules.state.find_object(frame["commanders"].pop(0))
        if obj is None:
            continue
        choice = rules._commander_zone_choice(obj, Zone.LIBRARY)
        choice.update(kind="group_hand_entry_commander", group_hand_entry=frame)
        rules.open_choice(choice)
        return
    _shuffle_and_draw(rules, frame)


@continuations.choice("group_hand_entry_commander", answer=continuations.ANSWER_STR, rule="903.9b")
def _resume_shuffle_replacement(rules, choice, answer):
    if answer not in {None, "command"}:
        rules.open_choice(choice)
        raise ValueError("Choose whether to move the commander to the command zone")
    frame = choice["group_hand_entry"]
    if answer == "command":
        frame["send_to_command"].append(choice["instance_id"])
    _choose_shuffle_replacements(rules, frame)


def _shuffle_and_draw(rules, frame):
    state = rules.state
    players = state.living_players_apnap()
    shuffled_count = {player.id: 0 for player in players}
    with state.simultaneous():
        for iid, inc in frame.pop("shuffle_visits"):
            obj = state.find_object(iid)
            if obj is None or obj.zone_incarnation != inc or obj.owner_id not in shuffled_count:
                continue
            if iid in frame["send_to_command"]:
                rules._move_for_library_shuffle(obj, Zone.COMMAND)
            else:
                rules._move_for_library_shuffle(obj, Zone.LIBRARY)
                shuffled_count[obj.owner_id] += 1
                # RULE 111.7: a shuffled token counts toward the draw but cannot be drawn.
                if obj.is_token:
                    rules._cease_to_exist(obj, state.player_by_id(obj.owner_id).library)
    for player in players:
        rules.shuffle_library(player)
    draws = [_DrawForPlayer(player.id, shuffled_count[player.id]) for player in players]
    source = state.find_object(frame["source_id"])
    _apply_effects_partitioned([*draws, _ContinueHandEntry(frame)], rules.context, None, None, source=source)


class _DrawForPlayer(GameEffect):
    def __init__(self, player_id, count):
        super().__init__()
        self.player_id, self.count = player_id, count

    def apply(self, context, targets=None):
        player = context.state.player_by_id(self.player_id)
        if not player.has_lost:
            context.engine.draw(player, self.count)


class _ContinueHandEntry(GameEffect):
    def __init__(self, frame):
        super().__init__()
        self.frame = frame

    def apply(self, context, targets=None):
        _advance(context.engine, self.frame)


class _ReturnExiledToHand(GameEffect):
    def __init__(self, visit):
        super().__init__()
        self.visit = visit

    def apply(self, context, targets=None):
        instance_id, incarnation = self.visit
        obj = context.state.find_object(instance_id)
        if obj is not None and not obj.is_token and obj.zone == Zone.EXILE and obj.zone_incarnation == incarnation:
            context.engine.return_to_hand(obj)


class _ExileResolvingSpell(GameEffect):
    def __init__(self, incarnation, source):
        super().__init__(source)
        self.incarnation = incarnation

    def apply(self, context, targets=None):
        if (self.source is not None and self.source.zone == Zone.STACK
                and self.source.zone_incarnation == self.incarnation):
            context.engine.exile(self.source)


def _finish(rules, frame, entered):
    state = rules.state
    effects = []
    if frame["draw_if_missed"]:
        effects.extend(_DrawForPlayer(p.id, 1) for p in state.living_players_apnap()
                       if p.id != frame["controller_id"] and p.id not in entered)
    if frame["after"] == "return_exiled_and_exile_source":
        effects.extend(_ReturnExiledToHand(visit) for visit in frame["exiled_visits"])
    source = state.find_object(frame["source_id"])
    if frame["after"]:
        effects.append(_ExileResolvingSpell(frame["source_incarnation"], source))
    if effects:
        _apply_effects_partitioned(effects, rules.context, None, None, source=source)


def cancel_conceded_hand_entry(rules, player_id, ending_game=False):
    choice = rules.state.pending_choice or {}
    frame = choice.get("group_hand_entry")
    if frame is None:
        return
    if ending_game or frame["controller_id"] == player_id:
        rules.state.pending_choice = None
        rules.state.deferred_effects = [tail for tail in rules.state.deferred_effects
            if not ending_game and getattr(tail.get("source"), "controller_id", None) != player_id]
    elif choice["player_id"] == player_id:
        rules.state.pending_choice = None
        if choice["kind"] == "group_hand_entry_commander":
            _choose_shuffle_replacements(rules, frame)
        else:
            frame["cursor"] += 1
            _advance(rules, frame)
