"""RULE 707.10c: choose a copy's targets before putting that copy on the stack.

Pending copies and their target rounds belong to GameState, so choice rollback
never retains references to a discarded engine. The wire choice carries IDs only.
"""
from __future__ import annotations

import dataclasses
from collections import Counter

from . import continuations, targeting
from ..models.game.game_object import GameObject


def _source(item):
    return item.obj if item.obj is not None else item.source


def _key(rules, target, incarnation=None):
    if isinstance(target, dict):
        if "stack_id" in target:
            item = next((i for i in rules.state.stack if i.stack_id == target["stack_id"]), None)
            if item is not None and item.obj is not None:
                return _key(rules, item.obj, incarnation)
            return ("stack", target["stack_id"])
        if "instance_id" in target:
            obj = rules.state.find_object(target["instance_id"])
            return ("object", target["instance_id"], getattr(obj, "zone_incarnation", incarnation))
        return ("player", target.get("player_id"))
    if isinstance(target, GameObject):
        return ("object", target.instance_id, target.zone_incarnation if incarnation is None else incarnation)
    if hasattr(target, "stack_id"):
        if target.obj is not None:
            return _key(rules, target.obj, incarnation)
        return ("stack", target.stack_id)
    return ("player", getattr(target, "id", None))


def _descriptor_target(rules, descriptor):
    if "stack_id" in descriptor:
        return next((i for i in rules.state.stack if i.stack_id == descriptor["stack_id"]), None)
    if "instance_id" in descriptor:
        return rules.state.find_object(descriptor["instance_id"])
    return rules.state.player_by_id(descriptor["player_id"])


def _spec_options(rules, item, specs, prior_target=None):
    source = _source(item)
    saved_x = getattr(source, "x_paid", None)
    if source is not None:
        source.x_paid = item.x
    try:
        combined = None
        for spec in specs:
            if spec.prior_target_antecedent and prior_target is not None:
                spec = dataclasses.replace(spec, scoped_player_id=(getattr(prior_target, "id", None)
                                                                or getattr(prior_target, "controller_id", None)))
            rounds = [spec]
            if spec.per_player in targeting.PER_PLAYER_SCOPES:
                rounds, _ = targeting.expand_counts([spec], rules.state, item.controller_id, source)
            options = {}
            for current in rounds:
                for option in targeting.legal_targets(rules.state, item.controller_id, current,
                                                     source=source, trigger_event=item.trigger_event):
                    options[_key(rules, option)] = option
            combined = options if combined is None else {key: value for key, value in combined.items() if key in options}
        return list((combined or {}).values())
    finally:
        if source is not None:
            source.x_paid = saved_x


def make_frame(rules, item, may_choose):
    body = item.effects
    if len(body) == 1 and hasattr(body[0], "effects"):
        body = body[0].effects
    specs = targeting.effects_target_specs(body)
    if item.kind == "spell" and item.obj is not None and not specs:
        specs = ([targeting.TargetSpec(kind="non_human_creature_you_own")]
                 if item.obj.cast_via_mutate else targeting.spell_target_specs(item.obj))
    groups = item.target_groups or targeting.partition_targets(specs, item.targets)
    if groups is not None and len(groups) == len(specs):
        groups = [list(group) for group in groups]
        spec_sets = [[spec] for spec in specs]
        grouped = True
    else:
        groups, spec_sets, grouped = [list(item.targets)], [specs], False
    slots = []
    for group_index, group in enumerate(groups):
        for index in range(len(group)):
            slots.append({"group": group_index, "index": index, "specs": spec_sets[group_index]})
    flat = [target for group in groups for target in group]
    incarnations = list(item.target_incarnations)
    if len(incarnations) != len(flat):
        incarnations = [getattr(t, "zone_incarnation", None) for t in flat]
    return {"item": item, "groups": groups, "grouped": grouped, "slots": slots,
            "index": 0, "may_choose": bool(may_choose), "changed": [False] * len(slots),
            "keys": [_key(rules, t, inc) for t, inc in zip(flat, incarnations)],
            "incarnations": incarnations}


def _flat(frame):
    return [t for group in frame["groups"] for t in group]


