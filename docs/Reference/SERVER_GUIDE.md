# Server-Anleitung (Betrieb mit Konten)

Für alle, die DeckLab auf einem Rechner für andere bereitstellen (LAN oder Internet).
Technische Details zu Start, Netzwerk und Konfiguration: [OPERATIONS.md](OPERATIONS.md).
Entwurf und Entscheidungen: [Konten-Plan](../concepts/15_ACCOUNT_SYSTEM_PLAN.md).

> **Stand: ausgeliefert (Cutover PLR-9e).** Betriebsarten, Netz-Allowlist, Konten mit Einladung,
> Sitzungen, Deck- und Upload-Besitz, Multiplayer-Identität, `/admin` mit MFA, Löschfrist,
> verschlüsselte `accounts.db` (SQLCipher), Backups, Sicherheits-Log und Aufbewahrungsfristen sind
> gebaut und getestet. `./start.sh` ohne Option startet jetzt den **LAN-Modus mit Konten**; der alte
> Zustand "ohne Login, nur dieser Rechner" existiert nicht mehr (für die Entwicklung: `--localdev`).
> Eine bestehende Installation wird mit dem Ablauf in Abschnitt 7 umgestellt.

## 1. Installation

```bash
python3 setup/install.py          # Windows: python setup\install.py
```

Das legt `backend/venv` an und installiert `backend/requirements.txt`, darunter `psutil` (liest die
Netze des Servers für die LAN-Allowlist) und `sqlcipher3-wheels` (verschlüsselt `accounts.db`; fertige
Wheels für macOS arm64/Intel, Linux x86_64/aarch64 und Windows, Python 3.9 bis 3.13; für Python 3.14
fehlt das Linux-x86_64-Wheel, dort ist Python 3.13 zu nehmen). Nach einem Update mit neuer Abhängigkeit einmal
`install.py` mit Internet ausführen. Offline-Installation: auf einem Rechner mit Internet
`python3 setup/install.py --download-wheels`, den Ordner `setup/wheels/` auf den Server kopieren
(gleiches Betriebssystem und gleiche Python-Version). Danach startet die App ohne Netzwerk.

## 2. Betriebsarten

| Start | Wer kommt rein | Transport | Konten |
| --- | --- | --- | --- |
| `./start.sh` (= `--lan`, Standard) | erlaubte Netze plus dieser Rechner | HTTP | Anmeldung per Einladung |
| `./start.sh --localdev` | nur dieser Rechner | HTTP | Standardnutzer `local` ist automatisch angemeldet; Abmelden und echter Login sind möglich |
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
- **Administration aus der Ferne** ist in `--online` möglich, aber **nur über HTTPS und nur mit
  Passwort + Authenticator-Code bei jeder Anfrage** (Abschnitt 3a). Ohne HTTPS antwortet `/admin`
  mit 403 `admin_https_required`. In `--lan` und `--localdev` bleibt `/admin` auf den Server-Rechner
  beschränkt. Hinter einem Proxy (`--behind-tls-proxy`) vertraut das Backend dem Header
  `X-Forwarded-Proto: https` (und nur dann): der Proxy muss der **einzige** Weg zum Backend sein
  (Firewall: Backend-Port nur für den Proxy offen) und den Header selbst setzen, nie durchreichen.
- **Erster Admin in `--online`:** dort wird kein Admin angelegt. Der Betreiber erzeugt ihn auf dem
  Server-Rechner mit `venv/bin/python scripts/manage_accounts.py create-admin NAME` (Abschnitt 3a).

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
- **Passwort vergessen:** Ein Reset durch Admins ist bewusst nicht vorgesehen (ein Admin würde sonst
  ein fremdes Konto übernehmen können). Der Server-Betreiber erzeugt auf dem Server-Rechner einen
  einmaligen, ablaufenden Wiederherstellungs-Zugang (`MTG_RECOVERY_TTL_SECONDS`, Standard 1 Stunde):

  ```bash
  venv/bin/python scripts/manage_accounts.py recover NAME
  ```

  Der Zugang wird einmal angezeigt (in der Datenbank steht nur sein Digest), macht frühere Zugänge
  desselben Kontos ungültig und darf **nur ein neues Passwort setzen**. Der Kontoinhaber löst ihn
  über `POST /api/auth/recover` (Spieler) bzw. auf der Admin-Seite („Passwort wiederherstellen“,
  mindestens 15 Zeichen) ein; das beendet alle Sitzungen und meldet **nicht** an. Außerhalb von
  Logs und Support-Chats weitergeben. Spieler lösen ihn in der App unter Profil → Konto →
  „Passwort vergessen“ ein.

