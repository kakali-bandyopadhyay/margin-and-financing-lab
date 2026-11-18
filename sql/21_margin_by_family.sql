SELECT f.pb_id, f.product_id, f.liquidity_tier, f.vol_bucket,
       SUM(f.margin_usd) AS margin_usd, SUM(f.gross_usd) AS gross_usd,
       SUM(f.net_usd) AS net_usd,
       CASE WHEN SUM(f.gross_usd) = 0 THEN NULL
            ELSE 1.0 - SUM(f.net_usd) / SUM(f.gross_usd) END AS offset_ratio,
       MAX(f.r) AS r, MAX(f.phi) AS phi
FROM family_margin f
GROUP BY f.pb_id, f.product_id, f.liquidity_tier, f.vol_bucket
ORDER BY margin_usd DESC, f.pb_id, f.product_id
LIMIT 25
