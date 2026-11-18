WITH totals AS (
  SELECT scenario, status, objective_usd, financing_usd, margin_funding_usd,
         total_margin_usd, total_charge_usd
  FROM sensitivity_summary
), base AS (SELECT * FROM totals WHERE scenario = 'base')
SELECT t.scenario, t.status, t.objective_usd, t.financing_usd,
       t.margin_funding_usd, t.total_margin_usd, t.total_charge_usd,
       t.objective_usd - b.objective_usd AS delta_objective_usd,
       t.total_margin_usd - b.total_margin_usd AS delta_margin_usd,
       t.total_charge_usd - b.total_charge_usd AS delta_charge_usd,
       100.0 * (t.objective_usd - b.objective_usd) / NULLIF(b.objective_usd, 0) AS objective_change_pct
FROM totals t CROSS JOIN base b
ORDER BY t.scenario
