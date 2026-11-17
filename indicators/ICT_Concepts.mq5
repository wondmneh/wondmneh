//+------------------------------------------------------------------+
//|                                                 ICT_Concepts.mq5 |
//|  Chart overlay of the concepts in "The ICT Bible - V1" (Ali Khan) |
//|                                                                  |
//|  Draws: three-bar swings, buyside/sellside liquidity, fair value |
//|  gaps (BISI/SIBI) with consequent encroachment, order blocks     |
//|  with mean threshold, breaker and mitigation blocks, the current |
//|  dealing range with premium/discount, killzones, the New York    |
//|  midnight open (Power of 3) and optional SMT divergence.         |
//+------------------------------------------------------------------+
#property copyright "ICT Concepts"
#property version   "1.00"
#property indicator_chart_window
#property indicator_buffers 2
#property indicator_plots   2

#property indicator_label1  "Swing High"
#property indicator_type1   DRAW_ARROW
#property indicator_color1  clrTomato
#property indicator_width1  1

#property indicator_label2  "Swing Low"
#property indicator_type2   DRAW_ARROW
#property indicator_color2  clrDodgerBlue
#property indicator_width2  1

input group "General"
input int    InpLookback          = 1000;   // Bars to analyse
input int    InpSwingStrength     = 1;      // Bars each side of a swing (1 = three-bar swing)
input bool   InpShowInvalidated   = false;  // Keep zones that price has closed through

input group "Liquidity (old highs / lows)"
input bool   InpShowLiquidity     = true;   // Show BSL / SSL levels
input int    InpMaxLiquidity      = 5;      // Untaken levels shown per side
input color  InpBSLColor          = clrTomato;
input color  InpSSLColor          = clrDodgerBlue;

input group "Fair Value Gaps"
input bool   InpShowFVG           = true;   // Show FVGs (BISI / SIBI)
input int    InpMaxFVG            = 8;      // Most recent FVGs shown
input int    InpFVGMinPoints      = 0;      // Minimum gap size in points
input bool   InpShowCE            = true;   // Show consequent encroachment (50%)
input color  InpBISIColor         = C'32,84,60';
input color  InpSIBIColor         = C'104,40,44';

input group "Order Blocks"
input bool   InpShowOB            = true;   // Show order blocks
input int    InpMaxOB             = 4;      // Most recent order blocks shown
input bool   InpOBRequireSweep    = true;   // Block must run liquidity past a prior swing
input int    InpBlockMaxCandles   = 2;      // Max consecutive candles merged into a block
input bool   InpShowMeanThreshold = true;   // Show mean threshold (50%)
input color  InpBullOBColor       = C'28,64,110';
input color  InpBearOBColor       = C'120,60,20';

input group "Breaker / Mitigation Blocks"
input bool   InpShowBreaker       = true;   // Show breaker blocks
input bool   InpShowMitigation    = true;   // Show mitigation blocks
input int    InpMaxBreaker        = 3;      // Most recent shown, per type
input color  InpBullBreakerColor  = C'24,96,104';
input color  InpBearBreakerColor  = C'104,32,88';
input color  InpBullMBColor       = C'70,84,30';
input color  InpBearMBColor       = C'90,50,50';

input group "Dealing Range (premium / discount)"
input bool   InpShowRange         = true;   // Show current dealing range
input int    InpRangeSwing        = 10;     // Bars each side of a range swing
input color  InpRangeColor        = clrSilver;

input group "Time (killzones are New York time)"
input int    InpServerMinusNY     = 7;      // Broker server time minus New York time, hours
input bool   InpShowAsia          = true;   // FX Asia 8pm-12am
input bool   InpShowLondon        = true;   // FX London 2am-5am
input bool   InpShowNewYork       = true;   // FX New York 7am-10am
input bool   InpShowLondonClose   = false;  // FX London Close 10am-12pm
input bool   InpShowIndexAM       = false;  // Index AM session 8:30am-12pm
input bool   InpShowIndexPM       = false;  // Index PM session 1:30pm-4pm
input int    InpMaxKillzoneDays   = 5;      // Days of killzones shown
input bool   InpShowMidnightOpen  = true;   // Show 12am New York open (Power of 3)
input int    InpMidnightDays      = 3;      // Days of midnight opens shown
input color  InpMidnightColor     = clrGold;

