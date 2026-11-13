//+------------------------------------------------------------------+
//|                                   GoldHedgeGridScalper_MT5.mq5   |
//|  Behavioural reconstruction of the gold scalper shown in         |
//|  fastest-scalper-ea-bot.mp4 (XAUUSDm, M5, Strategy Tester).      |
//|                                                                  |
//|  Observed in the recording and reproduced here:                  |
//|   - buy and sell baskets run at the same time (hedging account)  |
//|   - a side with no positions re-enters at once with 0.01         |
//|   - a side adds when price moves ~2.15-2.45 against its worst    |
//|     entry; lots go 0.01 0.01 0.02 0.02 0.03 0.04 0.05 (x1.3)     |
//|   - S/L and T/P columns stay 0.000: exits are done by the EA     |
//|   - a whole side closes ~0.80 past its average entry price       |
//|   - yellow "Net Profit" label with the EA name underneath        |
//+------------------------------------------------------------------+
#property copyright "Gold Hedge Grid Scalper"
#property link      ""
#property version   "1.00"
#property description "Two-sided averaging grid scalper for gold (hedging accounts)"
#property description "Reconstructed from observed trading behaviour; no hard stop per trade"

#include <Trade\Trade.mqh>

input group "=== Main Settings ==="
input ulong    InpMagicNumber       = 880010;        // Magic Number
input string   InpComment           = "Gold Scalper EA MT5"; // Order Comment / Chart Name
input bool     InpTradeBuy          = true;          // Run Buy Basket
input bool     InpTradeSell         = true;          // Run Sell Basket

input group "=== Grid (price units, e.g. 2.00 = $2 on gold) ==="
input double   InpGridStep          = 2.00;          // Grid Step Against Worst Entry
input bool     InpAddSpreadToStep   = true;          // Add Current Spread To Step
input double   InpTakeProfit        = 0.80;          // Basket TP Beyond Average Price
input int      InpMaxLevels         = 10;            // Max Positions Per Side

input group "=== Lot Size ==="
input double   InpStartLot          = 0.01;          // First Lot
input double   InpLotMultiplier     = 1.3;           // Lot Multiplier Per Level
input double   InpMaxLot            = 1.0;           // Maximum Lot Per Order

input group "=== Protection ==="
input double   InpMaxSpread         = 0.50;          // Max Spread For New Orders (price, 0=off)
input double   InpMaxDrawdownPct    = 30.0;          // Close All And Stop At Drawdown % (0=off)
input int      InpReentryDelaySec   = 0;             // Delay Before A Closed Side Re-enters (sec)
input int      InpRetryDelaySec     = 5;             // Delay After A Rejected Order (sec)
input int      InpSlippagePoints    = 30;            // Max Slippage (points)

input group "=== Display ==="
input bool     InpShowPanel         = true;          // Show Net Profit Label
input color    InpProfitColor       = clrYellow;     // Net Profit Color
input color    InpNameColor         = clrGainsboro;  // Name Color
input int      InpProfitFontSize    = 20;            // Net Profit Font Size

struct SideStats
{
   int    count;
   double lots;
   double avgPrice;     // volume-weighted entry
   double worstPrice;   // lowest buy / highest sell entry
   double profit;
};

CTrade   g_trade;
string   g_prefix;
double   g_closedProfit = 0.0;
datetime g_retryAfter   = 0;
datetime g_lastClose[2];
bool     g_halted       = false;

//+------------------------------------------------------------------+
int OnInit()
{
   if(InpGridStep <= 0 || InpTakeProfit <= 0 || InpStartLot <= 0 || InpLotMultiplier < 1.0 || InpMaxLevels < 1)
   {
      Print("Invalid inputs: step, TP and lot must be > 0, multiplier >= 1, levels >= 1");
      return INIT_PARAMETERS_INCORRECT;
   }
   // Both baskets are held at once, which a netting account would merge into one position.
   if(InpTradeBuy && InpTradeSell &&
      (ENUM_ACCOUNT_MARGIN_MODE)AccountInfoInteger(ACCOUNT_MARGIN_MODE) != ACCOUNT_MARGIN_MODE_RETAIL_HEDGING)
   {
      Print("This EA needs a hedging account to run both sides. Disable one side or use a hedging account.");
      return INIT_FAILED;
   }

   g_trade.SetExpertMagicNumber(InpMagicNumber);
   g_trade.SetDeviationInPoints(InpSlippagePoints);
   g_trade.SetTypeFillingBySymbol(_Symbol);

   g_prefix = "GHGS_" + IntegerToString((long)InpMagicNumber) + "_";
   g_lastClose[0] = 0;
   g_lastClose[1] = 0;
   g_halted = false;
   g_closedProfit = LoadClosedProfit();

   if(InpShowPanel) CreatePanel();
   return INIT_SUCCEEDED;
}

