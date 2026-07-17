# 8. Engine-Status

Der Tab **Engine-Status** ist nichts, womit du interagierst — er ist
eine **Transparenzseite**, die auflistet, was die Regel-Engine heute
tatsächlich unterstützt und was noch fehlt, gegliedert nach
Themenbereich (Zugablauf, Kampf-Schlüsselwörter, statische
Fähigkeiten, aktivierte/ausgelöste Fähigkeiten, Kartentypen und mehr).

Jeder Eintrag trägt eine von drei Markierungen:

- **✅ Vollständig** — umgesetzt und getestet.
- **◐ Teilweise** — der Grundfall funktioniert, mit dokumentierten
  Grenzen.
- **✖ Geplant** — vorgesehen, aber noch nicht umgesetzt.

## Wozu das nützlich ist

Goldfisch und Puzzle/Replay laufen gegen eine echte Regel-Engine, kein
vereinfachtes Mock-Modell — aber diese Engine hat, wie jede
Umsetzung eines so komplexen Spiels wie Magic, noch Ecken, die sie
nicht abdeckt. Verhält sich eine Karte unerwartet (eine Fähigkeit
scheint nichts zu tun, oder ein Schlüsselwort scheint nicht zu
greifen), ist dieser Tab die erste Anlaufstelle: Er sagt dir ehrlich,
ob genau dieser Mechanismus schon modelliert ist, statt dich raten zu
lassen, ob du auf einen Fehler oder eine bewusste Lücke gestoßen bist.

Er wird von Hand parallel zur Engine selbst aktuell gehalten — behandle
ihn also als maßgebliche Antwort auf die Frage "unterstützt die App
X tatsächlich?" für jede Regelfrage, die dir beim Spielen begegnet.
