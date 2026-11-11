//+------------------------------------------------------------------+
//|                                   InstitutionalPlaybook_MT5.mq5  |
//|        Liquidity sweep -> structure shift -> FVG retest strategy |
//+------------------------------------------------------------------+
// Rule-based version of the "Institutional Trading Playbook" process:
//   1. Context   - higher-timeframe bias from swing structure (HH+HL / LH+LL)
//   2. Liquidity - previous day/week extremes and untaken swing highs/lows (BSL/SSL, EQH/EQL)
//   3. Setup     - sweep / swing failure: wick through liquidity, close back inside
//   4. Entry     - market structure shift (CHoCH) in the bias direction, limit at the FVG it leaves
//   5. Risk      - stop beyond the sweep extreme, lot sized from a fixed % of balance
//   6. Target    - next opposing liquidity that pays at least the minimum R:R
//   7. Manage    - partial close and break-even at a set R multiple
// Attach to the execution timeframe (e.g. M5/M15); bias is read from InpBiasTF.
#property copyright "Institutional Playbook EA"
#property version   "1.00"
#property description "Trades liquidity sweeps that shift structure in the higher-timeframe direction."
#property description "Entry on the fair value gap retest, stop beyond the sweep, target at opposing liquidity."

#include <Trade\Trade.mqh>

enum ENUM_ENTRY_MODE
{
   Entry_FVGLimit = 0,   // Limit order at the fair value gap
   Entry_Market   = 1    // Market order on the structure shift
};

//--- General
input group "=== General ==="
input long              InpMagicNumber        = 777092;        // Magic number
input bool              InpAutoTrading        = true;          // Enable trading
input bool              InpShowDashboard      = true;          // Show status on chart

//--- Context
input group "=== 1. Context (HTF bias) ==="
input ENUM_TIMEFRAMES   InpBiasTF             = PERIOD_H4;     // Bias timeframe
input int               InpBiasSwingLen       = 3;             // Bias swing strength (bars each side)
input int               InpBiasBars           = 300;           // Bias bars to scan
input bool              InpUsePremiumDiscount = false;         // Longs only in discount, shorts only in premium

//--- Liquidity
input group "=== 2. Liquidity ==="
input int               InpSwingLen           = 3;             // Swing strength on chart timeframe
input int               InpLiquidityLookback  = 100;           // Bars to scan for swing liquidity
input bool              InpUsePrevDayWeek     = true;          // Use previous day/week high and low

//--- Setup and entry
input group "=== 3-4. Setup & Entry ==="
input int               InpSetupExpiryBars    = 12;            // Bars allowed from sweep to structure shift
input ENUM_ENTRY_MODE   InpEntryMode          = Entry_FVGLimit;// Entry mode
input double            InpFVGFill            = 0.5;           // Entry depth into the FVG (0=edge, 1=full)
input int               InpOrderExpiryBars    = 10;            // Cancel unfilled limit after N bars
input int               InpMaxSpreadPoints    = 0;             // Max spread in points (0=off)

//--- Risk and target
input group "=== 5-6. Risk & Target ==="
input double            InpRiskPercent        = 0.5;           // Risk per trade, % of balance (0=fixed lot)
input double            InpFixedLot           = 0.01;          // Fixed lot when risk % is 0
input double            InpSLBufferATR        = 0.1;           // Stop buffer beyond the sweep (x ATR)
input int               InpATRPeriod          = 14;            // ATR period
input double            InpMinRR              = 2.0;           // Minimum reward:risk
input bool              InpTargetLiquidity    = true;          // Target the next opposing liquidity
input double            InpFixedRR            = 3.0;           // Reward:risk when no liquidity target

//--- Management
input group "=== 7. Management ==="
input double            InpBreakEvenAtR       = 1.0;           // Move stop to entry at this R (0=off)
input double            InpPartialPercent     = 50.0;          // % of position closed at that point (0=off)
input int               InpBEOffsetPoints     = 0;             // Break-even offset in points

