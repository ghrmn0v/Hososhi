import type { Metadata } from 'next';
import { Suspense } from 'react';
import { IBM_Plex_Sans, Oswald, Shippori_Mincho } from 'next/font/google';
import './globals.css';
import { TopNav, Sawtooth } from '@/components/Chrome';

const plex = IBM_Plex_Sans({
  subsets: ['latin'],
  weight: ['400', '600'],
  variable: '--font-plex',
  display: 'swap',
});

const mincho = Shippori_Mincho({
  subsets: ['latin'],
  weight: ['600'],
  variable: '--font-mincho',
  display: 'swap',
});

const oswald = Oswald({
  subsets: ['latin'],
  weight: ['500'],
  variable: '--font-oswald',
  display: 'swap',
});

export const metadata: Metadata = {
  title: 'Hososhi — workflow intelligence',
  description:
    'Hososhi discovers the workflows a company actually runs, explains why each step exists, and automates only what is provably safe.',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${plex.variable} ${mincho.variable} ${oswald.variable}`}>
      <body>
        <Suspense fallback={<div className="top" />}>
          <TopNav />
        </Suspense>
        <Sawtooth />
        {children}
      </body>
    </html>
  );
}