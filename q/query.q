/ ============================================================
/ mqlScraper - convenience queries over the HDB
/ -
/   q q/query.q -hdb data/hdb         / prints a few summaries
/   q -> \l data/hdb -> \l q/query.q  / interactive: use .mq.* helpers
/ ============================================================

.mq.hdb:$[count a:.Q.opt[.z.x]`hdb; first a; "data/hdb"]
if[not `snap in tables[]; system "l ",.mq.hdb]

/ latest headline snapshot per signal
.mq.latest:{[] `growthPct xdesc 0!select by signalId from `ts xasc select from snap }

/ leaderboard: latest headline numbers joined to the registry
.mq.leaderboard:{[n]
  l:.mq.latest[];
  r:`signalId xkey select signalId,name,authorLogin,accountType from sig;
  n sublist `growthPct xdesc r lj `signalId xkey
    select signalId,ts,growthPct,monthlyGrowthPct,drawdownMaxPct,profitFactor,subscribers,weeks,balanceUsd from l }

/ balance / equity curve for one signal
.mq.curve:{[sid] `ts xasc select ts,balance,equity from equity where signalId=sid }

/ weekly growth curve for one signal
.mq.growth:{[sid] `date xasc select date,growthPct from growth where signalId=sid }

/ monthly returns for one signal (year/month grid)
.mq.monthly:{[sid] `year`month xasc select year,month,returnPct,yearlyPct from monthly where signalId=sid }

/ latest per-symbol trade distribution for one signal
.mq.bySymbol:{[sid]
  t:select from symdist where signalId=sid;
  if[0=count t; :t];
  t:select from t where ts=max ts;
  `deals xdesc select symbol,deals,buyTrades,sellTrades from t }

/ closed-trade blotter for one signal (executed deals only; excludes cancelled orders & balance ops)
.mq.blotter:{[sid]
  `closeTime xasc select openTime,closeTime,orderType,symbol,volume,openPrice,closePrice,sl,tp,swap,commission,profit
    from trade where signalId=sid, kind=`trade, not cancelled }

/ per-symbol P/L for one signal, from the trade history
.mq.tradeBySymbol:{[sid]
  `netProfit xdesc select deals:count i, netProfit:sum profit, winPct:100*avg profit>0,
    avgVol:avg volume, grossSwap:sum swap by symbol
    from trade where signalId=sid, kind=`trade, not cancelled }

/ headline trade metrics for one signal from the raw history
.mq.tradeStats:{[sid]
  t:select from trade where signalId=sid, kind=`trade, not cancelled;
  d:select from trade where signalId=sid, kind=`balance;
  `deals`wins`losses`winPct`netProfit`grossProfit`grossLoss`bestTrade`worstTrade`deposits`withdrawals!
   (count t; sum t`profit>0; sum t`profit<0; 100*avg t`profit>0; sum t`profit;
    sum(t`profit) where t[`profit]>0; sum(t`profit) where t[`profit]<0; max t`profit; min t`profit;
    sum(d`profit) where d[`action]=`deposit; sum(d`profit) where d[`action]=`withdrawal) }

/ per-brokerage aggregate: signals grouped by their trade-server's broker company
.mq.byBroker:{[]
  s:select signalId,broker,accountType,mtVersion from sig where not null broker, broker<>`;
  g:`signalId xkey select signalId,growthPct,subscribers from .mq.latest[];
  j:s lj g;
  `signals xdesc select signals:count i, realAccts:sum accountType=`Real,
    mt4:sum mtVersion=4, mt5:sum mtVersion=5,
    avgGrowth:avg growthPct, medGrowth:med growthPct, subs:sum subscribers
    by broker from j }

/ per-broker (signal account server) aggregate of the latest snapshots
.mq.byServer:{[]
  `signals xdesc select signals:count i, avgGrowth:avg growthPct, avgDrawdown:avg drawdownMaxPct,
    medProfitFactor:med profitFactor, subs:sum subscribers by server from .mq.latest[] }

.mq.summary:{
  -1 "tables: ",", " sv string tables[];
  -1 "\n== leaderboard (top 10 by latest growth) ==";
  show .mq.leaderboard 10;
  -1 "\n== by account server (top rows) ==";
  show 10 sublist .mq.byServer[];
  }

if[not count getenv `MQ_QUIET; .mq.summary[]]
if[.z.f like "*query.q"; exit 0]