//--- Limits and filters
input group "=== Limits & Filters ==="
input int               InpMaxTradesPerDay    = 2;             // Max trades per day (0=off)
input double            InpDailyLossPercent   = 2.0;           // Stop for the day at this loss % (0=off)
input bool              InpUseTradingHours    = false;         // Restrict trading hours
input int               InpStartHour          = 7;             // Start hour (server time)
input int               InpEndHour            = 20;            // End hour (server time)
input bool              InpAvoidNews          = true;          // Skip entries around high-impact news
input int               InpNewsMinutesBefore  = 30;            // Minutes before news
input int               InpNewsMinutesAfter   = 30;            // Minutes after news

struct SSetup
{
   bool     active;
   int      dir;          // 1 = long, -1 = short
   double   level;        // liquidity level that was swept
   double   extreme;      // furthest price reached by the sweep
   double   mssLevel;     // close beyond this confirms the structure shift
   datetime sweepTime;
   int      barsLeft;
};

CTrade   g_trade;
SSetup   g_setup;
int      g_atrHandle = INVALID_HANDLE;
string   g_status    = "";

//+------------------------------------------------------------------+
int OnInit()
{
   if(InpSwingLen < 1 || InpBiasSwingLen < 1 || InpLiquidityLookback < 4 * InpSwingLen + 5 ||
      InpMinRR <= 0 || InpFixedRR <= 0 || InpFVGFill < 0 || InpFVGFill > 1)
   {
      Print("ERROR: Invalid input parameters!");
      return(INIT_PARAMETERS_INCORRECT);
   }

   g_trade.SetExpertMagicNumber(InpMagicNumber);
   g_trade.SetDeviationInPoints(20);
   g_trade.SetTypeFilling(GetFillingMode());

   g_atrHandle = iATR(_Symbol, PERIOD_CURRENT, InpATRPeriod);
   if(g_atrHandle == INVALID_HANDLE)
   {
      Print("ERROR: Failed to create ATR indicator handle!");
      return(INIT_FAILED);
   }

   ResetSetup();
   return(INIT_SUCCEEDED);
}

//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   if(g_atrHandle != INVALID_HANDLE) IndicatorRelease(g_atrHandle);
   Comment("");
}

//+------------------------------------------------------------------+
void OnTick()
{
   ManagePositions();

   if(!IsNewBar()) return;

   CancelExpiredOrders();

   MqlRates r[];
   ArraySetAsSeries(r, true);
   int need = InpLiquidityLookback + InpSwingLen + 5;
   if(CopyRates(_Symbol, PERIOD_CURRENT, 0, need, r) < need) return;

   double atrBuf[];
   if(CopyBuffer(g_atrHandle, 0, 1, 1, atrBuf) < 1) return;

   double equilibrium = 0;
   int bias = GetBias(equilibrium);

   ProcessSetup(r, bias, equilibrium, atrBuf[0]);

   if(InpShowDashboard) UpdateDashboard(bias);
}

//+------------------------------------------------------------------+
//| Setup state machine: sweep -> structure shift -> order           |
//+------------------------------------------------------------------+
void ProcessSetup(const MqlRates &r[], int bias, double equilibrium, double atr)
{
   if(g_setup.active)
   {
      int d = g_setup.dir;
      if(bias != d)
         ResetSetup();
      else
      {
         if(d > 0 && r[1].low < g_setup.extreme)  g_setup.extreme = r[1].low;
         if(d < 0 && r[1].high > g_setup.extreme) g_setup.extreme = r[1].high;

         bool shifted = (d > 0) ? (r[1].close > g_setup.mssLevel) : (r[1].close < g_setup.mssLevel);
         if(shifted)
         {
            TryEnter(r, atr);
            ResetSetup();
         }
         else if(--g_setup.barsLeft <= 0)
            ResetSetup();
         return;
      }
   }

   if(bias == 0 || !EntryAllowed()) return;

   if(InpUsePremiumDiscount)
   {
      double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
      if((bias > 0 && bid > equilibrium) || (bias < 0 && bid < equilibrium))
      {
         g_status = "Wrong side of equilibrium";
         return;
      }
   }

   double level = 0;
   if(!FindSweep(r, bias, level)) return;

   double mss = FindMssLevel(r, bias);
   if(mss == 0) return;

   g_setup.active    = true;
   g_setup.dir       = bias;
   g_setup.level     = level;
   g_setup.extreme   = (bias > 0) ? r[1].low : r[1].high;
   g_setup.mssLevel  = mss;
   g_setup.sweepTime = r[1].time;
   g_setup.barsLeft  = InpSetupExpiryBars;
   PrintFormat("%s liquidity swept at %s, waiting for close beyond %s",
               (bias > 0) ? "Sell-side" : "Buy-side",
               DoubleToString(level, _Digits), DoubleToString(mss, _Digits));
}

