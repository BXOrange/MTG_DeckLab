# AGENTS.md — gemeinsame LLM-Einstiegsebene

Diese Datei ist der gemeinsame Startpunkt für Codex, Claude und andere
Coding-Agenten. Sie verteilt nur zu den passenden Wissensquellen; sie
dupliziert deren Inhalt bewusst nicht.

## Einstieg und Routing

1. Lies zuerst diese Datei.
2. Für Projektkontext, Architektur, Konventionen, Arbeitsabläufe und die
   fachliche Orientierung lies [`CLAUDE.md`](CLAUDE.md). Sie ist das
   kanonische Projekt-Wiki.
3. Wenn eine Aufgabe eine Magic-Comprehensive-Rule, einen `RULE <n>`-Kommentar
   oder einen Glossarbegriff betrifft, wechsle zusätzlich zum
   [Rules-Wiki](docs/Reference/rules_wiki/README.md). Es ist die
   token-sparende Navigationsschicht zur vollständigen Regelquelle und damit
   das Codex-LLM-Wiki für Regelrecherche.
4. Für eine konkrete Arbeitsfrage folge den Verweisen in `CLAUDE.md`, bevor du
   breit im Repository suchst. Bereichsdokumentation unter `docs/` oder
   verzeichnisnahe `AGENTS.md`-Dateien, falls vorhanden, präzisieren diese
   Einstiegsebene.

## Wann welche Quelle maßgeblich ist

| Anliegen | Maßgebliche Quelle |
| --- | --- |
| Projektüberblick, Architektur, Tests, Konventionen, offene Arbeit | [`CLAUDE.md`](CLAUDE.md) |
| Wortlaut oder Auslegung einer Comprehensive Rule | [Rules-Wiki](docs/Reference/rules_wiki/README.md) → `MagicCompRules <date>.txt` |
| Anforderung, Design, Referenz oder Implementierungsstand | [`docs/README.md`](docs/README.md) und das dort geroutete Dokument |
| Bedienung der Anwendung | [`user-docs/`](user-docs/) |
| Nächsten Backlog-Auftrag planen, wenn `workingOn.md` leer ist | [Backlog-Loop-Planer](.github/agents/backlog-loop-planner.agent.md) |
| Paketierte Workflows (Claude-Code-Skills unter `.claude/skills/`, nur für den Claude-Code-Agenten aufrufbar) | [`CLAUDE.md`](CLAUDE.md) |

Bei Widersprüchen gilt: konkrete, näher am Code oder Thema liegende
Dokumentation vor dieser Datei; der offizielle Comprehensive-Rules-Text vor
seinen Indizes; der aktuelle Code und seine Tests vor veralteter Beschreibung.

## Wechsel zwischen Claude-Wiki und Codex-Regel-Wiki

- Beginne bei `CLAUDE.md`, um zu verstehen, **wo** im Projekt gearbeitet wird
  und welche Schutzregeln gelten.
- Wechsle zum Rules-Wiki nur für die benötigte Regel oder Definition: Nummer
  beziehungsweise Begriff nachschlagen, die angegebene Stelle im
  `MagicCompRules`-Text lesen und danach zum betroffenen Code zurückkehren.
- Kehre zu `CLAUDE.md` zurück, sobald es wieder um Projektentscheidungen,
  Implementierungsmuster, Tests oder Dokumentationspflege geht.
- Lade den fast 1-MB-großen Regeltext nie vollständig ohne Anlass; das
  Rules-Wiki liefert die passende Zeile. Nach einem Regelupdate das Wiki mit
  `python3 docs/Reference/rules_wiki/build_wiki.py` neu erzeugen.

## Pflege

- Änderungen an Architektur, Konventionen, Tests oder Engine-Abdeckung gehören
  in `CLAUDE.md` und gegebenenfalls in die verlinkte Bereichsdokumentation.
- Änderungen an der Navigation oder an der Aufteilung dieser Wissensquellen
  gehören hierher.
- Änderungen an Regelindizes oder der Zuordnung Engine → Rules gehören in
  `docs/Reference/rules_wiki/` beziehungsweise dessen `build_wiki.py`.
- **Temporäre Dateien und Worklogs:** Arbeitsnotizen, Zwischenstände,
  Recherche-Schnipsel, Checklisten und andere sitzungsbezogene Inhalte gehören
  in klar temporäre, nicht versionierte Dateien. Sie dürfen nicht in
  Planungs- oder Statusdokumente gelangen (insbesondere nicht in
  `docs/implementation-state/`, `BACKLOG.md`, Roadmaps oder `Done_*.md`).
  Nur dauerhaft relevante, nach Abschluss geprüfte Entscheidungen,
  Anforderungen oder gelieferte Ergebnisse werden prägnant in die passende
  Projektdokumentation übernommen.
