/ ============================================================
/ mqlScraper - in-memory ingest helpers
/ -
/ Optional. The normal path is CSV -> q/load.q -> HDB. These helpers
/ push parsed rows straight into in-memory tables (tests, ad-hoc
/ sessions, a future live feed). Load q/schema.q first.
/ ============================================================

if[not `snap in tables[]; @[system;"l q/schema.q";{[e] @[system;"l schema.q";{[e] '"load q/schema.q first"}]}]]

/ upsert one registry row (dict or 1-row table), keeping firstSeen stable
.mq.upsertSignal:{[s]
  s:$[98h=type s; first s; s];
  id:s`signalId;
  $[id in exec signalId from sig;
    [ `sig upsert update lastSeen:s`lastSeen from sig where signalId=id ];
    [ `sig insert s ] ];
  }

/ append a headline snapshot row (dict or table)
.mq.addSnapshot:{[s] `snap insert $[98h=type s; s; enlist s]; count s }

/ replace a signal's weekly growth curve
.mq.replaceGrowth:{[sid;t]
  delete from `growth where signalId=sid;
  if[count t; `growth insert t];
  count t }

/ replace a signal's balance/equity curve
.mq.replaceEquity:{[sid;t]
  delete from `equity where signalId=sid;
  if[count t; `equity insert t];
  count t }

/ replace a signal's monthly returns
.mq.replaceMonthly:{[sid;t]
  delete from `monthly where signalId=sid;
  if[count t; `monthly insert t];
  count t }

/ append a per-symbol distribution snapshot
.mq.addSymbols:{[t] if[0=count t; :0]; `symdist insert t; count t }
