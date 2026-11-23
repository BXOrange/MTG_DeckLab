"""Lock and pay the non-mana portion of a combat declaration."""
from __future__ import annotations

from . import combat
from .continuations import ANSWER_INT, choice


def payment_slots(engine, player, entries, participants):
    life = 0
    slots = []
    for entry in entries:
        payment = entry.get("payment")
        if payment is None:
            continue
        if payment == "life":
            life += entry["count"]
            continue
        filt = entry["payment_filter"]
        if payment == "sacrifice":
            candidates = engine.rules._sacrifice_candidates(player, object_filter=filt)
        else:
            candidates = [
                obj for obj in engine.state.permanents_controlled_by(player.id)
                if combat.matches_object_filter(obj, filt, state=engine.state)
                and (payment != "tap" or (
                    not obj.tapped and obj.instance_id not in participants
                    and not obj.attacking and not combat.blocking_attacker_ids(obj)
                ))
            ]
        slots.extend((payment, candidates) for _ in range(entry["count"]))
    if life and (player.life < life or engine.rules._life_locked(player)):
        raise ValueError("cannot pay the life cost to declare combat")
    return life, slots


def _can_match(slots, used):
    """Check that every remaining payment can use a distinct permanent."""
    matched = {}

    def assign(index, seen):
        for obj in slots[index][1]:
            iid = obj.instance_id
            if iid in used or iid in seen:
                continue
            seen.add(iid)
            if iid not in matched or assign(matched[iid], seen):
                matched[iid] = index
                return True
        return False

    return all(assign(index, set()) for index in range(len(slots)))


def select_permanents(engine, player, slots, draft, selections):
    """Validate all picks before payment, suspending the declaration if needed."""
    used = set()
    payments = []
    if len(selections) > len(slots) or not _can_match(slots, used):
        raise ValueError("cannot pay the permanent costs to declare combat")
    for index, (payment, candidates) in enumerate(slots):
        options = [
            obj for obj in candidates
            if obj.instance_id not in used
            and _can_match(slots[index + 1:], used | {obj.instance_id})
        ]
        if index < len(selections):
            chosen = next((obj for obj in options if obj.instance_id == selections[index]), None)
            if chosen is None:
                raise ValueError("invalid combat cost payment")
        elif len(options) == 1:
            chosen = options[0]
        else:
            prompts = {
                "sacrifice": "Bleibende Karte für die Kampfkosten opfern",
                "return": "Bleibende Karte für die Kampfkosten auf die Hand zurücknehmen",
                "tap": "Kreatur für die Kampfkosten tappen",
            }
            engine.rules.open_choice({
                "kind": "combat_payment", "player_id": player.id, "optional": True,
                "prompt": prompts[payment], "draft": draft,
                "selections": [obj.instance_id for _, obj in payments],
                "options": [{"id": str(obj.instance_id), "label": obj.name,
                             "instance_id": obj.instance_id} for obj in options],
            })
            return None
        used.add(chosen.instance_id)
        payments.append((payment, chosen))
    return payments


@choice("combat_payment", answer=ANSWER_INT, rule="508.1j")
def _resume_combat_payment(rules, pending, answer):
    if answer is None:
        return
    if not any(int(option["id"]) == answer for option in pending["options"]):
        rules.open_choice(pending)
        raise ValueError("choose a listed permanent")
    pending["selections"].append(answer)
    pending["confirmed"] = True


def resume_declaration(engine, pending):
    if not pending.get("confirmed"):
        return
    draft = pending["draft"]
    player = engine.state.player_by_id(pending["player_id"])
    if draft["verb"] == "attack":
        engine.declare_attackers(player, [
            {**entry, "attacker": engine.state.find_object(entry["attacker"]),
             "enlist": [engine.state.find_object(iid) for iid in entry["enlist"]]}
            for entry in draft["entries"]
        ], cost_choices=pending["selections"])
    else:
        engine.declare_blockers(player, [
            (engine.state.find_object(blocker), engine.state.find_object(attacker))
            for blocker, attacker in draft["entries"]
        ], pay_block_tax=draft["pay_tax"], cost_choices=pending["selections"])


def pay(engine, player, life, payments):
    # RULE 508.1j / 509.1f: the complete cost was validated before any payment.
    if life:
        engine.rules.lose_life(player, life, cause="cost")
    with engine.state.simultaneous():
        for payment, obj in payments:
            if payment == "sacrifice":
                engine.rules.put_into_graveyard(obj)
            elif payment == "return":
                engine.rules.return_to_hand(obj)
            else:
                engine.rules.set_tapped(obj, True, reason="cost", tapper_id=player.id)
