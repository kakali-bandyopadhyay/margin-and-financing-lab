SELECT a.pb_id,
       SUM(a.notional_alloc_usd) AS gross_usd,
       SUM(CASE WHEN p.side > 0 THEN a.notional_alloc_usd ELSE 0 END) AS long_usd,
       SUM(CASE WHEN p.side < 0 THEN a.notional_alloc_usd ELSE 0 END) AS short_usd,
       SUM(p.side * a.notional_alloc_usd) AS net_usd,
       pr.capacity_usd AS capacity_usd,
       100.0 * SUM(a.notional_alloc_usd) / NULLIF(pr.capacity_usd, 0) AS capacity_used_pct,
       COUNT(*) FILTER (WHERE a.w > 1e-9) AS position_count
FROM allocation a
JOIN positions p USING (pos_id)
JOIN providers pr USING (pb_id)
GROUP BY a.pb_id, pr.capacity_usd
ORDER BY a.pb_id
