/ ============================================================
/ mqlScraper - unioned `equity`/`growth`/`trade` at C:/data/r, combining the
/ _mql and _myfxbook tables already there. Adds `platform` (`mql`/`fxbook`)
/ and a common `acctId` (signalId or systemId renamed) so both sides can be
/ queried together in one go; every other column keeps its native name and
/ is `uj`-ed, so a column only one platform has is simply null on the other
/ side - nothing is dropped, this sits ALONGSIDE the _mql/_myfxbook tables,
/ doesn't replace them.
/ -
/   q q/union.q -root C:/data/r
/ ============================================================

.un.args:.Q.opt .z.x
.un.rootPath:$[count .un.args`root; first .un.args`root; "C:/data/r"]
.un.root:hsym `$.un.rootPath

system "l ",.un.rootPath;
-1 "[union] root=",.un.rootPath;

/ some tables at this shared root (built by another process) are still
/ .Q.en-enumerated (type 20h) even though they display resolved - de-enum
/ explicitly before writing plain, same reasoning as compose.q.
.un.deenum:{[t] {[t;c] $[20h=type t c; @[t;c;value]; t]}/[t;cols t] }

.un.writePart:{[tname;dt;t]
  if[`date in cols t; t:delete date from t];
  tdir:.Q.dd[.Q.dd[.un.root; `$string dt]; tname];
  {[tdir;t;c] (.Q.dd[tdir;c]) set t c}[tdir;t;] each cols t;
  (.Q.dd[tdir;`.d]) set cols t; }

.un.writePartitioned:{[tname;t;partCol]
  if[0=count t; -1 "[union] ",string[tname],": no rows"; :()];
  pv:t partCol;
  parts:asc distinct pv where not null pv;
  {[tname;t;pv;dt] .un.writePart[tname;dt; t where pv=dt] }[tname;t;pv;] each parts;
  -1 "[union] ",string[tname],": ",string[count t]," rows over ",string[count parts]," partitions"; }

/ \l only registers a table from the overall newest partition - backfill an
/ empty splay for these 3 new tables into every existing date dir so a plain
/ \l always finds them (same pattern as compose.q / backfill_r.q).
.un.backfill:{[tname;t]
  emptyT:.un.deenum 0#t;
  dates:{x where x like "[12][0-9][0-9][0-9].[0-9][0-9].[0-9][0-9]"} string key .un.root;
  {[root;tname;emptyT;d]
    if[not tname in key .Q.dd[root;`$d];
      .un.writePart[tname; "D"$d; emptyT] ] }[.un.root;tname;emptyT;] each dates; }

/ ---- equity -----------------------------------------------------------

em:.un.deenum select date,platform:`mql,acctId:signalId,ts,balance,equity from equity_mql;
ef:.un.deenum select date,platform:`fxbook,acctId:systemId,ts:`timestamp$date,balance,equity from equity_myfxbook;
eq:em uj ef;
.un.writePartitioned[`equity; eq; `date];
.un.backfill[`equity; eq];

/ ---- growth -----------------------------------------------------------

gm:.un.deenum select date,platform:`mql,acctId:signalId,growthPct from growth_mql;
gf:.un.deenum select date,platform:`fxbook,acctId:systemId,growthPct from growth_myfxbook;
gr:gm uj gf;
.un.writePartitioned[`growth; gr; `date];
.un.backfill[`growth; gr];

/ ---- trade --------------------------------------------------------------

tm:.un.deenum select date,platform:`mql,acctId:signalId,tradeKey,kind,action,orderType,
  symbol,openTime,closeTime,openPrice,closePrice,sl,tp,volume,commission,swap,profit,
  cancelled,comment,collectedAt from trade_mql;
tf:.un.deenum select date,platform:`fxbook,acctId:systemId,tradeKey,action,symbol,
  openTime,closeTime,openPrice,closePrice,sl,tp,volume:lots,commission,swap,profit,
  username,systemName,ticket,pips,gainPct,durationSec,collectedAt from trade_myfxbook;
tr:tm uj tf;
.un.writePartitioned[`trade; tr; `date];
.un.backfill[`trade; tr];

-1 "[union] done. Load with:  q -> \\l ",.un.rootPath;
exit 0
