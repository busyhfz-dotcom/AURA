export type Candle = { time: number; open: number; high: number; low: number; close: number; volume: number };
export type Analysis = {
  symbol: string; market: "crypto" | "forex"; timeframe: string; source: string;
  price: number; priceTime: number; candleTime: number; candles: Candle[];
  change: number; ema20: number; ema50: number; rsi: number; atr: number;
  signal: "long" | "short" | "wait"; entry?: number; stop?: number; target?: number;
  rr?: number; reasons: string[]; risk: string[]; freshness: "fresh" | "stale";
};
function ema(values: number[], period: number) {
  let value = values.slice(0, period).reduce((a,b)=>a+b,0)/period;
  const k=2/(period+1);
  for (const next of values.slice(period)) value=next*k+value*(1-k);
  return value;
}
function rsi(values: number[]) {
  let gain=0,loss=0;
  const changes=values.slice(-15).map((v,i,a)=>i?v-a[i-1]:0).slice(1);
  for(const c of changes){gain+=Math.max(c,0);loss+=Math.max(-c,0);}
  return loss===0?100:100-100/(1+gain/loss);
}
export function analyze(input:{symbol:string;market:"crypto"|"forex";timeframe:string;source:string;candles:Candle[];price:number;priceTime:number;seconds:number}):Analysis {
  const candles=input.candles.filter(c=>[c.time,c.open,c.high,c.low,c.close].every(Number.isFinite)&&c.high>=c.low).sort((a,b)=>a.time-b.time);
  if(candles.length<60||!Number.isFinite(input.price)||input.price<=0)throw new Error("دادهٔ کافی برای تحلیل وجود ندارد.");
  const now=Date.now(), completed=candles.filter(c=>c.time*1000+input.seconds*1000<=now);
  if(completed.length<60)throw new Error("کندل‌های کامل کافی نیستند.");
  const last=completed.at(-1)!, closes=completed.map(c=>c.close);
  const ema20=ema(closes,20),ema50=ema(closes,50),momentum=rsi(closes);
  const window=completed.slice(-15);
  const trs=window.slice(1).map((c,i)=>Math.max(c.high-c.low,Math.abs(c.high-window[i].close),Math.abs(c.low-window[i].close)));
  const atr=trs.reduce((a,b)=>a+b,0)/trs.length;
  const recent=completed.slice(-21,-1),high=Math.max(...recent.map(c=>c.high)),low=Math.min(...recent.map(c=>c.low));
  const fresh=now-input.priceTime<180000&&now-(last.time+input.seconds)*1000<input.seconds*2000+90000;
  const reasons:string[]=[],risk:string[]=[];
  let signal:Analysis["signal"]="wait",entry:number|undefined,stop:number|undefined,target:number|undefined;
  const closeToPrice=Math.abs(input.price-last.close)/last.close<.025;
  const trendUp=ema20>ema50&&input.price>ema20,trendDown=ema20<ema50&&input.price<ema20;
  reasons.push(trendUp?"میانگین ۲۰ دوره بالاتر از ۵۰ دوره است و قیمت بالای آن قرار دارد.":trendDown?"میانگین ۲۰ دوره پایین‌تر از ۵۰ دوره است و قیمت زیر آن قرار دارد.":"جهت روند کوتاه‌مدت تأیید نشده است.");
  reasons.push(`RSI چهارده‌دوره‌ای: ${momentum.toFixed(1)} · نوسان ATR: ${atr.toPrecision(4)}`);
  if(fresh&&closeToPrice&&atr>0&&trendUp&&momentum>=52&&momentum<=68&&input.price>high&&input.price-high<atr*.8){
    entry=input.price;stop=Math.min(low,entry-1.5*atr);target=entry+2*(entry-stop);signal="long";
    reasons.push("شکست سقف ۲۰ کندل اخیر با مومنتوم تأیید شده است.");
  }else if(fresh&&closeToPrice&&atr>0&&trendDown&&momentum>=32&&momentum<=48&&input.price<low&&low-input.price<atr*.8){
    entry=input.price;stop=Math.max(high,entry+1.5*atr);target=entry-2*(stop-entry);signal="short";
    reasons.push("شکست کف ۲۰ کندل اخیر با مومنتوم تأیید شده است.");
  }else reasons.push("شرط شکست محدوده، روند و مومنتوم همزمان برقرار نیست؛ فعلاً ورود مجاز نیست.");
  if(!fresh)risk.push("داده تازه نیست؛ صدور سیگنال متوقف شده است.");
  if(!closeToPrice)risk.push("قیمت لحظه‌ای با آخرین کندل اختلاف غیرعادی دارد.");
  risk.push("اسپرد، لغزش قیمت، خبرهای اقتصادی و کارمزد در نتیجهٔ این مدل لحاظ نشده‌اند.");
  return {...input,candles:completed,candleTime:last.time*1000,change:(input.price/completed.at(-25)!.close-1)*100,ema20,ema50,rsi:momentum,atr,signal,entry,stop,target,rr:signal==="wait"?undefined:2,reasons,risk,freshness:fresh?"fresh":"stale"};
}
