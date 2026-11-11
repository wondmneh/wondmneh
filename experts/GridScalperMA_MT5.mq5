//+------------------------------------------------------------------+
//|                                           GridScalperMA_MT5.mq5  |
//|                        Grid Scalper MA - Fixed Edition v2.2      |
//|                                                                  |
//+------------------------------------------------------------------+
#property copyright "Grid Scalper MA"
#property link      ""
#property version   "2.20"
#property description "Grid Scalper with Moving Average filter"
#property description "Fixed: MA filter no longer blocks grid entries"
#property description "Fixed: Dynamic ORDER_FILLING detection"
#property description "Fixed: Reliable grid level detection"
#property description "Fixed: Independent Buy/Sell grid tracking"
#property description "Added: Hard Equity protection and Trailing Basket TP"
#property description "Fixed: Risk controls run on every tick, even when entries are blocked"
#property strict

#include <Trade\Trade.mqh>

//--- Enums
enum ENUM_MA_MODE
{
   MA_Disabled = 0,      // Disabled
   MA_Price_Cross = 1,   // Price Crosses MA
   MA_Slope_Filter = 2,  // MA Slope Filter (bias only)
   MA_Trend_Follow = 3   // MA Trend Follow
};

enum ENUM_LOT_MODE
{
   Lot_Fixed = 0,        // Fixed Lot
   Lot_RiskPercent = 1,  // Risk % of Balance
   Lot_Compound = 2      // Compound Growth
};

enum ENUM_GRID_FROM
{
   Grid_From_CurrentPrice = 0,  // From Current Price
   Grid_From_LastOrder = 1      // From Last Order Price
};

//--- Input Groups
input group "=== Main Settings ==="
input ulong    InpMagicNumber      = 777007;      // Magic Number
input bool     InpAutoTrading      = true;         // Enable Auto Trading
input int      InpMaxOpenOrders    = 20;           // Max Open Orders (total)
input string   InpComment          = "GridScalper"; // Order Comment
input ENUM_GRID_FROM InpGridFrom   = Grid_From_LastOrder; // Grid Reference

input group "=== Grid Settings ==="
input double   InpGridSize         = 10.0;         // Grid Step Size (points)
input bool     InpUseATRGridSize   = false;        // Use ATR-Based Grid Size
input int      InpATRPeriod        = 14;           // ATR Period
input double   InpATRMultiplier    = 1.0;          // ATR Multiplier

input group "=== Lot Size ==="
input ENUM_LOT_MODE InpLotMode     = Lot_Fixed;    // Lot Mode
input double   InpFixedLot         = 0.01;         // Fixed Lot Size
input double   InpRiskPercent      = 1.0;          // Risk Percent
input double   InpLotMultiplier    = 1.5;          // Compound Lot Multiplier
input int      InpMaxMultiplierSteps = 10;         // Max Multiplier Steps
input double   InpMaxLot           = 10.0;         // Maximum Lot Size

input group "=== MA Filter ==="
input ENUM_MA_MODE InpMAMode       = MA_Slope_Filter; // MA Mode
input int      InpFastMA           = 50;           // Fast MA Period
input int      InpSlowMA           = 200;          // Slow MA Period
input ENUM_MA_METHOD InpMAMethod   = MODE_SMA;     // MA Method
input ENUM_APPLIED_PRICE InpMAPrice = PRICE_CLOSE; // MA Applied Price

input group "=== RSI Filter ==="
input bool     InpUseRSI           = false;        // Enable RSI Filter
input int      InpRSIPeriod        = 14;           // RSI Period
input double   InpRSIOverbought    = 70.0;         // RSI Overbought Level
input double   InpRSIOversold      = 30.0;         // RSI Oversold Level

input group "=== Geometry Guard ==="
input bool     InpGeometryGuard    = true;         // Enable Geometry Guard
input int      InpMaxBuys          = 10;           // Max Buys
input int      InpMaxSells         = 10;           // Max Sells
input int      InpMaxTotal         = 15;           // Max Total Orders

