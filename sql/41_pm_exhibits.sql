SELECT a.pm_id, a.usage_usd AS usage_fixed_usd,
       r.usage_resolve_usd, r.delta_objective_usd,
       c.financing_usd, c.margin_funding_usd, c.all_in_usd,
       e.euler_usd, e.euler_low_usd, e.euler_high_usd,
       a.attributed_margin_usd
FROM attribution a
LEFT JOIN resolve r USING (pm_id)
LEFT JOIN all_in c USING (pm_id)
LEFT JOIN euler e USING (pm_id)
ORDER BY a.pm_id
