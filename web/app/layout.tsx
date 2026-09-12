import type { Metadata } from "next";
import "./globals.css";
import PlanProvider from "./components/PlanProvider";
import RoleProvider from "./components/RoleProvider";
import Sidebar from "./components/Sidebar";
import TopBar from "./components/TopBar";

export const metadata: Metadata = {
  title: "TRACKSEN — Railway Maintenance Control Centre",
  description:
    "AI-Powered Railway Maintenance Intelligence & Planning. Coordinated block planning "
    + "across Engineering, S&T and Traction Distribution.",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>
        <RoleProvider>
          <PlanProvider>
            <Sidebar />
            <TopBar />
            <main
              className="min-h-screen"
              style={{
                marginLeft: "var(--sidebar-w)",
                paddingTop: "var(--topbar-h)",
              }}
            >
              <div className="p-5 mx-auto" style={{ maxWidth: 1560 }}>{children}</div>
            </main>
          </PlanProvider>
        </RoleProvider>
      </body>
    </html>
  );
}
