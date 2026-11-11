//+------------------------------------------------------------------+
//| GoldDipM1.mq5 - long-only M1 dip buyer with M15 trend filter     |
//+------------------------------------------------------------------+
#property version   "1.02"
#property strict

input double          InpRiskPercent     = 0.25;       // Risk per trade, % of equity
input double          InpMaxRiskPercent  = 1.0;        // Max risk % when forced to minimum lot (0 = never use min lot)
input int             InpRSIPeriod       = 2;          // M1 RSI period
input double          InpRSIBuyLevel     = 5.0;        // Buy when RSI closes below
input ENUM_TIMEFRAMES InpTrendTF         = PERIOD_M15; // Trend timeframe
input int             InpFastEMA         = 50;
input int             InpSlowEMA         = 200;
input int             InpATRPeriod       = 14;
input double          InpSLATR           = 1.5;        // Stop, ATR multiples
input double          InpTPATR           = 1.5;        // Target, ATR multiples
input double          InpMaxSpreadSLPct  = 30.0;       // Skip entries when spread exceeds this % of stop distance (0 = off)
input int             InpMaxSpreadPoints = 0;          // Skip entries above this spread in points (0 = off)
input int             InpStartHour       = 7;          // Server time
input int             InpEndHour         = 20;         // Server time
input double          InpDailyLossPct    = 2.0;        // Stop for the day after this loss
input int             InpMaxTradesPerDay = 20;
input ulong           InpMagic           = 20261111;

int      hRSI, hATR, hFast, hSlow;
datetime g_lastBar = 0;
int      g_day = -1, g_tradesToday = 0;
double   g_dayStartEquity = 0;

// Why bars were skipped, reported in the Journal when the test ends
enum ENUM_SKIP { SK_HOURS, SK_MAXTRADES, SK_DAILYLOSS, SK_NODATA, SK_TREND, SK_RSI,
                 SK_SPREAD, SK_STOPLEVEL, SK_LOT, SK_ORDERFAIL, SK_COUNT };
string   g_skipName[SK_COUNT] = { "outside trading hours", "max trades per day", "daily loss limit",
                                  "indicator data not ready", "trend filter (fast EMA <= slow EMA)",
                                  "RSI not below buy level", "spread too wide", "stop inside broker stop level",
                                  "lot below minimum for risk budget", "order rejected" };
long     g_skip[SK_COUNT];
long     g_bars = 0, g_signals = 0, g_orders = 0;

void Skip(ENUM_SKIP reason, string detail = "")
{
   // Log the first occurrence with numbers so the cause is visible in the Journal
   if(g_skip[reason] == 0 && detail != "")
      Print("GoldDipM1 first skip - ", g_skipName[reason], ": ", detail);
   g_skip[reason]++;
}

int OnInit()
{
   hRSI  = iRSI(_Symbol, PERIOD_M1, InpRSIPeriod, PRICE_CLOSE);
   hATR  = iATR(_Symbol, PERIOD_M1, InpATRPeriod);
   hFast = iMA(_Symbol, InpTrendTF, InpFastEMA, 0, MODE_EMA, PRICE_CLOSE);
   hSlow = iMA(_Symbol, InpTrendTF, InpSlowEMA, 0, MODE_EMA, PRICE_CLOSE);
   if(hRSI == INVALID_HANDLE || hATR == INVALID_HANDLE || hFast == INVALID_HANDLE || hSlow == INVALID_HANDLE)
      return INIT_FAILED;
   ArrayInitialize(g_skip, 0);
   return INIT_SUCCEEDED;
}

void OnDeinit(const int reason)
{
   IndicatorRelease(hRSI); IndicatorRelease(hATR);
   IndicatorRelease(hFast); IndicatorRelease(hSlow);

   PrintFormat("GoldDipM1 summary: %I64d M1 bars checked, %I64d signals, %I64d orders placed", g_bars, g_signals, g_orders);
   for(int i = 0; i < SK_COUNT; i++)
      if(g_skip[i] > 0)
         PrintFormat("  skipped %I64d x %s", g_skip[i], g_skipName[i]);
}

bool HasPosition()
{
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket > 0 && PositionGetString(POSITION_SYMBOL) == _Symbol &&
         (ulong)PositionGetInteger(POSITION_MAGIC) == InpMagic)
         return true;
   }
   return false;
}

// Value of closed bar 1 from an indicator handle
bool Closed(int handle, double &value)
{
   double buf[1];
   if(CopyBuffer(handle, 0, 1, 1, buf) != 1) return false;
   value = buf[0];
   return true;
}

double LotForRisk(double slDistance, string &detail)
{
   double tickSize  = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
   double tickValue = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE);
   double step      = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   double minLot    = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double maxLot    = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
   if(tickSize <= 0 || tickValue <= 0 || step <= 0 || slDistance <= 0)
   {
      detail = "symbol tick/volume data unavailable";
      return 0;
   }
   double equity     = AccountInfoDouble(ACCOUNT_EQUITY);
   double lossPerLot = slDistance / tickSize * tickValue;
   double lot = MathFloor(equity * InpRiskPercent / 100.0 / lossPerLot / step) * step;
   if(lot < minLot)
   {
      // Fall back to the minimum lot only while its risk stays under the hard cap
      double minLotRiskPct = minLot * lossPerLot / equity * 100.0;
      if(minLotRiskPct > InpMaxRiskPercent)
      {
         detail = StringFormat("minimum lot %.2f would risk %.2f%% of equity %.2f (cap %.2f%%)",
                               minLot, minLotRiskPct, equity, InpMaxRiskPercent);
         return 0;
      }
      lot = minLot;
   }
   return NormalizeDouble(MathMin(lot, maxLot), 2);
}