input group "=== Take Profit / Stop Loss ==="
input double   InpTakeProfit       = 50.0;         // Take Profit (points)
input double   InpStopLoss         = 0.0;          // Stop Loss (points, 0=off)
input bool     InpUseBasketTP      = true;         // Use Basket TP
input double   InpBasketTP         = 20.0;         // Basket TP ($)
input double   InpBasketTrailingStart = 10.0;      // Basket Trailing Start ($)
input double   InpBasketTrailingStep  = 2.0;       // Basket Trailing Step ($)
input bool     InpUseBasketSL      = false;        // Use Basket SL
input double   InpBasketSL         = 50.0;         // Basket SL ($)
input int      InpCooldownSec      = 300;          // Cooldown After Basket Close (sec)

input group "=== Risk Management ==="
input double   InpMaxEquityRiskPercent = 20.0;     // Max Equity Risk %
input double   InpDailyProfitTarget = 0.0;         // Daily Profit Target ($, 0=off)
input double   InpDailyLossLimit   = 50.0;         // Daily Loss Limit ($, closed + open, 0=off)
input bool     InpUseTrailingStop  = false;        // Use Trailing Stop
input int      InpTrailingStart    = 15;           // Trailing Start (points)
input int      InpTrailingStep     = 5;            // Trailing Distance (points)
input bool     InpUseBreakEven     = false;        // Use Break Even
input int      InpBreakEvenStart   = 10;           // Break Even Start (points)
input int      InpBreakEvenProfit  = 3;            // Break Even Profit (points)

input group "=== Trading Hours ==="
input bool     InpUseTradingHours  = false;        // Enable Trading Hours
input int      InpStartHour        = 8;            // Start Hour (server)
input int      InpEndHour          = 20;           // End Hour (server)
input bool     InpCloseOnFriday    = false;        // Close All on Friday
input int      InpFridayCloseHour  = 21;           // Friday Close Hour (server)

input group "=== Dashboard ==="
input bool     InpShowDashboard    = true;         // Show Dashboard

input group "=== Visual Settings ==="
input bool     InpShowGridLines    = true;         // Show Grid Lines
input color    InpGridColor        = clrDodgerBlue; // Grid Line Color
input color    InpBuyColor         = clrLime;      // Buy Label Color
input color    InpSellColor        = clrRed;       // Sell Label Color
input color    InpCloseColor       = clrGold;      // Close Label Color

//--- Global Variables
CTrade g_trade;
int g_maFastHandle = INVALID_HANDLE;
int g_maSlowHandle = INVALID_HANDLE;
int g_rsiHandle    = INVALID_HANDLE;
int g_atrHandle    = INVALID_HANDLE;

double g_maFast[];
double g_maSlow[];
double g_rsi[];
double g_atr[];

datetime g_lastTradeTime = 0;
datetime g_lastBasketCloseTime = 0;
double   g_basketTrailingLevel = 0;
int g_totalTrades = 0;
int g_winTrades = 0;
double g_totalProfit = 0;

string g_dashboardName = "GridScalper_Dashboard";

