# Comprehensive Rules — Master Index

> Auto-generated from `MagicCompRules 20261106.txt` — do not edit by hand.
> Regenerate with `python3 docs/Reference/rules_wiki/build_wiki.py`.

Line numbers point into the source rules file and equal the `Read` tool's
`offset`. Sections are short (~10–60 lines); read a whole section by its line.
For a specific subrule, use `rule_line_index.json`.

**Source:** [`MagicCompRules 20261106.txt`](../MagicCompRules%2020261106.txt) · **Glossary starts at line 7147** (see [glossary_index.md](glossary_index.md))

| How to jump | Example |
| --- | --- |
| Whole section | look up `613` below → `Read(source, offset=<line>, limit=60)` |
| One subrule | `rule_line_index.json` → `subrules["613.7"]` → `Read(...)` |
| A defined term | [glossary_index.md](glossary_index.md) → term → line |

## 1. Game Concepts  ·  _line 183_

| Rule | Title | Line | Subrules |
| --- | --- | --- | --- |
| **100** | General | 185 | 19 |
| **101** | The Magic Golden Rules | 225 | 10 |
| **102** | Players | 249 | 4 |
| **103** | Starting the Game | 259 | 32 |
| **104** | Ending the Game | 325 | 30 |
| **105** | Colors | 387 | 8 |
| **106** | Mana | 405 | 20 |
| **107** | Numbers and Symbols | 450 | 49 |
| **108** | Cards | 555 | 11 |
| **109** | Objects | 579 | 16 |
| **110** | Permanents | 613 | 14 |
| **111** | Tokens | 644 | 35 |
| **112** | Spells | 722 | 7 |
| **113** | Abilities | 739 | 41 |
| **114** | Emblems | 827 | 5 |
| **115** | Targets | 839 | 26 |
| **116** | Special Actions | 895 | 15 |
| **117** | Timing and Priority | 927 | 20 |
| **118** | Costs | 969 | 39 |
| **119** | Life | 1052 | 17 |
| **120** | Damage | 1088 | 25 |
| **121** | Drawing a Card | 1143 | 17 |
| **122** | Counters | 1179 | 20 |
| **123** | Stickers | 1221 | 26 |

## 2. Parts of a Card  ·  _line 1279_

| Rule | Title | Line | Subrules |
| --- | --- | --- | --- |
| **200** | General | 1281 | 3 |
| **201** | Name | 1289 | 22 |
| **202** | Mana Cost and Color | 1341 | 19 |
| **203** | Illustration | 1389 | 1 |
| **204** | Color Indicator | 1393 | 2 |
| **205** | Type Line | 1399 | 33 |
| **206** | Expansion Symbol | 1474 | 8 |
| **207** | Text Box | 1492 | 9 |
| **208** | Power/Toughness | 1512 | 10 |
| **209** | Loyalty | 1536 | 2 |
| **210** | Defense | 1542 | 1 |
| **211** | Hand Modifier | 1546 | 1 |
| **212** | Life Modifier | 1550 | 1 |
| **213** | Information Below the Text Box | 1554 | 8 |

## 3. Card Types  ·  _line 1572_

| Rule | Title | Line | Subrules |
| --- | --- | --- | --- |
| **300** | General | 1574 | 4 |
| **301** | Artifacts | 1584 | 15 |
| **302** | Creatures | 1616 | 10 |
| **303** | Enchantments | 1639 | 20 |
| **304** | Instants | 1681 | 5 |
| **305** | Lands | 1693 | 11 |
| **306** | Planeswalkers | 1718 | 13 |
| **307** | Sorceries | 1746 | 6 |
| **308** | Kindreds | 1760 | 3 |
| **309** | Dungeons | 1768 | 16 |
| **310** | Battles | 1802 | 24 |
| **311** | Planes | 1852 | 7 |
| **312** | Phenomena | 1868 | 7 |
| **313** | Vanguards | 1884 | 7 |
| **314** | Schemes | 1900 | 7 |
| **315** | Conspiracies | 1916 | 9 |

## 4. Zones  ·  _line 1936_

| Rule | Title | Line | Subrules |
| --- | --- | --- | --- |
| **400** | General | 1938 | 29 |
| **401** | Library | 1999 | 7 |
| **402** | Hand | 2015 | 3 |
| **403** | Battlefield | 2023 | 5 |
| **404** | Graveyard | 2035 | 3 |
| **405** | Stack | 2043 | 14 |
| **406** | Exile | 2073 | 10 |
| **407** | Ante | 2095 | 4 |
| **408** | Command | 2105 | 3 |

## 5. Turn Structure  ·  _line 2114_

| Rule | Title | Line | Subrules |
| --- | --- | --- | --- |
| **500** | General | 2116 | 15 |
| **501** | Beginning Phase | 2149 | 1 |
| **502** | Untap Step | 2153 | 5 |
| **503** | Upkeep Step | 2165 | 3 |
| **504** | Draw Step | 2173 | 2 |
| **505** | Main Phase | 2179 | 10 |
| **506** | Combat Phase | 2201 | 29 |
| **507** | Beginning of Combat Step | 2261 | 2 |
| **508** | Declare Attackers Step | 2267 | 39 |
| **509** | Declare Blockers Step | 2350 | 23 |
| **510** | Combat Damage Step | 2402 | 10 |
| **511** | End of Combat Step | 2425 | 3 |
| **512** | Ending Phase | 2433 | 1 |
| **513** | End Step | 2437 | 3 |
| **514** | Cleanup Step | 2445 | 4 |

