#!/usr/bin/env python3
"""Offline paired SmartBot campaign. Writes diagnostics only to --output.

Use isolated MTG_DATA_DIR/MTG_CACHE_DIR when measuring real decks. Local DB
arguments are always opened read-only. Baseline source is an explicitly
provided, trusted local Python policy snapshot (not data from card text).
"""
from __future__ import annotations
import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import hashlib
import importlib.util
import json
import os
import platform
from pathlib import Path
import sqlite3
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def parser():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--baseline-source',type=Path)
    p.add_argument('--decks-db',type=Path)
    p.add_argument('--cards-db',type=Path)
    p.add_argument('--seeds',type=int,default=2)
    p.add_argument('--workers',type=int,default=1)
    p.add_argument('--action-budget',type=int,default=400)
    p.add_argument('--turn-budget',type=int,default=12)
    p.add_argument('--deck-id',action='append',default=[])
    p.add_argument('--split',choices=['development','validation','test','all'],default='all')
    return p


def generated_decks():
    """Grouped strategy matrix independent of saved decks/named commanders.

    Each group stays within a split; alternate wordings, costs and creature
    mixes vary across split families. IDs describe mechanics, never policy keys.
    These are controlled engine fixtures, not claims of competitive decklists.
    """
    from mtg_analyzer.models.cards.card import Card
    def card(name,text='',cost='',types='Sorcery',power=None,toughness=None):
        import re
        mv=sum(int(x) if x.isdigit() else 1 for x in re.findall(r'\{([^}]*)\}',cost) if x!='X')
        return Card(id=name,name=name,oracle_text=text,mana_cost_string=cost,converted_mana_cost=mv,
                    type_line=types,is_land='Land' in types,is_creature='Creature' in types,
                    is_instant=types=='Instant',is_sorcery=types=='Sorcery',
                    power=power,toughness=toughness,color_identity={'G','U','B','W','R'})
    basics=[Card(id=c,name=c,type_line=f'Basic Land — {c}',is_land=True) for c in ('Forest','Island','Swamp','Mountain','Plains')]
    texts={
        'aggro': ('Haste','Creature','{R}',2,1),
        'tempo': ('Flying','Creature','{1}{U}',2,1),
        'midrange': ('When this creature enters, draw a card.','Creature','{2}{G}',3,3),
        'control': ('Counter target spell.','Instant','{1}{U}',None,None),
        'ramp': ('Search your library for a basic land card, put that card onto the battlefield tapped, then shuffle.','Sorcery','{1}{G}',None,None),
        'spells': ('Whenever you cast a noncreature spell, draw a card.','Creature','{2}{U}',1,3),
        'tokens': ('Create two 1/1 white Soldier creature tokens.','Sorcery','{1}{W}',None,None),
        'sacrifice': ('Sacrifice another creature: Draw a card.','Creature','{2}{B}',2,2),
        'graveyard': ('Return target creature card from your graveyard to the battlefield.','Sorcery','{3}{B}',None,None),
        'voltron': ('Equipped creature gets +2/+2.\nEquip {1}','Artifact — Equipment','{1}',None,None),
        'counters': ('Put two +1/+1 counters on target creature.','Sorcery','{1}{G}',None,None),
        'lands': ('Landfall — Whenever a land you control enters, draw a card.','Creature','{2}{G}',2,2),
        'burn': ('This spell deals 3 damage to any target.','Instant','{R}',None,None),
        'mill': ('Target player mills three cards.','Sorcery','{U}',None,None),
        'stax': ("Each player can't cast more than one spell each turn.",'Enchantment','{2}{W}',None,None),
        'combo': ('Sacrifice another creature: Create a 1/1 black Rat creature token.','Creature','{1}{B}',1,2),
        'alternate-win': ('You win the game.','Sorcery','{8}{U}{U}',None,None),
    }
    for split,index in [('development',0),('validation',1),('test',2)]:
        for family,args in texts.items():
            cards=[]
            for i in range(8):
                text,types,cost,p,t=args
                # Holdouts include distinct stat/cost realizations and a
                # different support mix, not merely reshuffled same lists.
                if index and 'Creature' in types:
                    cost='{1}'+cost;p=(p or 0)+index;t=(t or 0)+index
                name=f'{split}-{family}-mechanic-{i}'
                text=text.replace('This spell',name)
                if family=='combo' and i>=4:
                    text='Whenever another creature you control dies, each opponent loses 1 life.'
                cards.append(card(name,text,cost,types,p,t))
            support=[card(f'{split}-{family}-body-{i}','', '{1}{G}' if index!=2 else '{2}{G}',
                          'Creature',2+index,2+index) for i in range(12)]
            draw=[card(f'{split}-{family}-draw-{i}','Draw two cards.' if index!=1 else 'Draw three cards.',
                       '{2}{U}' if index!=1 else '{3}{U}') for i in range(4)]
            if index==2:
                # Composition holdout: support creatures acquire capabilities
                # absent from development's vanilla support shell.
                for i,c in enumerate(support):
                    if i<4:c.oracle_text='Vigilance'
                    elif i<8:c.oracle_text=f'Whenever {c.name} attacks, scry 1.'
            cards += support+draw+basics*7
            yield {'id':f'{split}/{family}','group':f'{split}/{family}','split':split,'family':family,
                   'cards':[c.to_dict() for c in cards],'commanders':[],'archetypes':None}