def _constraints_ok(frame, keys, targets, considered):
    """Only changed targets must satisfy the cross-target constraints.

    Unchanged illegal targets remain permitted under RULE 707.10c. Prefix
    validation allows a swap: later targets can still be changed before completion.
    """
    for index in considered:
        slot = frame["slots"][index]
        same_group = [i for i in considered if frame["slots"][i]["group"] == slot["group"]]
        if not any(frame["changed"][i] for i in same_group):
            continue
        if len({keys[i] for i in same_group}) != len(same_group):
            return False  # RULE 115.3: distinct picks for one plural target requirement.
        if any(s.distinct_from_others for s in slot["specs"]):
            if any(keys[index] == keys[i] for i in considered if i != index):
                return False
        if any(s.distinct_controllers or s.per_player in targeting.PER_PLAYER_SCOPES for s in slot["specs"]):
            controllers = []
            for i in same_group:
                target = targets[i]
                if isinstance(target, GameObject) and keys[i] == ("object", target.instance_id, target.zone_incarnation):
                    controllers.append(target.controller_id)
            limit = 1
            if not any(s.distinct_controllers for s in slot["specs"]):
                limit = max(1, slot["specs"][0].count)
            if any(count > limit for count in Counter(controllers).values()):
                return False
    return True



def _prior(frame, slot):
    group = frame["groups"][slot["group"] - 1] if slot["group"] else []
    return group[0] if group else None


def _can_finish(rules, frame, start):
    """Reject partial changes that leave no legal completion (including swaps)."""
    if start == len(frame["slots"]):
        return _constraints_ok(frame, frame["keys"], _flat(frame), range(start))
    slot = frame["slots"][start]
    if (_constraints_ok(frame, frame["keys"], _flat(frame), range(start + 1))
            and _can_finish(rules, frame, start + 1)):
        return True
    old_target = frame["groups"][slot["group"]][slot["index"]]
    old_key, old_changed = frame["keys"][start], frame["changed"][start]
    try:
        for option in _spec_options(rules, frame["item"], slot["specs"], _prior(frame, slot)):
            frame["groups"][slot["group"]][slot["index"]] = _descriptor_target(rules, option)
            frame["keys"][start] = _key(rules, option)
            frame["changed"][start] = True
            if (_constraints_ok(frame, frame["keys"], _flat(frame), range(start + 1))
                    and _can_finish(rules, frame, start + 1)):
                return True
        return False
    finally:
        frame["groups"][slot["group"]][slot["index"]] = old_target
        frame["keys"][start], frame["changed"][start] = old_key, old_changed


def stage(rules, items, *, may_choose=False, defer=False):
    rules.state.pending_stack_copies.extend(make_frame(rules, item, may_choose) for item in items)
    if not defer and not rules.state.pending_choice:
        advance(rules)


def advance(rules):
    state = rules.state
    while state.pending_stack_copies:
        frame = state.pending_stack_copies[0]
        item = frame["item"]
        if frame["may_choose"]:
            while frame["index"] < len(frame["slots"]):
                index = frame["index"]
                slot = frame["slots"][index]
                targets = _flat(frame)
                prior = _prior(frame, slot)
                options = []
                for descriptor in _spec_options(rules, item, slot["specs"], prior):
                    key = _key(rules, descriptor)
                    if key == frame["keys"][index]:
                        continue
                    trial_keys, trial_targets = list(frame["keys"]), list(targets)
                    trial_keys[index], trial_targets[index] = key, _descriptor_target(rules, descriptor)
                    old_keys, old_changed = frame["keys"], frame["changed"][index]
                    old_target = frame["groups"][slot["group"]][slot["index"]]
                    frame["keys"] = trial_keys
                    frame["groups"][slot["group"]][slot["index"]] = trial_targets[index]
                    frame["changed"][index] = True
                    try:
                        valid = (_constraints_ok(frame, trial_keys, trial_targets, range(index + 1))
                                 and _can_finish(rules, frame, index + 1))
                    finally:
                        frame["keys"], frame["changed"][index] = old_keys, old_changed
                        frame["groups"][slot["group"]][slot["index"]] = old_target
                    if valid:
                        options.append({"id": f"target-{len(options)}", "label": descriptor["name"],
                                        **descriptor})
                if not options:
                    frame["index"] += 1
                    continue
                keep = []
                if _constraints_ok(frame, frame["keys"], targets, range(len(targets))):
                    keep.append({"id": "decline", "label": "Alle übrigen Ziele behalten"})
                if (_constraints_ok(frame, frame["keys"], targets, range(index + 1))
                        and _can_finish(rules, frame, index + 1)):
                    keep.append({"id": "keep", "label": "Dieses Ziel behalten"})
                rules.open_choice({"kind": "copy_targets", "player_id": item.controller_id,
                                   "copy_stack_id": item.stack_id, "optional": any(o["id"] == "decline" for o in keep),
                                   "prompt": f"{item.description}: Ziel {index + 1} von {len(targets)}",
                                   "options": [*keep, *options]})
                return
        item.targets = _flat(frame)
        item.target_groups = frame["groups"] if frame["grouped"] else None
        item.target_incarnations = list(frame["incarnations"])
        item.copy_target_roles = [slot["specs"] for slot in frame["slots"]]
        state.ready_stack_copies.append(item)
        state.pending_stack_copies.pop(0)
    ready, state.ready_stack_copies = state.ready_stack_copies, []
    # RULE 707.10c: every copy has its final targets before copies/events are announced.
    state.stack.extend(ready)
    for item in ready:
        if item.kind == "spell":
            rules._fire_spell_copied(item)
        if item.ward_check_deferred:
            item.deferred_ward_triggers = rules.check_ward(item, state.player_by_id(item.controller_id),
                                                          defer_stack=True)
        else:
            rules.check_ward(item, state.player_by_id(item.controller_id))


