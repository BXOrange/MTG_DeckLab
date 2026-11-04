# Server-Anleitung (Betrieb mit Konten)

Für alle, die DeckLab auf einem Rechner für andere bereitstellen (LAN oder Internet).
Technische Details zu Start, Netzwerk und Konfiguration: [OPERATIONS.md](OPERATIONS.md).
Entwurf und Entscheidungen: [Konten-Plan](../concepts/15_ACCOUNT_SYSTEM_PLAN.md).

> **Stand (PLR-9a/9b/9c, nur auf dem Integrationszweig `feature/PLR-9`).** Gebaut und getestet:
> Betriebsarten, Netz-Allowlist, Konten, Anmeldung per Einladung, Sitzungen, Passwort-Regeln,
> Profil-Oberfläche, Deck- und Sitzungs-Besitz (Abschnitt 4a) sowie Multiplayer-Identität und
> Einzel-Sitzungs-Sperre (Abschnitt 4b). **Noch nicht** gebaut:
> die `/admin`-Seite (PLR-9d), Verschlüsselung und Backups (PLR-9e).
> Auf diesem Zweig verlangen alle Deck-, Goldfisch-, Solo-, Replay- und Analyse-Routen eine
> Anmeldung (ohne Sitzung: 401); für die Entwicklung ohne Login `--localdev` starten. Auf `main`
> und echten Installationen ändert sich nichts vor dem Cutover (9e).

## 1. Installation

```bash
python3 setup/install.py          # Windows: python setup\install.py
```

Das legt `backend/venv` an und installiert `backend/requirements.txt`, darunter `psutil` (liest die
Netze des Servers für die LAN-Allowlist). Nach einem Update mit neuer Abhängigkeit einmal
`install.py` mit Internet ausführen. Offline-Installation: auf einem Rechner mit Internet
`python3 setup/install.py --download-wheels`, den Ordner `setup/wheels/` auf den Server kopieren
(gleiches Betriebssystem und gleiche Python-Version). Danach startet die App ohne Netzwerk.

## 2. Betriebsarten

| Start | Wer kommt rein | Transport | Konten |
| --- | --- | --- | --- |
| `./start.sh` (ohne Modus) | nur dieser Rechner | HTTP | keine (altes Verhalten bis zum Cutover) |
| `./start.sh --localdev` | nur dieser Rechner | HTTP | Standardnutzer `local` ist automatisch angemeldet; Abmelden und echter Login sind möglich |
| `./start.sh --lan` | erlaubte Netze | HTTP | Anmeldung per Einladung |
| `./start.sh --online …` | jede Adresse | nur HTTPS | Anmeldung per Einladung |

Windows: `start.bat` mit denselben Optionen. Die App ist danach auf Port 8000 erreichbar
(`--backend-port` ändert ihn). Der Frontend-Port bleibt intern.

### LAN

```bash
./start.sh --lan --allow-network 192.168.179.0/24
```

- Es binden alle Interfaces; **nur** Clients aus den erlaubten Netzen werden bedient (HTTP und
  WebSocket), alle anderen bekommen 403.
- `--allow-network` (mehrfach möglich) oder `MTG_ALLOWED_NETWORKS="192.168.179.0/24,10.8.0.0/16"`
  ist die **vollständige** Liste (Loopback kommt immer dazu). Ohne Angabe gelten die Subnetze der
  Netzwerkkarten dieses Rechners (VPN-Interfaces eingeschlossen). Lässt sich das nicht lesen
  (`psutil` fehlt), bleibt nur Loopback erlaubt und der Start meldet es im Log.
- Eine ungültige CIDR beendet den Start mit Fehler. IPv6 und IPv4-in-IPv6-Adressen werden
  erkannt. `X-Forwarded-For` wird nie ausgewertet.
- Auf den anderen Geräten `http://<IP des Servers>:8000` öffnen. IP herausfinden: macOS
  `ipconfig getifaddr en0`, Linux `hostname -I`, Windows `ipconfig`.
