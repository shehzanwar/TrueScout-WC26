"""Import mv_results.csv (produced by market_value_colab.py) into DuckDB."""
import csv
from pathlib import Path
import duckdb

DB_PATH    = Path("data/truescout.duckdb")
IN_CSV     = Path("data/mv_results.csv")

if not IN_CSV.exists():
    raise FileNotFoundError(f"Place mv_results.csv at {IN_CSV} first.")

con = duckdb.connect(str(DB_PATH))

existing_cols = {r[0] for r in con.execute("DESCRIBE identity_players").fetchall()}
if "market_value_eur" not in existing_cols:
    con.execute("ALTER TABLE identity_players ADD COLUMN market_value_eur BIGINT")
    print("Added market_value_eur column")

with open(IN_CSV, newline="", encoding="utf-8") as f:
    rows = list(csv.DictReader(f))

updated = skipped = 0
for row in rows:
    mv_str = row.get("market_value_eur", "").strip()
    if mv_str == "":
        skipped += 1
        continue
    con.execute(
        "UPDATE identity_players SET market_value_eur = ? WHERE reep_id = ?",
        [int(mv_str), row["reep_id"]],
    )
    updated += 1

con.close()
print(f"Imported {updated} values ({skipped} skipped / no data).")
