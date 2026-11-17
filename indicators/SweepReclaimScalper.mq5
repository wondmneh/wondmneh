//+------------------------------------------------------------------+
//|                                         SweepReclaimScalper.mq5  |
//| Marks failed breakouts (liquidity sweeps) of the recent range,   |
//| but only when trading costs are small relative to volatility.    |
//| Signals are set on closed bars only and never repaint.           |
//+------------------------------------------------------------------+
#property copyright "SweepReclaimScalper"
#property version   "1.00"
#property indicator_chart_window
#property indicator_buffers 6
#property indicator_plots   4

#property indicator_label1  "Buy (low swept and reclaimed)"
#property indicator_type1   DRAW_ARROW
#property indicator_color1  clrDodgerBlue
#property indicator_width1  2

#property indicator_label2  "Sell (high swept and rejected)"
#property indicator_type2   DRAW_ARROW
#property indicator_color2  clrOrangeRed
#property indicator_width2  2

#property indicator_label3  "Range high"
#property indicator_type3   DRAW_LINE
#property indicator_color3  clrDimGray
#property indicator_style3  STYLE_DOT

#property indicator_label4  "Range low"
#property indicator_type4   DRAW_LINE
#property indicator_color4  clrDimGray
#property indicator_style4  STYLE_DOT

input group "Sweep detection"
input int    InpLookback       = 20;    // Bars that define the range being swept
input double InpMinSweepATR    = 0.10;  // Minimum push beyond the range, in ATRs
input double InpMinWickRatio   = 0.50;  // Rejection wick as a share of the bar's range

input group "Volatility and cost filters"
input int    InpATRPeriod      = 14;    // Fast ATR period
input int    InpATRSlowPeriod  = 100;   // Slow ATR period (baseline volatility)
input double InpMinVolRatio    = 1.00;  // Minimum fast ATR / slow ATR (0 = off)
input double InpMaxSpreadATR   = 0.15;  // Maximum spread as a share of fast ATR (0 = off)

input group "Session filter (broker server time)"
input bool   InpUseSession     = true;  // Only signal inside the session window
input int    InpSessionStart   = 9;     // Session start hour
input int    InpSessionEnd     = 19;    // Session end hour (exclusive)

input group "Alerts"
input bool   InpAlerts         = false; // Alert when a signal bar closes

double BuyBuffer[];
double SellBuffer[];
double RangeHighBuffer[];
double RangeLowBuffer[];
double AtrFastBuffer[];
double AtrSlowBuffer[];

int      atrFastHandle = INVALID_HANDLE;
int      atrSlowHandle = INVALID_HANDLE;
datetime lastAlertTime = 0;

//+------------------------------------------------------------------+
int OnInit()
  {
   if(InpLookback < 2 || InpATRPeriod < 1 || InpATRSlowPeriod < 1)
     {
      Print("SweepReclaimScalper: lookback must be >= 2 and ATR periods >= 1");
      return(INIT_PARAMETERS_INCORRECT);
     }

   SetIndexBuffer(0, BuyBuffer, INDICATOR_DATA);
   SetIndexBuffer(1, SellBuffer, INDICATOR_DATA);
   SetIndexBuffer(2, RangeHighBuffer, INDICATOR_DATA);
   SetIndexBuffer(3, RangeLowBuffer, INDICATOR_DATA);
   SetIndexBuffer(4, AtrFastBuffer, INDICATOR_CALCULATIONS);
   SetIndexBuffer(5, AtrSlowBuffer, INDICATOR_CALCULATIONS);

   PlotIndexSetInteger(0, PLOT_ARROW, 233);
   PlotIndexSetInteger(1, PLOT_ARROW, 234);

   int drawBegin = MathMax(InpLookback, InpATRSlowPeriod) + 1;
   for(int p = 0; p < 4; p++)
     {
      PlotIndexSetDouble(p, PLOT_EMPTY_VALUE, EMPTY_VALUE);
      PlotIndexSetInteger(p, PLOT_DRAW_BEGIN, drawBegin);
     }

   atrFastHandle = iATR(_Symbol, _Period, InpATRPeriod);
   atrSlowHandle = iATR(_Symbol, _Period, InpATRSlowPeriod);
   if(atrFastHandle == INVALID_HANDLE || atrSlowHandle == INVALID_HANDLE)
     {
      Print("SweepReclaimScalper: failed to create ATR handles");
      return(INIT_FAILED);
     }

   IndicatorSetString(INDICATOR_SHORTNAME, "SweepReclaimScalper(" + IntegerToString(InpLookback) + ")");
   IndicatorSetInteger(INDICATOR_DIGITS, _Digits);
   return(INIT_SUCCEEDED);
  }

//+------------------------------------------------------------------+
void OnDeinit(const int reason)
  {
   if(atrFastHandle != INVALID_HANDLE)
      IndicatorRelease(atrFastHandle);
   if(atrSlowHandle != INVALID_HANDLE)
      IndicatorRelease(atrSlowHandle);
  }

