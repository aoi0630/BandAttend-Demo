import "./globals.css";

export const metadata = {
  title: "BandAttend",
  description: "吹奏楽部運営支援アプリ",
  manifest: "/manifest.json",
  appleWebApp: {
    capable: true,
    title: "BandAttend",
    statusBarStyle: "default",
  },
  icons: {
    icon: [
      { url: "/favicon.svg", type: "image/svg+xml" },
      { url: "/icon-192.png", sizes: "192x192", type: "image/png" },
      { url: "/icon-512.png", sizes: "512x512", type: "image/png" },
    ],
    apple: [{ url: "/apple-touch-icon.png", sizes: "180x180", type: "image/png" }],
  },
};

export const viewport = {
  themeColor: "#111111",
};

export default function RootLayout({ children }) {
  return (
    <html lang="ja">
      <head>
        <script
          dangerouslySetInnerHTML={{
            __html:
              'window.__bandAttendApiWarmup=fetch("/api/health?warm="+Date.now(),{cache:"no-store"});',
          }}
        />
      </head>
      <body>{children}</body>
    </html>
  );
}
