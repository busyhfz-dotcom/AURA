import { detectMarketStructure, type MarketStructure } from "./market-structure";

export type Candle = { time: number; open: number; high: number; low: number; close: number; volume: number };
export type Analysis = {
  symbol: string; market: "crypto" | "forex"; timeframe: string; source: string;
  price: number; priceTime: number; candleTime: number; candles: Candle[];
  change: number; ema20: number; ema50: number; rsi: number; atr: number;
  signal: "long" | "short" | "wait"; entry?: number; stop?: number; target?: number;
  rr?: number; setup?: "gap_retest" | "breakout"; structure: MarketStructure;
  reasons: string[]; risk: string[]; freshness: "fresh" | "stale";
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
  const structure=detectMarketStructure(completed,input.seconds,atr,input.price,input.market);
  const recent=completed.slice(-21,-1),high=Math.max(...recent.map(c=>c.high)),low=Math.min(...recent.map(c=>c.low));
  const fresh=now-input.priceTime<180000&&now-(last.time+input.seconds)*1000<input.seconds*2000+90000;
  const reasons:string[]=[],risk:string[]=[];
  let signal:Analysis["signal"]="wait",entry:number|undefined,stop:number|undefined,target:number|undefined,setup:Analysis["setup"];
  const closeToPrice=Math.abs(input.price-last.close)/last.close<.025;
  const trendUp=ema20>ema50&&input.price>ema20,trendDown=ema20<ema50&&input.price<ema20;
  reasons.push(trendUp?"میانگین ۲۰ دوره بالاتر از ۵۰ دوره است و قیمت بالای آن قرار دارد.":trendDown?"میانگین ۲۰ دوره پایین‌تر از ۵۰ دوره است و قیمت زیر آن قرار دارد.":"جهت روند کوتاه‌مدت تأیید نشده است.");
  reasons.push(`RSI چهارده‌دوره‌ای: ${momentum.toFixed(1)} · نوسان ATR: ${atr.toPrecision(4)}`);
  const confluence=structure.gaps.find(z => z.overlapCount>1 && z.swing && z.formedIndex<completed.length-1 &&
    Math.abs(input.price-last.close)<=atr*.5 && (
      z.direction==="bullish"
        ? trendUp && momentum>=45 && momentum<=68 && last.low<=z.upper && last.low>z.lower && last.close>z.upper && last.close>last.open && input.price>z.upper
        : trendDown && momentum>=32 && momentum<=55 && last.high>=z.lower && last.high<z.upper && last.close<z.lower && last.close<last.open && input.price<z.lower
    ));
  if(fresh&&closeToPrice&&atr>0&&confluence){
    const direction=confluence.direction;
    const proposedStop=direction==="bullish"
      ? Math.min(confluence.lower,confluence.swing!.price)-.15*atr
      : Math.max(confluence.upper,confluence.swing!.price)+.15*atr;
    const distance=Math.abs(input.price-proposedStop);
    if(distance<=3*atr){
      entry=input.price;stop=proposedStop;
      target=direction==="bullish"?entry+2*distance:entry-2*distance;
      signal=direction==="bullish"?"long":"short";setup="gap_retest";
      reasons.push("بازآزمایی شکاف‌های همپوشان کنار سوینگ تأییدشده با کندل برگشتی بسته شده است.");
    }
  }
  const opposingLong=structure.gaps.some(z=>z.direction==="bearish"&&z.lower>input.price&&z.lower-input.price<2*atr);
  const opposingShort=structure.gaps.some(z=>z.direction==="bullish"&&z.upper<input.price&&input.price-z.upper<2*atr);
  if(signal==="wait"&&fresh&&closeToPrice&&atr>0&&trendUp&&momentum>=52&&momentum<=68&&input.price>high&&input.price-high<atr*.8&&!opposingLong){
    entry=input.price;stop=Math.min(low,entry-1.5*atr);target=entry+2*(entry-stop);signal="long";
    setup="breakout";
    reasons.push("شکست سقف ۲۰ کندل اخیر با مومنتوم تأیید شده است.");
  }else if(signal==="wait"&&fresh&&closeToPrice&&atr>0&&trendDown&&momentum>=32&&momentum<=48&&input.price<low&&low-input.price<atr*.8&&!opposingShort){
    entry=input.price;stop=Math.max(high,entry+1.5*atr);target=entry-2*(stop-entry);signal="short";
    setup="breakout";
    reasons.push("شکست کف ۲۰ کندل اخیر با مومنتوم تأیید شده است.");
  }
  if(structure.focus){
    const z=structure.focus;
    reasons.push(`شکاف ${z.direction==="bullish"?"حمایتی":"مقاومتی"} در محدودهٔ ${z.lower.toPrecision(6)} تا ${z.upper.toPrecision(6)}؛ ${z.overlapCount>1?"همپوشانی "+z.overlapCount+" شکاف":"بدون همپوشانی"}${z.swing?" و نزدیک سوینگ تأییدشده":""}.`);
  }else reasons.push("شکاف فعال نزدیک قیمت شناسایی نشد.");
  if(signal==="wait")reasons.push("ترکیب شکاف، سوینگ و تأیید قیمت یا شروط شکست کامل نیست؛ فعلاً ورود مجاز نیست.");
  if(opposingLong||opposingShort)risk.push("شکاف فعال در جهت مخالف، فضای حرکت قیمت را محدود می‌کند.");
  if(!fresh)risk.push("داده تازه نیست؛ صدور سیگنال متوقف شده است.");
  if(!closeToPrice)risk.push("قیمت لحظه‌ای با آخرین کندل اختلاف غیرعادی دارد.");
  risk.push("همپوشانی شکاف و سوینگ احتمال عددی یا تضمین واکنش نیست؛ بدون آزمون تاریخی نمی‌توان نرخ موفقیت اعلام کرد.");
  risk.push("اسپرد، لغزش قیمت، خبرهای اقتصادی و کارمزد در نتیجهٔ این مدل لحاظ نشده‌اند.");
  return {...input,candles:completed,candleTime:last.time*1000,change:(input.price/completed.at(-25)!.close-1)*100,ema20,ema50,rsi:momentum,atr,signal,entry,stop,target,rr:signal==="wait"?undefined:2,setup,structure,reasons,risk,freshness:fresh?"fresh":"stale"};
}