def local_decks(decks_path,cards_path):
    from mtg_analyzer.parser.deckliste_parser import parse_deck_sections
    ro=lambda p:sqlite3.connect(f'file:{p.resolve()}?mode=ro',uri=True)
    with ro(cards_path) as cache:
        lookup={n.casefold():json.loads(d) for n,d in cache.execute('SELECT name,data FROM cards')}
    for n,d in list(lookup.items()):
        lookup.setdefault(n.replace(' // ',' / '),d)
        lookup.setdefault(n.split(' // ')[0],d)
    with ro(decks_path) as db:
        rows=db.execute('SELECT id,name,data FROM decks').fetchall()
    for did,name,raw in rows:
        d=json.loads(raw)
        parsed=parse_deck_sections(d.get('commanderText',''),d.get('mainboardText',''),d.get('sideboardText',''),d.get('isCube',False))
        missing=[]
        def resolve(entries):
            result=[]
            for e in entries:
                c=lookup.get(e.name.casefold())
                if c:result.extend([c]*e.qty)
                else:missing.append(e.name)
            return result
        main=resolve(parsed.main_deck);cmd=resolve(parsed.commanders)
        yield {'id':did,'name':name,'group':did,'split':'known_regression','family':'local',
               'cube':bool(d.get('isCube')),'missing':missing,'cards':main,'commanders':cmd,'archetypes':d.get('archetypes')}


def run_job(job):
    from mtg_analyzer.models.cards.card import Card
    from mtg_analyzer.services.bot_policies.smart import SmartBot
    from mtg_analyzer.services.bot_policies.smart2 import SmartBot2
    from mtg_analyzer.services.bot_policies.greedy import GreedyBot
    from mtg_analyzer.services.smart_bot2.benchmark import run_match
    from mtg_analyzer.parser.oracle.gate import parse_oracle
    from mtg_analyzer.game.card_registry.core import is_authored_card
    d,kind,seed,baseline,ab,tb=job
    policies={'smart1':SmartBot,'candidate':SmartBot2}
    if baseline:
        spec=importlib.util.spec_from_file_location('mtg_analyzer.services.bot_policies.smart2_baseline',baseline)
        mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
        policies['baseline2']=mod.SmartBot2
    try:
        # An unchanged, proactive benchmark opponent is used for every policy;
        # it is deliberately independent of the changing candidate class.
        from mtg_analyzer.models.cards.card import Card as C
        opponent=[C(id='Forest',name='Forest',type_line='Basic Land — Forest',is_land=True)]*24
        opponent += [C(id=f'fixed-body-{i}',name=f'Fixed Body {i}',type_line='Creature',is_creature=True,
                       power=2,toughness=2,mana_cost_string='{1}{G}',converted_mana_cost=2) for i in range(36)]
        resolved=[Card.from_dict(c) for c in d['cards']]
        commanders=[Card.from_dict(c) for c in d['commanders']]
        unique={c.name:c for c in resolved+commanders}
        unsupported=[c.name for c in unique.values() if c.oracle_text and not is_authored_card(c) and not parse_oracle(c).modeled]
        result=run_match(resolved, commanders,
                        policies[kind],seed=seed,seat=seed%2,opponent_cards=opponent,
                        opponent_policy=GreedyBot,action_budget=ab,turn_budget=tb,archetypes=d['archetypes'])
    except Exception as exc:
        result={'status':'error','errors':[f'{type(exc).__name__}: {exc}']}
    result['unmodeled_cards']=unsupported if 'unsupported' in locals() else []
    return {'deck_id':d['id'],'group':d['group'],'family':d['family'],'split':d['split'],'policy':kind,'seed':seed,**result}


