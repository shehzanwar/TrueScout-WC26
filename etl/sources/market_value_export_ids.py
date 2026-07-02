"""Export WC player Sofascore IDs to CSV for fetching in a cloud environment."""
import csv
from pathlib import Path
import duckdb

DB_PATH     = Path("data/truescout.duckdb")
LINEUP_GLOB = "data/bronze/sofascore/lineups/*.parquet"
OUT_CSV     = Path("data/mv_ids.csv")

con = duckdb.connect(str(DB_PATH))

rows = con.execute(f"""
    SELECT ip.reep_id, ip.key_sofascore
    FROM identity_players ip
    WHERE ip.key_sofascore IN (
        SELECT DISTINCT CAST(player_id AS VARCHAR)
        FROM read_parquet('{LINEUP_GLOB}', union_by_name=true)
        WHERE minutes_played > 0
    )
    AND ip.key_sofascore IS NOT NULL
""").fetchall()

con.close()

with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
    writer = csv.writer(f)
    writer.writerow(["reep_id", "sofascore_id"])
    writer.writerows(rows)

print(f"Exported {len(rows)} player IDs to {OUT_CSV}")