void ResetSetup()
{
   g_setup.active    = false;
   g_setup.dir       = 0;
   g_setup.level     = 0;
   g_setup.extreme   = 0;
   g_setup.mssLevel  = 0;
   g_setup.sweepTime = 0;
   g_setup.barsLeft  = 0;
}

//+------------------------------------------------------------------+
//| Higher-timeframe bias from the last two swing highs and lows     |
//+------------------------------------------------------------------+
int GetBias(double &equilibrium)
{
   MqlRates h[];
   ArraySetAsSeries(h, true);
   int n = CopyRates(_Symbol, InpBiasTF, 0, InpBiasBars, h);
   if(n < 4 * InpBiasSwingLen + 10) return 0;

   double sh[2], sl[2];
   int nh = 0, nl = 0;
   for(int i = InpBiasSwingLen + 1; i < n - InpBiasSwingLen && (nh < 2 || nl < 2); i++)
   {
      if(nh < 2 && IsSwing(h, i, InpBiasSwingLen, true))  sh[nh++] = h[i].high;
      if(nl < 2 && IsSwing(h, i, InpBiasSwingLen, false)) sl[nl++] = h[i].low;
   }
   if(nh < 2 || nl < 2) return 0;

   equilibrium = (sh[0] + sl[0]) / 2.0;
   if(sh[0] > sh[1] && sl[0] > sl[1]) return 1;
   if(sh[0] < sh[1] && sl[0] < sl[1]) return -1;
   return 0;
}

//+------------------------------------------------------------------+
//| Fractal swing on closed bars of a series array                   |
//+------------------------------------------------------------------+
bool IsSwing(const MqlRates &r[], int i, int len, bool high)
{
   int n = ArraySize(r);
   if(i - len < 1 || i + len >= n) return false;
   for(int j = 1; j <= len; j++)
   {
      if(high)
      {
         if(r[i - j].high >= r[i].high || r[i + j].high > r[i].high) return false;
      }
      else
      {
         if(r[i - j].low <= r[i].low || r[i + j].low < r[i].low) return false;
      }
   }
   return true;
}

bool IsSweepOf(const MqlRates &r[], int d, double level)
{
   if(level <= 0) return false;
   if(d > 0) return (r[1].low < level && r[1].close > level);
   return (r[1].high > level && r[1].close < level);
}

//+------------------------------------------------------------------+
//| Did the last closed bar sweep liquidity against the bias?        |
//| Longs need sell-side liquidity taken, shorts buy-side.           |
//+------------------------------------------------------------------+
bool FindSweep(const MqlRates &r[], int d, double &level)
{
   if(InpUsePrevDayWeek)
   {
      double pd = (d > 0) ? iLow(_Symbol, PERIOD_D1, 1) : iHigh(_Symbol, PERIOD_D1, 1);
      double pw = (d > 0) ? iLow(_Symbol, PERIOD_W1, 1) : iHigh(_Symbol, PERIOD_W1, 1);
      if(IsSweepOf(r, d, pd)) { level = pd; return true; }
      if(IsSweepOf(r, d, pw)) { level = pw; return true; }
   }

   // Swing levels count only while no later bar has already traded through them
   int maxI = MathMin(InpLiquidityLookback, ArraySize(r) - InpSwingLen - 1);
   double run = (d > 0) ? DBL_MAX : -DBL_MAX;
   for(int i = 2; i <= maxI; i++)
   {
      double p = (d > 0) ? r[i].low : r[i].high;
      bool untaken = (d > 0) ? (p <= run) : (p >= run);
      if(untaken && IsSwing(r, i, InpSwingLen, d < 0) && IsSweepOf(r, d, p))
      {
         level = p;
         return true;
      }
      run = (d > 0) ? MathMin(run, p) : MathMax(run, p);
   }
   return false;
}

