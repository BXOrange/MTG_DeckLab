"""Bounded public-board combat estimates, not a replacement rules engine."""
from __future__ import annotations
from itertools import combinations
import re
from .context import W, MAX_COMBAT_PACKAGES, POISON_LETHAL, COMMANDER_LETHAL, number, stable


DEFENSIVE_RESERVE_FACTOR = .5  # only part of material value represents a future block

def keywords(obj):
    return {str(k).casefold() for k in obj.get('keywords', [])}


def damage(ctx, obj):
    # RULE 510.1a: power unless a known public ability explicitly substitutes
    # toughness. Never infer damage basis merely from the archetype label.
    text = ctx.text(obj)
    own = obj.get('controller_id') == ctx.player_id
    grants = ctx.public_text() if own else '\n'.join(ctx.text(o) for o in ctx.theirs
                    if o.get('controller_id') == obj.get('controller_id'))
    toughness = 'combat damage equal to its toughness' in text or (
        'each creature you control assigns combat damage equal to its toughness' in grants)
    return max(0, number(obj.get('toughness' if toughness else 'power')))


def can_block(ctx, attacker, blocker):
    a, b = keywords(attacker), keywords(blocker)
    if blocker.get('tapped') or blocker.get('phased_out') or not blocker.get('is_creature'):
        return False
    if 'flying' in a and not {'flying', 'reach'} & b:
        return False
    text = ctx.text(attacker)
    if "can't be blocked" in text and 'except' not in text and 'by ' not in text:
        return False
    if 'shadow' in a and 'shadow' not in b or 'shadow' in b and 'shadow' not in a:
        return False
    return True


def dies(ctx, victim, hitters):
    if 'indestructible' in keywords(victim):
        return False
    marked = number(victim.get('damage_marked'))
    return (sum(damage(ctx, b) for b in hitters) + marked >= number(victim.get('toughness'), 1)
            or any(damage(ctx, b) > 0 and 'deathtouch' in keywords(b) for b in hitters))


def exchange(ctx, attacker, blockers):
    """Estimate face damage and material cost with first/double strike.

    RULE 510.4 / 702.2 / 702.19. Choose a plausible damaging block; multi-
    blocks are pessimistic for attacker survival. Unknown taxes remain legal-
    action/engine concerns. No estimate is advertised as a verified win.
    """
    ak = keywords(attacker)
    power = damage(ctx, attacker)
    double = 'double strike' in ak
    first = double or 'first strike' in ak
    if not blockers:
        return power * (2 if double else 1), 0.0
    bvalue = 0.0
    remaining = list(blockers)
    if first:
        budget = power
        for b in sorted(blockers, key=ctx.value, reverse=True):
            lethal = 1 if 'deathtouch' in ak and power else max(0, number(b.get('toughness'), 1) - number(b.get('damage_marked')))
            if budget >= lethal and 'indestructible' not in keywords(b):
                remaining.remove(b)
                bvalue += ctx.value(b)
                budget -= lethal
    early = [b for b in blockers if {'first strike', 'double strike'} & keywords(b)]
    dead_early = dies(ctx, attacker, early)
    dead = dead_early or dies(ctx, attacker, remaining)
    if not first and not dead_early:
        budget = power
        for b in sorted(blockers, key=ctx.value, reverse=True):
            lethal = 1 if 'deathtouch' in ak and power else max(0, number(b.get('toughness'), 1) - number(b.get('damage_marked')))
            if budget >= lethal and 'indestructible' not in keywords(b):
                bvalue += ctx.value(b)
                budget -= lethal
    face = 0
    if 'trample' in ak and not dead_early:
        shields = sum(1 if 'deathtouch' in ak and power else max(0, number(b.get('toughness'), 1) - number(b.get('damage_marked'))) for b in blockers)
        face = max(0, power - shields)
        if double and not dead:
            face += max(0, power - sum(max(0, number(b.get('toughness'), 1)) for b in remaining))
    return face, (ctx.value(attacker) * W.loss if dead else 0) - bvalue