// Sends the market buy directly so the EA does not depend on the standard Trade library
bool SendBuy(double lot, double sl, double tp, uint &retcode, string &retText)
{
   MqlTradeRequest req;
   MqlTradeResult  res;
   ZeroMemory(req);
   ZeroMemory(res);
   long filling = SymbolInfoInteger(_Symbol, SYMBOL_FILLING_MODE);
   req.action       = TRADE_ACTION_DEAL;
   req.symbol       = _Symbol;
   req.type         = ORDER_TYPE_BUY;
   req.volume       = lot;
   req.price        = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   req.sl           = sl;
   req.tp           = tp;
   req.deviation    = 20;
   req.magic        = InpMagic;
   req.comment      = "GoldDipM1";
   req.type_filling = (filling & SYMBOL_FILLING_FOK) != 0 ? ORDER_FILLING_FOK :
                      (filling & SYMBOL_FILLING_IOC) != 0 ? ORDER_FILLING_IOC : ORDER_FILLING_RETURN;
   bool sent = OrderSend(req, res);
   retcode = res.retcode;
   retText = res.comment;
   return sent && (res.retcode == TRADE_RETCODE_DONE || res.retcode == TRADE_RETCODE_PLACED);
}

void OnTick()
{
   datetime barTime = iTime(_Symbol, PERIOD_M1, 0);
   if(barTime == g_lastBar) return;   // act once per new M1 bar
   g_lastBar = barTime;

   MqlDateTime t;
   TimeToStruct(TimeCurrent(), t);
   if(t.day_of_year != g_day)
   {
      g_day = t.day_of_year;
      g_tradesToday = 0;
      g_dayStartEquity = AccountInfoDouble(ACCOUNT_EQUITY);
   }

   if(HasPosition()) return;
   g_bars++;
   if(t.hour < InpStartHour || t.hour >= InpEndHour) { Skip(SK_HOURS); return; }
   if(g_tradesToday >= InpMaxTradesPerDay) { Skip(SK_MAXTRADES); return; }
   if(AccountInfoDouble(ACCOUNT_EQUITY) <= g_dayStartEquity * (1.0 - InpDailyLossPct / 100.0)) { Skip(SK_DAILYLOSS); return; }

   double rsi, atr, fast, slow;
   if(!Closed(hRSI, rsi) || !Closed(hATR, atr) || !Closed(hFast, fast) || !Closed(hSlow, slow) || atr <= 0)
   {
      Skip(SK_NODATA, StringFormat("error %d - the %s EMA %d needs enough history before the test start date",
                                   GetLastError(), EnumToString(InpTrendTF), InpSlowEMA));
      return;
   }
   if(fast <= slow) { Skip(SK_TREND); return; }
   if(rsi >= InpRSIBuyLevel) { Skip(SK_RSI); return; }
   g_signals++;

   double ask     = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double bid     = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double spread  = ask - bid;
   double slDist  = InpSLATR * atr;
   double tpDist  = InpTPATR * atr;

   // Spread is judged against the stop size so the filter works for 2- and 3-digit gold alike
   if((InpMaxSpreadSLPct > 0 && spread > slDist * InpMaxSpreadSLPct / 100.0) ||
      (InpMaxSpreadPoints > 0 && spread > InpMaxSpreadPoints * _Point))
   {
      Skip(SK_SPREAD, StringFormat("spread %.0f points (%.1f%% of the %.0f point stop)",
                                   spread / _Point, spread / slDist * 100.0, slDist / _Point));
      return;
   }

   // A buy closes at the bid, so the broker measures stop distance from the bid
   double minDist = (double)SymbolInfoInteger(_Symbol, SYMBOL_TRADE_STOPS_LEVEL) * _Point;
   if(slDist - spread < minDist || tpDist + spread < minDist)
   {
      Skip(SK_STOPLEVEL, StringFormat("stop %.0f points, spread %.0f, broker minimum %.0f",
                                      slDist / _Point, spread / _Point, minDist / _Point));
      return;
   }

   string detail = "";
   double lot = LotForRisk(slDist, detail);
   if(lot <= 0) { Skip(SK_LOT, detail); return; }

   double sl = NormalizeDouble(ask - slDist, _Digits);
   double tp = NormalizeDouble(ask + tpDist, _Digits);
   uint   retcode = 0;
   string retText = "";
   if(SendBuy(lot, sl, tp, retcode, retText))
   {
      g_tradesToday++;
      g_orders++;
   }
   else
      Skip(SK_ORDERFAIL, StringFormat("retcode %u %s, error %d", retcode, retText, GetLastError()));
}
//+------------------------------------------------------------------+