- Firewall: Port 8000 (TCP) für das lokale Netz freigeben, nicht im Router weiterleiten.
- Die Allowlist ist eine Komfortgrenze, **keine Anmeldung**: Wer im erlaubten Netz sitzt
  (öffentliches WLAN, fremde Geräte in deinem VPN), erreicht die Seite. HTTP-Cookies und Passwörter
  kann dort jemand mitlesen. Für alles außerhalb eines vertrauten Netzes `--online` nutzen.

### Online (Internet)

Nur mit HTTPS. Entweder die App terminiert TLS selbst:

```bash
./start.sh --online --tls-cert fullchain.pem --tls-key privkey.pem
```

oder ein Reverse-Proxy davor (z. B. nginx, Caddy) übernimmt TLS:

```bash
MTG_ALLOWED_HOSTS=decklab.example.org ./start.sh --online --behind-tls-proxy
```

- Der Hostname, unter dem Nutzer die Seite aufrufen, muss in `MTG_ALLOWED_HOSTS` stehen, sonst
  antwortet die App mit 400 (Schutz gegen DNS-Rebinding).
- Der Proxy muss WebSockets (`/ws/…`) durchreichen und `Host` unverändert weitergeben.
- Es gibt keine IP-Allowlist; der Schutz sind Konten, Einladungen und HTTPS. Das Sitzungs-Cookie
  heißt dann `__Host-mtg_session` und ist `Secure`.
- Fernzugriff auf die Admin-Seite wird erst mit MFA freigegeben (PLR-9d); bis dahin ist sie
  nur lokal geplant.

## 3. Konten und Einladungen

Registrierung gibt es **nur per Einladungs-Token**. Das Token ist 256 Bit lang, gilt einmal,
läuft nach 7 Tagen ab (`MTG_INVITE_TTL_SECONDS`) und wird nur einmal angezeigt.

**Erste Einladung auf einem frischen Server** (noch niemand kann sich anmelden):

```bash
cd backend
venv/bin/python scripts/manage_accounts.py invite      # Windows: venv_win\Scripts\python.exe
venv/bin/python scripts/manage_accounts.py list        # Übersicht, ohne Token
```

Das Token dem neuen Spieler auf einem sicheren Weg schicken. Er öffnet **Profil → Konto →
Konto anlegen**, trägt Kontonamen, Token und Passwort ein. Ein Link mit `#invite=<Token>` füllt das
Feld vor (das Fragment geht nie an den Server).

**Weitere Einladungen** erzeugen angemeldete Spieler selbst unter Profil → Konto → Einladungen
(Standard: höchstens 5 offen und 10 pro Tag, `MTG_INVITE_MAX_OUTSTANDING`, `MTG_INVITE_MAX_PER_DAY`).
Sie können offene Einladungen widerrufen. Wird ein Konto gesperrt, werden seine offenen Einladungen
ungültig.

- **Name:** 3–32 Zeichen, eindeutig ohne Groß-/Kleinschreibung; er ist zugleich der Spielername.
  Reservierte Namen (`local`, `admin`, …) sind gesperrt.
- **Passwort:** mindestens 10 Zeichen (`MTG_PASSWORD_MIN_LENGTH`), Unicode und Leerzeichen sind
  erlaubt; verbreitete Passwörter, Wiederholungen und Zahlen-/Buchstabenreihen sowie der eigene Kontoname werden abgelehnt. Die Liste lässt sich vergrößern: `venv/bin/python scripts/update_password_blocklist.py <Liste.txt>` (z. B. eine SecLists-Datei, MIT-Lizenz). Die Anzeige beim Eingeben zeigt **Rot**
  (zu kurz, wird blockiert), **Gelb** (gültig, aber eine Zahl, ein Sonderzeichen oder mehr
  Länge fehlen) und **Grün**.
- **Sitzungen:** Unter Profil → Konto → Aktive Sitzungen siehst du alle eigenen Sitzungen und kannst sie beenden. Die Sitzung ist ein Cookie; serverseitig gelten 8 Stunden Leerlauf und 14 Tage absolut
  (`MTG_SESSION_IDLE_SECONDS`, `MTG_SESSION_ABSOLUTE_SECONDS`). Passwort ändern beendet alle anderen
  Sitzungen; „Überall abmelden“ beendet alle.