//+------------------------------------------------------------------+
//| Most recent opposing swing the market must close beyond          |
//+------------------------------------------------------------------+
double FindMssLevel(const MqlRates &r[], int d)
{
   int maxI = MathMin(InpLiquidityLookback, ArraySize(r) - InpSwingLen - 1);
   for(int i = InpSwingLen + 1; i <= maxI; i++)
   {
      if(!IsSwing(r, i, InpSwingLen, d > 0)) continue;
      double p = (d > 0) ? r[i].high : r[i].low;
      if((d > 0) ? (p > r[1].close) : (p < r[1].close)) return p;
   }
   return 0;
}

//+------------------------------------------------------------------+
//| Newest fair value gap formed since the sweep                     |
//| nearEdge is the side price reaches first on the retrace.         |
//+------------------------------------------------------------------+
bool FindFVG(const MqlRates &r[], int d, int sweepShift, double &nearEdge, double &farEdge)
{
   int maxK = MathMin(sweepShift - 1, ArraySize(r) - 3);
   for(int k = 1; k <= maxK; k++)
   {
      if(d > 0 && r[k].low > r[k + 2].high)
      {
         nearEdge = r[k].low;
         farEdge  = r[k + 2].high;
         return true;
      }
      if(d < 0 && r[k].high < r[k + 2].low)
      {
         nearEdge = r[k].high;
         farEdge  = r[k + 2].low;
         return true;
      }
   }
   return false;
}

void ConsiderTarget(double p, int d, double minTarget, double &best)
{
   if(p <= 0) return;
   if(d > 0 && p >= minTarget && (best == 0 || p < best)) best = p;
   if(d < 0 && p <= minTarget && (best == 0 || p > best)) best = p;
}

//+------------------------------------------------------------------+
//| Nearest untaken opposing liquidity at or beyond the minimum R:R  |
//+------------------------------------------------------------------+
double FindTarget(const MqlRates &r[], int d, double minTarget)
{
   double best = 0;

   if(InpUsePrevDayWeek)
   {
      if(d > 0)
      {
         double pdh = iHigh(_Symbol, PERIOD_D1, 1), pwh = iHigh(_Symbol, PERIOD_W1, 1);
         if(iHigh(_Symbol, PERIOD_D1, 0) < pdh) ConsiderTarget(pdh, d, minTarget, best);
         if(iHigh(_Symbol, PERIOD_W1, 0) < pwh) ConsiderTarget(pwh, d, minTarget, best);
      }
      else
      {
         double pdl = iLow(_Symbol, PERIOD_D1, 1), pwl = iLow(_Symbol, PERIOD_W1, 1);
         if(iLow(_Symbol, PERIOD_D1, 0) > pdl) ConsiderTarget(pdl, d, minTarget, best);
         if(iLow(_Symbol, PERIOD_W1, 0) > pwl) ConsiderTarget(pwl, d, minTarget, best);
      }
   }

   int maxI = MathMin(InpLiquidityLookback, ArraySize(r) - InpSwingLen - 1);
   double run = (d > 0) ? -DBL_MAX : DBL_MAX;
   for(int i = 1; i <= maxI; i++)
   {
      double p = (d > 0) ? r[i].high : r[i].low;
      bool untaken = (d > 0) ? (p >= run) : (p <= run);
      if(untaken && IsSwing(r, i, InpSwingLen, d > 0)) ConsiderTarget(p, d, minTarget, best);
      run = (d > 0) ? MathMax(run, p) : MathMin(run, p);
   }
   return best;
}

