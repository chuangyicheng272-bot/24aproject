import "./globals.css";

export const metadata = {
  title: "Construction Safety Monitor",
  description: "Real-time worker safety monitoring interface"
};

export default function RootLayout({ children }) {
  return (
    <html lang="zh-Hant">
      <body>{children}</body>
    </html>
  );
}