## 3a. Administration (PLR-9d, PLR-17)

Eine schlichte Seite `http://127.0.0.1:8000/admin` (Port wie beim Start) und die API `/api/admin`.
**Nur auf dem Server-Rechner** (in `--online` zusätzlich aus der Ferne über HTTPS, siehe MFA unten):
Anfragen von anderen Adressen, mit `X-Forwarded-For`/`Forwarded` oder mit fremdem `Host` bekommen
sonst 403, auch über den eingebauten Frontend-Proxy.

- **Kein Admin-Cookie, keine Admin-Sitzung.** Jede Anfrage trägt Name und Passwort (`Authorization:
  Basic`, UTF-8); der Server prüft sie jedes Mal mit demselben Hash wie beim Spieler-Login.
  Die Seite hält das Passwort nur im Speicher, vergisst es beim Abmelden oder nach 5 Minuten
  Leerlauf und fragt es bei Löschungen erneut ab. Fehlversuche werden **je Admin-Name** gedrosselt
  (Quelle ist immer Loopback); Antworten sind generisch. Spieler-Cookies gelten auf `/api/admin` nie,
  Admin-Zugangsdaten melden nie in der Spieler-Oberfläche an. Die Seite hat eine eigene strenge CSP
  (kein Inline-Skript, keine externen Quellen) und zeigt alle Namen nur als Text.
- **Authenticator-App (MFA, TOTP).** Standard-TOTP nach RFC 6238 (6 Stellen, 30 s, SHA-1, funktioniert
  mit jeder Authenticator-App), nur mit der Standardbibliothek umgesetzt. **Pflicht in `--online`**,
  **optional** auf dem Server-Rechner in LAN/Localdev (wer eingerichtet hat, braucht den Code danach
  immer). Einrichten unter *Mein Konto → Authenticator-App einrichten*: Passwort ist nötig, die Seite
  zeigt den geheimen Schlüssel und die `otpauth://`-Adresse als **Text** (bewusst kein QR-Code, wegen
  der strengen CSP), und die Einrichtung gilt erst, wenn ein gültiger Code eingegeben wurde. Danach
  erscheinen **10 Recovery-Codes einmalig** (nur ihr SHA-256-Digest wird gespeichert, jeder gilt
  einmal). Ersetzen der App, neue Recovery-Codes und Ausschalten (nur außerhalb von `--online`)
  verlangen zusätzlich einen aktuellen Code oder einen Recovery-Code. Ein Code (und jeder Zeitschritt)
  wird je Admin **höchstens einmal** akzeptiert (Replay-Schutz); ±1 Zeitschritt Uhrabweichung ist
  erlaubt (`TOTP_SKEW_STEPS`); falsche Codes zählen gegen dieselbe Drosselung wie falsche Passwörter.
  Der Code reist pro Anfrage im Header `X-Admin-OTP` (App-Code oder Recovery-Code). Weil ein Code nur einen Zeitschritt
  gilt, tauscht die Seite **einen** verifizierten Code gegen eine **kurzlebige, serverseitig gehaltene
  Freigabe** (`X-Admin-Grant`; 5 Minuten Leerlauf, 30 Minuten absolut, höchstens 5 je Admin, nur im
  Speicher, gebunden an Admin, Client-Adresse und Passwort-/MFA-Stand). Das Passwort geht trotzdem
  bei jeder Anfrage mit, und es gibt weiterhin **kein Cookie**. Passwort ändern, App ersetzen oder
  Neustart beenden alle Freigaben. In `--online` kann ein Admin ohne Authenticator **nichts außer der
  Einrichtung** (403 `mfa_enrollment_required`); die Admin-Registrierung dort legt das Konto an,
  aktiv wird es erst nach der Einrichtung.
  **Erster Admin / verlorenes Gerät:** `manage_accounts.py create-admin NAME` legt ein Admin-Konto
  ohne Passwort an und gibt einmalig einen Wiederherstellungs-Zugang aus (wie `recover`); der neue Admin
  löst ihn auf `/admin` unter „Passwort wiederherstellen“ ein (mindestens 15 Zeichen), meldet sich an und
  richtet die App ein. `manage_accounts.py reset-mfa NAME` entfernt App und Recovery-Codes (verlorenes
  Gerät und Codes); in `--online` muss der Admin dann neu einrichten. Beides steht im Audit-Log als
  `operator`.
