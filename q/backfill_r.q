/ ============================================================
/ mqlScraper - patch C:/data/r so every registered partitioned table has an
/ (empty, if needed) splay in every date directory. Pure additive on-disk
/ patch: never overwrites a partition that already has real data for a
/ table, only seeds a 0-row splay where one is genuinely missing. Needed
/ whenever one side (mql or myfxbook) adds new date partitions the other
/ side's tables were never backfilled into.
/ -
/   q q/backfill_r.q -out C:/data/r
/ ============================================================

.bf.args:.Q.opt .z.x
.bf.out:$[count .bf.args`out; first .bf.args`out; "C:/data/r"]
.bf.root:hsym `$.bf.out

system "l ",.bf.out;
-1 "[backfill] tables currently registered: ",", " sv string tables[];

.bf.dates:{x where x like "[12][0-9][0-9][0-9].[0-9][0-9].[0-9][0-9]"} string key .bf.root;
-1 "[backfill] ",string[count .bf.dates]," date partitions";

.bf.writePart:{[tname;dt;t]
  if[`date in cols t; t:delete date from t];
  tdir:.Q.dd[.Q.dd[.bf.root; `$string dt]; tname];
  {[tdir;t;c] (.Q.dd[tdir;c]) set t c}[tdir;t;] each cols t;
  (.Q.dd[tdir;`.d]) set cols t; }

.bf.doTable:{[tname]
  existing:.bf.dates where {[root;tname;d] tname in key .Q.dd[root;`$d]}[.bf.root;tname;] each .bf.dates;
  if[0=count existing; -1 "[backfill] ",string[tname],": no existing partition, skipping"; :()];
  sampleDate:"D"$first existing;
  / 0#tname alone raises 'par on a partitioned table on this build - go through
  / a partition-pruned functional select first (real table, no par restriction)
  emptyT:0#?[tname; enlist(=;`date;sampleDate); 0b; ()];
  {[tname;emptyT;d]
    if[not tname in key .Q.dd[.bf.root;`$d];
      .bf.writePart[tname; "D"$d; emptyT] ] }[tname;emptyT;] each .bf.dates;
  -1 "[backfill] ",string[tname],": checked ",string[count .bf.dates]," dates"; }

/ every table `tables[]` found EXCEPT the two root splays (sig_mql/sig_myfxbook,
/ not date-partitioned at all)
.bf.targets:tables[] except `sig_mql`sig_myfxbook;
.bf.doTable each .bf.targets;

-1 "[backfill] done.";
exit 0
