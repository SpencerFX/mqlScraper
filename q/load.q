/ ============================================================
/ mqlScraper - CSV -> on-disk partitioned kdb+ HDB loader
/ -
/   q q/load.q -hdb data/hdb -csv data/csv
/ -
/ Rebuilds every touched partition from the CSVs in full, so re-running
/ is idempotent. `sig`, `monthly` and `symdist` are written as plain splays
/ (the distribution table is NOT called `sym` - that name is the HDB's
/ enumeration-domain file).
/ at <hdb>/. Writedown is hand-rolled (.Q.en + per-column set + .d)
/ rather than .Q.dpft, whose arity is unreliable on kdb+ 4.0 w64. After
/ the data pass, every partition gets an empty splay for any missing
/ partitioned table so that `\l` registers all tables.
/ ============================================================

@[system;"l q/schema.q";{[e]@[system;"l schema.q";{[e]'"load.q: cannot locate schema.q"}]}]

.load.args:.Q.opt .z.x
.load.hdb:$[count .load.args`hdb; first .load.args`hdb; "data/hdb"]
.load.csv:$[count .load.args`csv; first .load.args`csv; "data/csv"]
.load.root:hsym `$.load.hdb

-1 "[load] hdb=",.load.hdb," csv=",.load.csv;

/ ---- csv reading ----------------------------------------------------------

.load.readSafe:{[name;colz;ty]
  path:hsym `$.load.csv,"/",name;
  if[()~key path; -1 "[load] missing ",name; :flip colz!(count colz)#()];
  lines:read0 path;
  if[2>count lines; -1 "[load] empty ",name; :flip colz!(count colz)#()];
  lines:1_lines;
  lines:lines where 0<count each lines;
  if[0=count lines; :flip colz!(count colz)#()];
  flip colz!(ty;",") 0: lines }

/ trades/<signalId>.csv - one small file per signal instead of one huge CSV
.load.readOneCsv:{[path;colz;ty]
  lines:read0 path;
  if[2>count lines; :flip colz!(count colz)#()];
  lines:1_lines;
  lines:lines where 0<count each lines;
  if[0=count lines; :flip colz!(count colz)#()];
  flip colz!(ty;",") 0: lines }

.load.readTradesDir:{[dir;colz;ty]
  d:hsym `$dir;
  if[()~key d; -1 "[load] missing trades dir ",dir; :flip colz!(count colz)#()];
  files:key d;
  if[0=count files; -1 "[load] empty trades dir ",dir; :flip colz!(count colz)#()];
  raze {[dir;colz;ty;f] .load.readOneCsv[hsym `$dir,"/",string f;colz;ty] }[dir;colz;ty;] each files }

/ header order MUST match normalizer.normalize *_FIELDS
.load.cSig:`signalId`mtVersion`name`authorLogin`authorName`accountType`url`firstSeen`lastSeen`broker`server
.load.cSnap:`ts`signalId`name`authorLogin`growthPct`profitUsd`equityUsd`balanceUsd`initialDepositUsd`depositsUsd`withdrawalsUsd`currency`subscribers`subscriberFundsUsd`weeks`tradingDays`tradingDaysPct`tradesPerWeek`avgHoldingSec`latestTradeText`startedAt`trades`profitTrades`lossTrades`winRatePct`longTrades`longPct`shortTrades`shortPct`bestTradeUsd`worstTradeUsd`grossProfitUsd`grossProfitPips`grossLossUsd`grossLossPips`profitFactor`expectedPayoffUsd`avgProfitUsd`avgLossUsd`sharpeRatio`recoveryFactor`maxConsecWins`maxConsecWinsUsd`maxConsecLosses`maxConsecLossesUsd`tradingActivityPct`maxDepositLoadPct`algoTradingPct`monthlyGrowthPct`annualForecastPct`drawdownAbsUsd`drawdownMaxUsd`drawdownMaxPct`drawdownBalancePct`drawdownEquityPct`leverage`server
.load.cGrowth:`signalId`date`growthPct
.load.cEquity:`signalId`ts`balance`equity
.load.cMonthly:`signalId`year`month`returnPct`yearlyPct
.load.cSym:`ts`signalId`symbol`deals`buyTrades`sellTrades
.load.cTrade:`tradeKey`signalId`kind`action`orderType`symbol`openTime`closeTime`openPrice`closePrice`sl`tp`volume`commission`swap`profit`cancelled`comment`collectedAt

/ ---- value coercion -----------------------------------------------------

.load.pTs:{  / list of char vectors -> timestamp vector (ISO-8601 in, tz suffix ignored)
  s:23$'x;                       / pad/truncate each to 23 chars: 2026-09-08T21:43:08.597
  s:@[;4 7;:;"."] each s;        / date separators -> .
  s:@[;10;:;"D"] each s;         / T -> D
  "P"$ s }
.load.pDate:{ "D"$ @[;4 7;:;"."] each 10$'x }

/ ---- writedown ----------------------------------------------------------------

.load.writeSplay:{[tname;t]
  d:.Q.dd[.load.root;tname];
  t:.Q.en[.load.root;t];
  {[d;t;c] (.Q.dd[d;c]) set t c}[d;t;] each cols t;
  (.Q.dd[d;`.d]) set cols t;
  -1 "[load] ",string[tname]," splay: ",string[count t]," rows"; }

.load.writePart:{[tname;dt;t]
  if[`date in cols t; t:delete date from t];
  t:`signalId xasc t;
  if[`signalId in cols t; t:update `p#signalId from t];
  tdir:.Q.dd[.Q.dd[.load.root; `$string dt]; tname];
  t:.Q.en[.load.root;t];
  {[tdir;t;c] (.Q.dd[tdir;c]) set t c}[tdir;t;] each cols t;
  (.Q.dd[tdir;`.d]) set cols t; }

.load.writePartitioned:{[tname;t;partCol]
  if[0=count t; -1 "[load] ",string[tname],": no rows"; :()];
  pv:t partCol;
  parts:asc distinct pv where not null pv;
  {[tname;t;pv;dt] .load.writePart[tname;dt; t where pv=dt] }[tname;t;pv;] each parts;
  -1 "[load] ",string[tname],": ",string[count t]," rows over ",string[count parts]," partitions"; }

/ ensure every partition dir carries a splay for tname (empty one if absent)
.load.backfill:{[tname;emptyT]
  root:.load.root;
  dates:{x where x like "[12][0-9][0-9][0-9].[0-9][0-9].[0-9][0-9]"} string key root;
  {[tname;emptyT;root;d]
    if[not tname in key .Q.dd[root;`$d];
      .load.writePart[tname; "D"$d; emptyT] ] }[tname;emptyT;root;] each dates; }

/ ---- per-table processing --------------------------------------------------

.load.doSig:{
  t:.load.readSafe["signals.csv"; .load.cSig; "JJSSSSS**SS"];
  if[0=count t; :()];
  t:update firstSeen:.load.pTs firstSeen, lastSeen:.load.pTs lastSeen from t;
  .load.writeSplay[`sig; t] }

.load.doSnap:{
  t:.load.readSafe["snapshots.csv"; .load.cSnap; "*JSSFFFFFFFSJFJJFFJS*JJJFJFJFFFFFFFFFFFFFJFJFFFFFFFFFFFJS"];
  if[0=count t; -1 "[load] snap: no rows"; :()];
  t:update ts:.load.pTs ts, startedAt:.load.pTs startedAt from t;
  t:update date:`date$ts from t;
  .load.writePartitioned[`snap; t; `date] }

.load.doGrowth:{
  t:.load.readSafe["growth.csv"; .load.cGrowth; "J*F"];
  if[0=count t; -1 "[load] growth: no rows"; :()];
  t:update date:.load.pDate date from t;
  .load.writePartitioned[`growth; t; `date] }

.load.doEquity:{
  t:.load.readSafe["equity.csv"; .load.cEquity; "J*FF"];
  if[0=count t; -1 "[load] equity: no rows"; :()];
  t:update ts:.load.pTs ts from t;
  t:update date:`date$ts from t;
  .load.writePartitioned[`equity; t; `date] }

.load.doMonthly:{
  t:.load.readSafe["monthly.csv"; .load.cMonthly; "JJJFF"];
  if[0=count t; -1 "[load] monthly: no rows"; :()];
  .load.writeSplay[`monthly; t] }

.load.doSym:{
  t:.load.readSafe["symbols.csv"; .load.cSym; "*JSJJJ"];
  if[0=count t; -1 "[load] symdist: no rows"; :()];
  t:update ts:.load.pTs ts from t;
  .load.writeSplay[`symdist; t] }

.load.doTrade:{
  t:.load.readTradesDir[.load.csv,"/trades"; .load.cTrade; "SJSSSS**FFFFFFFFJS*"];
  if[0=count t; -1 "[load] trade: no rows"; :()];
  t:update openTime:.load.pTs openTime, closeTime:.load.pTs closeTime, collectedAt:.load.pTs collectedAt from t;
  t:update pd:`date$closeTime from t;
  t:update pd:`date$openTime from t where null pd;
  t:update date:pd from t;
  t:delete pd from t;
  t:delete from t where null date;            / no usable timestamp -> cannot partition
  .load.writePartitioned[`trade; t; `date] }

/ ---- run ------------------------------------------------------------------

.load.doSig[]
.load.doSnap[]
.load.doGrowth[]
.load.doEquity[]
.load.doMonthly[]
.load.doSym[]
.load.doTrade[]
.load.backfill[`snap; snap]
.load.backfill[`growth; growth]
.load.backfill[`equity; equity]
.load.backfill[`trade; trade]
-1 "[load] done. Load with:  q -> \\l ",.load.hdb;
exit 0