//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   ObjectsDeleteAll(0, g_prefix);
   ChartRedraw(0);
}

//+------------------------------------------------------------------+
void OnTick()
{
   MqlTick tick;
   if(!SymbolInfoTick(_Symbol, tick) || tick.bid <= 0 || tick.ask <= 0) return;

   SideStats buy, sell;
   CollectStats(POSITION_TYPE_BUY, buy);
   CollectStats(POSITION_TYPE_SELL, sell);

   if(InpShowPanel) UpdatePanel(g_closedProfit + buy.profit + sell.profit);

   if(g_halted)
   {
      // Keep retrying closes that were rejected when the limit was hit.
      if(buy.count > 0)  CloseSide(POSITION_TYPE_BUY);
      if(sell.count > 0) CloseSide(POSITION_TYPE_SELL);
      return;
   }
   if(DrawdownExceeded())
   {
      Print("Drawdown limit reached: closing all positions and stopping until the EA is restarted");
      CloseSide(POSITION_TYPE_BUY);
      CloseSide(POSITION_TYPE_SELL);
      g_halted = true;
      return;
   }

   // Exits: buys close on bid, sells close on ask.
   if(buy.count > 0 && tick.bid >= buy.avgPrice + InpTakeProfit)
   {
      CloseSide(POSITION_TYPE_BUY);
      return;
   }
   if(sell.count > 0 && tick.ask <= sell.avgPrice - InpTakeProfit)
   {
      CloseSide(POSITION_TYPE_SELL);
      return;
   }

   if(TimeCurrent() < g_retryAfter) return;
   double spread = tick.ask - tick.bid;
   if(InpMaxSpread > 0 && spread > InpMaxSpread) return;
   double step = InpGridStep + (InpAddSpreadToStep ? spread : 0.0);

   if(InpTradeBuy)
   {
      if(buy.count == 0)
      {
         if(TimeCurrent() - g_lastClose[0] >= InpReentryDelaySec) OpenPosition(ORDER_TYPE_BUY, 0, tick.ask);
      }
      else if(buy.count < InpMaxLevels && buy.worstPrice - tick.ask >= step)
         OpenPosition(ORDER_TYPE_BUY, buy.count, tick.ask);
   }
   if(InpTradeSell)
   {
      if(sell.count == 0)
      {
         if(TimeCurrent() - g_lastClose[1] >= InpReentryDelaySec) OpenPosition(ORDER_TYPE_SELL, 0, tick.bid);
      }
      else if(sell.count < InpMaxLevels && tick.bid - sell.worstPrice >= step)
         OpenPosition(ORDER_TYPE_SELL, sell.count, tick.bid);
   }
}

//+------------------------------------------------------------------+
void OnTradeTransaction(const MqlTradeTransaction &trans,
                        const MqlTradeRequest &request,
                        const MqlTradeResult &result)
{
   if(trans.type != TRADE_TRANSACTION_DEAL_ADD || trans.deal == 0) return;
   if(!HistoryDealSelect(trans.deal)) return;
   g_closedProfit += DealResult(trans.deal);
}

//+------------------------------------------------------------------+
double DealResult(ulong deal)
{
   if(HistoryDealGetString(deal, DEAL_SYMBOL) != _Symbol) return 0.0;
   if(HistoryDealGetInteger(deal, DEAL_MAGIC) != (long)InpMagicNumber) return 0.0;
   return HistoryDealGetDouble(deal, DEAL_PROFIT) + HistoryDealGetDouble(deal, DEAL_SWAP) +
          HistoryDealGetDouble(deal, DEAL_COMMISSION);
}

double LoadClosedProfit()
{
   double total = 0.0;
   if(!HistorySelect(0, TimeCurrent())) return 0.0;
   for(int i = HistoryDealsTotal() - 1; i >= 0; i--)
   {
      ulong deal = HistoryDealGetTicket(i);
      if(deal != 0) total += DealResult(deal);
   }
   return total;
}

//+------------------------------------------------------------------+
void CollectStats(ENUM_POSITION_TYPE type, SideStats &s)
{
   s.count = 0; s.lots = 0.0; s.avgPrice = 0.0; s.worstPrice = 0.0; s.profit = 0.0;
   double weighted = 0.0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0) continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol) continue;
      if(PositionGetInteger(POSITION_MAGIC) != (long)InpMagicNumber) continue;
      if((ENUM_POSITION_TYPE)PositionGetInteger(POSITION_TYPE) != type) continue;

      double price = PositionGetDouble(POSITION_PRICE_OPEN);
      double vol   = PositionGetDouble(POSITION_VOLUME);
      if(s.count == 0) s.worstPrice = price;
      else if(type == POSITION_TYPE_BUY) s.worstPrice = MathMin(s.worstPrice, price);
      else s.worstPrice = MathMax(s.worstPrice, price);

      s.count++;
      s.lots   += vol;
      weighted += price * vol;
      s.profit += PositionGetDouble(POSITION_PROFIT) + PositionGetDouble(POSITION_SWAP);
   }
   if(s.lots > 0) s.avgPrice = weighted / s.lots;
}

