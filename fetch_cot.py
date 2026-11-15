#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Holt die wöchentlichen CFTC-Commitments-of-Traders-Daten (Legacy, Futures Only,
Combined Long Format) direkt von der CFTC und schreibt sie im selben Format,
wie es das Trading-Journal erwartet, nach cot.csv + manifest.json.

Quelle: https://www.cftc.gov/dea/newcot/deafut.txt
        (von der CFTC selbst wöchentlich aktualisierte Rohdatei, kein Login,
         keine Anmeldung, kein API-Key nötig)

Format cot.csv (Header bleibt so, wie es das Journal erwartet):
datum,waehrung,cftc_code,comm_long,comm_short,noncomm_long,noncomm_short,nonrep_long,nonrep_short
"""

import csv
import io
import json
import sys
import urllib.request
from datetime import datetime, timezone

SOURCE_URL = "https://www.cftc.gov/dea/newcot/deafut.txt"
COT_CSV = "cot.csv"
MANIFEST_JSON = "manifest.json"
HEADER = ["datum", "waehrung", "cftc_code", "comm_long", "comm_short",
          "noncomm_long", "noncomm_short", "nonrep_long", "nonrep_short"]

# Welche CFTC-Contract-Market-Codes zu welcher Journal-Bezeichnung gehören.
# Exakt übernommen aus den bisherigen Daten im Journal, damit nichts umbenannt wird.
CODE_MAP = {
    "232741": "AUD",
    "088691": "GOLD",
    "084691": "SILBER",
    "076651": "PLATIN",
    "085692": "KUPFER",
    "067651": "OEL",
    "080732": "ZUCKER",
    "083731": "KAFFEE",
    "209742": "NQ",
    "13874A": "ES",
}

# WICHTIG: Die CFTC-Rohdatei (deafut.txt) hat KEINE Kopfzeile -- sie beginnt
# direkt mit den Daten. Die Spaltenreihenfolge ist aber offiziell dokumentiert
# unter https://www.cftc.gov/MarketReports/CommitmentsofTraders/HistoricalViewable/cotvariableslegacy.html
# und wurde zusätzlich 1:1 gegen eine echte Zeile aus der Live-Datei verifiziert
# (0-basierter Index in der Zeile):
#   0  Market_and_Exchange_Names
#   1  As_of_Date_In_Form_YYMMDD
#   2  As_of_Date_In_Form_YYYY-MM-DD   <- date
#   3  CFTC_Contract_Market_Code        <- code
#   4  CFTC_Market_Code_In_Initials
#   5  CFTC_Region_Code
#   6  CFTC_Commodity_Code
#   7  Open_Interest_All
#   8  Noncommercial_Positions_Long_All   <- noncomm_long
#   9  Noncommercial_Positions_Short_All  <- noncomm_short
#   10 Noncommercial_Positions_Spreading_All
#   11 Commercial_Positions_Long_All   <- comm_long
#   12 Commercial_Positions_Short_All  <- comm_short
#   13 Total_Reportable_Positions_Long_All
#   14 Total_Reportable_Positions_Short_All
#   15 Nonreportable_Positions_Long_All   <- nonrep_long
#   16 Nonreportable_Positions_Short_All  <- nonrep_short
COL_INDEX = {
    "date": 2,
    "code": 3,
    "noncomm_long": 8,
    "noncomm_short": 9,
    "comm_long": 11,
    "comm_short": 12,
    "nonrep_long": 15,
    "nonrep_short": 16,
}
MIN_COLS = max(COL_INDEX.values()) + 1


def fetch_raw():
    req = urllib.request.Request(
        SOURCE_URL,
        headers={"User-Agent": "Mozilla/5.0 (compatible; cot-feed-bot/1.0)"},
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        raw = resp.read()
    # CFTC liefert die Datei i.d.R. als Latin-1 / Windows-1252.
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("latin-1")


def parse_rows(text):
    reader = csv.reader(io.StringIO(text))

    out = {}  # waehrung -> row-dict (nur die neueste Zeile je Code, falls mehrere)
    seen_any_row = False
    for row in reader:
        if not row or len(row) < MIN_COLS:
            continue
        seen_any_row = True
        code = (row[COL_INDEX["code"]] or "").strip()
        waehrung = CODE_MAP.get(code)
        if not waehrung:
            continue
        datum_raw = (row[COL_INDEX["date"]] or "").strip()
        try:
            datum = datetime.strptime(datum_raw, "%Y-%m-%d").strftime("%Y-%m-%d")
        except ValueError:
            # Falls das Datum schon im richtigen Format ist oder abweicht.
            datum = datum_raw[:10]
        existing = out.get(waehrung)
        if existing is None or datum > existing["datum"]:
            out[waehrung] = {
                "datum": datum,
                "waehrung": waehrung,
                "cftc_code": code,
                "comm_long": (row[COL_INDEX["comm_long"]] or "").strip(),
                "comm_short": (row[COL_INDEX["comm_short"]] or "").strip(),
                "noncomm_long": (row[COL_INDEX["noncomm_long"]] or "").strip(),
                "noncomm_short": (row[COL_INDEX["noncomm_short"]] or "").strip(),
                "nonrep_long": (row[COL_INDEX["nonrep_long"]] or "").strip(),
                "nonrep_short": (row[COL_INDEX["nonrep_short"]] or "").strip(),
            }

    if not seen_any_row:
        print("FEHLER: Keine einzige auswertbare Zeile in der Rohdatei gefunden "
              "(Datei evtl. leer oder Format hat sich grundlegend geändert).",
              file=sys.stderr)
        sys.exit(1)

    return list(out.values())


def load_existing():
    try:
        with open(COT_CSV, "r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            return list(reader)
    except FileNotFoundError:
        return []


def merge(existing, new_rows):
    # Schlüssel: (datum, waehrung) -- vorhandene Wochen fürs selbe Paar ersetzen,
    # neue anhängen, alte Reihenfolge ansonsten erhalten.
    by_key = {(r["datum"], r["waehrung"]): r for r in existing}
    for r in new_rows:
        by_key[(r["datum"], r["waehrung"])] = r
    rows = list(by_key.values())
    rows.sort(key=lambda r: (r["datum"], r["waehrung"]))
    return rows


def write_csv(rows):
    with open(COT_CSV, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=HEADER)
        writer.writeheader()
        for r in rows:
            writer.writerow({k: r.get(k, "") for k in HEADER})


def write_manifest():
    manifest = {
        "updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "files": ["cot.csv"],
    }
    with open(MANIFEST_JSON, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False)


def main():
    raw = fetch_raw()
    new_rows = parse_rows(raw)
    if not new_rows:
        print("Keine passenden Zeilen in der CFTC-Datei gefunden -- nichts geschrieben.",
              file=sys.stderr)
        sys.exit(1)
    existing = load_existing()
    merged = merge(existing, new_rows)
    write_csv(merged)
    write_manifest()
    print("OK: %d neue/aktualisierte Zeilen, %d Zeilen insgesamt." % (len(new_rows), len(merged)))


if __name__ == "__main__":
    main()