- **Ersteinrichtung.** Beim ersten Start mit leerer Admin-Tabelle (nicht in `--online`) wird einmalig das
  Konto `admin` mit dem **Anfangspasswort `admin`** angelegt. Es kann nur die Einrichtung öffnen:
  neues Passwort (mindestens **15 Zeichen**, nicht `admin`, nicht auf der Sperrliste), danach zeigt die Seite
  **eine Admin- und eine Spieler-Einladung** einmalig an. Bis dahin verweigert jede andere Admin-Funktion
  und jede Spieler-Funktion mit diesem Zugang; der Start meldet `ADMIN SETUP OPEN` im Log, die Seite
  zeigt ein Banner. Das Konto wird nie ein zweites Mal angelegt (auch nicht nach einem Löschen durch den
  Betreiber).
- **Was Admins können:** Spieler suchen/auflisten, sperren/entsperren, Sitzungen beenden, löschen;
  Einladungen (Spieler und Admin) erzeugen, auflisten (nur Metadaten) und widerrufen; globale Decks
  anlegen/bearbeiten/löschen; die erlaubten Datenbank-Updates starten und verfolgen; das Audit-Log
  lesen. **Nicht:** private Decks oder Uploads lesen, spielen, Bot-/MCP-Plätze steuern,
  Passwörter zurücksetzen, Rollen ändern, SQL, Shell, LLM-/Server-Einstellungen.
- **Neue Admins** entstehen nur über eine Admin-Einladung, die auf der Admin-Seite
  („Admin-Registrierung“) eingelöst wird (Passwort mindestens 15 Zeichen), oder per
  `manage_accounts.py invite --role admin`. Spieler-Einladungen ergeben nie einen Admin und umgekehrt.
- **Konto löschen (durch den Admin)** zeigt vorher nur Zahlen (Decks, Uploads, Sitzungen), verlangt den
  eingetippten Namen und das Admin-Passwort und entfernt Konto, private Decks, Uploads und Sitzungen sofort,
  schließt Sockets (spätestens beim nächsten Sweep, etwa 1 s) und gibt den Tisch-Platz sofort frei
  (im laufenden Spiel konzediert der Platz). Der Name ist `MTG_NAME_TOMBSTONE_DAYS` (7) Tage gesperrt,
  die UUID wird nie wiederverwendet. Admin-Konten und der Standardnutzer `local` sind nicht löschbar.
- **Konto löschen (durch den Spieler, mit Frist).** Unter Profil → Konto → „Konto löschen …“ beantragt ein
  Spieler die Löschung des eigenen Kontos (Passwort, eingetippter Kontoname und CSRF-Nachweis nötig,
  `POST /api/auth/delete-account`). Das Konto wird **sofort gesperrt** (Sitzungen beendet, Sockets
  geschlossen, Anmeldung mit der üblichen generischen Fehlermeldung abgelehnt) und mit
  `deletion_requested_at` markiert. Während der **Frist** `MTG_ACCOUNT_DELETION_GRACE_DAYS` (Standard 7)
  zeigt `/admin` die Anträge mit Fälligkeitsdatum; „Freigeben (Löschung abbrechen)“ (= Entsperren)
  nimmt die Löschung zurück. Danach löscht ein Sweep (beim Start und stündlich) das Konto mit
  denselben Schritten wie die Admin-Löschung (private Decks, Uploads, Spiel-Sitzungen, Sitzungen,
  Platz) und setzt die Namenssperre. Jeder Schritt steht im Audit-Log (`account.deletion_requested`,
  `player.deletion_cancelled`, `player.deleted` mit Akteur `system`). Ein Admin kann einen
  beantragten Löschfall auch sofort löschen.
  **Backup-Hinweis:** Wer ein Backup von `accounts.db`/`decks.db` zurückspielt, bringt Konten zurück, deren
  Löschung nach dem Backup abgeschlossen wurde. Diese Konten nach dem Restore anhand des Audit-Logs
  (`player.deleted`) von Hand erneut löschen.
