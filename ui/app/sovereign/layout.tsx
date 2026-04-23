import { Metadata, Viewport } from 'next';

export const metadata: Metadata = {
  title: 'Sovereign Operating Interface | Assistant OS',
  description: 'MSO-centric control interface for the governed multi-agent system',
};

export const viewport: Viewport = {
  themeColor: '#0f172a',
  width: 'device-width',
  initialScale: 1,
};

export default function SovereignLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return <>{children}</>;
}