## 6. Spells, Abilities, and Effects  ·  _line 2456_

| Rule | Title | Line | Subrules |
| --- | --- | --- | --- |
| **600** | General | 2458 | 0 |
| **601** | Casting Spells | 2460 | 27 |
| **602** | Activating Activated Abilities | 2522 | 19 |
| **603** | Handling Triggered Abilities | 2563 | 47 |
| **604** | Handling Static Abilities | 2671 | 8 |
| **605** | Mana Abilities | 2689 | 13 |
| **606** | Loyalty Abilities | 2719 | 6 |
| **607** | Linked Abilities | 2734 | 25 |
| **608** | Resolving Spells and Abilities | 2791 | 24 |
| **609** | Effects | 2850 | 12 |
| **610** | One-Shot Effects | 2879 | 13 |
| **611** | Continuous Effects | 2908 | 13 |
| **612** | Text-Changing Effects | 2942 | 11 |
| **613** | Interaction of Continuous Effects | 2966 | 41 |
| **614** | Replacement Effects | 3062 | 36 |
| **615** | Prevention Effects | 3144 | 15 |
| **616** | Interaction of Replacement and/or Prevention Effects | 3179 | 9 |

## 7. Additional Rules  ·  _line 3204_

| Rule | Title | Line | Subrules |
| --- | --- | --- | --- |
| **700** | General | 3206 | 36 |
| **701** | Keyword Actions | 3285 | 305 |
| **702** | Keyword Abilities | 3912 | 774 |
| **703** | Turn-Based Actions | 5488 | 20 |
| **704** | State-Based Actions | 5530 | 39 |
| **705** | Flipping a Coin | 5615 | 3 |
| **706** | Rolling a Die | 5623 | 18 |
| **707** | Copying Objects | 5661 | 33 |
| **708** | Face-Down Spells and Permanents | 5752 | 14 |
| **709** | Split Cards | 5782 | 22 |
| **710** | Flip Cards | 5830 | 8 |
| **711** | Leveler Cards | 5849 | 9 |
| **712** | Double-Faced Cards | 5869 | 34 |
| **713** | Meld Cards | 5939 | 27 |
| **714** | Substitute Cards | 6002 | 8 |
| **715** | Saga Cards | 6020 | 13 |
| **716** | Adventurer Cards | 6048 | 12 |
| **717** | Class Cards | 6074 | 8 |
| **718** | Attraction Cards | 6092 | 9 |
| **719** | Prototype Cards | 6112 | 10 |
| **720** | Case Cards | 6134 | 6 |
| **721** | Omen Cards | 6148 | 12 |
| **722** | Station Cards | 6174 | 7 |
| **723** | Preparation Cards | 6190 | 12 |
| **724** | Controlling Another Player | 6217 | 13 |
| **725** | Ending Turns and Phases | 6250 | 15 |
| **726** | The Monarch | 6282 | 5 |
| **727** | The Initiative | 6294 | 5 |
| **728** | Restarting the Game | 6306 | 9 |
| **729** | Rad Counters | 6327 | 2 |
| **730** | Subgames | 6333 | 16 |
| **731** | Merging with Permanents | 6368 | 18 |
| **732** | Day and Night | 6406 | 6 |
| **733** | Taking Shortcuts | 6420 | 12 |
| **734** | Handling Illegal Actions | 6450 | 2 |

## 8. Multiplayer Rules  ·  _line 6456_

| Rule | Title | Line | Subrules |
| --- | --- | --- | --- |
| **800** | General | 6458 | 21 |
| **801** | Limited Range of Influence Option | 6507 | 28 |
| **802** | Attack Multiple Players Option | 6580 | 10 |
| **803** | Attack Left and Attack Right Options | 6603 | 3 |
| **804** | Deploy Creatures Option | 6611 | 2 |
| **805** | Shared Team Turns Option | 6617 | 25 |
| **806** | Free-for-All Variant | 6669 | 6 |
| **807** | Grand Melee Variant | 6683 | 20 |
| **808** | Team vs. Team Variant | 6727 | 7 |
| **809** | Emperor Variant | 6743 | 14 |
| **810** | Two-Headed Giant Variant | 6775 | 27 |
| **811** | Alternating Teams Variant | 6840 | 8 |

## 9. Casual Variants  ·  _line 6860_

| Rule | Title | Line | Subrules |
| --- | --- | --- | --- |
| **900** | General | 6862 | 2 |
| **901** | Planechase | 6868 | 35 |
| **902** | Vanguard | 6940 | 9 |
| **903** | Commander | 6963 | 50 |
| **904** | Archenemy | 7071 | 22 |
| **905** | Conspiracy Draft | 7117 | 14 |