//+------------------------------------------------------------------+
//| Expert initialization function                                     |
//+------------------------------------------------------------------+
int OnInit()
{
   //--- Set up trade object
   g_trade.SetExpertMagicNumber(InpMagicNumber);
   g_trade.SetDeviationInPoints(10);
   g_trade.SetTypeFilling(GetFillingMode());

   //--- Reject settings that would make the grid fire on every tick
   if(InpGridSize <= 0 || InpFixedLot <= 0)
   {
      Print("ERROR: Grid Step Size and Fixed Lot Size must be above zero.");
      return(INIT_PARAMETERS_INCORRECT);
   }
   //--- A two-sided grid needs separate buy and sell positions
   if((ENUM_ACCOUNT_MARGIN_MODE)AccountInfoInteger(ACCOUNT_MARGIN_MODE) != ACCOUNT_MARGIN_MODE_RETAIL_HEDGING)
   {
      Print("ERROR: This EA needs a hedging account. Netting accounts merge positions and break the grid.");
      return(INIT_FAILED);
   }

   //--- Create indicator handles
   g_maFastHandle = iMA(_Symbol, PERIOD_CURRENT, InpFastMA, 0, InpMAMethod, InpMAPrice);
   g_maSlowHandle = iMA(_Symbol, PERIOD_CURRENT, InpSlowMA, 0, InpMAMethod, InpMAPrice);

   if(InpUseRSI)
      g_rsiHandle = iRSI(_Symbol, PERIOD_CURRENT, InpRSIPeriod, PRICE_CLOSE);

   if(InpUseATRGridSize)
      g_atrHandle = iATR(_Symbol, PERIOD_CURRENT, InpATRPeriod);

   //--- Check handles
   if(g_maFastHandle == INVALID_HANDLE || g_maSlowHandle == INVALID_HANDLE)
   {
      Print("ERROR: Failed to create MA indicator handles!");
      return(INIT_FAILED);
   }
   if(InpUseRSI && g_rsiHandle == INVALID_HANDLE)
   {
      Print("ERROR: Failed to create RSI indicator handle!");
      return(INIT_FAILED);
   }

   if(InpUseATRGridSize && g_atrHandle == INVALID_HANDLE)
   {
      Print("ERROR: Failed to create ATR indicator handle!");
      return(INIT_FAILED);
   }

   //--- Set arrays as series
   ArraySetAsSeries(g_maFast, true);
   ArraySetAsSeries(g_maSlow, true);
   ArraySetAsSeries(g_rsi, true);
   ArraySetAsSeries(g_atr, true);

   //--- Create dashboard
   if(InpShowDashboard)
      CreateDashboard();

   //--- Draw grid lines
   if(InpShowGridLines)
      DrawGridLines();

   Print("Grid Scalper MA v2.2 initialized on ", _Symbol);

   return(INIT_SUCCEEDED);
}

//+------------------------------------------------------------------+
//| Expert deinitialization function                                   |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   if(g_maFastHandle != INVALID_HANDLE) IndicatorRelease(g_maFastHandle);
   if(g_maSlowHandle != INVALID_HANDLE) IndicatorRelease(g_maSlowHandle);
   if(g_rsiHandle != INVALID_HANDLE)    IndicatorRelease(g_rsiHandle);
   if(g_atrHandle != INVALID_HANDLE)    IndicatorRelease(g_atrHandle);

   ObjectsDeleteAll(0, g_dashboardName);
   ObjectsDeleteAll(0, "GridLine_");
   ObjectsDeleteAll(0, "GridLabel_");
   Comment("");
   Print("Grid Scalper MA removed. Reason: ", reason);
}

//+------------------------------------------------------------------+
//| Expert tick function                                               |
//+------------------------------------------------------------------+
void OnTick()
{
   if(!InpAutoTrading) return;

   //--- Protection first: it must run on every tick, even when new entries are blocked
   bool entriesAllowed = CheckDailyLimits();
   if(!CheckFridayClose()) entriesAllowed = false;
   CheckBasketTPSL();
   if(InpUseTrailingStop) ManageTrailingStop();
   if(InpUseBreakEven)    ManageBreakEven();

   static datetime lastBarTime = 0;
   datetime currentBarTime = iTime(_Symbol, PERIOD_CURRENT, 0);
   bool newBar = (currentBarTime != lastBarTime);
   if(newBar) lastBarTime = currentBarTime;

   bool buffersOk = CopyIndicatorBuffers();
   double gridStepPrice = GetGridStep() * _Point;

   int buyCount = CountPositionsByType(POSITION_TYPE_BUY);
   int sellCount = CountPositionsByType(POSITION_TYPE_SELL);
   int totalOrders = buyCount + sellCount;

   if(InpShowDashboard) UpdateDashboard(buyCount, sellCount, gridStepPrice, GetGridReferencePrice(POSITION_TYPE_BUY));
   if(InpShowGridLines && newBar) DrawGridLines();

   //--- Entry gates
   if(!entriesAllowed || !buffersOk) return;
   if(!CheckTradingHours()) return;
   if(g_lastBasketCloseTime > 0 && (int)(TimeCurrent() - g_lastBasketCloseTime) < InpCooldownSec) return;

   //--- A full side only blocks that side, not the whole grid
   int maxTotal = InpGeometryGuard ? MathMin(InpMaxOpenOrders, InpMaxTotal) : InpMaxOpenOrders;
   bool buyAllowed  = (!InpGeometryGuard || buyCount < InpMaxBuys);
   bool sellAllowed = (!InpGeometryGuard || sellCount < InpMaxSells);

   if(buyAllowed && totalOrders < maxTotal && CheckBuySignal(buyCount))
   {
      double lot = CalculateLotSize(POSITION_TYPE_BUY, buyCount);
      if(lot > 0 && OpenTrade(ORDER_TYPE_BUY, lot, InpTakeProfit, InpStopLoss)) totalOrders++;
   }

   if(sellAllowed && totalOrders < maxTotal && CheckSellSignal(sellCount))
   {
      double lot = CalculateLotSize(POSITION_TYPE_SELL, sellCount);
      if(lot > 0 && OpenTrade(ORDER_TYPE_SELL, lot, InpTakeProfit, InpStopLoss)) totalOrders++;
   }
}

