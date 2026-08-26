# Comprehensive Rules — Master Index

> Auto-generated from `MagicCompRules 20260807.txt` — do not edit by hand.
> Regenerate with `python3 docs/Reference/rules_wiki/build_wiki.py`.

Line numbers point into the source rules file and equal the `Read` tool's
`offset`. Sections are short (~10–60 lines); read a whole section by its line.
For a specific subrule, use `rule_line_index.json`.

**Source:** [`MagicCompRules 20260807.txt`](../MagicCompRules%2020260807.txt) · **Glossary starts at line 7100** (see [glossary_index.md](glossary_index.md))

| How to jump | Example |
| --- | --- |
| Whole section | look up `613` below → `Read(source, offset=<line>, limit=60)` |
| One subrule | `rule_line_index.json` → `subrules["613.7"]` → `Read(...)` |
| A defined term | [glossary_index.md](glossary_index.md) → term → line |

## 1. Game Concepts  ·  _line 182_

| Rule | Title | Line | Subrules |
| --- | --- | --- | --- |
| **100** | General | 184 | 19 |
| **101** | The Magic Golden Rules | 224 | 10 |
| **102** | Players | 248 | 4 |
| **103** | Starting the Game | 258 | 32 |
| **104** | Ending the Game | 324 | 30 |
| **105** | Colors | 386 | 8 |
| **106** | Mana | 404 | 20 |
| **107** | Numbers and Symbols | 449 | 49 |
| **108** | Cards | 554 | 11 |
| **109** | Objects | 578 | 16 |
| **110** | Permanents | 612 | 14 |
| **111** | Tokens | 643 | 34 |
| **112** | Spells | 719 | 7 |
| **113** | Abilities | 736 | 41 |
| **114** | Emblems | 824 | 5 |
| **115** | Targets | 836 | 26 |
| **116** | Special Actions | 892 | 15 |
| **117** | Timing and Priority | 924 | 20 |
| **118** | Costs | 966 | 39 |
| **119** | Life | 1049 | 17 |
| **120** | Damage | 1085 | 25 |
| **121** | Drawing a Card | 1140 | 17 |
| **122** | Counters | 1176 | 20 |
| **123** | Stickers | 1218 | 26 |

## 2. Parts of a Card  ·  _line 1276_

| Rule | Title | Line | Subrules |
| --- | --- | --- | --- |
| **200** | General | 1278 | 3 |
| **201** | Name | 1286 | 22 |
| **202** | Mana Cost and Color | 1338 | 19 |
| **203** | Illustration | 1386 | 1 |
| **204** | Color Indicator | 1390 | 2 |
| **205** | Type Line | 1396 | 33 |
| **206** | Expansion Symbol | 1470 | 8 |
| **207** | Text Box | 1488 | 9 |
| **208** | Power/Toughness | 1508 | 10 |
| **209** | Loyalty | 1532 | 2 |
| **210** | Defense | 1538 | 1 |
| **211** | Hand Modifier | 1542 | 1 |
| **212** | Life Modifier | 1546 | 1 |
| **213** | Information Below the Text Box | 1550 | 8 |

## 3. Card Types  ·  _line 1568_

| Rule | Title | Line | Subrules |
| --- | --- | --- | --- |
| **300** | General | 1570 | 4 |
| **301** | Artifacts | 1580 | 15 |
| **302** | Creatures | 1612 | 10 |
| **303** | Enchantments | 1635 | 20 |
| **304** | Instants | 1677 | 5 |
| **305** | Lands | 1689 | 11 |
| **306** | Planeswalkers | 1714 | 13 |
| **307** | Sorceries | 1742 | 6 |
| **308** | Kindreds | 1756 | 3 |
| **309** | Dungeons | 1764 | 16 |
| **310** | Battles | 1798 | 24 |
| **311** | Planes | 1848 | 7 |
| **312** | Phenomena | 1864 | 7 |
| **313** | Vanguards | 1880 | 7 |
| **314** | Schemes | 1896 | 7 |
| **315** | Conspiracies | 1912 | 9 |

## 4. Zones  ·  _line 1932_

| Rule | Title | Line | Subrules |
| --- | --- | --- | --- |
| **400** | General | 1934 | 29 |
| **401** | Library | 1995 | 7 |
| **402** | Hand | 2011 | 3 |
| **403** | Battlefield | 2019 | 5 |
| **404** | Graveyard | 2031 | 3 |
| **405** | Stack | 2039 | 14 |
| **406** | Exile | 2069 | 10 |
| **407** | Ante | 2091 | 4 |
| **408** | Command | 2101 | 3 |

## 5. Turn Structure  ·  _line 2110_

