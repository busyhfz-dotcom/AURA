import type { AppProps } from 'next/app';
import Head from 'next/head';
import '../styles/globals.css';

export default function App({ Component, pageProps }: AppProps) {
  return (
    <>
      <Head>
        <title>VERTEX — Global Market Intelligence</title>
        <meta name="description" content="Monitor crypto and forex market structure, risk, signals, and economic news in one live workspace." />
        <meta name="theme-color" content="#030b15" />
        <meta property="og:title" content="VERTEX — Global Market Intelligence" />
        <meta property="og:description" content="Live market monitoring and explainable risk analysis for crypto and forex." />
        <meta property="og:type" content="website" />
        <link rel="icon" type="image/svg+xml" href="/vertex-mark.svg" />
      </Head>
      <Component {...pageProps} />
    </>
  );
}