@continuations.choice("copy_targets", answer=continuations.ANSWER_STR, rule="707.10c")
def resume(rules, choice, answer):
    if answer is None:
        answer = "decline"
    frame = rules.state.pending_stack_copies[0]
    if frame["item"].stack_id != choice["copy_stack_id"]:
        raise ValueError("the pending copy changed")
    option = next((o for o in choice["options"] if o["id"] == answer), None)
    if option is None:
        rules.open_choice(choice)
        raise ValueError("Choose a listed target or keep the existing targets")
    index = frame["index"]
    if answer == "decline":
        frame["index"] = len(frame["slots"])
    elif answer == "keep":
        frame["index"] += 1
    else:
        slot = frame["slots"][index]
        target = _descriptor_target(rules, option)
        legal = {_key(rules, o) for o in _spec_options(rules, frame["item"], slot["specs"], _prior(frame, slot))}
        if target is None or _key(rules, option) not in legal:
            rules.open_choice(choice)
            raise ValueError("the new target is no longer legal")
        frame["groups"][slot["group"]][slot["index"]] = target
        frame["keys"][index] = _key(rules, target)
        frame["incarnations"][index] = getattr(target, "zone_incarnation", None)
        frame["changed"][index] = True
        frame["index"] += 1
    advance(rules)


def target_is_legal(rules, item, index, target):
    if hasattr(target, "stack_id") and target not in rules.state.stack:
        return False  # A former spell/ability item cannot refer to a later casting of its card.
    if index >= len(item.copy_target_roles) or not item.copy_target_roles[index]:
        return True
    frame = make_frame(rules, item, False)
    prior = _prior(frame, frame["slots"][index])
    return _key(rules, target) in {_key(rules, o) for o in _spec_options(rules, item, item.copy_target_roles[index], prior)}


def resolution_targets(rules, item):
    """RULE 608.2b: mask illegal occurrences without shifting target slots.

    Legality is checked once as resolution begins. Instructions and suspended
    continuations receive the same slots, including absent targets, so a later
    target cannot inherit an earlier target's clause or allocated damage.
    """
    legal = []
    for index, target in enumerate(item.targets):
        incarnation = item.target_incarnations[index] if index < len(item.target_incarnations) else None
        obj = target if isinstance(target, GameObject) else getattr(target, "obj", None)
        same_object = obj is None or incarnation in (None, obj.zone_incarnation)
        legal.append(same_object and target_is_legal(rules, item, index, target))
    targets = [target if valid else None for target, valid in zip(item.targets, legal)]
    groups = None
    if item.target_groups is not None:
        groups = []
        offset = 0
        for group in item.target_groups:
            groups.append(targets[offset:offset + len(group)])
            offset += len(group)
    return targets, groups, legal
