SELECT kinds.kind, COUNT(k.kind) AS kink_count
FROM (VALUES ('net'), ('hinge')) AS kinds(kind)
LEFT JOIN kinks k ON k.kind = kinds.kind
GROUP BY kinds.kind
ORDER BY kinds.kind
