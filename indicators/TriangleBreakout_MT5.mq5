//+------------------------------------------------------------------+
//|                                        TriangleBreakout_MT5.mq5  |
//|   Descending-triangle breakdown / reversal Buy & Sell signals    |
//+------------------------------------------------------------------+
#property copyright "Triangle Breakout"
#property link      ""
#property version   "1.00"
#property description "Falling trendline from the swing high + flat support."
#property description "SELL: close below support. BUY: close above the trendline,"
#property description "support reclaimed after a breakdown, or reversal at the target."
#property description "Signals are set on closed bars only (no repaint)."
#property strict

#property indicator_chart_window
#property indicator_buffers 5
#property indicator_plots   5

#property indicator_label1  "Buy"
#property indicator_type1   DRAW_ARROW
#property indicator_color1  clrLime
#property indicator_width1  2

#property indicator_label2  "Sell"
#property indicator_type2   DRAW_ARROW
#property indicator_color2  clrRed
#property indicator_width2  2

#property indicator_label3  "Resistance"
#property indicator_type3   DRAW_LINE
#property indicator_color3  clrWhite
#property indicator_width3  1

#property indicator_label4  "Support"
#property indicator_type4   DRAW_LINE
#property indicator_color4  clrWhite
#property indicator_width4  1

#property indicator_label5  "Target"
#property indicator_type5   DRAW_LINE
#property indicator_color5  clrOrange
#property indicator_width5  2

input group "=== Pattern Detection ==="
input int      InpPivotLen           = 5;      // Swing strength (bars each side)
input int      InpLookback           = 300;    // Lookback for the pattern (bars)
input int      InpMinSpan            = 20;     // Min bars between trendline anchors
input int      InpMinSupportTouches  = 2;      // Min swing lows on support
input double   InpFlatTolATR         = 1.0;    // Support flatness tolerance (ATR)
input double   InpMinHeightATR       = 5.0;    // Min pattern height (ATR)
input int      InpATRPeriod          = 14;     // ATR Period

input group "=== Signals ==="
input double   InpBreakBufATR        = 0.25;   // Close beyond level by (ATR)
input double   InpTargetFrac         = 0.33;   // Target = support - height * this
input double   InpManualTarget       = 0.0;    // Manual target price (0 = auto)
input int      InpReversalBars       = 3;      // Reversal: close above high of N bars
input int      InpMaxBarsAfterBreak  = 150;    // Give up on reversal after N bars

input group "=== Display ==="
input int      InpMaxBars            = 5000;   // Bars of history to process
input bool     InpAlerts             = true;   // Alert on new signal

struct STri
{
   int    a;      // bar index of the trendline anchor (highest swing high)
   double top;    // price at the anchor
   double slope;  // price change per bar (negative)
   double sup;    // support price
};

double BuyBuf[], SellBuf[], ResBuf[], SupBuf[], TgtBuf[];
int    g_ph[], g_pl[], g_nph, g_npl;
int    g_atr = INVALID_HANDLE;
string g_prefix = "TriBrk_";

//+------------------------------------------------------------------+
int OnInit()
{
   if(InpPivotLen < 1 || InpLookback < 4 * InpPivotLen || InpATRPeriod < 1 || InpReversalBars < 1)
      return INIT_PARAMETERS_INCORRECT;

   SetIndexBuffer(0, BuyBuf,  INDICATOR_DATA);
   SetIndexBuffer(1, SellBuf, INDICATOR_DATA);
   SetIndexBuffer(2, ResBuf,  INDICATOR_DATA);
   SetIndexBuffer(3, SupBuf,  INDICATOR_DATA);
   SetIndexBuffer(4, TgtBuf,  INDICATOR_DATA);
   PlotIndexSetInteger(0, PLOT_ARROW, 233);
   PlotIndexSetInteger(1, PLOT_ARROW, 234);
   for(int i = 0; i < 5; i++)
      PlotIndexSetDouble(i, PLOT_EMPTY_VALUE, EMPTY_VALUE);

   g_atr = iATR(_Symbol, _Period, InpATRPeriod);
   if(g_atr == INVALID_HANDLE)
      return INIT_FAILED;

   IndicatorSetString(INDICATOR_SHORTNAME, "Triangle Breakout");
   return INIT_SUCCEEDED;
}

