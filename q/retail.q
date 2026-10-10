/ ============================================================
/ mqlScraper - "retail" HDB: signals + curves + trade history
/ -
/   q q/retail.q -hdb C:/data/retail -csv data/csv
/ -
/ Writes five tables into a standalone HDB, separate from data/hdb:
/   sig      - signal registry            (root splay)
/   monthly  - monthly returns grid       (root splay)
/   growth   - weekly growth curve        (partition: date)
/   equity   - balance / equity curve     (partition: date of ts)
/   trade    - per-trade Trading history  (partition: date of closeTime, else openTime)
/ (snap / symdist are intentionally left in data/hdb only.)
/ -
/ Every touched partition is rebuilt in full from the CSVs so re-running
/ as the --trades pass accumulates more history stays idempotent. After
/ the data pass every partition dir gets an empty splay for any missing
/ partitioned table so `\l` registers them all. Writedown is hand-rolled
/ (.Q.en + per-column set + .d) rather than .Q.dpft, whose arity is
/ unreliable on kdb+ 4.0 w64. Symbol columns enumerate against <hdb>/sym.
/ ============================================================

@[system;"l q/schema.q";{[e]@[system;"l schema.q";{[e]'"retail.q: cannot locate schema.q"}]}]

.rt.args:.Q.opt .z.x
.rt.hdb:$[count .rt.args`hdb; first .rt.args`hdb; "C:/data/retail"]
.rt.csv:$[count .rt.args`csv; first .rt.args`csv; "data/csv"]
.rt.root:hsym `$.rt.hdb
.rt.minDate:2000.01.01                 / drop rows dated before this (corrupt zero epochs)

-1 "[retail] hdb=",.rt.hdb," csv=",.rt.csv;

/ header order MUST match normalizer.normalize *_FIELDS
.rt.cSig:`signalId`mtVersion`name`authorLogin`authorName`accountType`url`firstSeen`lastSeen`broker`server
.rt.cGrowth:`signalId`date`growthPct
.rt.cEquity:`signalId`ts`balance`equity
.rt.cMonthly:`signalId`year`month`returnPct`yearlyPct
.rt.cTrade:`tradeKey`signalId`kind`action`orderType`symbol`openTime`closeTime`openPrice`closePrice`sl`tp`volume`commission`swap`profit`cancelled`comment`collectedAt

/ ---- csv reading --------------------------------------------------------

.rt.readSafe:{[name;colz;ty]
  path:hsym `$.rt.csv,"/",name;
  if[()~key path; -1 "[retail] missing ",name; :flip colz!(count colz)#()];
  lines:read0 path;
  if[2>count lines; -1 "[retail] empty ",name; :flip colz!(count colz)#()];
  lines:1_lines;
  lines:lines where 0<count each lines;
  if[0=count lines; :flip colz!(count colz)#()];
  flip colz!(ty;",") 0: lines }

/ trades/<signalId>.csv - one small file per signal instead of one huge CSV
.rt.readOneCsv:{[path;colz;ty]
  lines:read0 path;
  if[2>count lines; :flip colz!(count colz)#()];
  lines:1_lines;
  lines:lines where 0<count each lines;
  if[0=count lines; :flip colz!(count colz)#()];
  flip colz!(ty;",") 0: lines }

.rt.readTradesDir:{[dir;colz;ty]
  d:hsym `$dir;
  if[()~key d; -1 "[retail] missing trades dir ",dir; :flip colz!(count colz)#()];
  files:key d;
  if[0=count files; -1 "[retail] empty trades dir ",dir; :flip colz!(count colz)#()];
  raze {[dir;colz;ty;f] .rt.readOneCsv[hsym `$dir,"/",string f;colz;ty] }[dir;colz;ty;] each files }

/ ---- value coercion ---------------------------------------------------

.rt.pTs:{  / list of char vectors -> timestamp vector (ISO-8601 in, tz suffix ignored)
  s:23$'x;                       / pad/truncate each to 23 chars: 2026-09-08T21:43:08.597
  s:@[;4 7;:;"."] each s;        / date separators -> .
  s:@[;10;:;"D"] each s;         / T -> D
  "P"$ s }
.rt.pDate:{ "D"$ @[;4 7;:;"."] each 10$'x }

/ ---- writedown ------------------------------------------------------------

.rt.writeSplay:{[tname;t]
  d:.Q.dd[.rt.root;tname];
  t:.Q.en[.rt.root;t];
  {[d;t;c] (.Q.dd[d;c]) set t c}[d;t;] each cols t;
  (.Q.dd[d;`.d]) set cols t;
  -1 "[retail] ",string[tname]," splay: ",string[count t]," rows"; }

.rt.writePart:{[tname;dt;t]
  if[`date in cols t; t:delete date from t];
  t:`signalId xasc t;
  if[`signalId in cols t; t:update `p#signalId from t];
  tdir:.Q.dd[.Q.dd[.rt.root; `$string dt]; tname];
  t:.Q.en[.rt.root;t];
  {[tdir;t;c] (.Q.dd[tdir;c]) set t c}[tdir;t;] each cols t;
  (.Q.dd[tdir;`.d]) set cols t; }

.rt.writePartitioned:{[tname;t;partCol]
  if[0=count t; -1 "[retail] ",string[tname],": no rows"; :()];
  pv:t partCol;
  parts:asc distinct pv where not null pv;
  {[tname;t;pv;dt] .rt.writePart[tname;dt; t where pv=dt] }[tname;t;pv;] each parts;
  -1 "[retail] ",string[tname],": ",string[count t]," rows over ",string[count parts]," partitions"; }

/ ensure every partition dir carries a splay for tname (empty one if absent)
.rt.backfill:{[tname;emptyT]
  root:.rt.root;
  dates:{x where x like "[12][0-9][0-9][0-9].[0-9][0-9].[0-9][0-9]"} string key root;
  {[tname;emptyT;root;d]
    if[not tname in key .Q.dd[root;`$d];
      .rt.writePart[tname; "D"$d; emptyT] ] }[tname;emptyT;root;] each dates; }

/ ---- per-table processing -----------------------------------------------

.rt.doSig:{
  t:.rt.readSafe["signals.csv"; .rt.cSig; "JJSSSSS**SS"];
  if[0=count t; -1 "[retail] sig: no rows"; :()];
  t:update firstSeen:.rt.pTs firstSeen, lastSeen:.rt.pTs lastSeen from t;
  .rt.writeSplay[`sig; t] }

.rt.doMonthly:{
  t:.rt.readSafe["monthly.csv"; .rt.cMonthly; "JJJFF"];
  if[0=count t; -1 "[retail] monthly: no rows"; :()];
  .rt.writeSplay[`monthly; t] }

.rt.doGrowth:{
  t:.rt.readSafe["growth.csv"; .rt.cGrowth; "J*F"];
  if[0=count t; -1 "[retail] growth: no rows"; :()];
  t:update date:.rt.pDate date from t;
  t:delete from t where (null date)|date<.rt.minDate;
  .rt.writePartitioned[`growth; t; `date] }

.rt.doEquity:{
  t:.rt.readSafe["equity.csv"; .rt.cEquity; "J*FF"];
  if[0=count t; -1 "[retail] equity: no rows"; :()];
  t:update ts:.rt.pTs ts from t;
  t:update date:`date$ts from t;
  t:delete from t where (null date)|date<.rt.minDate;
  .rt.writePartitioned[`equity; t; `date] }

.rt.doTrade:{
  t:.rt.readTradesDir[.rt.csv,"/trades"; .rt.cTrade; "SJSSSS**FFFFFFFFJS*"];
  if[0=count t; -1 "[retail] trade: no rows"; :()];
  t:update openTime:.rt.pTs openTime, closeTime:.rt.pTs closeTime, collectedAt:.rt.pTs collectedAt from t;
  t:update pd:`date$closeTime from t;
  t:update pd:`date$openTime from t where null pd;
  t:update date:pd from t;
  t:delete pd from t;
  t:delete from t where (null date)|date<.rt.minDate;    / no usable timestamp -> cannot partition
  .rt.writePartitioned[`trade; t; `date] }

/ ---- run --------------------------------------------------------------

.rt.doSig[]
.rt.doMonthly[]
.rt.doGrowth[]
.rt.doEquity[]
.rt.doTrade[]
.rt.backfill[`growth; growth]
.rt.backfill[`equity; equity]
.rt.backfill[`trade; trade]
-1 "[retail] done. Load with:  q -> \\l ",.rt.hdb;
exit 0