//+------------------------------------------------------------------+
//| Helper functions                                                   |
//+------------------------------------------------------------------+
bool CopyIndicatorBuffers()
{
   if(CopyBuffer(g_maFastHandle, 0, 0, 3, g_maFast) < 3) return false;
   if(CopyBuffer(g_maSlowHandle, 0, 0, 3, g_maSlow) < 3) return false;
   if(InpUseRSI && CopyBuffer(g_rsiHandle, 0, 0, 3, g_rsi) < 3) return false;
   if(InpUseATRGridSize && CopyBuffer(g_atrHandle, 0, 0, 3, g_atr) < 3) return false;
   return true;
}

bool CheckBuySignal(int currentBuyCount)
{
   if(currentBuyCount == 0 && InpMAMode != MA_Disabled)
   {
      double close0 = iClose(_Symbol, PERIOD_CURRENT, 0);
      double close1 = iClose(_Symbol, PERIOD_CURRENT, 1);
      bool maBiasBullish = false;
      switch(InpMAMode)
      {
         case MA_Price_Cross: if(close1 <= g_maFast[1] && close0 > g_maFast[0]) maBiasBullish = true; break;
         case MA_Slope_Filter: if(g_maFast[0] > g_maFast[1]) maBiasBullish = true; break;
         case MA_Trend_Follow: if(g_maFast[0] > g_maSlow[0] && g_maFast[0] > g_maFast[1]) maBiasBullish = true; break;
         default: maBiasBullish = true; break;
      }
      if(!maBiasBullish) return false;
   }
   if(InpUseRSI && g_rsi[0] >= InpRSIOverbought) return false;
   if(currentBuyCount == 0) return true;
   return IsNewGridLevel(POSITION_TYPE_BUY, SymbolInfoDouble(_Symbol, SYMBOL_BID), GetGridStep() * _Point);
}

bool CheckSellSignal(int currentSellCount)
{
   if(currentSellCount == 0 && InpMAMode != MA_Disabled)
   {
      double close0 = iClose(_Symbol, PERIOD_CURRENT, 0);
      double close1 = iClose(_Symbol, PERIOD_CURRENT, 1);
      bool maBiasBearish = false;
      switch(InpMAMode)
      {
         case MA_Price_Cross: if(close1 >= g_maFast[1] && close0 < g_maFast[0]) maBiasBearish = true; break;
         case MA_Slope_Filter: if(g_maFast[0] < g_maFast[1]) maBiasBearish = true; break;
         case MA_Trend_Follow: if(g_maFast[0] < g_maSlow[0] && g_maFast[0] < g_maFast[1]) maBiasBearish = true; break;
         default: maBiasBearish = true; break;
      }
      if(!maBiasBearish) return false;
   }
   if(InpUseRSI && g_rsi[0] <= InpRSIOversold) return false;
   if(currentSellCount == 0) return true;
   return IsNewGridLevel(POSITION_TYPE_SELL, SymbolInfoDouble(_Symbol, SYMBOL_ASK), GetGridStep() * _Point);
}