//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   ObjectsDeleteAll(0, g_prefix);
   if(g_atr != INVALID_HANDLE)
      IndicatorRelease(g_atr);
}

//+------------------------------------------------------------------+
void DrawLine(const string name, datetime t1, double p1, datetime t2, double p2, color clr, int width)
{
   string n = g_prefix + name;
   if(ObjectFind(0, n) < 0)
   {
      ObjectCreate(0, n, OBJ_TREND, 0, t1, p1, t2, p2);
      ObjectSetInteger(0, n, OBJPROP_RAY_RIGHT, true);
      ObjectSetInteger(0, n, OBJPROP_SELECTABLE, false);
      ObjectSetInteger(0, n, OBJPROP_HIDDEN, true);
   }
   ObjectMove(0, n, 0, t1, p1);
   ObjectMove(0, n, 1, t2, p2);
   ObjectSetInteger(0, n, OBJPROP_COLOR, clr);
   ObjectSetInteger(0, n, OBJPROP_WIDTH, width);
}

//+------------------------------------------------------------------+
//| Fit the pattern using only swings already confirmed at bar i     |
//+------------------------------------------------------------------+
bool Fit(const int i, const int from, const double &high[], const double &low[],
         const double atr, STri &t)
{
   int lo = MathMax(from, i - InpLookback);
   int hi = i - InpPivotLen;

   // Anchor: highest swing high in the window
   int a = -1;
   for(int k = g_nph - 1; k >= 0; k--)
   {
      int p = g_ph[k];
      if(p > hi) continue;
      if(p < lo) break;
      if(a < 0 || high[p] > high[a]) a = p;
   }
   if(a < 0) return false;

   // Trendline: flattest line from the anchor that no later swing high pierces
   double best = -DBL_MAX;
   int b = -1;
   for(int k = g_nph - 1; k >= 0; k--)
   {
      int p = g_ph[k];
      if(p > hi) continue;
      if(p <= a) break;
      double s = (high[p] - high[a]) / (p - a);
      if(s > best) { best = s; b = p; }
   }
   if(b < 0 || best >= 0.0 || b - a < InpMinSpan) return false;

   // Support: lowest swing low after the anchor, with enough lows resting near it
   double sup = DBL_MAX;
   for(int k = g_npl - 1; k >= 0; k--)
   {
      int p = g_pl[k];
      if(p > hi) continue;
      if(p <= a) break;
      if(low[p] < sup) sup = low[p];
   }
   if(sup == DBL_MAX) return false;

   int touches = 0;
   for(int k = g_npl - 1; k >= 0; k--)
   {
      int p = g_pl[k];
      if(p > hi) continue;
      if(p <= a) break;
      if(low[p] <= sup + InpFlatTolATR * atr) touches++;
   }
   if(touches < InpMinSupportTouches) return false;

   if(high[a] - sup < InpMinHeightATR * atr) return false;
   if(high[a] + best * (i - a) <= sup) return false;   // already past the apex

   t.a = a;
   t.top = high[a];
   t.slope = best;
   t.sup = sup;
   return true;
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
   // Everything is derived from closed bars, so only recompute on a new bar
   if(prev_calculated == rates_total) return rates_total;
   if(rates_total < InpATRPeriod + 4 * InpPivotLen + 10) return 0;

   ArraySetAsSeries(time, false);
   ArraySetAsSeries(high, false);
   ArraySetAsSeries(low, false);
   ArraySetAsSeries(close, false);

   static double atr[];
   ArraySetAsSeries(atr, false);
   if(BarsCalculated(g_atr) < rates_total) return 0;
   if(CopyBuffer(g_atr, 0, 0, rates_total, atr) != rates_total) return 0;

   ArrayInitialize(BuyBuf,  EMPTY_VALUE);
   ArrayInitialize(SellBuf, EMPTY_VALUE);
   ArrayInitialize(ResBuf,  EMPTY_VALUE);
   ArrayInitialize(SupBuf,  EMPTY_VALUE);
   ArrayInitialize(TgtBuf,  EMPTY_VALUE);

   int last  = rates_total - 2;   // last closed bar
   int start = MathMax(InpATRPeriod, rates_total - InpMaxBars);

   // Swing highs / lows, each usable InpPivotLen bars after it forms
   ArrayResize(g_ph, rates_total);
   ArrayResize(g_pl, rates_total);
   g_nph = 0;
   g_npl = 0;
   for(int p = start + InpPivotLen; p <= last - InpPivotLen; p++)
   {
      bool isH = true, isL = true;
      for(int j = 1; j <= InpPivotLen && (isH || isL); j++)
      {
         if(high[p - j] >= high[p] || high[p + j] > high[p]) isH = false;
         if(low[p - j]  <= low[p]  || low[p + j]  < low[p])  isL = false;
      }
      if(isH) g_ph[g_nph++] = p;
      if(isL) g_pl[g_npl++] = p;
   }

   // state: 0 = searching, 1 = inside the pattern, 2 = broke down, waiting for a buy
   int    state = 0, from = start, breakBar = 0;
   bool   reached = false;
   double target = 0.0;
   STri   t;
   t.a = 0; t.top = 0.0; t.slope = 0.0; t.sup = 0.0;

   for(int i = start + 2 * InpPivotLen; i <= last; i++)
   {
      double a = atr[i];
      if(a <= 0.0) continue;
      double buf = InpBreakBufATR * a;

      if(state <= 1)
      {
         STri n;
         n.a = 0; n.top = 0.0; n.slope = 0.0; n.sup = 0.0;
         if(Fit(i, from, high, low, a, n))
         {
            double nl = n.top + n.slope * (i - n.a);
            if(close[i] <= nl + buf && close[i] >= n.sup - buf)
            {
               t = n;
               state = 1;
            }
         }

         if(state == 1)
         {
            double line = t.top + t.slope * (i - t.a);
            if(line <= t.sup)
            {
               state = 0;
               from = i;
            }
            else if(close[i] < t.sup - buf)
            {
               SellBuf[i] = high[i] + 0.5 * a;
               state = 2;
               breakBar = i;
               reached = false;
               target = (InpManualTarget > 0.0) ? InpManualTarget
                                                : t.sup - InpTargetFrac * (t.top - t.sup);
            }
            else if(close[i] > line + buf)
            {
               BuyBuf[i] = low[i] - 0.5 * a;
               state = 0;
               from = i;
            }
            else
            {
               ResBuf[i] = line;
               SupBuf[i] = t.sup;
            }
         }
      }
      else
      {
         if(low[i] <= target) reached = true;

         double hh = high[i - 1];
         for(int j = 2; j <= InpReversalBars; j++)
            hh = MathMax(hh, high[i - j]);

         // Failed breakdown (support reclaimed) or reversal after the target was hit
         if(close[i] > t.sup + buf || (reached && close[i] > hh))
         {
            BuyBuf[i] = low[i] - 0.5 * a;
            state = 0;
            from = i;
         }
         else if(i - breakBar > InpMaxBarsAfterBreak)
         {
            state = 0;
            from = i;
         }
         else
         {
            SupBuf[i] = t.sup;
            TgtBuf[i] = target;
         }
      }
   }

   // Full-length lines for the pattern that is still live
   if(state == 0)
      ObjectsDeleteAll(0, g_prefix);
   else
   {
      DrawLine("Support", time[t.a], t.sup, time[last], t.sup, clrWhite, 2);
      if(state == 1)
      {
         DrawLine("Resistance", time[t.a], t.top, time[last], t.top + t.slope * (last - t.a), clrWhite, 2);
         ObjectDelete(0, g_prefix + "Target");
      }
      else
      {
         DrawLine("Target", time[breakBar], target, time[last], target, clrOrange, 2);
         ObjectDelete(0, g_prefix + "Resistance");
      }
   }

   if(InpAlerts && prev_calculated > 0)
   {
      static datetime lastAlert = 0;
      if(time[last] != lastAlert && (BuyBuf[last] != EMPTY_VALUE || SellBuf[last] != EMPTY_VALUE))
      {
         lastAlert = time[last];
         Alert(_Symbol, " ", EnumToString(_Period), ": Triangle Breakout ",
               (BuyBuf[last] != EMPTY_VALUE ? "BUY" : "SELL"), " at ", DoubleToString(close[last], _Digits));
      }
   }

   return rates_total;
}
//+------------------------------------------------------------------+