- **Datenbank-Updates (PLR-17).** `POST /api/cards/update` und `POST /api/combos/update` verlangen
  Admin-Zugangsdaten (sonst 401; Spieler und Anonyme auch bei direktem Aufruf, von anderen Adressen
  403). Die Admin-Seite startet dieselben Updates als Job (`/api/admin/jobs`) und zeigt den
  Fortschritt; der Start liefert ein **Job-Token** nur zum Lesen dieses einen Jobs (nur sein Digest
  liegt im Speicher, gültig bis der Job eine Stunde nach seinem Ende verworfen wird), damit der
  Fortschritt ohne Passwort abgefragt werden kann. Pro Art läuft höchstens ein Job. Im
  Spieler-Bereich sind die Update-Knöpfe entfernt.
- **MCP-Server-Token (PLR-17).** Angemeldete Spieler dürfen Status und Einrichtungsbefehle (mit dem
  Token) unter Einstellungen ansehen (`GET /api/mcp-settings`, `POST /api/mcp-settings/setup`; Anonyme: 401).
  **Erzeugen/Erneuern** (`POST /api/mcp-settings/rotate`) kann nur ein Admin, nur auf `/admin` (Tab
  „MCP-Token“); es trennt bestehende MCP-Verbindungen und steht im Audit-Log (ohne das Token).
- **Audit-Log:** Akteur, Aktion, Ziel, Zeit, Ergebnis; nie Passwörter, Token oder private Inhalte.
  Nur für Admins lesbar (`/api/admin/audit`). Fehlversuche gegen ein echtes Admin-Konto werden
  protokolliert.

## 4. Daten, Sicherung, Dateien

Alles Dauerhafte liegt unter `MTG_DATA_DIR` (Standard `backend/data/`): `accounts.db`
(Konten, Passwort-Hashes, Sitzungs- und Token-Digests, Audit-Log, TOTP-Geheimnisse; **verschlüsselt**,
Abschnitt 4c), `decks.db`, `player_assets.db` (beide **unverschlüsselt**: dafür den Datenträger
verschlüsseln, FileVault/BitLocker/LUKS), `logs/` und `backups/`.
**Nicht löschen, nicht per Webserver ausliefern, nicht ins Git** (`.gitignore` deckt Datenordner,
Schlüsseldateien, Backups und Logs ab; die App liefert nichts aus diesem Ordner aus und Bug-Reports
enthalten ihn nicht). Das Backend setzt den Ordner auf Rechte 0700 und alle Datenbanken samt
WAL/Journal-Dateien, Logs, Backups und das MCP-Token auf 0600 (unter Windows gelten die ACLs des
Benutzerprofils). Ein einfaches Backup der unverschlüsselten Speicher ist eine Kopie des Ordners
bei gestopptem Server (`c` + Enter im Server-Fenster); für `accounts.db` den Befehl `backup` aus 4c
nehmen und den **Schlüssel getrennt** sichern. Der Karten-Cache (`MTG_CACHE_DIR`) ist verzichtbar.

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

- **Sichtbarkeit.** Jedes Deck hat einen Geltungsbereich: `global` (für alle lesbar, auch ohne Login, nur
  durch den Betreiber/Admin änderbar) oder `private` (gehört genau einem Konto). Ein Spieler sieht
  globale und eigene private Decks; neue Decks sind immer privat und gehören dem angemeldeten Konto.
  Ein fremdes privates Deck und eine unbekannte ID liefern dieselbe 404-Antwort. Ein globales Deck
  wird über `POST /api/decks/{id}/copy` in ein neues privates Deck kopiert; die Quelle bleibt
  unverändert. Die Oberfläche zeigt zwei Spalten, „Globale Decks" und „Meine Decks", und bietet bei globalen
  Decks „Kopieren & editieren".
