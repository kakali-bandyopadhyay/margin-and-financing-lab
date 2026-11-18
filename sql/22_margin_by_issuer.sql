SELECT i.pb_id, i.issuer_id, i.issuer_gross_usd, i.pb_gross_usd,
       i.threshold_usd, i.conc_rate, i.addon_usd,
       i.issuer_gross_usd / NULLIF(i.pb_gross_usd, 0) AS issuer_share_pb_gross
FROM issuer_margin i
WHERE i.addon_usd > 0
ORDER BY i.addon_usd DESC, i.pb_id, i.issuer_id
