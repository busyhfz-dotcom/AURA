import dynamic from 'next/dynamic';
import Head from 'next/head';

const TradingTerminal = dynamic(() => import('../components/TradingTerminal'), { ssr: false });

export default function Home() {
  return (
    <>
      <Head>
        <title>AURA — Institutional Trading Intelligence</title>
        <meta name="description" content="AURA is an institutional-style market intelligence, risk and execution workspace." />
        <meta name="theme-color" content="#020811" />
        <meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1" />
      </Head>
      <TradingTerminal />
    </>
  );
}