input group "SMT Divergence"
input string InpSMTSymbol         = "";     // Correlated symbol (empty = off)
input bool   InpSMTInverse        = false;  // Symbol is inversely correlated
input color  InpSMTColor          = clrMagenta;

#define PREFIX "ICTC_"

enum ZoneType { ZONE_FVG = 0, ZONE_OB = 1, ZONE_BREAKER = 2, ZONE_MB = 3 };

struct Swing
  {
   int               idx;
   double            price;
   bool              isHigh;
   int               sweptAt;   // bar that traded through the level, -1 while untaken
  };

struct Zone
  {
   int               type;
   bool              bull;
   int               i1;        // bar the zone is drawn from
   int               from;      // bar that confirmed the zone
   int               i2;        // bar that invalidated it
   double            top;
   double            bot;
   bool              active;
  };

double SwingHighBuf[];
double SwingLowBuf[];

Swing  g_swings[];
Zone   g_zones[];
int    g_objId = 0;

//+------------------------------------------------------------------+
int OnInit()
  {
   SetIndexBuffer(0, SwingHighBuf, INDICATOR_DATA);
   SetIndexBuffer(1, SwingLowBuf, INDICATOR_DATA);
   PlotIndexSetInteger(0, PLOT_ARROW, 159);
   PlotIndexSetInteger(1, PLOT_ARROW, 159);
   PlotIndexSetInteger(0, PLOT_ARROW_SHIFT, -8);
   PlotIndexSetInteger(1, PLOT_ARROW_SHIFT, 8);
   PlotIndexSetDouble(0, PLOT_EMPTY_VALUE, EMPTY_VALUE);
   PlotIndexSetDouble(1, PLOT_EMPTY_VALUE, EMPTY_VALUE);
   IndicatorSetString(INDICATOR_SHORTNAME, "ICT Concepts");
   if(InpSMTSymbol != "")
      SymbolSelect(InpSMTSymbol, true);
   return(INIT_SUCCEEDED);
  }

//+------------------------------------------------------------------+
void OnDeinit(const int reason)
  {
   ObjectsDeleteAll(0, PREFIX);
  }

//+------------------------------------------------------------------+
//| Drawing helpers                                                  |
//+------------------------------------------------------------------+
string NextName(const string tag)
  {
   g_objId++;
   return(PREFIX + tag + "_" + IntegerToString(g_objId));
  }

void DrawRect(const string tag, datetime t1, double p1, datetime t2, double p2, color c, bool fill)
  {
   string name = NextName(tag);
   if(!ObjectCreate(0, name, OBJ_RECTANGLE, 0, t1, p1, t2, p2))
      return;
   ObjectSetInteger(0, name, OBJPROP_COLOR, c);
   ObjectSetInteger(0, name, OBJPROP_FILL, fill);
   ObjectSetInteger(0, name, OBJPROP_BACK, true);
   ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
   ObjectSetInteger(0, name, OBJPROP_HIDDEN, true);
  }

void DrawLine(const string tag, datetime t1, double p1, datetime t2, double p2, color c, ENUM_LINE_STYLE style)
  {
   string name = NextName(tag);
   if(!ObjectCreate(0, name, OBJ_TREND, 0, t1, p1, t2, p2))
      return;
   ObjectSetInteger(0, name, OBJPROP_COLOR, c);
   ObjectSetInteger(0, name, OBJPROP_STYLE, style);
   ObjectSetInteger(0, name, OBJPROP_WIDTH, 1);
   ObjectSetInteger(0, name, OBJPROP_RAY_RIGHT, false);
   ObjectSetInteger(0, name, OBJPROP_RAY_LEFT, false);
   ObjectSetInteger(0, name, OBJPROP_BACK, false);
   ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
   ObjectSetInteger(0, name, OBJPROP_HIDDEN, true);
  }