bool IsNewGridLevel(ENUM_POSITION_TYPE posType, double price, double gridStepPrice)
{
   double lastPrice = GetLastPositionPrice(posType);
   if(lastPrice <= 0) return true;
   if(gridStepPrice <= 0) return false;
   return (posType == POSITION_TYPE_BUY) ? (price <= lastPrice - gridStepPrice) : (price >= lastPrice + gridStepPrice);
}

double GetGridReferencePrice(ENUM_POSITION_TYPE posType)
{
   if(InpGridFrom == Grid_From_LastOrder)
   {
      double lastPrice = GetLastPositionPrice(posType);
      if(lastPrice > 0) return lastPrice;
   }
   return (posType == POSITION_TYPE_BUY) ? SymbolInfoDouble(_Symbol, SYMBOL_BID) : SymbolInfoDouble(_Symbol, SYMBOL_ASK);
}

double GetGridStep()
{
   if(InpUseATRGridSize && ArraySize(g_atr) > 0)
   {
      double atrValue = g_atr[0];
      if(atrValue > 0) return MathMax(atrValue / _Point * InpATRMultiplier, 1.0);
   }
   return InpGridSize;
}

double CalculateLotSize(ENUM_POSITION_TYPE posType, int currentCount)
{
   double lot = 0;
   switch(InpLotMode)
   {
      case Lot_Fixed: lot = InpFixedLot; break;
      case Lot_RiskPercent:
      {
         double balance = AccountInfoDouble(ACCOUNT_BALANCE);
         double tickValue = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE);
         double tickSize = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
         double slPoints = (InpStopLoss > 0) ? InpStopLoss : GetGridStep() * 3;
         double riskMoney = balance * InpRiskPercent / 100.0;
         //--- Money lost per lot over the stop distance = points * point / tickSize * tickValue
         if(tickValue > 0 && tickSize > 0 && slPoints > 0) lot = riskMoney / (slPoints * _Point / tickSize * tickValue);
         break;
      }
      case Lot_Compound: lot = InpFixedLot * MathPow(InpLotMultiplier, MathMin(currentCount, InpMaxMultiplierSteps)); break;
   }
   double minLot = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double maxLot = MathMin(InpMaxLot, SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX));
   double lotStep = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   if(lotStep <= 0) lotStep = 0.01;
   if(lot <= 0 || maxLot < minLot) return 0;
   lot = MathMin(maxLot, lot);
   //--- Epsilon stops 0.29 / 0.01 = 28.99... from rounding down a whole step
   lot = MathFloor(lot / lotStep + 1e-9) * lotStep;
   if(lot < minLot) lot = minLot;
   int lotDigits = (int)MathMax(0.0, MathCeil(-MathLog10(lotStep) - 1e-9));
   return NormalizeDouble(lot, lotDigits);
}

//--- Broker minimum distance between price and a stop, in price units
double MinStopDistance()
{
   return (double)SymbolInfoInteger(_Symbol, SYMBOL_TRADE_STOPS_LEVEL) * _Point;
}

bool OpenTrade(ENUM_ORDER_TYPE orderType, double lot, double tpPoints, double slPoints)
{
   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double minDist = MinStopDistance();
   double price, sl = 0, tp = 0;
   if(orderType == ORDER_TYPE_BUY)
   {
      price = ask;
      if(tpPoints > 0) tp = MathMax(price + tpPoints * _Point, bid + minDist);
      if(slPoints > 0) sl = MathMin(price - slPoints * _Point, bid - minDist);
   }
   else
   {
      price = bid;
      if(tpPoints > 0) tp = MathMin(price - tpPoints * _Point, ask - minDist);
      if(slPoints > 0) sl = MathMax(price + slPoints * _Point, ask + minDist);
   }
   sl = NormalizeDouble(sl, _Digits);
   tp = NormalizeDouble(tp, _Digits);

   double margin = 0;
   if(!OrderCalcMargin(orderType, _Symbol, lot, price, margin) || margin > AccountInfoDouble(ACCOUNT_MARGIN_FREE))
   {
      static datetime lastWarn = 0;
      if(TimeCurrent() - lastWarn >= 60)
      {
         Print("Skipped entry: not enough free margin for ", DoubleToString(lot, 2), " lots.");
         lastWarn = TimeCurrent();
      }
      return false;
   }

   string comment = InpComment + "_" + IntegerToString(GetTickCount() % 10000);
   if(g_trade.PositionOpen(_Symbol, orderType, lot, price, sl, tp, comment))
   {
      g_lastTradeTime = TimeCurrent();
      g_totalTrades++;
      return true;
   }
   return false;
}