- **Fehlversuche:** 10 pro 15 Minuten je Quelle und je Kontoname, danach 429 bis das Fenster
  weitergelaufen ist (`MTG_LOGIN_FAILURE_LIMIT`, `MTG_LOGIN_FAILURE_WINDOW_SECONDS`). Es gibt keine
  dauerhafte Sperre. Die Fehlermeldung verrät nicht, ob ein Konto existiert.
- **CSRF:** Jede Anfrage, die etwas ändert und ein gültiges Sitzungs-Cookie mitschickt, braucht den Header `X-CSRF-Token` (die Oberfläche setzt ihn selbst). Skripte ohne Cookie brauchen ihn nicht.
- **Passwort vergessen:** Ein Reset durch Admins ist bewusst nicht vorgesehen; Wiederherstellung wird
  ein Operator-Befehl (PLR-9d).

## 4. Daten, Sicherung, Dateien

Alles Dauerhafte liegt unter `MTG_DATA_DIR` (Standard `backend/data/`): `accounts.db`
(Konten, Passwort-Hashes, Sitzungs- und Token-Digests), `decks.db`, `player_assets.db`.
**Nicht löschen, nicht per Webserver ausliefern, nicht ins Git.** Ein einfaches Backup ist eine
Kopie dieses Ordners bei gestopptem Server (`c` + Enter im Server-Fenster). `accounts.db` enthält
Hashes, keine Klartext-Passwörter; sie ist **nicht verschlüsselt** — Dateirechte auf den Dienst-Benutzer
beschränken und den Datenträger verschlüsseln (Verschlüsselung und Backups: PLR-9e).
Der Karten-Cache (`MTG_CACHE_DIR`) ist verzichtbar.

## 4b. Multiplayer-Identität und Einzel-Sitzung (PLR-9c)

- **Wer man am Tisch ist.** Der Lobby-Spieler gehört dem angemeldeten Konto; der Kontoname ist der
  Anzeigename. Name, Client-Token und Sitz-Geheimnis gibt es nicht mehr: Wiederverbinden und jede
  Multiplayer-Anfrage (REST und WebSocket) prüfen nur das Konto der Sitzung. Fremde Spieler-IDs
  werden mit 403 abgelehnt, nie stillschweigend umgebucht. Bots und MCP-Sitze behalten ihre eigenen
  Zugänge (Bot ohne Client, MCP-Sitz-Token).
- **Der WebSocket `/ws/lobby`** prüft beim Verbindungsaufbau das Sitzungs-Cookie und den Origin
  (Schutz gegen fremde Webseiten); erst danach kommt ein erster `auth`-Frame (Tab-ID, optional der
  CSRF-Nachweis der Sitzung) innerhalb weniger Sekunden, vorher wird nichts gesendet. Unangemeldete
  Verbindungen sind zeitlich und zahlenmäßig begrenzt (global 16 gleichzeitig), Nachrichten haben
  Größen- und Raten-Limits (zu viele Nachrichten: Trennung mit `rate_limited`), Kompression ist
  abgeschaltet (`--ws-per-message-deflate false`, Rahmengröße 64 KiB). Jede Nachricht prüft, ob die
  Sitzung noch gilt; der Wächter prüft es zusätzlich jede Sekunde.
- **Eine Verbindung pro Konto.** Ein zweiter Tab oder ein zweites Gerät mit demselben Konto wird mit
  „Blockiert aufgrund paralleler Session" abgewiesen (Schließcode 1008, Grund `parallel_session`),
  ohne automatischen Wiederholversuch; der erste Tab bleibt unberührt. Der Server vergibt die
  Tab-ID (Browser-`sessionStorage`); nur der Tab mit der vom Server vergebenen ID und derselben
  Sitzung ersetzt seine eigene tote Verbindung. Ein kopierter Tab (Tab duplizieren) oder eine
  geratene ID verdrängt nie einen lebenden Tab. Eine Verbindung ohne Lebenszeichen für 90 s
  (`SOCKET_STALE_SECONDS`) gilt als tot und sperrt das Konto nicht aus. **Bekannte Folge:** nach
  einem Browser-Neustart ist `sessionStorage` leer, die eigene alte Verbindung blockiert dann bis zu
  90 s – kein Fehler.