def hit_value(ctx, obj, face, defender):
    value = face * W.combat_damage
    text, kw = ctx.text(obj), keywords(obj)
    if 'combat-hit' in ctx.roles(obj) and face > 0:
        value += W.attack_trigger
    if 'lifelink' in kw and number(ctx.me.get('life'), 40) < number(defender.get('life'), 40):
        value += face
    if 'infect' in kw:
        value = face * W.combat_damage
        if face + number(defender.get('poison')) >= POISON_LETHAL:
            value += W.lethal
    else:
        toxic = max([int(m) for k in kw for m in re.findall(r'toxic (\d+)', k)] or [0])
        if face and toxic + number(defender.get('poison')) >= POISON_LETHAL:
            value += W.lethal
        if face >= number(defender.get('life'), 40):
            value += W.lethal
    if obj.get('instance_id') in {c.get('instance_id') for c in ctx.me.get('command', [])} or obj.get('is_commander') or (
        # Commander identity is own setup knowledge, not a strategic name bonus.
        (ctx.plan(obj) and ctx.plan(obj).name.casefold() in ctx.profile.commanders)):
        entry = (defender.get('commander_damage') or {}).get(str(obj.get('instance_id')), {})
        if face + number(entry.get('amount')) >= COMMANDER_LETHAL:
            value += W.lethal
    return value


def _equivalence(ctx, obj):
    # Group ordinary tokens/vanilla bodies only. Commander identities and
    # individual attack/hit engines need their own decisions.
    if ctx.roles(obj) & {'attack', 'combat-hit'} or (ctx.plan(obj) and ctx.plan(obj).name.casefold() in ctx.profile.commanders):
        return ('individual', obj.get('instance_id'))
    return (number(obj.get('power')), number(obj.get('toughness')), tuple(sorted(keywords(obj))),
            obj.get('damage_marked', 0))