void ManageTrailingStop()
{
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      if(PositionGetSymbol(i) != _Symbol || PositionGetInteger(POSITION_MAGIC) != InpMagicNumber) continue;
      ulong ticket = PositionGetTicket(i);
      double openPrice = PositionGetDouble(POSITION_PRICE_OPEN);
      double currentSL = PositionGetDouble(POSITION_SL);
      ENUM_POSITION_TYPE posType = (ENUM_POSITION_TYPE)PositionGetInteger(POSITION_TYPE);
      if(posType == POSITION_TYPE_BUY)
      {
         double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
         if(bid - openPrice > InpTrailingStart * _Point)
         {
            double newSL = NormalizeDouble(bid - MathMax(InpTrailingStep * _Point, MinStopDistance()), _Digits);
            if(newSL > currentSL + _Point) g_trade.PositionModify(ticket, newSL, PositionGetDouble(POSITION_TP));
         }
      }
      else
      {
         double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
         if(openPrice - ask > InpTrailingStart * _Point)
         {
            double newSL = NormalizeDouble(ask + MathMax(InpTrailingStep * _Point, MinStopDistance()), _Digits);
            if(newSL < currentSL - _Point || currentSL == 0) g_trade.PositionModify(ticket, newSL, PositionGetDouble(POSITION_TP));
         }
      }
   }
}

void ManageBreakEven()
{
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      if(PositionGetSymbol(i) != _Symbol || PositionGetInteger(POSITION_MAGIC) != InpMagicNumber) continue;
      ulong ticket = PositionGetTicket(i);
      double openPrice = PositionGetDouble(POSITION_PRICE_OPEN);
      double currentSL = PositionGetDouble(POSITION_SL);
      ENUM_POSITION_TYPE posType = (ENUM_POSITION_TYPE)PositionGetInteger(POSITION_TYPE);
      if(posType == POSITION_TYPE_BUY)
      {
         double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
         if(bid - openPrice >= InpBreakEvenStart * _Point)
         {
            double newSL = NormalizeDouble(openPrice + InpBreakEvenProfit * _Point, _Digits);
            if(currentSL < newSL && bid - newSL >= MinStopDistance()) g_trade.PositionModify(ticket, newSL, PositionGetDouble(POSITION_TP));
         }
      }
      else
      {
         double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
         if(openPrice - ask >= InpBreakEvenStart * _Point)
         {
            double newSL = NormalizeDouble(openPrice - InpBreakEvenProfit * _Point, _Digits);
            if((currentSL > newSL || currentSL == 0) && newSL - ask >= MinStopDistance()) g_trade.PositionModify(ticket, newSL, PositionGetDouble(POSITION_TP));
         }
      }
   }
}

