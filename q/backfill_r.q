/ ============================================================
/ mqlScraper - patch C:/data/r so every known partitioned table has an
/ (empty, if needed) splay in every date directory. Pure additive on-disk
/ patch: never overwrites a partition that already has real data for a
/ table, only seeds a 0-row splay where one is genuinely missing.
/ -
/ Works PURELY off raw file paths - no \l, no tables[], no functional
/ select - because \l only auto-registers a table if it happens to live
/ in the single OVERALL newest date directory across the whole root, and
/ with 8 partitioned tables spanning different date ranges from two
/ independent pipelines, most of them never land there. Reading a sample
/ partition's `.d` file + per-column `get` sidesteps that entirely.
/ -
/   q q/backfill_r.q -out C:/data/r
/ ============================================================

.bf.args:.Q.opt .z.x
.bf.out:$[count .bf.args`out; first .bf.args`out; "C:/data/r"]
.bf.root:hsym `$.bf.out

.bf.dates:{x where x like "[12][0-9][0-9][0-9].[0-9][0-9].[0-9][0-9]"} string key .bf.root;
-1 "[backfill] ",string[count .bf.dates]," date partitions";

/ every partitioned table this root is known to carry (splays sig_mql/
/ sig_myfxbook live at root, not per-date, so excluded here)
.bf.knownTables:`equity_mql`equity_myfxbook`growth_mql`growth_myfxbook`snap_mql`snap_myfxbook`trade_mql`trade_myfxbook;

.bf.tableDir:{[d;tname] .Q.dd[.Q.dd[.bf.root;`$d];tname] }

.bf.hasTable:{[d;tname]
  tdir:.bf.tableDir[d;tname];
  (not ()~key tdir) and `.d in key tdir }

/ build a 0-row template purely from one real on-disk partition: read `.d`
/ for column order, `get` each column file directly (a plain vector read,
/ not a partitioned-select), take 0# of each.
.bf.emptyFrom:{[d;tname]
  tdir:.bf.tableDir[d;tname];
  cs:get .Q.dd[tdir;`.d];
  cols2vals:{[tdir;c] 0#get .Q.dd[tdir;c]}[tdir;] each cs;
  cs!cols2vals }

.bf.writePart:{[tname;dt;t]
  tdir:.Q.dd[.Q.dd[.bf.root; `$string dt]; tname];
  {[tdir;t;c] (.Q.dd[tdir;c]) set t c}[tdir;t;] each key t;
  (.Q.dd[tdir;`.d]) set key t; }

.bf.doTable:{[tname]
  existing:.bf.dates where .bf.hasTable[;tname] each .bf.dates;
  if[0=count existing; -1 "[backfill] ",string[tname],": no existing partition, skipping"; :()];
  emptyT:.bf.emptyFrom[first existing;tname];
  n:0;
  {[tname;emptyT;d]
    if[not .bf.hasTable[d;tname];
      .bf.writePart[tname; "D"$d; emptyT];
      n+:1 ] }[tname;emptyT;] each .bf.dates;
  -1 "[backfill] ",string[tname],": checked ",string[count .bf.dates]," dates, seeded ",string n; }

.bf.doTable each .bf.knownTables;

-1 "[backfill] done.";
exit 0