- **Ohne Login (PLR-18).** Globale Decks sind ohne Konto sichtbar und nutzbar: Liste, Detail, Legalität und
  Abdeckung, Analyse, Goldfisch, Solo (Bot-Decks ebenfalls nur global) und Replay. Speichern, Kopieren, Favoriten,
  private Decks, Uploads und Multiplayer brauchen ein Konto (401); private oder unbekannte IDs liefern dieselbe
  404-Antwort. Ein anonymer Besucher erhält beim ersten Spielstart ein serverseitig erzeugtes Cookie
  (`mtg_anon`, in `--online` `__Host-mtg_anon` und Secure, immer HttpOnly und SameSite=Lax); die Sitzung gehört
  `anon:<Digest>` dieser ID, nie `None`. Konto und anonyme ID erreichen die Sitzungen des jeweils anderen nicht.
  Anonyme Sitzungen sind begrenzt (`MTG_ANON_SESSION_MAX_PER_OWNER` = 5 je ID, `MTG_ANON_SESSION_MAX_TOTAL` = 40
  insgesamt) und werden vor Konto-Sitzungen verdrängt. Ein Admin-Zugang gilt auf diesen Routen als anonym.
- **Spiele.** Goldfisch-, Solo- und Replay-Sitzungen gehören dem Konto (oder der anonymen ID), das sie gestartet hat
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

## 4c. Verschlüsselung, Schlüssel, Backups, Logs (PLR-9e)

**Was verschlüsselt ist.** Nur `accounts.db` (SQLCipher, AES-256; die WAL-Datei, Journals und
temporäre Daten sind mit verschlüsselt). Wer die Datei kopiert, bekommt ohne Schlüssel nur Zufallsbytes.
`decks.db` und `player_assets.db` sind gewöhnliches SQLite und gelten **nicht** als verschlüsselt;
sie brauchen einen verschlüsselten Datenträger. Verschlüsselung schützt gestohlene Kopien, nicht
einen laufenden Server: Der Server liest die Daten selbst, also bleiben Rechte, Isolation und Audit
wichtig.

**Der Schlüssel** sind 32 Zufallsbytes (64 Hex-Zeichen) und liegen **außerhalb** von Datenbank,
Datenordner und Backups:

1. Umgebungsvariable `MTG_ACCOUNTS_DB_KEY` (hat Vorrang; nie in `config.json`), sonst
2. die Schlüsseldatei `MTG_ACCOUNTS_DB_KEY_FILE` (Standard `~/.decklab/accounts.key`, Rechte 600;
   eine Datei, die andere lesen dürfen oder die im Datenordner liegt, wird abgelehnt).

Es gibt bewusst keinen Eintrag im Betriebssystem-Schlüsselbund: Er brauchte eine plattformspezifische
Abhängigkeit und fehlt auf einem Server ohne Desktop. **Fehlt der Schlüssel, ist er falsch oder ist
`accounts.db` noch unverschlüsselt, startet das Backend nicht** und nennt den Grund; es gibt keinen
Rückfall auf Klartext und es wird nie eine leere Datenbank über eine vorhandene gelegt. Nur auf einer
ganz neuen Installation (weder Schlüssel noch Datenbank) erzeugt der erste Start die Schlüsseldatei
selbst und warnt im Log. **Den Schlüssel getrennt vom Datenordner sichern (Passwortmanager, anderer
Datenträger); ohne ihn ist `accounts.db` unwiederbringlich.**

Befehle (`cd backend`, dann `venv/bin/python scripts/manage_accounts.py …`, Windows
`venv_win\Scripts\python.exe`; "offline" = Server gestoppt):

