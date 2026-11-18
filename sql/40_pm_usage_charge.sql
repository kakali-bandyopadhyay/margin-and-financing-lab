WITH rows AS (
  SELECT pm_id, usage_usd, solo_margin_usd, share, residual_usd,
         attributed_margin_usd, charge_usd,
         CAST(NULL AS DOUBLE) AS sum_attributed_minus_M
  FROM attribution
), total AS (
  SELECT 'TOTAL' AS pm_id, SUM(usage_usd) AS usage_usd,
         SUM(solo_margin_usd) AS solo_margin_usd, SUM(share) AS share,
         SUM(residual_usd) AS residual_usd, SUM(attributed_margin_usd) AS attributed_margin_usd,
         SUM(charge_usd) AS charge_usd,
         SUM(attributed_margin_usd) - (SELECT SUM(margin_usd) FROM pb_margin) AS sum_attributed_minus_M
  FROM attribution
)
SELECT * FROM rows UNION ALL SELECT * FROM total
