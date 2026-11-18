WITH cap AS (
  SELECT 'capacity' AS block, a.pb_id, CAST(NULL AS VARCHAR) AS issuer_id,
         p.capacity_usd AS limit_usd, SUM(a.notional_alloc_usd) AS used_usd,
         d.dual_usd_per_usd
  FROM allocation a JOIN providers p USING (pb_id)
  LEFT JOIN duals_capacity d USING (pb_id)
  GROUP BY a.pb_id, p.capacity_usd, d.dual_usd_per_usd
), cp AS (
  SELECT 'counterparty' AS block, m.pb_id, CAST(NULL AS VARCHAR) AS issuer_id,
         p.counterparty_limit_usd AS limit_usd, m.margin_usd AS used_usd,
         d.dual_usd_per_usd
  FROM pb_margin m JOIN providers p USING (pb_id)
  LEFT JOIN duals_counterparty d USING (pb_id)
), br AS (
  SELECT 'borrow' AS block, b.pb_id, b.issuer_id, b.borrow_available_usd AS limit_usd,
         COALESCE(u.used_usd, 0.0) AS used_usd,
         d.dual_usd_per_usd
  FROM pb_borrow b
  LEFT JOIN (
    SELECT a.pb_id, prod.issuer_id, SUM(a.notional_alloc_usd) AS used_usd
    FROM allocation a
    JOIN positions pos USING (pos_id)
    JOIN products prod USING (product_id)
    WHERE pos.side < 0 AND prod.needs_locate
    GROUP BY a.pb_id, prod.issuer_id
  ) u ON u.pb_id = b.pb_id AND u.issuer_id = b.issuer_id
  LEFT JOIN duals_borrow d ON d.pb_id = b.pb_id AND d.issuer_id = b.issuer_id
)
SELECT block, pb_id, issuer_id, limit_usd, used_usd,
       limit_usd - used_usd AS slack_usd,
       limit_usd - used_usd <= 1e-6 * GREATEST(1.0, limit_usd) AS binding,
       dual_usd_per_usd
FROM (SELECT * FROM cap UNION ALL SELECT * FROM cp UNION ALL SELECT * FROM br)
ORDER BY block, pb_id, issuer_id