| Befehl | Zweck |
| --- | --- |
| `status` | zeigt, ob `accounts.db` verschlüsselt ist, woher der Schlüssel kommt und ob sie sich öffnen lässt |
| `init-key [--print]` | legt die Schlüsseldatei an (frische Installation); ersetzt nie einen vorhandenen Schlüssel |
| `encrypt-db --yes [--keep-plaintext-backup PFAD]` | **offline.** Wandelt eine alte Klartext-`accounts.db` um: exportiert in eine neue verschlüsselte Datei, prüft sie (öffnet mit Schlüssel, Integritätsprüfung, Zeilenzahlen, Schema-Version) und tauscht sie atomar ein. Das Klartext-Original wird gelöscht, außer der Betreiber nennt mit `--keep-plaintext-backup` einen Ort: dann bleibt es **unverschlüsselt** dort liegen (Warnung!). Reste können auf einem unverschlüsselten Datenträger in freien Blöcken überleben. |
| `rekey --yes` | **offline.** Schlüsselwechsel: neuer Schlüssel in `accounts.key.next`, Datenbank neu verschlüsseln und prüfen, alter Schlüssel bleibt als `accounts.key.previous-<Zeit>` (Backups davor brauchen ihn). Bei Schlüssel aus der Umgebungsvariable wird der neue einmal ausgegeben. |
| `backup [--to PFAD] [--keep N]` | verschlüsselte, konsistente Kopie (auch bei laufendem Server) nach `MTG_ACCOUNTS_BACKUP_DIR` (Standard `data/backups/accounts-<UTC-Zeit>.db`, überschreibt nie); es bleiben die neuesten `MTG_ACCOUNTS_BACKUP_KEEP` (14) |
| `restore BACKUP --yes` | **offline.** Prüft das Backup mit dem aktuellen Schlüssel und ersetzt `accounts.db`; die bisherige Datei bleibt als `accounts.db.pre-restore`. Danach gelöschte Konten von Hand erneut löschen (Abschnitt 3a, Backup-Hinweis). |

Regelmäßige Sicherung z. B. per Cron: `venv/bin/python scripts/manage_accounts.py backup` (täglich).
Ein Backup lässt sich nur mit dem Schlüssel öffnen, mit dem es erstellt wurde.

**Sicherheits-Log.** Eigene Datei `MTG_DATA_DIR/logs/security.log` (Rechte 600, Logger
`decklab.security`, getrennt vom Anwendungs-Log; `MTG_SECURITY_LOG_FILE` ändert oder, leer, schaltet die Datei
ab). Eine Zeile pro Ereignis (`event="auth.login" outcome="failure" source="…"`): Anmeldung,
Registrierung und Wiederherstellung (Erfolg, Misserfolg, Drosselung), Sitzungsbeginn und -ende,
Passwortwechsel, jede abgewiesene API-Anfrage (401/403/429), jede Anfrage an `/api/admin` mit der
UUID des Admins, und eine Kopie jedes Audit-Log-Eintrags. Nie enthalten: Passwörter, Cookies,
Sitzungs-, CSRF-, Einladungs- und Wiederherstellungs-Token, TOTP-Geheimnisse und -Codes,
Anfrage-Inhalte. Namen und Pfade sind von Spielern kontrolliert und werden von Steuerzeichen befreit
und auf 120 Zeichen gekürzt. Die Datei rotiert bei 5 MiB und behält 9 Dateien
(`MTG_SECURITY_LOG_MAX_BYTES`, `MTG_SECURITY_LOG_BACKUPS`); darüber hinaus löscht nichts. Prüfen:
regelmäßig auf viele `outcome="failure"`/`throttled` von einer Quelle und unerwartete `admin.request`
von fremden Konten schauen; die Logdatei wie die Datenbank behandeln (Rechte, nicht weitergeben).

**Aufbewahrung.** Ein Sweep (beim Start und stündlich) löscht in `accounts.db`: beendete Sitzungen
nach 7 Tagen (`MTG_SESSION_RETENTION_DAYS`), abgeschlossene Wiederherstellungs-Zugänge nach 7 Tagen
(`MTG_RECOVERY_RETENTION_DAYS`), abgelaufene/eingelöste/widerrufene Einladungen nach 30 Tagen
(`MTG_INVITATION_RETENTION_DAYS`), abgelaufene Namenssperren sofort und das Audit-Log nach 365 Tagen
(`MTG_AUDIT_RETENTION_DAYS`). Backups behält `backup --keep`; das Sicherheits-Log die Rotation.

