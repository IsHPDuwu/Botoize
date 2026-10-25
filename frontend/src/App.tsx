import { Routes, Route, Navigate } from "react-router-dom";
import { SWRConfig } from "swr";
import { MotionConfig } from "framer-motion";
import { QQAuthProvider } from "@/hooks/use-qq-auth";
import { ThemeProvider } from "@/hooks/use-theme";
import { Toaster } from "@/components/ui/sonner";
import { LoginPage } from "@/pages/qq-login";
import { DashboardLayout } from "@/pages/layout";
import { DashboardPage } from "@/pages/qq/dashboard";
import { ProvidersPage } from "@/pages/qq/providers";
import { TokensPage } from "@/pages/qq/tokens";
import { UsersPage } from "@/pages/qq/users";
import { GroupsPage } from "@/pages/qq/groups";
import { LogsPage } from "@/pages/qq/logs";
import { SettingsPage } from "@/pages/qq/settings";
import { ApiInfoPage } from "@/pages/qq/api-info";
import { SubscriptionsPage } from "@/pages/qq/subscriptions";
import "@/i18n";

function App() {
  return (
    <MotionConfig reducedMotion="user">
      <ThemeProvider>
        <SWRConfig
          value={{
            revalidateOnFocus: true,
            revalidateOnReconnect: true,
            dedupingInterval: 2000,
          }}
        >
          <QQAuthProvider>
            <Routes>
              <Route path="/login" element={<LoginPage />} />
              {/* Dashboard routes - admin panel */}
              <Route path="/dashboard" element={<DashboardLayout />}>
                <Route index element={<DashboardPage />} />
                <Route path="providers" element={<ProvidersPage />} />
                <Route path="tokens" element={<TokensPage />} />
                <Route path="logs" element={<LogsPage />} />
                <Route path="subscriptions" element={<SubscriptionsPage />} />
                <Route path="users" element={<UsersPage />} />
                <Route path="groups" element={<GroupsPage />} />
                <Route path="admin-settings" element={<SettingsPage />} />
                <Route path="api-info" element={<ApiInfoPage />} />
              </Route>
              {/* Redirect root to dashboard */}
              <Route path="/" element={<Navigate to="/dashboard" replace />} />
              <Route path="*" element={<Navigate to="/dashboard" replace />} />
            </Routes>
          </QQAuthProvider>
        </SWRConfig>
        <Toaster />
      </ThemeProvider>
    </MotionConfig>
  );
}

export default App;
