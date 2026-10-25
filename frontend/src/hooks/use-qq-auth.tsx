/* eslint-disable react-refresh/only-export-components */
import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { useSWRConfig } from "swr";
import { clearManagementSession, onUnauthorized, qqApi, type SessionUser } from "@/lib/qq-api";

interface AuthContextValue {
  user: SessionUser | null;
  loading: boolean;
  login: (username: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  refreshUser: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function QQAuthProvider({ children }: { children: ReactNode }) {
  const { cache, mutate } = useSWRConfig();
  const [user, setUser] = useState<SessionUser | null>(null);
  const [loading, setLoading] = useState(true);

  const clearAuthenticatedCache = useCallback(async () => {
    await mutate(() => true, undefined, { revalidate: false });
    if (cache instanceof Map) cache.clear();
  }, [cache, mutate]);

  const refreshUser = useCallback(async () => {
    try {
      setUser(await qqApi.me());
    } catch {
      setUser(null);
      await clearAuthenticatedCache();
    }
  }, [clearAuthenticatedCache]);

  useEffect(() => {
    const unsubscribe = onUnauthorized(() => {
      setUser(null);
      void clearAuthenticatedCache();
    });
    void Promise.resolve().then(refreshUser).finally(() => setLoading(false));
    return unsubscribe;
  }, [clearAuthenticatedCache, refreshUser]);

  const login = async (username: string, password: string) => {
    await clearAuthenticatedCache();
    setUser(await qqApi.login(username, password));
  };

  const logout = async () => {
    try {
      await qqApi.logout();
    } finally {
      clearManagementSession();
      setUser(null);
      await clearAuthenticatedCache();
    }
  };

  return <AuthContext.Provider value={{ user, loading, login, logout, refreshUser }}>{children}</AuthContext.Provider>;
}

export function useQQAuth() {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useQQAuth must be used within QQAuthProvider");
  return value;
}