void CheckBasketTPSL()
{
   if(CountPositionsByType(POSITION_TYPE_BUY) + CountPositionsByType(POSITION_TYPE_SELL) == 0)
   {
      g_basketTrailingLevel = 0;
      return;
   }
   double totalProfit = GetTotalProfit();
   double balance = AccountInfoDouble(ACCOUNT_BALANCE);
   if(InpMaxEquityRiskPercent > 0 && balance > 0 && (-totalProfit) >= balance * InpMaxEquityRiskPercent / 100.0)
   {
      CloseAllPositions();
      g_lastBasketCloseTime = TimeCurrent();
      g_basketTrailingLevel = 0;
      return;
   }
   if(InpUseBasketTP)
   {
      //--- Once armed, the trail must fire even if profit has slipped back under the basket target
      if(g_basketTrailingLevel > 0 && totalProfit <= g_basketTrailingLevel)
      {
         CloseAllPositions();
         g_lastBasketCloseTime = TimeCurrent();
         g_basketTrailingLevel = 0;
         return;
      }
      if(totalProfit >= InpBasketTP)
      {
         if(InpBasketTrailingStep > 0 && totalProfit >= InpBasketTrailingStart)
         {
            double newTrail = totalProfit - InpBasketTrailingStep;
            if(newTrail > g_basketTrailingLevel) g_basketTrailingLevel = newTrail;
         }
         if(g_basketTrailingLevel <= 0)
         {
            CloseAllPositions();
            g_lastBasketCloseTime = TimeCurrent();
            return;
         }
      }
   }
   if(InpUseBasketSL && totalProfit <= -InpBasketSL)
   {
      CloseAllPositions();
      g_lastBasketCloseTime = TimeCurrent();
      g_basketTrailingLevel = 0;
   }
}

double GetTotalProfit()
{
   double profit = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      if(PositionGetSymbol(i) == _Symbol && PositionGetInteger(POSITION_MAGIC) == InpMagicNumber)
         profit += PositionGetDouble(POSITION_PROFIT) + PositionGetDouble(POSITION_SWAP);
   }
   return profit;
}

void CloseAllPositions()
{
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      if(PositionGetSymbol(i) == _Symbol && PositionGetInteger(POSITION_MAGIC) == InpMagicNumber)
         g_trade.PositionClose(PositionGetTicket(i));
   }
}

int CountPositionsByType(ENUM_POSITION_TYPE posType)
{
   int count = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      if(PositionGetSymbol(i) == _Symbol && PositionGetInteger(POSITION_MAGIC) == InpMagicNumber && PositionGetInteger(POSITION_TYPE) == posType)
         count++;
   }
   return count;
}

double GetLastPositionPrice(ENUM_POSITION_TYPE posType)
{
   double price = 0;
   datetime latestTime = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      if(PositionGetSymbol(i) == _Symbol && PositionGetInteger(POSITION_MAGIC) == InpMagicNumber && PositionGetInteger(POSITION_TYPE) == posType)
      {
         datetime openTime = (datetime)PositionGetInteger(POSITION_TIME);
         if(openTime > latestTime) { latestTime = openTime; price = PositionGetDouble(POSITION_PRICE_OPEN); }
      }
   }
   return price;
}

bool CheckTradingHours()
{
   if(!InpUseTradingHours) return true;
   MqlDateTime dt; TimeToStruct(TimeCurrent(), dt);
   if(InpStartHour < InpEndHour) { if(dt.hour < InpStartHour || dt.hour >= InpEndHour) return false; }
   else { if(dt.hour < InpStartHour && dt.hour >= InpEndHour) return false; }
   return true;
}

bool CheckFridayClose()
{
   if(!InpCloseOnFriday) return true;
   MqlDateTime dt; TimeToStruct(TimeCurrent(), dt);
   if(dt.day_of_week == 5 && dt.hour >= InpFridayCloseHour)
   {
      CloseAllPositions(); return false;
   }
   return true;
}

bool CheckDailyLimits()
{
   MqlDateTime dtNow, dtStart; TimeToStruct(TimeCurrent(), dtNow);
   dtStart = dtNow; dtStart.hour = 0; dtStart.min = 0; dtStart.sec = 0;
   datetime todayStart = StructToTime(dtStart);
   double dailyPnL = 0;
   HistorySelect(todayStart, TimeCurrent());
   for(int i = HistoryDealsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = HistoryDealGetTicket(i);
      if(HistoryDealGetInteger(ticket, DEAL_MAGIC) == InpMagicNumber && HistoryDealGetString(ticket, DEAL_SYMBOL) == _Symbol)
         dailyPnL += HistoryDealGetDouble(ticket, DEAL_PROFIT) + HistoryDealGetDouble(ticket, DEAL_SWAP) + HistoryDealGetDouble(ticket, DEAL_COMMISSION);
   }
   //--- Open losses count too, otherwise the limit only triggers after the damage is done
   dailyPnL += GetTotalProfit();
   if((InpDailyProfitTarget > 0 && dailyPnL >= InpDailyProfitTarget) || (InpDailyLossLimit > 0 && dailyPnL <= -InpDailyLossLimit))
   {
      CloseAllPositions(); return false;
   }
   return true;
}