| Rule | Title | Line | Subrules |
| --- | --- | --- | --- |
| **500** | General | 2112 | 15 |
| **501** | Beginning Phase | 2145 | 1 |
| **502** | Untap Step | 2149 | 5 |
| **503** | Upkeep Step | 2161 | 3 |
| **504** | Draw Step | 2169 | 2 |
| **505** | Main Phase | 2175 | 10 |
| **506** | Combat Phase | 2197 | 28 |
| **507** | Beginning of Combat Step | 2255 | 2 |
| **508** | Declare Attackers Step | 2261 | 38 |
| **509** | Declare Blockers Step | 2342 | 23 |
| **510** | Combat Damage Step | 2393 | 10 |
| **511** | End of Combat Step | 2416 | 3 |
| **512** | Ending Phase | 2424 | 1 |
| **513** | End Step | 2428 | 3 |
| **514** | Cleanup Step | 2436 | 4 |

## 6. Spells, Abilities, and Effects  ·  _line 2447_

| Rule | Title | Line | Subrules |
| --- | --- | --- | --- |
| **600** | General | 2449 | 0 |
| **601** | Casting Spells | 2451 | 27 |
| **602** | Activating Activated Abilities | 2514 | 19 |
| **603** | Handling Triggered Abilities | 2555 | 47 |
| **604** | Handling Static Abilities | 2663 | 8 |
| **605** | Mana Abilities | 2681 | 13 |
| **606** | Loyalty Abilities | 2711 | 6 |
| **607** | Linked Abilities | 2726 | 25 |
| **608** | Resolving Spells and Abilities | 2783 | 24 |
| **609** | Effects | 2842 | 12 |
| **610** | One-Shot Effects | 2871 | 13 |
| **611** | Continuous Effects | 2900 | 13 |
| **612** | Text-Changing Effects | 2934 | 11 |
| **613** | Interaction of Continuous Effects | 2958 | 41 |
| **614** | Replacement Effects | 3054 | 37 |
| **615** | Prevention Effects | 3138 | 15 |
| **616** | Interaction of Replacement and/or Prevention Effects | 3173 | 9 |

## 7. Additional Rules  ·  _line 3198_

| Rule | Title | Line | Subrules |
| --- | --- | --- | --- |
| **700** | General | 3200 | 35 |
| **701** | Keyword Actions | 3277 | 294 |
| **702** | Keyword Abilities | 3879 | 771 |
| **703** | Turn-Based Actions | 5449 | 20 |
| **704** | State-Based Actions | 5491 | 39 |
| **705** | Flipping a Coin | 5576 | 3 |
| **706** | Rolling a Die | 5584 | 18 |
| **707** | Copying Objects | 5622 | 33 |
| **708** | Face-Down Spells and Permanents | 5713 | 14 |
| **709** | Split Cards | 5743 | 22 |
| **710** | Flip Cards | 5791 | 8 |
| **711** | Leveler Cards | 5810 | 9 |
| **712** | Double-Faced Cards | 5830 | 58 |
| **713** | Substitute Cards | 5958 | 8 |
| **714** | Saga Cards | 5976 | 13 |
| **715** | Adventurer Cards | 6004 | 12 |
| **716** | Class Cards | 6030 | 8 |
| **717** | Attraction Cards | 6048 | 9 |
| **718** | Prototype Cards | 6068 | 10 |
| **719** | Case Cards | 6090 | 6 |
| **720** | Omen Cards | 6104 | 12 |
| **721** | Station Cards | 6130 | 7 |
| **722** | Preparation Cards | 6146 | 12 |
| **723** | Controlling Another Player | 6173 | 13 |
| **724** | Ending Turns and Phases | 6206 | 15 |
| **725** | The Monarch | 6238 | 5 |
| **726** | The Initiative | 6250 | 5 |
| **727** | Restarting the Game | 6262 | 9 |
| **728** | Rad Counters | 6283 | 2 |
| **729** | Subgames | 6289 | 16 |
| **730** | Merging with Permanents | 6324 | 18 |
| **731** | Day and Night | 6362 | 6 |
| **732** | Taking Shortcuts | 6376 | 12 |
| **733** | Handling Illegal Actions | 6406 | 2 |

## 8. Multiplayer Rules  ·  _line 6412_

| Rule | Title | Line | Subrules |
| --- | --- | --- | --- |
| **800** | General | 6414 | 21 |
| **801** | Limited Range of Influence Option | 6463 | 28 |
| **802** | Attack Multiple Players Option | 6536 | 10 |
| **803** | Attack Left and Attack Right Options | 6559 | 3 |
| **804** | Deploy Creatures Option | 6567 | 2 |
| **805** | Shared Team Turns Option | 6573 | 25 |
| **806** | Free-for-All Variant | 6625 | 6 |
| **807** | Grand Melee Variant | 6639 | 20 |
| **808** | Team vs. Team Variant | 6683 | 7 |
| **809** | Emperor Variant | 6699 | 14 |
| **810** | Two-Headed Giant Variant | 6731 | 27 |
| **811** | Alternating Teams Variant | 6796 | 8 |

## 9. Casual Variants  ·  _line 6816_

| Rule | Title | Line | Subrules |
| --- | --- | --- | --- |
| **900** | General | 6818 | 2 |
| **901** | Planechase | 6824 | 35 |
| **902** | Vanguard | 6896 | 9 |
| **903** | Commander | 6919 | 49 |
| **904** | Archenemy | 7024 | 22 |
| **905** | Conspiracy Draft | 7070 | 14 |
