SELECT m.pb_id, m.margin_usd, p.counterparty_limit_usd,
       p.counterparty_limit_usd - m.margin_usd AS headroom_usd,
       100.0 * m.margin_usd / NULLIF(p.counterparty_limit_usd, 0) AS used_pct,
       100.0 * m.margin_usd / NULLIF(SUM(m.margin_usd) OVER (), 0) AS share_total_pct
FROM pb_margin m JOIN providers p USING (pb_id)
ORDER BY m.pb_id