//+------------------------------------------------------------------+
//| Build and send the order once structure has shifted              |
//+------------------------------------------------------------------+
void TryEnter(const MqlRates &r[], double atr)
{
   if(!EntryAllowed()) return;

   int    d   = g_setup.dir;
   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double mkt = (d > 0) ? ask : bid;

   double entry = mkt;
   if(InpEntryMode == Entry_FVGLimit)
   {
      int sweepShift = iBarShift(_Symbol, PERIOD_CURRENT, g_setup.sweepTime);
      double nearEdge = 0, farEdge = 0;
      if(sweepShift < 2 || !FindFVG(r, d, sweepShift, nearEdge, farEdge))
      {
         Print("Structure shifted without a fair value gap - setup skipped");
         return;
      }
      entry = nearEdge + (farEdge - nearEdge) * InpFVGFill;
   }

   // Price already at or through the entry: take it at market
   bool market = (InpEntryMode == Entry_Market) || (d > 0 ? mkt <= entry : mkt >= entry);
   if(market) entry = mkt;

   double sl = g_setup.extreme - d * atr * InpSLBufferATR;
   if(d < 0) sl += (ask - bid);   // short stops trigger on the ask

   double risk     = (entry - sl) * d;
   double minStop  = (double)SymbolInfoInteger(_Symbol, SYMBOL_TRADE_STOPS_LEVEL) * _Point;
   if(risk <= 0 || risk < minStop)
   {
      Print("Stop distance invalid or inside broker stop level - setup skipped");
      return;
   }

   double minTarget = entry + d * InpMinRR * risk;
   double tp = InpTargetLiquidity ? FindTarget(r, d, minTarget) : 0;
   if(tp == 0) tp = entry + d * MathMax(InpFixedRR, InpMinRR) * risk;

   entry = NormPrice(entry);
   sl    = NormPrice(sl);
   tp    = NormPrice(tp);

   double lots = CalculateLotSize(d, entry, sl);
   if(lots <= 0)
   {
      Print("Risk budget too small for the minimum lot - setup skipped");
      return;
   }

   string comment = (d > 0) ? "IPB sweep long" : "IPB sweep short";
   bool sent;
   if(market)
      sent = (d > 0) ? g_trade.Buy(lots, _Symbol, 0, sl, tp, comment)
                     : g_trade.Sell(lots, _Symbol, 0, sl, tp, comment);
   else
      sent = (d > 0) ? g_trade.BuyLimit(lots, entry, _Symbol, sl, tp, ORDER_TIME_GTC, 0, comment)
                     : g_trade.SellLimit(lots, entry, _Symbol, sl, tp, ORDER_TIME_GTC, 0, comment);

   if(!sent)
      PrintFormat("Order failed: %d %s", g_trade.ResultRetcode(), g_trade.ResultRetcodeDescription());
}

//+------------------------------------------------------------------+
double CalculateLotSize(int d, double entry, double sl)
{
   double minLot  = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double maxLot  = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
   double lotStep = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   if(lotStep <= 0) return 0;

   double lot = InpFixedLot;
   if(InpRiskPercent > 0)
   {
      double lossPerLot = 0;
      ENUM_ORDER_TYPE type = (d > 0) ? ORDER_TYPE_BUY : ORDER_TYPE_SELL;
      if(!OrderCalcProfit(type, _Symbol, 1.0, entry, sl, lossPerLot) || lossPerLot >= 0) return 0;
      lot = AccountInfoDouble(ACCOUNT_BALANCE) * InpRiskPercent / 100.0 / (-lossPerLot);
   }

   lot = MathFloor(lot / lotStep + 1e-9) * lotStep;
   // Never round up past the risk budget
   if(lot < minLot) return 0;
   return NormalizeDouble(MathMin(lot, maxLot), 2);
}

double NormPrice(double price)
{
   double tick = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
   if(tick <= 0) return NormalizeDouble(price, _Digits);
   return NormalizeDouble(MathRound(price / tick) * tick, _Digits);
}