void DrawText(const string tag, datetime t, double p, const string text, color c, ENUM_ANCHOR_POINT anchor)
  {
   string name = NextName(tag);
   if(!ObjectCreate(0, name, OBJ_TEXT, 0, t, p))
      return;
   ObjectSetString(0, name, OBJPROP_TEXT, text);
   ObjectSetString(0, name, OBJPROP_FONT, "Arial");
   ObjectSetInteger(0, name, OBJPROP_FONTSIZE, 7);
   ObjectSetInteger(0, name, OBJPROP_COLOR, c);
   ObjectSetInteger(0, name, OBJPROP_ANCHOR, anchor);
   ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
   ObjectSetInteger(0, name, OBJPROP_HIDDEN, true);
  }

//+------------------------------------------------------------------+
//| Swing tests: the middle bar is higher/lower than n bars each side |
//+------------------------------------------------------------------+
bool IsSwingHigh(const double &high[], int k, int n)
  {
   for(int d = 1; d <= n; d++)
      if(high[k] < high[k - d] || high[k] <= high[k + d])
         return(false);
   return(true);
  }

bool IsSwingLow(const double &low[], int k, int n)
  {
   for(int d = 1; d <= n; d++)
      if(low[k] > low[k - d] || low[k] >= low[k + d])
         return(false);
   return(true);
  }

int AddSwing(int idx, double price, bool isHigh)
  {
   int n = ArraySize(g_swings);
   ArrayResize(g_swings, n + 1, 256);
   g_swings[n].idx     = idx;
   g_swings[n].price   = price;
   g_swings[n].isHigh  = isHigh;
   g_swings[n].sweptAt = -1;
   return(n);
  }

void AddZone(int type, bool bull, int i1, int from, double top, double bot)
  {
   int n = ArraySize(g_zones);
   ArrayResize(g_zones, n + 1, 256);
   g_zones[n].type   = type;
   g_zones[n].bull   = bull;
   g_zones[n].i1     = i1;
   g_zones[n].from   = from;
   g_zones[n].i2     = -1;
   g_zones[n].top    = top;
   g_zones[n].bot    = bot;
   g_zones[n].active = true;
  }

// Latest swing of one side that formed before bar `before`; -1 if none.
int PrevSwing(bool isHigh, int before)
  {
   for(int s = ArraySize(g_swings) - 1; s >= 0; s--)
      if(g_swings[s].isHigh == isHigh && g_swings[s].idx < before)
         return(s);
   return(-1);
  }

// Highest high or lowest low of the SMT symbol between two times.
bool OtherExtreme(datetime t1, datetime t2, bool wantLow, double &value)
  {
   double data[];
   int n = wantLow ? CopyLow(InpSMTSymbol, _Period, t1, t2, data)
                   : CopyHigh(InpSMTSymbol, _Period, t1, t2, data);
   if(n <= 0)
      return(false);
   value = wantLow ? data[ArrayMinimum(data)] : data[ArrayMaximum(data)];
   return(true);
  }

//+------------------------------------------------------------------+
//| SMT: this symbol runs liquidity past its previous swing while    |
//| the compared symbol fails to do the matching thing.              |
//+------------------------------------------------------------------+
void CheckSMT(const datetime &time[], int cur, bool isHigh, int n)
  {
   int prev = PrevSwing(isHigh, g_swings[cur].idx);
   if(prev < 0)
      return;
   int a = g_swings[prev].idx, b = g_swings[cur].idx;
   double pa = g_swings[prev].price, pb = g_swings[cur].price;
   if(isHigh ? (pb <= pa) : (pb >= pa))
      return;

   // A correlated symbol is compared on the same side, an inverse one on the opposite side.
   bool otherLow = InpSMTInverse ? isHigh : !isHigh;
   double oa, ob;
   if(!OtherExtreme(time[a - n], time[a + n], otherLow, oa) ||
      !OtherExtreme(time[b - n], time[b + n], otherLow, ob))
      return;
   bool diverges = otherLow ? (ob > oa) : (ob < oa);
   if(!diverges)
      return;

   DrawLine("SMT", time[a], pa, time[b], pb, InpSMTColor, STYLE_SOLID);
   DrawText("SMTt", time[b], pb, "SMT", InpSMTColor, isHigh ? ANCHOR_LEFT_LOWER : ANCHOR_LEFT_UPPER);
  }