def main():
    args=parser().parse_args()
    if args.seeds<1 or args.workers<1:raise SystemExit('seeds/workers must be positive')
    if bool(args.decks_db)!=bool(args.cards_db):raise SystemExit('both local DB paths are required')
    args.output.mkdir(parents=True,exist_ok=True)
    decks=list(local_decks(args.decks_db,args.cards_db) if args.decks_db else generated_decks())
    if not args.decks_db and args.split!='all':decks=[d for d in decks if d['split']==args.split]
    if args.deck_id:decks=[d for d in decks if d['id'] in set(args.deck_id)]
    policies=['smart1','baseline2','candidate'] if args.baseline_source else ['smart1','candidate']
    # Fail explicitly for missing identities. A cube isn't a normal deck.
    excluded=[{'id':d['id'],'reason':'cube' if d.get('cube') else 'missing_cards','missing':d.get('missing',[])}
              for d in decks if d.get('cube') or d.get('missing')]
    active=[d for d in decks if not d.get('cube') and not d.get('missing')]
    manifest={'version':2,'hardware':{'platform':platform.platform(),'python':platform.python_version(),'cpus':os.cpu_count()},'sources':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in list((ROOT/'mtg_analyzer/services/smart_bot2').glob('*.py'))+[ROOT/'mtg_analyzer/services/bot_policies/smart2.py',ROOT/'mtg_analyzer/game/engine/casting_mixin.py']},'seeds':args.seeds,'policies':policies,'action_budget':args.action_budget,
              'turn_budget':args.turn_budget,'excluded':excluded,'decks':[
                  {k:v for k,v in d.items() if k not in ('cards','commanders','name')} |
                  {'fingerprint':hashlib.sha256(json.dumps([d['cards'],d['commanders']],sort_keys=True).encode()).hexdigest()}
                  for d in active],
              'baseline_sha256':hashlib.sha256(args.baseline_source.read_bytes()).hexdigest() if args.baseline_source else None}
    (args.output/'manifest.json').write_text(json.dumps(manifest,indent=2))
    jobs=[(d,p,seed,str(args.baseline_source.resolve()) if args.baseline_source else None,args.action_budget,args.turn_budget)
          for d in active for seed in range(args.seeds) for p in policies]
    rows=[];start=time.monotonic()
    with (args.output/'matches.jsonl').open('w') as out:
        with ProcessPoolExecutor(max_workers=args.workers) as pool:
            futures=[pool.submit(run_job,j) for j in jobs]
            for f in as_completed(futures):
                row=f.result();rows.append(row);out.write(json.dumps(row,default=str)+'\n');out.flush()
                if len(rows)%25==0:print(f'{len(rows)}/{len(jobs)} matches in {time.monotonic()-start:.1f}s',flush=True)
    summary={}
    for p in policies:
        subset=[r for r in rows if r['policy']==p]
        counts={s:sum(r['status']==s for r in subset) for s in sorted({r['status'] for r in subset})}
        summary[p]={'matches':len(subset),'status':counts,'rejections':sum(bool(r.get('rejections')) for r in subset),
                    'worst_match_p95_ms':max((r.get('decision_ms',{}).get('p95',0) for r in subset),default=0)}
    (args.output/'summary.json').write_text(json.dumps(summary,indent=2))
    print(json.dumps(summary,indent=2))


if __name__=='__main__':main()