def _homogeneous_swing(ctx, attackers, blockers, defender):
    if len({_equivalence(ctx,a) for a in attackers}) != 1 or len({_equivalence(ctx,b) for b in blockers}) > 1:
        return None
    a = attackers[0]
    legal_blockers = blockers if blockers and can_block(ctx,a,blockers[0]) else []
    needed = 2 if 'menace' in keywords(a) else 1
    blocked = min(len(attackers),len(legal_blockers)//needed)
    face, loss = exchange(ctx,a,legal_blockers[:needed]) if blocked else (0,0)
    unblocked = len(attackers)-blocked
    total_face = blocked*face + unblocked*damage(ctx,a)*(2 if 'double strike' in keywords(a) else 1)
    utility = total_face*W.combat_damage - blocked*loss
    player = next((p for p in ctx.opponents if p['id']==defender.get('id')), {})
    if total_face >= number(player.get('life'),40):
        utility += W.lethal
    if ctx.behind and 'vigilance' not in keywords(a):
        utility -= sum(ctx.value(o) for o in attackers)*DEFENSIVE_RESERVE_FACTOR
    return utility


def attack(ctx, offers):
    if not offers:
        return None
    legal = {o['instance_id']: o for o in offers}
    attackers = [ctx.obj(o) for o in offers]
    attackers.sort(key=lambda o: (-damage(ctx, o), str(o.get('instance_id'))))
    if len(attackers) > MAX_COMBAT_PACKAGES:
        # Common huge token boards are evaluated analytically by equivalent
        # bodies; mixed boards use a bounded conservative subset instead.
        swings = []
        for defender in offers[0].get('legal_defenders', []):
            if defender.get('kind') != 'player':
                continue
            eligible = [a for a in attackers if defender in legal[a['instance_id']].get('legal_defenders', [])]
            pool = [b for b in ctx.theirs if b.get('controller_id')==defender.get('id')
                    and b.get('is_creature') and not b.get('tapped')]
            if eligible:
                utility = _homogeneous_swing(ctx,eligible,pool,defender)
                if utility is not None and utility > 0:
                    swings.append((utility,defender,eligible))
        if swings:
            _,defender,chosen = max(swings,key=lambda x:(x[0],stable(x[1])))
            return {'type':'attack','instance_ids':[a['instance_id'] for a in chosen],'defender':defender}
        attackers = attackers[:MAX_COMBAT_PACKAGES]
    packages = [attackers]
    # Sample broad and small alternatives before singleton packages can fill
    # the budget; otherwise a token board would become all-or-one.
    sizes = sorted({len(attackers)//2, max(1,len(attackers)-1), 2, 3, 4})
    packages += [attackers[:i] for i in sizes if 0 < i < len(attackers)]
    packages += [[o] for o in attackers[:MAX_COMBAT_PACKAGES]]
    best = (0.0, None)
    defenders = {stable(d): d for offer in offers for d in offer.get('legal_defenders', [])}
    for defender in sorted(defenders.values(), key=stable):
        pid = defender.get('id')
        player = next((p for p in ctx.opponents if p['id'] == pid), {})
        # Planeswalkers and battles are keyed by instance_id, players by id.
        permanent = {} if pid is not None else ctx.by_id.get(defender.get('instance_id'), {})
        if permanent.get('is_battle') and permanent.get('controller_id') != ctx.me.get('id'):
            continue  # RULE 310.8b: only flipping our own Siege is worth the attack
        # RULE 310.8b: a battle is defended by its protector, a planeswalker by its controller.
        defending_id = pid if player else (permanent.get('protector_id') if permanent.get('is_battle')
                                           else permanent.get('controller_id'))
        pool = [b for b in ctx.theirs if b.get('controller_id') == defending_id
                and b.get('is_creature') and not b.get('tapped')]
        for package in packages[:MAX_COMBAT_PACKAGES]:
            chosen = [a for a in package if defender in legal[a['instance_id']].get('legal_defenders', [])]
            if not chosen:
                continue
            blockers = list(pool)
            score, total_face = 0.0, 0.0
            for a in chosen:
                relevant = [b for b in blockers if can_block(ctx, a, b)]
                groups = [[b] for b in relevant[:MAX_COMBAT_PACKAGES]]
                if 'menace' in keywords(a):
                    groups = [list(p) for p in combinations(relevant[:MAX_COMBAT_PACKAGES], 2)][:MAX_COMBAT_PACKAGES]
                elif len(relevant) > 1:
                    groups += [relevant]  # pessimistic gang block
                possibilities = [(exchange(ctx, a, g), g) for g in groups]
                # Opponent prefers to prevent damage and win material.
                result, picked = max(possibilities, key=lambda p: (damage(ctx, a) - p[0][0]) * W.combat_damage + p[0][1],
                                     default=((damage(ctx, a) * (2 if 'double strike' in keywords(a) else 1), 0), []))
                face, loss = result
                for b in picked:
                    if b in blockers:
                        blockers.remove(b)
                score += (hit_value(ctx, a, face, player) if player else face * W.combat_damage) - loss
                total_face += face
                if 'attack' in ctx.roles(a):
                    score += W.attack_trigger
                if 'dethrone' in ctx.text(a) and player and number(player.get('life'), 40) >= max(number(p.get('life'), 40) for p in ctx.players):
                    score += W.attack_trigger
            if player and total_face >= number(player.get('life'), 40) and not any('infect' in keywords(a) for a in chosen):
                score += W.lethal
            if permanent and total_face >= number(permanent.get('loyalty', permanent.get('defense')), 1):
                score += ctx.value(permanent)
            # Keep a real defensive reserve when we are behind. Vigilance and
            # public attack-untap abilities don't consume a blocker.
            exposed = [a for a in chosen if 'vigilance' not in keywords(a) and 'untap it' not in ctx.text(a)]
            if ctx.behind:
                score -= sum(ctx.value(a) for a in exposed) * DEFENSIVE_RESERVE_FACTOR
            if score > best[0]:
                best = (score, {'type': 'attack', 'instance_ids': [a['instance_id'] for a in chosen], 'defender': defender})
    return best[1]


def blocks(ctx, offers):
    available = {o['instance_id']: o for o in offers}
    used, assignments = set(), []
    attackers = {a['instance_id']: ctx.obj(a) for o in offers for a in o.get('legal_attackers', [])}
    for a in sorted(attackers.values(), key=lambda a: (-damage(ctx, a), str(a.get('instance_id')))):
        legal = [ctx.obj(o) for i, o in available.items() if i not in used
                 and any(t['instance_id'] == a['instance_id'] for t in o.get('legal_attackers', []))]
        count = 2 if 'menace' in keywords(a) else 1
        groups = list(combinations(legal[:MAX_COMBAT_PACKAGES], count))[:MAX_COMBAT_PACKAGES]
        if count == 1:
            groups += list(combinations(legal[:MAX_COMBAT_PACKAGES], 2))[:MAX_COMBAT_PACKAGES]
        best = (0.0, ())
        for group in groups:
            face, loss = exchange(ctx, a, list(group))
            prevented = damage(ctx, a) * (2 if 'double strike' in keywords(a) else 1) - face
            # Attacker's material loss benefits defender; damage prevention
            # matters even if no one creature would be lethal in isolation.
            score = prevented * W.combat_damage + loss
            incoming = sum(damage(ctx, x) for x in attackers.values())
            if incoming >= number(ctx.me.get('life'), 40) or (
                'infect' in keywords(a) and damage(ctx, a) + number(ctx.me.get('poison')) >= POISON_LETHAL):
                score += W.lethal * bool(prevented)
            if score > best[0]:
                best = score, group
        for b in best[1]:
            used.add(b['instance_id'])
            assignments.append({'blocker': b['instance_id'], 'attacker': a['instance_id']})
    return assignments