//+------------------------------------------------------------------+
//| Break-even and partial close once the trade reaches the R trigger|
//+------------------------------------------------------------------+
void ManagePositions()
{
   if(InpBreakEvenAtR <= 0) return;

   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0) continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol) continue;
      if(PositionGetInteger(POSITION_MAGIC) != InpMagicNumber) continue;

      int    d    = (PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY) ? 1 : -1;
      double open = PositionGetDouble(POSITION_PRICE_OPEN);
      double sl   = PositionGetDouble(POSITION_SL);
      double tp   = PositionGetDouble(POSITION_TP);
      double vol  = PositionGetDouble(POSITION_VOLUME);

      // A stop at or beyond entry means this step has already run
      double risk = (open - sl) * d;
      if(sl == 0 || risk <= 0) continue;

      double price = (d > 0) ? SymbolInfoDouble(_Symbol, SYMBOL_BID) : SymbolInfoDouble(_Symbol, SYMBOL_ASK);
      if((price - open) * d < InpBreakEvenAtR * risk) continue;

      double newSL = NormPrice(open + d * InpBEOffsetPoints * _Point);
      if(!g_trade.PositionModify(ticket, newSL, tp) || g_trade.ResultRetcode() != TRADE_RETCODE_DONE) continue;

      if(InpPartialPercent > 0)
      {
         double minLot   = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
         double lotStep  = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
         double closeVol = (lotStep > 0) ? MathFloor(vol * InpPartialPercent / 100.0 / lotStep + 1e-9) * lotStep : 0;
         closeVol = NormalizeDouble(closeVol, 2);
         if(closeVol >= minLot && vol - closeVol >= minLot - 1e-9)
            g_trade.PositionClosePartial(ticket, closeVol);
      }
   }
}

//+------------------------------------------------------------------+
void CancelExpiredOrders()
{
   if(InpOrderExpiryBars <= 0) return;
   long maxAge = (long)InpOrderExpiryBars * PeriodSeconds();

   for(int i = OrdersTotal() - 1; i >= 0; i--)
   {
      ulong ticket = OrderGetTicket(i);
      if(ticket == 0) continue;
      if(OrderGetString(ORDER_SYMBOL) != _Symbol) continue;
      if(OrderGetInteger(ORDER_MAGIC) != InpMagicNumber) continue;
      if((long)TimeCurrent() - OrderGetInteger(ORDER_TIME_SETUP) >= maxAge)
         g_trade.OrderDelete(ticket);
   }
}

//+------------------------------------------------------------------+
//| Execution checklist gates for opening new risk                   |
//+------------------------------------------------------------------+
bool EntryAllowed()
{
   if(!InpAutoTrading)       { g_status = "Trading disabled";      return false; }
   if(HasExposure())         { g_status = "In a trade";            return false; }
   if(!IsTradingHours())     { g_status = "Outside trading hours"; return false; }
   if(IsNewsWindow())        { g_status = "News window";           return false; }

   if(InpMaxSpreadPoints > 0 && SymbolInfoInteger(_Symbol, SYMBOL_SPREAD) > InpMaxSpreadPoints)
   {
      g_status = "Spread too wide";
      return false;
   }

   int trades = 0;
   double pnl = 0;
   GetDailyStats(trades, pnl);
   if(InpMaxTradesPerDay > 0 && trades >= InpMaxTradesPerDay)
   {
      g_status = "Daily trade limit reached";
      return false;
   }
   if(InpDailyLossPercent > 0 && pnl <= -AccountInfoDouble(ACCOUNT_BALANCE) * InpDailyLossPercent / 100.0)
   {
      g_status = "Daily loss limit reached";
      return false;
   }

   g_status = "Scanning";
   return true;
}

bool HasExposure()
{
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      if(PositionGetTicket(i) == 0) continue;
      if(PositionGetString(POSITION_SYMBOL) == _Symbol && PositionGetInteger(POSITION_MAGIC) == InpMagicNumber)
         return true;
   }
   for(int i = OrdersTotal() - 1; i >= 0; i--)
   {
      if(OrderGetTicket(i) == 0) continue;
      if(OrderGetString(ORDER_SYMBOL) == _Symbol && OrderGetInteger(ORDER_MAGIC) == InpMagicNumber)
         return true;
   }
   return false;
}

