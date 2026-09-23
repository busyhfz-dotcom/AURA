import { NextRequest, NextResponse } from "next/server";
import { analyze, type Candle } from "@/lib/analysis";
const crypto=new Set(["BTC-USD","ETH-USD","SOL-USD","XRP-USD"]);
const forex=new Set(["EUR_USD","GBP_USD","USD_JPY","XAU_USD"]);
const intervals:Record<string,{coinbase:number;oanda:string}>={"15m":{coinbase:900,oanda:"M15"},"1h":{coinbase:3600,oanda:"H1"},"4h":{coinbase:21600,oanda:"H4"},"1d":{coinbase:86400,oanda:"D"}};
export const dynamic="force-dynamic";
export async function GET(req:NextRequest){
  const symbol=req.nextUrl.searchParams.get("symbol")||"BTC-USD",timeframe=req.nextUrl.searchParams.get("timeframe")||"1h",interval=intervals[timeframe];
  if(!interval||(!crypto.has(symbol)&&!forex.has(symbol)))return NextResponse.json({error:"نماد یا بازهٔ زمانی نامعتبر است."},{status:400});
  const market=crypto.has(symbol)?"crypto":"forex";
  if(market==="forex"&&(!process.env.OANDA_API_TOKEN||!process.env.OANDA_ACCOUNT_ID))
    return NextResponse.json({error:"اتصال دادهٔ فارکس هنوز فعال نشده است. کلید OANDA و شناسهٔ حساب باید در تنظیمات امن سرور ثبت شوند.",code:"PROVIDER_NOT_CONFIGURED"},{status:503});
  try{
    let candles:Candle[],price:number,priceTime:number;
    if(market==="crypto"){
      const base=`https://api.exchange.coinbase.com/products/${symbol}`,headers={Accept:"application/json","User-Agent":"MarketSentinel/1.0"};
      const [cRes,pRes]=await Promise.all([
        fetch(`${base}/candles?granularity=${interval.coinbase}`,{headers,signal:AbortSignal.timeout(8000),next:{revalidate:45}}),
        fetch(`${base}/ticker`,{headers,signal:AbortSignal.timeout(8000),cache:"no-store"})
      ]);
      if(!cRes.ok||!pRes.ok)throw new Error("دریافت داده از Coinbase ناموفق بود.");
      const raw=await cRes.json() as number[][],ticker=await pRes.json() as {price:string;time:string};
      candles=raw.map(([time,low,high,open,close,volume])=>({time,low,high,open,close,volume}));
      price=Number(ticker.price);priceTime=Date.parse(ticker.time);
    }else{
      const host=process.env.OANDA_ENVIRONMENT==="live"?"https://api-fxtrade.oanda.com":"https://api-fxpractice.oanda.com";
      const headers={Authorization:`Bearer ${process.env.OANDA_API_TOKEN}`,Accept:"application/json"};
      const [cRes,pRes]=await Promise.all([
        fetch(`${host}/v3/instruments/${symbol}/candles?count=200&granularity=${interval.oanda}&price=M`,{headers,signal:AbortSignal.timeout(8000),cache:"no-store"}),
        fetch(`${host}/v3/accounts/${encodeURIComponent(process.env.OANDA_ACCOUNT_ID!)}/pricing?instruments=${symbol}`,{headers,signal:AbortSignal.timeout(8000),cache:"no-store"})
      ]);
      if(!cRes.ok||!pRes.ok)throw new Error(`دریافت داده از OANDA ناموفق بود (${cRes.status}/${pRes.status}).`);
      const raw=await cRes.json() as {candles:{time:string;complete:boolean;mid:{o:string;h:string;l:string;c:string};volume:number}[]};
      const quote=await pRes.json() as {prices:{time:string;bids:{price:string}[];asks:{price:string}[]}[]};
      const q=quote.prices[0];if(!q?.bids[0]||!q?.asks[0])throw new Error("قیمت قابل معامله دریافت نشد.");
      candles=raw.candles.filter(c=>c.complete).map(c=>({time:Date.parse(c.time)/1000,open:Number(c.mid.o),high:Number(c.mid.h),low:Number(c.mid.l),close:Number(c.mid.c),volume:c.volume}));
      price=(Number(q.bids[0].price)+Number(q.asks[0].price))/2;priceTime=Date.parse(q.time);
    }
    return NextResponse.json(analyze({symbol,market,timeframe,source:market==="crypto"?"Coinbase Exchange":"OANDA",candles,price,priceTime,seconds:interval.coinbase}),{headers:{"Cache-Control":"private, max-age=30"}});
  }catch(e){return NextResponse.json({error:e instanceof Error?e.message:"داده در دسترس نیست.",code:"DATA_UNAVAILABLE"},{status:503});}
}
