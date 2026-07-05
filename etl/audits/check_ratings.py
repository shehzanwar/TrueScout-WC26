# In your Python env from the TrueScout dir:
import duckdb, pandas as pd
conn = duckdb.connect('data/truescout.duckdb', read_only=True)
df = conn.execute("""
    SELECT pr.name, pr.national_team, pr.position_macro,
           pr.posterior_mean, pr.confidence_score, pr.shrinkage_weight,
           pr.wc_minutes, pr.percentile_rank,
           CASE WHEN cp.player_id IS NULL THEN 'no_prior' ELSE 'has_prior' END as prior_status
    FROM player_ratings pr
    LEFT JOIN club_priors cp ON pr.player_id = cp.player_id
    WHERE pr.national_team IN (
        'Morocco','France','Brazil','Norway','Mexico','England',
        'Portugal','Spain','United States','Belgium','Switzerland',
        'Colombia','Argentina','Egypt'
    )
    ORDER BY pr.posterior_mean DESC
""").df()
print(df.to_string(max_rows=50))
conn.close()