void GetDailyStats(int &trades, double &pnl)
{
   trades = 0;
   pnl = 0;
   datetime dayStart = iTime(_Symbol, PERIOD_D1, 0);
   if(!HistorySelect(dayStart, TimeCurrent() + 60)) return;

   for(int i = HistoryDealsTotal() - 1; i >= 0; i--)
   {
      ulong deal = HistoryDealGetTicket(i);
      if(deal == 0) continue;
      if(HistoryDealGetString(deal, DEAL_SYMBOL) != _Symbol) continue;
      if(HistoryDealGetInteger(deal, DEAL_MAGIC) != InpMagicNumber) continue;
      if(HistoryDealGetInteger(deal, DEAL_ENTRY) == DEAL_ENTRY_IN) trades++;
      pnl += HistoryDealGetDouble(deal, DEAL_PROFIT) + HistoryDealGetDouble(deal, DEAL_SWAP) +
             HistoryDealGetDouble(deal, DEAL_COMMISSION);
   }
}

bool IsTradingHours()
{
   if(!InpUseTradingHours) return true;
   MqlDateTime dt;
   TimeToStruct(TimeCurrent(), dt);
   if(InpStartHour <= InpEndHour) return (dt.hour >= InpStartHour && dt.hour < InpEndHour);
   return (dt.hour >= InpStartHour || dt.hour < InpEndHour);
}

//+------------------------------------------------------------------+
//| High-impact calendar events for either currency of the symbol.   |
//| The economic calendar is not available in the strategy tester.   |
//+------------------------------------------------------------------+
bool IsNewsWindow()
{
   if(!InpAvoidNews || MQLInfoInteger(MQL_TESTER)) return false;

   string currencies[2];
   currencies[0] = SymbolInfoString(_Symbol, SYMBOL_CURRENCY_BASE);
   currencies[1] = SymbolInfoString(_Symbol, SYMBOL_CURRENCY_PROFIT);

   // Window is mirrored: an event N minutes ahead is "before", one N minutes ago is "after"
   datetime now  = TimeTradeServer();
   datetime from = now - InpNewsMinutesAfter * 60;
   datetime to   = now + InpNewsMinutesBefore * 60;

   for(int c = 0; c < 2; c++)
   {
      MqlCalendarValue values[];
      CalendarValueHistory(values, from, to, NULL, currencies[c]);
      for(int i = 0; i < ArraySize(values); i++)
      {
         MqlCalendarEvent ev;
         if(CalendarEventById(values[i].event_id, ev) && ev.importance == CALENDAR_IMPORTANCE_HIGH)
            return true;
      }
   }
   return false;
}

bool IsNewBar()
{
   static datetime lastBar = 0;
   datetime current = iTime(_Symbol, PERIOD_CURRENT, 0);
   if(current == 0 || current == lastBar) return false;
   lastBar = current;
   return true;
}

ENUM_ORDER_TYPE_FILLING GetFillingMode()
{
   uint filling = (uint)SymbolInfoInteger(_Symbol, SYMBOL_FILLING_MODE);
   if((filling & SYMBOL_FILLING_FOK) == SYMBOL_FILLING_FOK) return ORDER_FILLING_FOK;
   if((filling & SYMBOL_FILLING_IOC) == SYMBOL_FILLING_IOC) return ORDER_FILLING_IOC;
   return ORDER_FILLING_RETURN;
}

void UpdateDashboard(int bias)
{
   string biasText = (bias > 0) ? "Bullish" : (bias < 0) ? "Bearish" : "Neutral (no trades)";
   string setupText = "None";
   if(g_setup.active)
      setupText = StringFormat("%s sweep of %s, needs close %s %s (%d bars left)",
                               (g_setup.dir > 0) ? "Long:" : "Short:",
                               DoubleToString(g_setup.level, _Digits),
                               (g_setup.dir > 0) ? "above" : "below",
                               DoubleToString(g_setup.mssLevel, _Digits), g_setup.barsLeft);

   Comment("Institutional Playbook v1.0\n",
           "Bias (", EnumToString(InpBiasTF), "): ", biasText, "\n",
           "Setup: ", setupText, "\n",
           "Status: ", g_status);
}
//+------------------------------------------------------------------+
