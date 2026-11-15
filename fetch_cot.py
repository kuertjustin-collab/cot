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

# Mögliche Spaltennamen in der CFTC-Rohdatei (variiert leicht je nach Jahr/Version,
# daher mehrere Kandidaten pro logischem Feld -- robust gegen kleine Namensänderungen).
COL_CANDIDATES = {
    "date": ["As_of_Date_In_Form_YYYY-MM-DD", "As_of_Date_in_Form_YYYY-MM-DD",
             "Report_Date_as_YYYY-MM-DD", "report_date_as_yyyy_mm_dd"],
    "code": ["CFTC_Contract_Market_Code", "cftc_contract_market_code"],
    "comm_long": ["Commercial_Positions_Long_All", "Comm_Positions_Long_All",
                  "commercial_long_all"],
    "comm_short": ["Commercial_Positions_Short_All", "Comm_Positions_Short_All",
                   "commercial_short_all"],
    "noncomm_long": ["Noncommercial_Positions_Long_All", "NonComm_Positions_Long_All",
                      "noncomm_positions_long_all"],
    "noncomm_short": ["Noncommercial_Positions_Short_All", "NonComm_Positions_Short_All",
                       "noncomm_positions_short_all"],
    "nonrep_long": ["Nonreportable_Positions_Long_All", "nonrept_positions_long_all"],
    "nonrep_short": ["Nonreportable_Positions_Short_All", "nonrept_positions_short_all"],
}


def pick_column(fieldnames, candidates):
    lower_map = {f.lower(): f for f in fieldnames}
    for c in candidates:
        if c.lower() in lower_map:
            return lower_map[c.lower()]
    return None


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
    reader = csv.DictReader(io.StringIO(text))
    fieldnames = reader.fieldnames or []

    resolved = {}
    for key, candidates in COL_CANDIDATES.items():
        col = pick_column(fieldnames, candidates)
        if col is None:
            print("FEHLER: Spalte für '%s' nicht gefunden. Vorhandene Spalten:" % key,
                  file=sys.stderr)
            print(fieldnames, file=sys.stderr)
            sys.exit(1)
        resolved[key] = col

    out = {}  # waehrung -> row-dict (nur die neueste Zeile je Code, falls mehrere)
    for row in reader:
        code = (row.get(resolved["code"]) or "").strip()
        waehrung = CODE_MAP.get(code)
        if not waehrung:
            continue
        datum_raw = (row.get(resolved["date"]) or "").strip()
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
                "comm_long": row.get(resolved["comm_long"], "").strip(),
                "comm_short": row.get(resolved["comm_short"], "").strip(),
                "noncomm_long": row.get(resolved["noncomm_long"], "").strip(),
                "noncomm_short": row.get(resolved["noncomm_short"], "").strip(),
                "nonrep_long": row.get(resolved["nonrep_long"], "").strip(),
                "nonrep_short": row.get(resolved["nonrep_short"], "").strip(),
            }
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