//+------------------------------------------------------------------+
//| Last opposing candle(s) at a swing, scanning back from `from`    |
//| no further than `limit`. Merges up to InpBlockMaxCandles.        |
//+------------------------------------------------------------------+
bool FindBlock(const double &open[], const double &high[], const double &low[], const double &close[],
               int from, int limit, bool wantDownClose, int &at, double &top, double &bot)
  {
   int c = from;
   while(c >= limit && !(wantDownClose ? close[c] < open[c] : close[c] > open[c]))
      c--;
   if(c < limit)
      return(false);
   at  = c;
   top = high[c];
   bot = low[c];
   int merged = 1;
   while(merged < InpBlockMaxCandles && at - 1 >= limit &&
         (wantDownClose ? close[at - 1] < open[at - 1] : close[at - 1] > open[at - 1]))
     {
      at--;
      top = MathMax(top, high[at]);
      bot = MathMin(bot, low[at]);
      merged++;
     }
   return(true);
  }

//+------------------------------------------------------------------+
//| A close through a swing confirms the order block that started    |
//| the move and turns the broken swing into a breaker or mitigation |
//| block.                                                           |
//+------------------------------------------------------------------+
void OnStructureBreak(const double &open[], const double &high[], const double &low[], const double &close[],
                      int j, int brokenSwing, int start)
  {
   bool up = g_swings[brokenSwing].isHigh;      // true: close above a swing high
   int  s  = g_swings[brokenSwing].idx;

   // Extreme of the leg that preceded the break.
   int m = s + 1;
   for(int i = s + 1; i <= j; i++)
      if(up ? low[i] < low[m] : high[i] > high[m])
         m = i;
   double legExtreme = up ? low[m] : high[m];

   int prior = PrevSwing(!up, s);               // swing low before the high (or the reverse)
   bool ranLiquidity = (prior >= 0) &&
                       (up ? legExtreme < g_swings[prior].price : legExtreme > g_swings[prior].price);

   int at = 0;
   double top = 0, bot = 0;

   // Order block: last down-close candle(s) before the rally, last up-close before the drop.
   if(FindBlock(open, high, low, close, m, MathMax(s, start), up, at, top, bot))
     {
      bool validated = up ? close[j] > top : close[j] < bot;
      if(validated && (ranLiquidity || !InpOBRequireSweep))
         AddZone(ZONE_OB, up, at, j, top, bot);
     }

   // Breaker / mitigation block: last opposing candle(s) in the swing that just failed.
   if(prior >= 0 &&
      FindBlock(open, high, low, close, s, MathMax(g_swings[prior].idx, start), !up, at, top, bot))
      AddZone(ranLiquidity ? ZONE_BREAKER : ZONE_MB, up, at, j, top, bot);
  }

