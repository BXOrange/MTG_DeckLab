# Server-Anleitung (Betrieb mit Konten)

Für alle, die DeckLab auf einem Rechner für andere bereitstellen (LAN oder Internet).
Technische Details zu Start, Netzwerk und Konfiguration: [OPERATIONS.md](OPERATIONS.md).
Entwurf und Entscheidungen: [Konten-Plan](../concepts/15_ACCOUNT_SYSTEM_PLAN.md).

> **Stand (PLR-9a).** Gebaut und getestet: Betriebsarten, Netz-Allowlist, Konten, Anmeldung per
> Einladung, Sitzungen, Passwort-Regeln, Profil-Oberfläche. **Noch nicht** gebaut: Absicherung der
> Deck-, Spiel- und Multiplayer-Routen (PLR-9b/9c), die `/admin`-Seite (PLR-9d), Verschlüsselung und
> Backups (PLR-9e). Heute schützt in `--lan` die **Netz-Allowlist**; ein Login schützt Decks und
> Spiele noch nicht. Starte ohne Moduswahl, bis der Cutover (9e) dokumentiert ist, wenn du Decks
> vor Mitspielern im selben Netz verbergen musst.

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
  erlaubt, verbreitete Passwörter werden abgelehnt. Die Anzeige beim Eingeben zeigt **Rot**
  (zu kurz, wird blockiert), **Gelb** (gültig, aber eine Zahl, ein Sonderzeichen oder mehr
  Länge fehlen) und **Grün**.
- **Sitzungen:** Cookie, serverseitig 8 Stunden Leerlauf und 14 Tage absolut
  (`MTG_SESSION_IDLE_SECONDS`, `MTG_SESSION_ABSOLUTE_SECONDS`). Passwort ändern beendet alle anderen
  Sitzungen; „Überall abmelden“ beendet alle.
- **Fehlversuche:** 10 pro 15 Minuten je Quelle und je Kontoname, danach 429 bis das Fenster
  weitergelaufen ist (`MTG_LOGIN_FAILURE_LIMIT`, `MTG_LOGIN_FAILURE_WINDOW_SECONDS`). Es gibt keine
  dauerhafte Sperre. Die Fehlermeldung verrät nicht, ob ein Konto existiert.
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