**Browser.** Antworten mit Anmelde- oder privaten Daten (`/api/auth`, `/api/admin`, `/api/me`,
Decks, Spiele, Multiplayer, MCP, `/admin`) tragen `Cache-Control: no-store`, damit ein gemeinsam
genutzter Browser oder Proxy sie nicht dem nächsten Konto zeigt. Das Frontend hat keinen Service
Worker und nutzt keinen Cache-Speicher; Namen und Deck-Inhalte erscheinen nur als Text
(`escapeHtml`/`escapeAttr`).

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
| `MTG_ADMIN_PASSWORD_MIN_LENGTH` | 15 | kürzestes Admin-Passwort |
| `MTG_RECOVERY_TTL_SECONDS` | 3600 | Gültigkeit eines Wiederherstellungs-Zugangs |
| `MTG_ACCOUNT_DELETION_GRACE_DAYS` | 7 | Frist zwischen Löschantrag und endgültigem Löschen des Kontos |
| `MTG_BEHIND_TLS_PROXY` | aus | setzt `start.py --behind-tls-proxy`: `X-Forwarded-Proto` gilt als TLS-Nachweis für `/admin` aus der Ferne |
| `MTG_LOGIN_FAILURE_LIMIT` | 10 | Fehlversuche je Fenster |
| `MTG_DATA_DIR` | `backend/data` | Ort der Datenbanken |
| `MTG_ACCOUNTS_DB_KEY` / `MTG_ACCOUNTS_DB_KEY_FILE` | – / `~/.decklab/accounts.key` | Schlüssel von `accounts.db` (Abschnitt 4c) |
| `MTG_ACCOUNTS_BACKUP_DIR` / `MTG_ACCOUNTS_BACKUP_KEEP` | `data/backups` / 14 | Ziel und Anzahl der verschlüsselten Backups |
| `MTG_SECURITY_LOG_FILE` | `data/logs/security.log` | Sicherheits-Log (leer = nur Logger) |
| `MTG_SESSION_RETENTION_DAYS` / `MTG_RECOVERY_RETENTION_DAYS` / `MTG_INVITATION_RETENTION_DAYS` / `MTG_AUDIT_RETENTION_DAYS` | 7 / 7 / 30 / 365 | Aufbewahrung toter Zeilen in `accounts.db` |

Alle Werte lassen sich auch in `backend/mtg_analyzer/config.json` setzen
(Abschnitte `accounts`, `server`); die Umgebungsvariable gewinnt.

## 6. Fehlersuche

- **403 „network not allowed“ von einem LAN-Gerät:** dessen Adresse liegt nicht in der Allowlist.
  Beim Start steht `peer allowlist (lan mode): …` im Server-Log; passende
  `--allow-network` angeben.
- **400 „host not allowed“:** `Host` fehlt in `MTG_ALLOWED_HOSTS` (typisch hinter Proxy/Domain).
- **429 beim Anmelden:** zu viele Fehlversuche; `Retry-After` abwarten.
- **`/admin` zeigt 403:** die Seite ist nur vom Server-Rechner selbst (Loopback, ohne Proxy-Header) erreichbar.
- **Admin-Passwort vergessen:** `manage_accounts.py recover NAME` (Abschnitt 3); **Authenticator verloren:** `manage_accounts.py reset-mfa NAME` (Abschnitt 3a).
- **`/admin` aus der Ferne zeigt 403 `admin_https_required`:** nur HTTPS (und in `--online`); hinter einem Proxy muss `--behind-tls-proxy` gesetzt sein und der Proxy `X-Forwarded-Proto: https` senden.
- **`--online` startet nicht:** TLS fehlt; `--tls-cert`/`--tls-key` oder `--behind-tls-proxy` angeben.
- **Backend startet nicht nach Update:** `python3 setup/install.py` mit Internet ausführen
  (neue Abhängigkeiten `psutil`, `sqlcipher3-wheels`).
- **Start bricht mit "ACCOUNT DATABASE UNAVAILABLE" ab:** Schlüssel fehlt, ist falsch oder `accounts.db` ist noch
  Klartext. `manage_accounts.py status` zeigt den Grund; Klartext-Datei mit `encrypt-db` umwandeln (Abschnitt 7),
  Schlüssel aus der Sicherung zurückholen. Nichts wurde verändert.
- **Anmeldung wirkt „verloren“ nach Neustart:** Sitzungen liegen in `accounts.db` und überleben
  einen Neustart; Spiele im Speicher nicht.

## 7. Cutover-Runbook: bestehende Installation auf Konten umstellen

Für eine Installation, die bisher ohne Login lief (alte `decks.db`/`player_assets.db`, ggf. eine
Klartext-`accounts.db` aus der Entwicklungsphase). Der Ablauf ist **koordiniert**: Server und Browser
dürfen nie gemischt laufen (kein teilweise geschützter Betrieb). Eine frische Installation braucht ihn
nicht: sie legt Schlüssel und verschlüsselte Datenbank beim ersten Start selbst an.