//+------------------------------------------------------------------+
//| Killzone boxes spanning each session's high and low.             |
//+------------------------------------------------------------------+
void DrawSession(const datetime &time[], const double &high[], const double &low[],
                 int start, int total, const string label, int fromMin, int toMin, color c)
  {
   long offset  = (long)InpServerMinusNY * 3600;
   long lastDay = ((long)time[total - 1] - offset) / 86400;
   int  st = -1;
   long stDay = 0;
   double hi = 0, lo = 0;

   for(int i = start; i <= total; i++)
     {
      bool inside = false;
      long day = 0;
      if(i < total)
        {
         long ny = (long)time[i] - offset;
         int  minuteOfDay = (int)((ny % 86400) / 60);
         day    = ny / 86400;
         inside = (minuteOfDay >= fromMin && minuteOfDay < toMin);
        }
      if(st >= 0 && (!inside || day != stDay))
        {
         if(lastDay - stDay < InpMaxKillzoneDays)
           {
            DrawRect("KZ", time[st], hi, time[i - 1], lo, c, false);
            DrawText("KZt", time[st], hi, label, c, ANCHOR_LEFT_LOWER);
           }
         st = -1;
        }
      if(inside)
        {
         if(st < 0)
           {
            st = i;
            stDay = day;
            hi = high[i];
            lo = low[i];
           }
         else
           {
            hi = MathMax(hi, high[i]);
            lo = MathMin(lo, low[i]);
           }
        }
     }
  }

//+------------------------------------------------------------------+
//| 12am New York opening price: buy below it on a buy day, sell     |
//| above it on a sell day.                                          |
//+------------------------------------------------------------------+
void DrawMidnightOpens(const datetime &time[], const double &open[], int start, int total)
  {
   long offset = (long)InpServerMinusNY * 3600;
   datetime endTime = time[total - 1] + PeriodSeconds();
   int drawn = 0;
   for(int i = total - 1; i > start && drawn < InpMidnightDays; i--)
     {
      long dayNow  = ((long)time[i] - offset) / 86400;
      long dayPrev = ((long)time[i - 1] - offset) / 86400;
      if(dayNow == dayPrev)
         continue;
      DrawLine("MNO", time[i], open[i], endTime, open[i], InpMidnightColor, STYLE_DOT);
      DrawText("MNOt", endTime, open[i], "12am Open", InpMidnightColor, ANCHOR_RIGHT_LOWER);
      endTime = time[i];
      drawn++;
     }
  }

//+------------------------------------------------------------------+
//| Dealing range from the latest major swing high and low, split at |
//| 50% into premium and discount.                                   |
//+------------------------------------------------------------------+
void DrawDealingRange(const datetime &time[], const double &high[], const double &low[], int start, int total)
  {
   int n = MathMax(1, InpRangeSwing);
   int hiIdx = -1, loIdx = -1;
   for(int k = total - 2 - n; k >= start + n && (hiIdx < 0 || loIdx < 0); k--)
     {
      if(hiIdx < 0 && IsSwingHigh(high, k, n))
         hiIdx = k;
      if(loIdx < 0 && IsSwingLow(low, k, n))
         loIdx = k;
     }
   if(hiIdx < 0 || loIdx < 0)
      return;

   double top = high[hiIdx], bot = low[loIdx];
   if(top <= bot)
      return;
   double eq = (top + bot) / 2.0;
   datetime t1 = time[MathMin(hiIdx, loIdx)];
   datetime t2 = time[total - 1] + 10 * PeriodSeconds();

   DrawLine("DR", t1, top, t2, top, InpRangeColor, STYLE_SOLID);
   DrawLine("DR", t1, eq,  t2, eq,  InpRangeColor, STYLE_DASH);
   DrawLine("DR", t1, bot, t2, bot, InpRangeColor, STYLE_SOLID);
   DrawText("DRt", t2, top, "Range high (external BSL)", InpRangeColor, ANCHOR_RIGHT_LOWER);
   DrawText("DRt", t2, eq,  "Premium",                   InpRangeColor, ANCHOR_RIGHT_LOWER);
   DrawText("DRt", t2, eq,  "Discount",                  InpRangeColor, ANCHOR_RIGHT_UPPER);
   DrawText("DRt", t2, bot, "Range low (external SSL)",  InpRangeColor, ANCHOR_RIGHT_UPPER);
  }