- **Abmelden, Ablauf, Sperre, Löschung** schließen die Verbindungen des Kontos (spätestens nach
  einer Sekunde); der Sitz bleibt wie bei jedem Verbindungsabbruch für die Karenzzeit
  (`MTG_MULTIPLAYER_DISCONNECT_GRACE`, 90 s) reserviert, eine erneute Anmeldung darin setzt den Platz
  fort. Seite neu laden: Konto laden, mit dem eigenen Platz verbinden, frische Ansicht. Ein
  Neustart des Servers beendet alle Spiele im Speicher.
- **Rollout.** Beim Cutover den Server einmal neu starten: dadurch verfallen alle alten
  Sitz-Geheimnisse und Client-Token. Das alte Cookie `mtg_client_token` im Browser ist wirkungslos.

## 4a. Deck- und Sitzungs-Besitz, Migration (PLR-9b)

- **Sichtbarkeit.** Jedes Deck hat einen Geltungsbereich: `global` (für alle Spieler lesbar, nur
  durch den Betreiber/Admin änderbar) oder `private` (gehört genau einem Konto). Ein Spieler sieht
  globale und eigene private Decks; neue Decks sind immer privat und gehören dem angemeldeten Konto.
  Ein fremdes privates Deck und eine unbekannte ID liefern dieselbe 404-Antwort. Ein globales Deck
  wird über `POST /api/decks/{id}/copy` in ein neues privates Deck kopiert; die Quelle bleibt
  unverändert. Die Oberfläche zeigt den Geltungsbereich und bietet dafür „Kopieren & editieren".
- **Spiele.** Goldfisch-, Solo- und Replay-Sitzungen gehören dem Konto, das sie gestartet hat
  (Ansicht, Aktion, Rücknahme, Export, Löschen); eine fremde Sitzungs-ID verhält sich wie eine
  unbekannte. Beim Multiplayer-Deckwechsel wird das gewählte Deck als Server-Kopie am Sitz
  gespeichert; der Start liest nie aus dem Deck-Speicher, Mitspieler und der MCP-Sitz erhalten
  keinen Zugriff auf fremde private Decks.
- **Migration der alten Decks (Betreiber, einmalig beim Cutover, Server gestoppt):**
  `python backend/scripts/migrate_legacy_decks.py preview` (nur lesen), dann `apply`. Der Befehl
  legt unter `MTG_DATA_DIR/migration/backup-<Zeitstempel>/` ein eigenes, geprüftes Backup von
  `decks.db` und `player_assets.db` an (bricht ab, wenn es sich nicht prüfen lässt), migriert zuerst
  eine Kopie, prüft sie und wendet die Änderung dann je Speicher in einer Transaktion an. Alle
  bisherigen Decks werden `global` (IDs, Metadaten und Caches bleiben). Zeilen, die sich nicht
  eindeutig zuordnen lassen, bleiben unsichtbar (`unassigned`) und stehen im Bericht. Ein
  Journal (`migration/journal.json`) macht Abbrüche fortsetzbar, ein zweiter Lauf ändert nichts.
  Zurück: `restore --backup <Ordner> --yes`. Ohne diese Migration sind alte Decks nach dem
  Update unsichtbar (sie liegen als `unassigned` in der Datenbank, nichts geht verloren).

## 4b. Uploads und Favoriten gehören zum Konto (PLR-16)

- **Besitz.** Sleeves, Token-Bilder und Lieblingsdecks gehören dem angemeldeten Konto
  (`player_uuid`), nie einem Namen. Routen: `/api/me/sleeves`, `/api/me/token-images`,
  `/api/me/favorite-decks`; der Besitzer kommt immer aus der Sitzung, kein Name in der URL kann ein
  fremdes Konto auswählen. Ohne Anmeldung 401, fremde und unbekannte IDs liefern dieselbe 404.
  Andere Spieler (auch am selben Tisch) können fremde Uploads weder lesen noch ändern; das Brett
  lädt nur die eigenen Bilder. Eine Umbenennung ändert den Besitz nicht.