1. **Ankündigen und stoppen.** Laufende Spiele enden mit dem Neustart (alles im Arbeitsspeicher). Server
   mit `c` + Enter im Server-Fenster (oder Strg+C) stoppen; prüfen, dass kein `uvicorn`-Prozess mehr läuft.
2. **Sichern.** Den ganzen Ordner `MTG_DATA_DIR` kopieren (`cp -a backend/data /sicherer/ort/data-vor-cutover`),
   auf einen **verschlüsselten** Datenträger. Das ist der Rückweg für alles Folgende.
3. **Abhängigkeit installieren.** `python3 setup/install.py` (mit Internet, oder aus einer
   Wheelhouse: `setup/wheels/` enthält `sqlcipher3-wheels`). Prüfen: `cd backend && venv/bin/python -c "import sqlcipher3"`.
4. **Alte Decks und Uploads migrieren.**
   `venv/bin/python scripts/migrate_legacy_decks.py preview` (nur lesen, Bericht prüfen), dann `apply`.
   **Ohne** `--assign-assets-by-name`: alte Uploads werden keinem Konto zugeordnet (sie waren freier
   Text; ein Fremder mit gleichem Namen würde sonst erben) und bleiben unsichtbar, bis du sie
   bewusst zuweist. Der Befehl legt ein eigenes geprüftes Backup unter `data/migration/backup-<Zeit>/` an
   und ist wiederholbar (ein zweiter Lauf ändert nichts). Zurück: `restore --backup <Ordner> --yes`.
5. **`accounts.db` verschlüsseln.**
   - Existiert noch keine `accounts.db`: `venv/bin/python scripts/manage_accounts.py init-key`; der erste Start legt die
     verschlüsselte Datenbank an.
   - Existiert eine alte Klartext-`accounts.db`: `venv/bin/python scripts/manage_accounts.py status`
     (zeigt "plaintext"), dann `venv/bin/python scripts/manage_accounts.py encrypt-db --yes`. Der Befehl erzeugt bei
     Bedarf die Schlüsseldatei (`~/.decklab/accounts.key`), prüft die Kopie und tauscht sie atomar ein.
     Das Klartext-Original verschwindet; wer es als Rückfallkopie behalten will, gibt
     `--keep-plaintext-backup /pfad` an und **löscht die Datei, sobald der Server läuft** (sie enthält Hashes und
     TOTP-Geheimnisse unverschlüsselt). `status` muss danach "encrypted" und "opens: yes" zeigen.
   - **Schlüssel sichern** (Passwortmanager/anderer Datenträger, nicht in den Datenordner).
6. **Start.** `./start.sh` (LAN-Modus; ggf. `--allow-network CIDR`). Im Log muss stehen: kein "ACCOUNT DATABASE UNAVAILABLE"
   und, bei neuer Datenbank, "ADMIN SETUP OPEN". Auf dem Server-Rechner `http://127.0.0.1:8000/admin` öffnen,
   Anfangspasswort ersetzen (mindestens 15 Zeichen), die angezeigten Einladungen sichern. Optional Authenticator-App einrichten.
7. **Browser.** Spieler laden die Seite neu und melden sich mit Einladung an. Alte Cookies (`mtg_client_token`, `mtg_player_name`) werden
   beim Laden gelöscht; Sitz-Geheimnisse und Client-Token existieren nicht mehr; ein noch offener alter Tab
   muss neu geladen werden.
8. **Prüfen.** `manage_accounts.py status`; ein Test-Login; `data/logs/security.log` enthält die
   Anmeldeereignisse; `ls -l` zeigt `accounts.db` mit Rechten 600. Danach `manage_accounts.py backup`
   einrichten (täglich).

**Zurück** (nur solange niemand neue Konten oder Decks angelegt hat): Server stoppen, den Datenordner
aus Schritt 2 zurückkopieren und die alte Programmversion starten. **Gelöschte Konten** (Admin-Löschung,
Löschfrist) werden nicht aus einem Journal wiederholt; nach einer Wiederherstellung aus einem Backup
gelöschte Konten anhand des Audit-Logs (`player.deleted`) von Hand erneut löschen.