//+------------------------------------------------------------------+
void DrawZones(const datetime &time[], int total)
  {
   int shown[4] = {0, 0, 0, 0};
   for(int z = ArraySize(g_zones) - 1; z >= 0; z--)
     {
      if(!g_zones[z].active && !InpShowInvalidated)
         continue;

      int    type = g_zones[z].type;
      bool   bull = g_zones[z].bull;
      int    limit = 0;
      color  c = clrNONE;
      string label = "";
      switch(type)
        {
         case ZONE_FVG:
            if(!InpShowFVG)
               continue;
            limit = InpMaxFVG;
            c     = bull ? InpBISIColor : InpSIBIColor;
            label = bull ? "BISI" : "SIBI";
            break;
         case ZONE_OB:
            if(!InpShowOB)
               continue;
            limit = InpMaxOB;
            c     = bull ? InpBullOBColor : InpBearOBColor;
            label = bull ? "+OB" : "-OB";
            break;
         case ZONE_BREAKER:
            if(!InpShowBreaker)
               continue;
            limit = InpMaxBreaker;
            c     = bull ? InpBullBreakerColor : InpBearBreakerColor;
            label = bull ? "+BRK" : "-BRK";
            break;
         default:
            if(!InpShowMitigation)
               continue;
            limit = InpMaxBreaker;
            c     = bull ? InpBullMBColor : InpBearMBColor;
            label = bull ? "+MB" : "-MB";
            break;
        }
      if(shown[type] >= limit)
         continue;
      shown[type]++;

      datetime t1 = time[g_zones[z].i1];
      datetime t2 = g_zones[z].active ? time[total - 1] + 5 * PeriodSeconds() : time[g_zones[z].i2];
      double top = g_zones[z].top, bot = g_zones[z].bot;

      DrawRect("Z", t1, top, t2, bot, c, true);
      DrawText("Zt", t1, top, label, clrWhite, ANCHOR_LEFT_UPPER);

      bool midline = (type == ZONE_FVG) ? InpShowCE : (type == ZONE_OB ? InpShowMeanThreshold : false);
      if(midline)
         DrawLine("Zm", t1, (top + bot) / 2.0, t2, (top + bot) / 2.0, clrWhite, STYLE_DOT);
     }
  }

