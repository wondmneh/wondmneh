//+------------------------------------------------------------------+
//|                                       BurstBasketScalper_MT5.mq5 |
//| Behavioural reconstruction from a screen recording of a running  |
//| account. Not the original source: entry trigger and thresholds   |
//| are estimates. Extremely high risk - test on demo only.          |
//+------------------------------------------------------------------+
#property version   "1.00"
#property strict

#include <Trade/Trade.mqh>

input group "=== General ==="
input long   InpMagic            = 880021;  // Magic number
input int    InpSlippagePoints   = 50;      // Max deviation (points)

input group "=== Entry ==="
input int    InpTriggerPoints    = 300;     // Move vs previous M1 close that starts a basket (points)
input int    InpMaxSpreadPoints  = 400;     // Skip entries above this spread (points)
input int    InpBurstCount       = 3;       // Orders sent per burst (same price, same lot)
input int    InpBurstIntervalSec = 5;       // Seconds between bursts
input int    InpMaxPositions     = 30;      // Positions per basket

input group "=== Sizing ==="
input double InpMarginUsePct     = 95.0;    // % of free margin the full basket may consume
input double InpMaxLot           = 5.0;     // Per-position lot cap

input group "=== Basket exit ==="
input double InpBasketTPPct      = 30.0;    // Close all at +% of basket start balance
input double InpBasketSLPct      = 60.0;    // Close all at -% of basket start balance (0 = off)
input int    InpCooldownSec      = 10;      // Pause after a basket closes

CTrade   trade;
int      g_dir          = 0;   // +1 buy basket, -1 sell basket, 0 flat
double   g_lot          = 0.0; // fixed for the whole basket
double   g_startBalance = 0.0;
datetime g_lastBurst    = 0;
datetime g_lastClose    = 0;

//+------------------------------------------------------------------+
int OnInit()
  {
   if(InpBurstCount < 1 || InpMaxPositions < 1 || InpMarginUsePct <= 0 || InpMarginUsePct > 100)
      return INIT_PARAMETERS_INCORRECT;

   trade.SetExpertMagicNumber(InpMagic);
   trade.SetDeviationInPoints(InpSlippagePoints);
   trade.SetTypeFillingBySymbol(_Symbol);
   return INIT_SUCCEEDED;
  }

//+------------------------------------------------------------------+
//| Count our positions; returns floating P/L and basket direction   |
//+------------------------------------------------------------------+
int ScanBasket(double &profit, int &dir)
  {
   int count = 0;
   profit = 0.0;
   dir = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0 || PositionGetString(POSITION_SYMBOL) != _Symbol ||
         PositionGetInteger(POSITION_MAGIC) != InpMagic)
         continue;
      count++;
      profit += PositionGetDouble(POSITION_PROFIT) + PositionGetDouble(POSITION_SWAP);
      dir = (PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY) ? 1 : -1;
     }
   return count;
  }

//+------------------------------------------------------------------+
void CloseBasket()
  {
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0 || PositionGetString(POSITION_SYMBOL) != _Symbol ||
         PositionGetInteger(POSITION_MAGIC) != InpMagic)
         continue;
      if(!trade.PositionClose(ticket))
         Print("Close failed #", ticket, ": ", trade.ResultRetcodeDescription());
     }
   g_lastClose = TimeCurrent();
  }

//+------------------------------------------------------------------+
//| Momentum trigger: distance of price from the previous M1 close   |
//+------------------------------------------------------------------+
int GetSignal()
  {
   double prevClose = iClose(_Symbol, PERIOD_M1, 1);
   if(prevClose <= 0)
      return 0;
   double move = (SymbolInfoDouble(_Symbol, SYMBOL_BID) - prevClose) / _Point;
   if(move >= InpTriggerPoints)
      return 1;
   if(move <= -InpTriggerPoints)
      return -1;
   return 0;
  }

//+------------------------------------------------------------------+
//| Split the margin budget evenly across the planned basket         |
//+------------------------------------------------------------------+
double CalcBasketLot(int dir)
  {
   ENUM_ORDER_TYPE type = (dir > 0) ? ORDER_TYPE_BUY : ORDER_TYPE_SELL;
   double price = SymbolInfoDouble(_Symbol, dir > 0 ? SYMBOL_ASK : SYMBOL_BID);
   double marginPerLot = 0.0;
   if(!OrderCalcMargin(type, _Symbol, 1.0, price, marginPerLot) || marginPerLot <= 0)
      return 0.0;

   double budget = AccountInfoDouble(ACCOUNT_MARGIN_FREE) * InpMarginUsePct / 100.0;
   double lot    = budget / InpMaxPositions / marginPerLot;

   double step   = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   double minLot = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double maxLot = MathMin(SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX), InpMaxLot);
   lot = MathFloor(lot / step) * step;
   lot = MathMax(minLot, MathMin(maxLot, lot));
   return NormalizeDouble(lot, 2);
  }

//+------------------------------------------------------------------+
void SendBurst(int count)
  {
   ENUM_ORDER_TYPE type = (g_dir > 0) ? ORDER_TYPE_BUY : ORDER_TYPE_SELL;
   for(int n = 0; n < InpBurstCount && count + n < InpMaxPositions; n++)
     {
      double price = SymbolInfoDouble(_Symbol, g_dir > 0 ? SYMBOL_ASK : SYMBOL_BID);
      double need = 0.0;
      if(!OrderCalcMargin(type, _Symbol, g_lot, price, need) ||
         need > AccountInfoDouble(ACCOUNT_MARGIN_FREE))
         break;
      bool ok = (g_dir > 0) ? trade.Buy(g_lot, _Symbol, 0.0, 0.0, 0.0, "burst")
                            : trade.Sell(g_lot, _Symbol, 0.0, 0.0, 0.0, "burst");
      if(!ok)
        {
         Print("Order failed: ", trade.ResultRetcodeDescription());
         break;
        }
     }
   g_lastBurst = TimeCurrent();
  }

//+------------------------------------------------------------------+
void OnTick()
  {
   double profit;
   int    dir;
   int    count = ScanBasket(profit, dir);

   if(count > 0)
     {
      // Re-adopt a basket left open by a restart
      if(g_dir == 0)
        {
         g_dir = dir;
         g_startBalance = AccountInfoDouble(ACCOUNT_BALANCE);
         g_lot = CalcBasketLot(dir);
        }
      double tp = g_startBalance * InpBasketTPPct / 100.0;
      double sl = g_startBalance * InpBasketSLPct / 100.0;
      if(profit >= tp || (InpBasketSLPct > 0 && profit <= -sl))
        {
         CloseBasket();
         g_dir = 0;
         return;
        }
     }
   else
      g_dir = 0;

   if(TimeCurrent() - g_lastClose < InpCooldownSec)
      return;
   if(SymbolInfoInteger(_Symbol, SYMBOL_SPREAD) > InpMaxSpreadPoints)
      return;

   if(g_dir == 0)
     {
      int signal = GetSignal();
      if(signal == 0)
         return;
      double lot = CalcBasketLot(signal);
      if(lot <= 0)
         return;
      g_dir = signal;
      g_lot = lot;
      g_startBalance = AccountInfoDouble(ACCOUNT_BALANCE);
      g_lastBurst = 0;
     }

   if(count < InpMaxPositions && TimeCurrent() - g_lastBurst >= InpBurstIntervalSec)
      SendBurst(count);
  }
//+------------------------------------------------------------------+