//+------------------------------------------------------------------+
bool InSession(const datetime barTime)
  {
   if(!InpUseSession || InpSessionStart == InpSessionEnd)
      return(true);

   MqlDateTime dt;
   TimeToStruct(barTime, dt);
   if(InpSessionStart < InpSessionEnd)
      return(dt.hour >= InpSessionStart && dt.hour < InpSessionEnd);
   // Window wraps past midnight
   return(dt.hour >= InpSessionStart || dt.hour < InpSessionEnd);
  }

//+------------------------------------------------------------------+
int OnCalculate(const int rates_total,
                const int prev_calculated,
                const datetime &time[],
                const double &open[],
                const double &high[],
                const double &low[],
                const double &close[],
                const long &tick_volume[],
                const long &volume[],
                const int &spread[])
  {
   int minBars = MathMax(InpLookback, InpATRSlowPeriod) + 1;
   if(rates_total <= minBars)
      return(0);
   if(BarsCalculated(atrFastHandle) < rates_total || BarsCalculated(atrSlowHandle) < rates_total)
      return(0);

   int toCopy = (prev_calculated <= 0 || prev_calculated > rates_total)
                ? rates_total
                : rates_total - prev_calculated + 2;
   if(toCopy > rates_total)
      toCopy = rates_total;
   if(CopyBuffer(atrFastHandle, 0, 0, toCopy, AtrFastBuffer) <= 0)
      return(0);
   if(CopyBuffer(atrSlowHandle, 0, 0, toCopy, AtrSlowBuffer) <= 0)
      return(0);

   int start;
   if(prev_calculated <= 0 || prev_calculated > rates_total)
     {
      start = minBars;
      for(int i = 0; i < minBars; i++)
        {
         BuyBuffer[i] = EMPTY_VALUE;
         SellBuffer[i] = EMPTY_VALUE;
         RangeHighBuffer[i] = EMPTY_VALUE;
         RangeLowBuffer[i] = EMPTY_VALUE;
        }
     }
   else
      // Step back one bar so the bar that just closed gets evaluated
      start = MathMax(prev_calculated - 2, minBars);

   for(int i = start; i < rates_total; i++)
     {
      double rangeHigh = high[i - 1];
      double rangeLow  = low[i - 1];
      for(int k = 2; k <= InpLookback; k++)
        {
         if(high[i - k] > rangeHigh)
            rangeHigh = high[i - k];
         if(low[i - k] < rangeLow)
            rangeLow = low[i - k];
        }
      RangeHighBuffer[i] = rangeHigh;
      RangeLowBuffer[i]  = rangeLow;
      BuyBuffer[i]  = EMPTY_VALUE;
      SellBuffer[i] = EMPTY_VALUE;

      // The forming bar is never signalled, so arrows cannot repaint
      if(i == rates_total - 1)
         continue;

      double atr     = AtrFastBuffer[i];
      double atrSlow = AtrSlowBuffer[i];
      double barRange = high[i] - low[i];
      if(atr <= 0.0 || atrSlow <= 0.0 || barRange <= 0.0)
         continue;

      if(!InSession(time[i]))
         continue;
      if(InpMinVolRatio > 0.0 && atr / atrSlow < InpMinVolRatio)
         continue;
      if(InpMaxSpreadATR > 0.0 && spread[i] * _Point > InpMaxSpreadATR * atr)
         continue;

      double minSweep  = InpMinSweepATR * atr;
      double lowerWick = MathMin(open[i], close[i]) - low[i];
      double upperWick = high[i] - MathMax(open[i], close[i]);

      bool sweptLow  = low[i] < rangeLow - minSweep && close[i] > rangeLow;
      bool sweptHigh = high[i] > rangeHigh + minSweep && close[i] < rangeHigh;

      if(sweptLow && !sweptHigh && lowerWick / barRange >= InpMinWickRatio)
         BuyBuffer[i] = low[i] - 0.25 * atr;
      else
         if(sweptHigh && !sweptLow && upperWick / barRange >= InpMinWickRatio)
            SellBuffer[i] = high[i] + 0.25 * atr;
     }

   if(InpAlerts && prev_calculated > 0)
     {
      int last = rates_total - 2;
      if(time[last] != lastAlertTime)
        {
         if(BuyBuffer[last] != EMPTY_VALUE)
           {
            Alert(_Symbol, " ", EnumToString(_Period), ": low swept and reclaimed (buy setup)");
            lastAlertTime = time[last];
           }
         else
            if(SellBuffer[last] != EMPTY_VALUE)
              {
               Alert(_Symbol, " ", EnumToString(_Period), ": high swept and rejected (sell setup)");
               lastAlertTime = time[last];
              }
        }
     }

   return(rates_total);
  }
//+------------------------------------------------------------------+
