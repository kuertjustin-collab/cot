# COT-Feed

Automatisch aktualisierte CFTC-Commitments-of-Traders-Daten (Legacy, Futures Only).

- `cot.csv` enthält den Datenverlauf im Format, das das Trading-Journal erwartet.
- `manifest.json` zeigt den Zeitpunkt der letzten Aktualisierung.
- `.github/workflows/update-cot.yml` holt die Daten jeden Freitagabend automatisch
  direkt von der CFTC (https://www.cftc.gov/dea/newcot/deafut.txt) und committet sie.
- `fetch_cot.py` ist das Abruf-Skript dahinter, kann auch manuell per
  `python fetch_cot.py` ausgeführt werden.

Quelle der Rohdaten: U.S. Commodity Futures Trading Commission (öffentlich, kein Login).