//+------------------------------------------------------------------+
double LotForLevel(int level)
{
   double minLot  = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double maxLot  = MathMin(SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX), InpMaxLot);
   double lotStep = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   if(lotStep <= 0) lotStep = 0.01;

   // Rounded to nearest step: 0.01 x 1.3^n gives 0.01 0.01 0.02 0.02 0.03 0.04 0.05.
   double lots = InpStartLot * MathPow(InpLotMultiplier, level);
   lots = MathRound(lots / lotStep) * lotStep;
   lots = MathMax(minLot, MathMin(maxLot, lots));
   return NormalizeDouble(lots, 8);
}

bool OpenPosition(ENUM_ORDER_TYPE type, int level, double price)
{
   if(!TerminalInfoInteger(TERMINAL_TRADE_ALLOWED) || !MQLInfoInteger(MQL_TRADE_ALLOWED)) return false;

   double lots = LotForLevel(level);
   double margin = 0.0;
   if(!OrderCalcMargin(type, _Symbol, lots, price, margin) || margin > AccountInfoDouble(ACCOUNT_MARGIN_FREE))
   {
      g_retryAfter = TimeCurrent() + InpRetryDelaySec;
      Print("Not enough free margin for ", DoubleToString(lots, 2), " lots");
      return false;
   }

   bool sent = (type == ORDER_TYPE_BUY) ? g_trade.Buy(lots, _Symbol, 0.0, 0.0, 0.0, InpComment)
                                        : g_trade.Sell(lots, _Symbol, 0.0, 0.0, 0.0, InpComment);
   uint rc = g_trade.ResultRetcode();
   if(!sent || (rc != TRADE_RETCODE_DONE && rc != TRADE_RETCODE_DONE_PARTIAL && rc != TRADE_RETCODE_PLACED))
   {
      g_retryAfter = TimeCurrent() + InpRetryDelaySec;
      Print("Order rejected: ", rc, " ", g_trade.ResultRetcodeDescription());
      return false;
   }
   return true;
}

void CloseSide(ENUM_POSITION_TYPE type)
{
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0) continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol) continue;
      if(PositionGetInteger(POSITION_MAGIC) != (long)InpMagicNumber) continue;
      if((ENUM_POSITION_TYPE)PositionGetInteger(POSITION_TYPE) != type) continue;
      if(!g_trade.PositionClose(ticket, InpSlippagePoints))
         Print("Close failed for #", ticket, ": ", g_trade.ResultRetcodeDescription());
   }
   g_lastClose[type == POSITION_TYPE_BUY ? 0 : 1] = TimeCurrent();
}

bool DrawdownExceeded()
{
   if(InpMaxDrawdownPct <= 0) return false;
   double balance = AccountInfoDouble(ACCOUNT_BALANCE);
   if(balance <= 0) return false;
   return (balance - AccountInfoDouble(ACCOUNT_EQUITY)) / balance * 100.0 >= InpMaxDrawdownPct;
}

//+------------------------------------------------------------------+
void CreateLabel(string name, string font, int fontSize, color clr, int yDistance)
{
   if(ObjectFind(0, name) < 0) ObjectCreate(0, name, OBJ_LABEL, 0, 0, 0);
   ObjectSetInteger(0, name, OBJPROP_CORNER, CORNER_RIGHT_LOWER);
   ObjectSetInteger(0, name, OBJPROP_ANCHOR, ANCHOR_RIGHT_LOWER);
   ObjectSetInteger(0, name, OBJPROP_XDISTANCE, 10);
   ObjectSetInteger(0, name, OBJPROP_YDISTANCE, yDistance);
   ObjectSetInteger(0, name, OBJPROP_COLOR, clr);
   ObjectSetInteger(0, name, OBJPROP_FONTSIZE, fontSize);
   ObjectSetString(0, name, OBJPROP_FONT, font);
   ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
   ObjectSetInteger(0, name, OBJPROP_HIDDEN, true);
}

void CreatePanel()
{
   int nameSize = MathMax(8, InpProfitFontSize / 2);
   CreateLabel(g_prefix + "Name", "Arial", nameSize, InpNameColor, 60);
   CreateLabel(g_prefix + "Profit", "Arial Bold", InpProfitFontSize, InpProfitColor, 60 + nameSize * 2 + 6);
   ObjectSetString(0, g_prefix + "Name", OBJPROP_TEXT, InpComment);
   UpdatePanel(g_closedProfit);
}

void UpdatePanel(double netProfit)
{
   ObjectSetString(0, g_prefix + "Profit", OBJPROP_TEXT, "Net Profit: " + DoubleToString(netProfit, 2));
}
//+------------------------------------------------------------------+
