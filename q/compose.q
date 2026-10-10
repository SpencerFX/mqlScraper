/ ============================================================
/ mqlScraper - side-by-side platform tables at one root: <table>_mql /
/ <table>_myfxbook. Native per-platform columns are kept as-is (no forced
/ renaming across platforms - systemId stays systemId, signalId stays
/ signalId) so nothing is lost; this just puts both platforms' registry /
/ snapshot / growth / equity / trade tables under one HDB for side-by-side
/ querying.
/ -
/   q q/compose.q -out C:/data/r -mql C:/data/retail
/       -mqlFull C:/Users/giant/Downloads/Work/Git/mqlScraper/data/hdb
/       -fx C:/data/retail_myfxbook
/ -
/ kdb+ can't hold two same-named partitioned tables (both platforms use
/ `trade`/`snap`/...) live in one session, so the three source HDBs are
/ `\l`-ed one at a time, each one's tables immediately re-persisted under
/ their new suffixed name before the next `\l` overwrites the globals.
/ myfxbook has no native weekly-growth or per-event-equity feed (its own
/ collector only pulls a daily balance/equity chart) - growth_myfxbook is
/ a weekly resample of that, equity_myfxbook is the daily series reshaped
/ to (date,systemId,ts,balance,equity); both are clearly coarser than the
/ mql side and that's a genuine source limitation, not a shortcut here.
/ ============================================================

.cp.args:.Q.opt .z.x
.cp.out:$[count .cp.args`out; first .cp.args`out; "C:/data/r"]
.cp.mql:$[count .cp.args`mql; first .cp.args`mql; "C:/data/retail"]
.cp.mqlFull:$[count .cp.args`mqlFull; first .cp.args`mqlFull; "data/hdb"]
.cp.fx:$[count .cp.args`fx; first .cp.args`fx; "C:/data/retail_myfxbook"]
.cp.only:`$($[count .cp.args`only; first .cp.args`only; "both"])   / `mql, `myfxbook, or `both
.cp.root:hsym `$.cp.out

-1 "[compose] out=",.cp.out;

/ ---- writedown (per-column set + .d; symbol columns written PLAIN, not -----
/ ---- via .Q.en - this script alternates \l across three unrelated source ---
/ ---- hdbs, and .Q.en's shared-domain caching does not survive that; a ------
/ ---- plain (non-enumerated) symbol vector sidesteps the problem entirely --

/ `select` on an already-.Q.en-enumerated column keeps it type 20h (enum) -
/ it LOOKS resolved on display but is still bound to the source root's `sym`
/ domain. De-enumerate explicitly (value = the real de-enumerate primitive)
/ before writing plain, since this script has no single shared domain.
.cp.deenum:{[t] {[t;c] $[20h=type t c; @[t;c;value]; t]}/[t;cols t] }

.cp.writeSplay:{[tname;t]
  t:.cp.deenum t;
  d:.Q.dd[.cp.root;tname];
  {[d;t;c] (.Q.dd[d;c]) set t c}[d;t;] each cols t;
  (.Q.dd[d;`.d]) set cols t;
  -1 "[compose] ",string[tname]," splay: ",string[count t]," rows"; }

.cp.writePart:{[tname;dt;t]
  if[`date in cols t; t:delete date from t];
  t:.cp.deenum t;
  tdir:.Q.dd[.Q.dd[.cp.root; `$string dt]; tname];
  {[tdir;t;c] (.Q.dd[tdir;c]) set t c}[tdir;t;] each cols t;
  (.Q.dd[tdir;`.d]) set cols t; }

.cp.writePartitioned:{[tname;t;partCol]
  .cp.empty[tname]:.cp.deenum 0#t;     / empty typed template, for the backfill pass below
  if[0=count t; -1 "[compose] ",string[tname],": no rows"; :()];
  pv:t partCol;
  parts:asc distinct pv where not null pv;
  {[tname;t;pv;dt] .cp.writePart[tname;dt; t where pv=dt] }[tname;t;pv;] each parts;
  -1 "[compose] ",string[tname],": ",string[count t]," rows over ",string[count parts]," partitions"; }

.cp.empty:(`symbol$())!()    / tname -> empty template, filled in by writePartitioned as it goes

/ \l only registers a table found in the OVERALL newest partition dir - with
/ 7 partitioned tables spanning different date ranges sharing one root, most
/ would never get auto-discovered without this. Backfill an empty splay for
/ every partitioned table into every date dir that doesn't already have one.
.cp.backfill:{[]
  root:.cp.root;
  dates:{x where x like "[12][0-9][0-9][0-9].[0-9][0-9].[0-9][0-9]"} string key root;
  {[root;dates;tname]
    emptyT:.cp.empty tname;
    {[root;tname;emptyT;d]
      if[not tname in key .Q.dd[root;`$d];
        .cp.writePart[tname; "D"$d; emptyT] ] }[root;tname;emptyT;] each dates;
  }[root;dates;] each key .cp.empty; }

/ ---- step 1: mql retail (sig/growth/equity/trade) --------------------------

if[.cp.only in `mql`both;
  system "l ",.cp.mql;
  .cp.writeSplay[`sig_mql; select from sig];
  .cp.writePartitioned[`growth_mql; select from growth; `date];
  .cp.writePartitioned[`equity_mql; select from equity; `date];
  .cp.writePartitioned[`trade_mql; select from trade; `date];

  / ---- step 2: mql full hdb (has snap - retail.q deliberately excludes it) --
  system "l ",.cp.mqlFull;
  .cp.writePartitioned[`snap_mql; select from snap where date>2000.01.01; `date];
  ];

/ ---- step 3: myfxbook retail (sys/snap/daily/trade) ------------------------

if[.cp.only in `myfxbook`both;
  system "l ",.cp.fx;
  .cp.writeSplay[`sig_myfxbook; select from sys];
  .cp.writePartitioned[`snap_myfxbook; select from snap; `date];
  .cp.writePartitioned[`trade_myfxbook; select from trade; `date];

  / growth_myfxbook: weekly-resampled gain (myfxbook has no native weekly series)
  g:select from daily;
  ep:"i"$g`date;
  g:update week:`date$ep-ep mod 7 from g;
  gw:0!select growthPct:last gain by week,systemId from g;
  gw:`date`systemId`growthPct xcols update date:week from gw;
  .cp.writePartitioned[`growth_myfxbook; gw; `date];

  / equity_myfxbook: daily is the finest granularity myfxbook exposes (its own
  / collector only pulls chartType=1, a day-resolution feed) - reshaped to the
  / same (date,systemId,ts,balance,equity) column shape as equity_mql.
  e:select date,systemId,ts:`timestamp$date,balance,equity from daily;
  .cp.writePartitioned[`equity_myfxbook; e; `date];
  ];

/ ---- backfill so \l's newest-partition scan discovers every table ---------

.cp.backfill[];

-1 "[compose] done. Load with:  q -> \\l ",.cp.out;
exit 0