//+------------------------------------------------------------------+
void DrawLiquidity(const datetime &time[], int total)
  {
   int highs = 0, lows = 0;
   datetime t2 = time[total - 1] + 5 * PeriodSeconds();
   for(int s = ArraySize(g_swings) - 1; s >= 0; s--)
     {
      if(g_swings[s].sweptAt >= 0)
         continue;
      bool isHigh = g_swings[s].isHigh;
      if(isHigh ? highs >= InpMaxLiquidity : lows >= InpMaxLiquidity)
         continue;
      if(isHigh)
         highs++;
      else
         lows++;
      color c = isHigh ? InpBSLColor : InpSSLColor;
      DrawLine("LQ", time[g_swings[s].idx], g_swings[s].price, t2, g_swings[s].price, c, STYLE_DOT);
      DrawText("LQt", t2, g_swings[s].price, isHigh ? "BSL" : "SSL", c,
               isHigh ? ANCHOR_RIGHT_LOWER : ANCHOR_RIGHT_UPPER);
     }
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
   // Everything is derived from closed bars, so recalculate once per new bar.
   if(rates_total == prev_calculated)
      return(rates_total);

   ArraySetAsSeries(time, false);
   ArraySetAsSeries(open, false);
   ArraySetAsSeries(high, false);
   ArraySetAsSeries(low, false);
   ArraySetAsSeries(close, false);

   int n = MathMax(1, InpSwingStrength);
   if(rates_total < 4 * n + 10)
      return(0);

   ArrayInitialize(SwingHighBuf, EMPTY_VALUE);
   ArrayInitialize(SwingLowBuf, EMPTY_VALUE);
   ObjectsDeleteAll(0, PREFIX);
   g_objId = 0;
   ArrayResize(g_swings, 0, 256);
   ArrayResize(g_zones, 0, 256);

   int last  = rates_total - 2;                               // last closed bar
   int start = MathMax(0, last - MathMax(50, InpLookback));
   double minGap = InpFVGMinPoints * _Point;

   int curHigh = -1, curLow = -1;          // latest swing on each side
   bool highBroken = true, lowBroken = true;

   for(int j = start + 2; j <= last; j++)
     {
      // Old zones end when price closes through them.
      for(int z = ArraySize(g_zones) - 1; z >= 0; z--)
        {
         if(!g_zones[z].active || g_zones[z].from >= j)
            continue;
         if(g_zones[z].bull ? close[j] < g_zones[z].bot : close[j] > g_zones[z].top)
           {
            g_zones[z].active = false;
            g_zones[z].i2 = j;
           }
        }

      // Old highs and lows hold liquidity until price trades through them.
      for(int s = ArraySize(g_swings) - 1; s >= 0; s--)
        {
         if(g_swings[s].sweptAt >= 0)
            continue;
         if(g_swings[s].isHigh ? high[j] > g_swings[s].price : low[j] < g_swings[s].price)
            g_swings[s].sweptAt = j;
        }

      // Structure breaks.
      if(curHigh >= 0 && !highBroken && close[j] > g_swings[curHigh].price)
        {
         highBroken = true;
         OnStructureBreak(open, high, low, close, j, curHigh, start);
        }
      if(curLow >= 0 && !lowBroken && close[j] < g_swings[curLow].price)
        {
         lowBroken = true;
         OnStructureBreak(open, high, low, close, j, curLow, start);
        }

      // Fair value gap: the wicks of the first and third candle do not overlap.
      if(low[j] - high[j - 2] > minGap)
         AddZone(ZONE_FVG, true, j - 1, j, low[j], high[j - 2]);
      else
         if(low[j - 2] - high[j] > minGap)
            AddZone(ZONE_FVG, false, j - 1, j, low[j - 2], high[j]);

      // A swing at bar k is only known once n bars have closed after it.
      int k = j - n;
      if(k - n < start)
         continue;
      if(IsSwingHigh(high, k, n))
        {
         curHigh = AddSwing(k, high[k], true);
         highBroken = false;
         SwingHighBuf[k] = high[k];
         if(InpSMTSymbol != "")
            CheckSMT(time, curHigh, true, n);
        }
      if(IsSwingLow(low, k, n))
        {
         curLow = AddSwing(k, low[k], false);
         lowBroken = false;
         SwingLowBuf[k] = low[k];
         if(InpSMTSymbol != "")
            CheckSMT(time, curLow, false, n);
        }
     }

   DrawZones(time, rates_total);
   if(InpShowLiquidity)
      DrawLiquidity(time, rates_total);
   if(InpShowRange)
      DrawDealingRange(time, high, low, start, rates_total);

   // Sessions and the midnight open only make sense below the 4-hour chart.
   if(PeriodSeconds() <= 3600)
     {
      if(InpShowAsia)
         DrawSession(time, high, low, start, rates_total, "Asia", 20 * 60, 24 * 60, clrSlateGray);
      if(InpShowLondon)
         DrawSession(time, high, low, start, rates_total, "London", 2 * 60, 5 * 60, clrSteelBlue);
      if(InpShowNewYork)
         DrawSession(time, high, low, start, rates_total, "New York", 7 * 60, 10 * 60, clrSeaGreen);
      if(InpShowLondonClose)
         DrawSession(time, high, low, start, rates_total, "London Close", 10 * 60, 12 * 60, clrPeru);
      if(InpShowIndexAM)
         DrawSession(time, high, low, start, rates_total, "AM Session", 8 * 60 + 30, 12 * 60, clrSeaGreen);
      if(InpShowIndexPM)
         DrawSession(time, high, low, start, rates_total, "PM Session", 13 * 60 + 30, 16 * 60, clrMediumPurple);
      if(InpShowMidnightOpen)
         DrawMidnightOpens(time, open, start, rates_total);
     }

   ChartRedraw(0);
   return(rates_total);
  }
//+------------------------------------------------------------------+
