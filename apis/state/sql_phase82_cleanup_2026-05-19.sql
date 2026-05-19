-- Phase 82 cleanup (DEC-087, 2026-05-19): close Tue dual-invocation phantom
-- OPEN rows + Mon GOOGL close-loop-gap row.
--
-- Affected rows (4 total):
--   GOOG  qty=19 opened 2026-05-19 14:30  ← Tue c2 phantom from API-process writer
--   GOOGL qty=19 opened 2026-05-19 14:30  ← Tue c2 phantom from API-process writer
--   VRT   qty=23 opened 2026-05-19 14:30  ← Tue c2 phantom (no supporting orders row)
--   GOOGL qty=20 opened 2026-05-18 14:30  ← Mon close-loop gap (c3 SELL filled, position not closed)
--
-- The keep-side of each pair:
--   GOOG  qty=21 opened 2026-05-18 14:30  ← Mon legitimate momentum_v1 BUY
--   GOOGL <none after this cleanup>       ← Mon + Tue both phantom; AAPL/MRVL untouched
--   VRT   qty=23 opened 2026-05-19 13:35  ← Tue c1 legitimate c5b1-canonical BUY

BEGIN;

-- 1) Close Tue 2026-05-19 dup OPEN rows for GOOG + GOOGL (the dup-side of each pair).
UPDATE positions
   SET status='closed',
       closed_at='2026-05-19 13:35:00.000627',
       exit_price=entry_price,
       realized_pnl=0,
       quantity=0
 WHERE status='open'
   AND opened_at::date='2026-05-19'
   AND security_id IN (SELECT id FROM securities WHERE ticker IN ('GOOG','GOOGL'));

-- 2) Close the second VRT row (the c2 14:30 phantom — no matching orders ledger entry).
WITH dup AS (
  SELECT p.id
    FROM positions p
    JOIN securities s ON p.security_id=s.id
   WHERE p.status='open'
     AND s.ticker='VRT'
     AND p.opened_at::date='2026-05-19'
   ORDER BY p.opened_at DESC
   LIMIT 1
)
UPDATE positions
   SET status='closed',
       closed_at='2026-05-19 14:30:00.000744',
       exit_price=entry_price,
       realized_pnl=0,
       quantity=0
 WHERE id IN (SELECT id FROM dup);

-- 3) Close Mon 2026-05-18 GOOGL close-loop-gap row (c3 15:30 SELL filled
--    in orders ledger but position row never closed).
UPDATE positions
   SET status='closed',
       closed_at='2026-05-18 15:30:00.000721',
       exit_price=entry_price,
       realized_pnl=0
 WHERE status='open'
   AND security_id=(SELECT id FROM securities WHERE ticker='GOOGL')
   AND opened_at::date='2026-05-18';

COMMIT;

-- Verification: each of GOOG / GOOGL / VRT should have exactly 1 OPEN row.
SELECT s.ticker, COUNT(*) AS open_rows, SUM(p.quantity) AS total_qty
  FROM positions p
  JOIN securities s ON p.security_id=s.id
 WHERE p.status='open'
   AND s.ticker IN ('GOOG','GOOGL','VRT')
 GROUP BY s.ticker
 ORDER BY s.ticker;