ENUM_ORDER_TYPE_FILLING GetFillingMode()
{
   uint filling = (uint)SymbolInfoInteger(_Symbol, SYMBOL_FILLING_MODE);
   if((filling & SYMBOL_FILLING_FOK) == SYMBOL_FILLING_FOK) return ORDER_FILLING_FOK;
   if((filling & SYMBOL_FILLING_IOC) == SYMBOL_FILLING_IOC) return ORDER_FILLING_IOC;
   return ORDER_FILLING_RETURN;
}

void CreateDashboard()
{
   int x = 10, y = 30;
   CreateLabel(g_dashboardName + "_Header", "Grid Scalper MA v2.2", x, y, clrGold, 11);
   y += 23;
   CreateLabel(g_dashboardName + "_Buy", "Buys: 0", x, y, clrLime, 9);
   y += 18;
   CreateLabel(g_dashboardName + "_Sell", "Sells: 0", x, y, clrRed, 9);
   y += 18;
   CreateLabel(g_dashboardName + "_Profit", "P&L: $0.00", x, y, clrAqua, 9);
}

void CreateLabel(string name, string text, int x, int y, color clr, int fontSize)
{
   if(ObjectFind(0, name) < 0)
   {
      ObjectCreate(0, name, OBJ_LABEL, 0, 0, 0);
      ObjectSetInteger(0, name, OBJPROP_CORNER, CORNER_LEFT_UPPER);
      ObjectSetInteger(0, name, OBJPROP_XDISTANCE, x);
      ObjectSetInteger(0, name, OBJPROP_YDISTANCE, y);
      ObjectSetString(0, name, OBJPROP_FONT, "Consolas");
      ObjectSetInteger(0, name, OBJPROP_FONTSIZE, fontSize);
      ObjectSetInteger(0, name, OBJPROP_COLOR, clr);
   }
   ObjectSetString(0, name, OBJPROP_TEXT, text);
}

void UpdateDashboard(int buys, int sells, double gridStep, double refPrice)
{
   double profit = GetTotalProfit();
   ObjectSetString(0, g_dashboardName + "_Buy", OBJPROP_TEXT, "Buys: " + IntegerToString(buys));
   ObjectSetString(0, g_dashboardName + "_Sell", OBJPROP_TEXT, "Sells: " + IntegerToString(sells));
   ObjectSetString(0, g_dashboardName + "_Profit", OBJPROP_TEXT, "P&L: $" + DoubleToString(profit, 2));
   ObjectSetInteger(0, g_dashboardName + "_Profit", OBJPROP_COLOR, (profit >= 0) ? clrLime : clrRed);
}

void DrawGridLines()
{
   ObjectsDeleteAll(0, "GridLine_");
   double gridStepPrice = GetGridStep() * _Point;
   if(gridStepPrice <= 0) return;
   double refPrice = GetGridReferencePrice(POSITION_TYPE_BUY);
   double topPrice = SymbolInfoDouble(_Symbol, SYMBOL_BID) + gridStepPrice * 20;
   double botPrice = SymbolInfoDouble(_Symbol, SYMBOL_BID) - gridStepPrice * 20;
   double startPrice = refPrice + MathCeil((topPrice - refPrice) / gridStepPrice) * gridStepPrice;
   for(double p = startPrice; p >= botPrice; p -= gridStepPrice)
   {
      string lineName = "GridLine_" + DoubleToString(p, _Digits);
      ObjectCreate(0, lineName, OBJ_HLINE, 0, 0, p);
      ObjectSetInteger(0, lineName, OBJPROP_COLOR, InpGridColor);
      ObjectSetInteger(0, lineName, OBJPROP_STYLE, STYLE_DOT);
      ObjectSetInteger(0, lineName, OBJPROP_BACK, true);
   }
   ChartRedraw(0);
}