- **Alte Uploads (Betreiber, beim Cutover).** `apply` baut `player_assets.db` um (Zeilen bleiben
  unverändert, `owner_uuid` leer = unzugeordnet = unsichtbar). Standardmäßig wird **nichts**
  zugeordnet, weil alte Namen freier Text waren und ein Fremder mit gleichem Namen sonst fremde
  Uploads erben würde. Mit `apply --assign-assets-by-name` geht ein alter Name an das Spielerkonto
  mit genau diesem (normalisierten) Namen; `preview --assign-assets-by-name` zeigt vorher die
  Zuordnung. Nicht zugeordnete Namen stehen mit Zeilenzahl im Bericht; die Entscheidung gilt für den
  ganzen Lauf (Journal) und lässt sich bei einem Wiederanlauf nicht wechseln.
- **Konto löschen.** `AccountStore.delete_account` entfernt über `bind_account_cleanup` alle Assets
  des Kontos (Admin-Löschung nutzt denselben Pfad). Sperren (`set_disabled`) behält sie, weil es
  umkehrbar ist. `PlayerAssetStore.count_for_owner` liefert die Zahlen für die Lösch-Vorschau,
  `purge_orphans(live_uuids)` ist ein Betreiber-/Admin-Job für verwaiste Besitzer (kein Auto-Lauf:
  eine verlorene `accounts.db` würde sonst alles löschen).

## 5. Konfiguration (Auszug)

| Variable | Standard | Bedeutung |
| --- | --- | --- |
| `MTG_ALLOWED_NETWORKS` | leer | LAN: erlaubte CIDRs (ersetzt die Interface-Netze) |
| `MTG_ALLOWED_HOSTS` | leer | zusätzliche erlaubte `Host`-Namen (Online mit Domain) |
| `MTG_PASSWORD_MIN_LENGTH` | 10 | kürzestes Spielerpasswort |
| `MTG_PASSWORD_GREEN_LENGTH` | 12 | Länge für „Grün“ |
| `MTG_SESSION_IDLE_SECONDS` / `MTG_SESSION_ABSOLUTE_SECONDS` | 8 h / 14 d | Sitzungsdauer |
| `MTG_INVITE_TTL_SECONDS` | 7 d | Gültigkeit einer Einladung |
| `MTG_NAME_TOMBSTONE_DAYS` | 7 | Sperrfrist für gelöschte Kontonamen |
| `MTG_LOGIN_FAILURE_LIMIT` | 10 | Fehlversuche je Fenster |
| `MTG_DATA_DIR` | `backend/data` | Ort der Datenbanken |

Alle Werte lassen sich auch in `backend/mtg_analyzer/config.json` setzen
(Abschnitte `accounts`, `server`); die Umgebungsvariable gewinnt.

## 6. Fehlersuche

- **403 „network not allowed“ von einem LAN-Gerät:** dessen Adresse liegt nicht in der Allowlist.
  Beim Start steht `peer allowlist (lan mode): …` im Server-Log; passende
  `--allow-network` angeben.
- **400 „host not allowed“:** `Host` fehlt in `MTG_ALLOWED_HOSTS` (typisch hinter Proxy/Domain).
- **429 beim Anmelden:** zu viele Fehlversuche; `Retry-After` abwarten.
- **`--online` startet nicht:** TLS fehlt; `--tls-cert`/`--tls-key` oder `--behind-tls-proxy` angeben.
- **Backend startet nicht nach Update:** `python3 setup/install.py` mit Internet ausführen
  (neue Abhängigkeit `psutil`).
- **Anmeldung wirkt „verloren“ nach Neustart:** Sitzungen liegen in `accounts.db` und überleben
  einen Neustart; Spiele im Speicher nicht.
