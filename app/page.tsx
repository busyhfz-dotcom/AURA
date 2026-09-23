"use client";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Area, AreaChart, CartesianGrid, ReferenceArea, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Activity, ArrowDownLeft, ArrowUpRight, Bell, Check, ChevronLeft, Clock3, Crosshair, Info, RefreshCw, ShieldCheck, SlidersHorizontal, Wifi, WifiOff } from "lucide-react";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import type { Analysis } from "@/lib/analysis";

const groups={
  crypto:[["BTC-USD","بیت‌کوین"],["ETH-USD","اتریوم"],["SOL-USD","سولانا"],["XRP-USD","ریپل"]],
  forex:[["EUR_USD","یورو / دلار"],["GBP_USD","پوند / دلار"],["USD_JPY","دلار / ین"],["XAU_USD","طلا / دلار"]]
} as const;
const times=["15m","1h","4h","1d"] as const;
const persianTime:Record<string,string>={"15m":"۱۵ دقیقه","1h":"۱ ساعت","4h":"۴ ساعت","1d":"روزانه"};
const fmt=(n:number,symbol:string)=>new Intl.NumberFormat("en-US",{minimumFractionDigits:symbol==="USD_JPY"?2:symbol.includes("USD")&&!symbol.includes("-")?4:n>=100?2:n>=1?3:5,maximumFractionDigits:symbol==="USD_JPY"?2:symbol.includes("USD")&&!symbol.includes("-")?5:n>=100?2:n>=1?3:5}).format(n);
const clock=(n:number)=>new Intl.DateTimeFormat("fa-IR",{hour:"2-digit",minute:"2-digit",timeZone:"Asia/Tehran"}).format(n);
type Item={symbol:string;name:string};
export default function Home(){
  const [market,setMarket]=useState<"crypto"|"forex">("crypto");
  const [symbol,setSymbol]=useState("BTC-USD");
  const [timeframe,setTimeframe]=useState<string>("1h");
  const [data,setData]=useState<Record<string,Analysis>>({});
  const [error,setError]=useState<Record<string,string>>({});
  const [loading,setLoading]=useState(false);
  const [lastScan,setLastScan]=useState<number|null>(null);
  const [risk,setRisk]=useState(1);
  const [capital,setCapital]=useState(1000);
  const [copied,setCopied]=useState(false);
  const key=(s:string)=>`${s}:${timeframe}`;
  const scan=useCallback(async()=>{
    setLoading(true);
    const symbols=market==="crypto"?groups.crypto.map(x=>x[0]):[symbol];
    await Promise.all(symbols.map(async s=>{
      try{
        const res=await fetch(`/api/market?symbol=${s}&timeframe=${timeframe}`,{cache:"no-store"});
        const body=await res.json().catch(()=>({error:"پاسخ منبع داده معتبر نبود."})) as Analysis & {error?:string};
        if(!res.ok)throw new Error(body.error||"داده دریافت نشد.");
        setData(prev=>({...prev,[`${s}:${timeframe}`]:body as Analysis}));
        setError(prev=>({...prev,[`${s}:${timeframe}`]:""}));
      }catch(e){setData(prev=>{const next={...prev};delete next[`${s}:${timeframe}`];return next;});setError(prev=>({...prev,[`${s}:${timeframe}`]:e instanceof Error&&!e.message.startsWith("internal error")?e.message:"دریافت قیمت فعلاً ممکن نیست؛ کمی بعد دوباره بررسی کنید."}));}
    }));
    setLastScan(Date.now());setLoading(false);
  },[market,symbol,timeframe]);
  useEffect(()=>{scan();const timer=setInterval(scan,60000);return()=>clearInterval(timer);},[scan]);
  const current=data[key(symbol)];
  const currentError=error[key(symbol)];
  const list:Item[]=groups[market].map(([symbol,name])=>({symbol,name}));
  const chart=useMemo(()=>current?.candles.slice(-78).map(c=>({time:c.time,price:c.close})),[current]);
  const activeCount=list.filter(item=>data[key(item.symbol)]?.signal!=="wait"&&data[key(item.symbol)]?.freshness==="fresh"&&data[key(item.symbol)]).length;
  const riskAmount=capital*risk/100;
  const unitRisk=current?.entry&&current?.stop?Math.abs(current.entry-current.stop):0;
  const size=unitRisk?riskAmount/unitRisk:0;
  function changeMarket(value:"crypto"|"forex"){setMarket(value);setSymbol(groups[value][0][0]);}
  async function copyPlan(){
    if(!current?.entry||!current.stop||!current.target)return;
    await navigator.clipboard.writeText(`${current.symbol} | ${current.signal} | ${timeframe}\nEntry: ${current.entry}\nStop: ${current.stop}\nTarget: ${current.target}\nQuote: ${new Date(current.priceTime).toISOString()} | ${current.source}`);
    setCopied(true);setTimeout(()=>setCopied(false),1800);
  }
  return <div className="app-shell">
    <aside className="sidebar">
      <div className="brand"><div className="brand-icon"><Activity size={23}/></div><div><strong>دیدبان بازار</strong><span>MARKET SENTINEL</span></div></div>
      <div className="nav-label">فضای کاری</div>
      <a href="#market" className="nav-active"><Crosshair size={18}/> پایش بازار <span className="nav-mark"/></a>
      <a href="#analysis" className="nav-inert"><Activity size={18}/> تحلیل نمادها</a>
      <a href="#risk" className="nav-inert"><ShieldCheck size={18}/> مدیریت ریسک</a>
      <div className="sidebar-rule"/>
      <div className="nav-label">بازارهای تحت نظر</div>
      <button className={"market-nav "+(market==="crypto"?"chosen":"")} onClick={()=>changeMarket("crypto")}><span className="coin-mark">₿</span> رمزارز <span className="push">۲۴/۷</span></button>
      <button className={"market-nav "+(market==="forex"?"chosen":"")} onClick={()=>changeMarket("forex")}><span className="fx-mark">FX</span> فارکس <span className="push">۵ روز</span></button>
      <div className="sidebar-bottom"><span className="tiny-beacon"/><div><strong>پایش در زمان باز بودن پنل</strong><small>بازبینی خودکار هر ۶۰ ثانیه</small></div></div>
    </aside>
    <main className="main">
      <header className="topbar"><div className="mobile-brand">◈ <strong>دیدبان بازار</strong></div><div className="breadcrumb">فضای کاری <ChevronLeft size={14}/> <b>نمای کلی بازار</b></div><div className="top-actions"><span className="utc">ساعت تهران: {new Intl.DateTimeFormat("fa-IR",{hour:"2-digit",minute:"2-digit",timeZone:"Asia/Tehran"}).format(Date.now())}</span><div className="avatar">M</div></div></header>
      <div className="content">
        <div className="page-heading"><div><div className="eyebrow">MARKET INTELLIGENCE / 01</div><h1>رصد بازار، با انضباط معاملاتی.</h1><p>تحلیل قیمت و شناسایی موقعیت‌ها فقط پس از تأیید همزمان چند شرط.</p></div><div className="scan-pill"><span className={loading?"pulse-dot":"live-dot"}/>{loading?"در حال بررسی بازار":lastScan?`آخرین بررسی: ${clock(lastScan)}`:"در انتظار نخستین بررسی"}</div></div>
        <section className="summary-grid">
          <div className="summary-card"><div className="summary-label"><Crosshair size={17}/> بازار منتخب</div><strong>{market==="crypto"?"رمزارز":"فارکس"}</strong><span>{market==="crypto"?"معامله در تمام روزهای هفته":"معامله در روزهای کاری"}</span></div>
          <div className="summary-card"><div className="summary-label"><Activity size={17}/> نمادهای پایش شده</div><strong>{market==="crypto"?"۰۴":"۰۴"}</strong><span>{market==="forex"?"نیازمند اتصال دادهٔ OANDA":"دادهٔ عمومی Coinbase"}</span></div>
          <div className="summary-card"><div className="summary-label"><ArrowUpRight size={17}/> موقعیت تأیید شده</div><strong>{market==="crypto"?new Intl.NumberFormat("fa-IR").format(activeCount):"—"}</strong><span>سیگنال فقط با دادهٔ تازه</span></div>
          <div className="summary-card highlight"><div className="summary-label"><ShieldCheck size={17}/> ریسک پیشنهادی هر معامله</div><strong>{new Intl.NumberFormat("fa-IR").format(risk)}٪ <span className="small-strong">از سرمایه</span></strong><span>قابل تغییر در محاسبه‌گر پایین</span></div>
        </section>
        <div className="work-heading" id="market"><div><h2>نمای زندهٔ بازار</h2><p>نماد و بازهٔ زمانی را انتخاب کنید تا جزئیات تحلیل نمایش داده شود.</p></div><div className="controls"><Tabs value={market} onValueChange={v=>changeMarket(v as "crypto"|"forex")}><TabsList><TabsTrigger value="crypto">رمزارز</TabsTrigger><TabsTrigger value="forex">فارکس</TabsTrigger></TabsList></Tabs><Select value={timeframe} onValueChange={v=>setTimeframe(v||"1h")}><SelectTrigger className="time-select"><SelectValue/></SelectTrigger><SelectContent>{times.map(t=><SelectItem key={t} value={t}>{persianTime[t]}</SelectItem>)}</SelectContent></Select><Button variant="outline" size="icon" onClick={scan} disabled={loading} aria-label="بروزرسانی"><RefreshCw size={17} className={loading?"spin":""}/></Button></div></div>
        <div className="workspace-grid"><section className="watchlist panel"><div className="panel-head"><h3>فهرست نمادها</h3><span>{list.length} نماد</span></div><div className="watch-items">{list.map(item=>{const d=data[key(item.symbol)];return <button key={item.symbol} className={"watch-row "+(symbol===item.symbol?"selected":"")} onClick={()=>setSymbol(item.symbol)}><span className="watch-symbol"><strong dir="ltr">{item.symbol.replace("_","/")}</strong><small>{item.name}</small></span><span className="watch-price">{d?<><b dir="ltr">{fmt(d.price,item.symbol)}</b><small className={d.change>=0?"positive":"negative"} dir="ltr">{d.change>=0?"+":""}{d.change.toFixed(2)}%</small></>:<small>{market==="forex"?"نیازمند اتصال":error[key(item.symbol)]?"داده ناموجود":"در حال دریافت"}</small>}</span></button>})}</div><div className="watch-foot"><Wifi size={15}/> {market==="crypto"?"منبع: Coinbase Exchange":"منبع: OANDA پس از اتصال"}</div></section>
        <section className="chart-panel panel"><div className="chart-head"><div><span className="chart-kicker">نمودار قیمت · {persianTime[timeframe]}</span><h2 dir="ltr">{symbol.replace("_","/")} <span> / {list.find(x=>x.symbol===symbol)?.name}</span></h2></div>{current?<div className="price-block"><strong dir="ltr">{fmt(current.price,symbol)}</strong><span className={current.change>=0?"positive":"negative"} dir="ltr">{current.change>=0?"+":""}{current.change.toFixed(2)}% در ۲۴ دوره</span></div>:null}</div>
          {current&&chart?<><div className="chart-meta"><span><span className="legend-line"/> قیمت بسته‌شدن</span><span><span className="legend-line dotted"/> میانگین ۲۰ دوره</span></div><div className="chart"><ResponsiveContainer width="100%" height="100%"><AreaChart data={chart} margin={{top:14,right:6,bottom:0,left:12}}><defs><linearGradient id="pricefill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#26b69a" stopOpacity={.23}/><stop offset="100%" stopColor="#26b69a" stopOpacity={0}/></linearGradient></defs><CartesianGrid vertical={false} stroke="#263340" strokeDasharray="3 5"/><XAxis dataKey="time" tickFormatter={v=>clock(v*1000)} stroke="#667783" tickLine={false} axisLine={false} minTickGap={28} tick={{fontSize:11}}/><YAxis domain={["auto","auto"]} orientation="left" tickFormatter={v=>Number(v).toLocaleString("en-US",{maximumFractionDigits:v<10?3:0})} stroke="#667783" tickLine={false} axisLine={false} width={66} tick={{fontSize:11}}/><Tooltip labelFormatter={v=>new Date(Number(v)*1000).toLocaleString("fa-IR",{timeZone:"Asia/Tehran"})} formatter={v=>[fmt(Number(v),symbol),"قیمت"]} contentStyle={{background:"#14232d",border:"1px solid #30434e",borderRadius:10,color:"#f2f8f6"}}/>{current.structure?.focus && chart.length > 1 && <ReferenceArea x1={Math.max(current.structure.focus.formedAt,chart[0].time)} x2={chart.at(-1)!.time} y1={current.structure.focus.lower} y2={current.structure.focus.upper} fill={current.structure.focus.direction==="bullish"?"#3fcaa4":"#f0938c"} fillOpacity={.15} strokeOpacity={.4} stroke={current.structure.focus.direction==="bullish"?"#3fcaa4":"#f0938c"}/>}<ReferenceLine y={current.structure?.latestHigh?.price} stroke="#e18481" strokeDasharray="2 5" strokeOpacity={.7}/><ReferenceLine y={current.structure?.latestLow?.price} stroke="#57b9d1" strokeDasharray="2 5" strokeOpacity={.7}/><ReferenceLine y={current.ema20} stroke="#e8b26a" strokeDasharray="5 5" strokeWidth={1.4}/><Area type="monotone" dataKey="price" stroke="#32ccb0" strokeWidth={2.5} fill="url(#pricefill)" isAnimationActive={false}/></AreaChart></ResponsiveContainer></div><div className="chart-footer"><span><Clock3 size={15}/> آخرین قیمت: {clock(current.priceTime)} تهران</span><span>آخرین کندل کامل: {clock(current.candleTime)} تهران</span></div></>:<div className="chart-empty"><WifiOff size={30}/><strong>{currentError?"دادهٔ قابل اتکا در دسترس نیست":"در حال دریافت دادهٔ بازار..."}</strong><span>{currentError||"نمودار پس از دریافت قیمت‌های واقعی نمایش داده می‌شود."}</span></div>}
        </section>
        <section className="signal-panel panel"><div className="panel-head"><h3>ارزیابی موقعیت</h3><span className="evaluation-icon"><SlidersHorizontal size={17}/></span></div>{current?<><div className={"signal-state "+(current.signal==="wait"?"waiting":current.signal)}><span className="state-icon">{current.signal==="long"?<ArrowUpRight size={24}/>:current.signal==="short"?<ArrowDownLeft size={24}/>:<Crosshair size={22}/>}</span><div><small>وضعیت فعلی</small><strong>{current.signal==="long"?"شرایط خرید برقرار":current.signal==="short"?"شرایط فروش برقرار":"فعلاً ورود نکنید"}</strong></div></div><p className="state-explain">{current.signal==="wait"?"شکاف‌ها، سوینگ‌ها و روند بررسی شدند؛ ورود فقط با تأیید بازآزمایی یا شکست معتبر مجاز است.":"شرایط مدل برقرار است. پیش از هر تصمیم، قیمت اجرای واقعی، اسپرد و رویدادهای خبری را بررسی کنید."}</p>{current.setup&&<div className="setup-label">نوع سناریو: {current.setup==="gap_retest"?"بازآزمایی شکاف و سوینگ":"شکست محدوده"}</div>}<div className="levels"><div><span>نقطه ورود</span><strong dir="ltr">{current.entry?fmt(current.entry,symbol):"—"}</strong></div><div><span>حد ضرر</span><strong dir="ltr">{current.stop?fmt(current.stop,symbol):"—"}</strong></div><div><span>هدف اول</span><strong dir="ltr">{current.target?fmt(current.target,symbol):"—"}</strong></div></div><div className="ratio"><span>نسبت سود به زیان</span><strong dir="ltr">{current.rr?`1 : ${current.rr.toFixed(1)}`:"—"}</strong></div><Button className="copy-button" disabled={current.signal==="wait"} onClick={copyPlan}>{copied?<Check size={17}/>:<Bell size={17}/>} {copied?"طرح کپی شد":"کپی طرح معامله"}</Button><div className="signal-source"><span className={current.freshness==="fresh"?"live-dot":"stale-dot"}/>{current.freshness==="fresh"?"داده تازه":"داده قدیمی"} · {current.source}</div></>:<div className="signal-empty"><Info size={23}/><strong>هنوز ارزیابی نداریم</strong><span>{currentError?"پس از اتصال یا بازیابی منبع داده، تحلیل انجام می‌شود.":"در حال بررسی داده‌های قیمت..."}</span></div>}</section></div>
        <div className="bottom-grid"><section className="analysis-card panel" id="analysis"><div className="section-title"><div><h3>منطق تحلیل</h3><p>چرا پنل این وضعیت را نشان می‌دهد؟</p></div><Activity size={19}/></div>{current?<><div className="indicators"><div><span>EMA ۲۰</span><strong dir="ltr">{fmt(current.ema20,symbol)}</strong></div><div><span>EMA ۵۰</span><strong dir="ltr">{fmt(current.ema50,symbol)}</strong></div><div><span>RSI ۱۴</span><strong dir="ltr">{current.rsi.toFixed(1)}</strong></div><div><span>ATR ۱۴</span><strong dir="ltr">{fmt(current.atr,symbol)}</strong></div></div><ul className="reason-list">{current.reasons.map((r,i)=><li key={i}><span className="reason-bullet"/>{r}</li>)}</ul></>:<p className="muted-message">بعد از دریافت دادهٔ معتبر، توضیح شاخص‌ها و شروط ورود در این بخش نشان داده می‌شود.</p>}</section>
        <section className="risk-card panel" id="risk"><div className="section-title"><div><h3>محاسبه‌گر اندازهٔ معامله</h3><p>بر اساس ریسک ثابت از سرمایه</p></div><ShieldCheck size={20}/></div><div className="risk-fields"><label>سرمایه (دلار)<input type="number" min="1" value={capital} onChange={e=>setCapital(Math.max(0,Number(e.target.value)||0))} dir="ltr"/></label><label>ریسک هر معامله<select value={risk} onChange={e=>setRisk(Number(e.target.value))}><option value={.5}>۰٫۵٪</option><option value={1}>۱٪</option><option value={2}>۲٪</option></select></label></div><div className="risk-result"><div><span>زیان برنامه‌ریزی شده</span><strong dir="ltr">${riskAmount.toFixed(2)}</strong></div><div><span>حجم نظری بر اساس فاصلهٔ حد ضرر</span><strong dir="ltr">{size?size.toLocaleString("en-US",{maximumFractionDigits:5}):"—"}</strong></div></div><p className="risk-note">حجم نظری به واحد دارایی است و اندازهٔ لات فارکس نیست. پیش از معامله، مشخصات قرارداد و هزینه‌ها را در کارگزار بررسی کنید.</p></section></div>
        <section className="structure-card panel" id="structure"><div className="section-title"><div><h3>شکاف‌ها و Swing High / Low</h3><p>ناحیه‌های فعال، همپوشانی و سوینگ‌های تأییدشده در همین بازهٔ زمانی</p></div><Crosshair size={20}/></div>{current?.structure?<><div className="structure-summary"><div><span>شکاف‌های فعال</span><strong>{new Intl.NumberFormat("fa-IR").format(current.structure.activeGapCount)}</strong></div><div><span>آخرین Swing High</span><strong dir="ltr">{current.structure.latestHigh?fmt(current.structure.latestHigh.price,symbol):"—"}</strong></div><div><span>آخرین Swing Low</span><strong dir="ltr">{current.structure.latestLow?fmt(current.structure.latestLow.price,symbol):"—"}</strong></div></div><div className="gap-list">{current.structure.gaps.length?current.structure.gaps.slice(0,3).map((z,i)=><div className="gap-item" key={`${z.formedAt}-${z.kind}-${i}`}><div className="gap-title"><strong>{z.direction==="bullish"?"شکاف حمایتی":"شکاف مقاومتی"}</strong><span>{z.kind==="fvg"?"عدم تعادل سه‌کندلی":"شکاف بین کندل‌ها"}</span></div><div className="gap-range" dir="ltr">{fmt(z.lower,symbol)} — {fmt(z.upper,symbol)}</div><div className="gap-tags"><span>{z.overlapCount>1?`${new Intl.NumberFormat("fa-IR").format(z.overlapCount)} شکاف همپوشان`:"بدون همپوشانی"}</span><span>{z.swing?`نزدیک Swing ${z.swing.kind==="low"?"Low":"High"}`:"سوینگ نزدیک ندارد"}</span><span>{Math.round(z.fillPercent)}٪ پرشده</span></div></div>):<p className="muted-message">شکاف فعال معتبر در داده‌های این بازه پیدا نشد.</p>}</div><p className="structure-note">ناحیهٔ رنگی روی نمودار، نزدیک‌ترین شکاف فعال منتخب است. گپ سه‌کندلی با گپ واقعی بین دو کندل تفاوت دارد؛ همپوشانی به‌تنهایی احتمال موفقیت عددی نمی‌سازد.</p><ul className="risk-warnings">{current.risk.map((message,i)=><li key={i}>{message}</li>)}</ul></>:<p className="muted-message">پس از دریافت دادهٔ معتبر، ناحیه‌های شکاف و سوینگ در این بخش نمایش داده می‌شوند.</p>}</section>
        <footer className="footer"><span>این پنل ابزار تحلیل است؛ عملکرد گذشته یا نسبت ۱:۲، سود آینده را تضمین نمی‌کند.</span><span>بازبینی خودکار فقط هنگام باز بودن این صفحه فعال است.</span></footer>
      </div>
    </main>
  </div>;
}
