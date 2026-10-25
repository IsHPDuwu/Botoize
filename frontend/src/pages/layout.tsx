import { useState } from "react";
import { Navigate, Outlet, Link, useLocation } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Activity, BookOpen, Bot, Boxes, Cable, KeyRound, LayoutDashboard, LockKeyhole, Menu, PanelLeftClose, PanelLeftOpen, ScrollText, ServerCog, Users } from "lucide-react";
import { useQQAuth } from "@/hooks/use-qq-auth";
import { Button } from "@/components/ui/button";
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarProvider,
  SidebarSeparator,
  SidebarTrigger,
  useSidebar,
} from "@/components/ui/sidebar";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { motion } from "framer-motion";
import { cn } from "@/lib/utils";
import { MonoizeLogo } from "@/components/MonoizeLogo";
import { UserCenterMenu } from "@/components/user-center-menu";
import { springs } from "@/components/ui/motion";
import { DashboardScrollParentContext } from "@/lib/dashboard-scroll";
import { visibleProductRoutes } from "@/lib/product-routes";
import { resolveProductRoute } from "@/lib/product-routes";
import { EmptyState } from "@/components/ui/empty-state";

const navTransition = springs.snappy;
const navIcons: Record<string, React.ComponentType<{ className?: string }>> = {
  dashboard: LayoutDashboard,
  bot: Bot,
  key: KeyRound,
  groups: Boxes,
  logs: ScrollText,
  subscriptions: Cable,
  users: Users,
  settings: ServerCog,
  "api-info": BookOpen,
  playground: Activity,
  plans: Cable,
  models: Cable,
  wallet: Cable,
  payments: Cable,
};

function NavLink({
  to,
  icon: Icon,
  label,
  exact = false,
}: {
  to: string;
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  exact?: boolean;
}) {
  const location = useLocation();
  const { isMobile, state, setOpenMobile } = useSidebar();
  const isActive = exact
    ? location.pathname === to
    : location.pathname === to || location.pathname.startsWith(to + "/");

  return (
    <SidebarMenuItem>
      <SidebarMenuButton
        asChild
        isActive={isActive}
        tooltip={label}
        className="relative"
      >
        <Link
          to={to}
          onClick={() => setOpenMobile(false)}
          aria-current={isActive ? "page" : undefined}
          aria-label={label}
        >
          {isActive && !isMobile && (
            <motion.div
              layoutId={`nav-active-${state}`}
              className="absolute inset-0 rounded-md bg-sidebar-accent"
              transition={navTransition}
            />
          )}
          <Icon className={cn("relative", isActive && "text-primary")} />
          <span className="relative">{label}</span>
        </Link>
      </SidebarMenuButton>
    </SidebarMenuItem>
  );
}

function AppSidebar() {
  const { user } = useQQAuth();
  const { t } = useTranslation();
  const { isMobile, state, setOpenMobile, toggleSidebar } = useSidebar();
  const collapsed = !isMobile && state === "collapsed";
  const onNavigate = () => setOpenMobile(false);
  const visibleRoutes = visibleProductRoutes(user?.role);
  const navItems = visibleRoutes.filter((item) => !item.ownerOnly);
  const ownerNavItems = visibleRoutes.filter((item) => item.ownerOnly);

  return (
    <Sidebar variant="sidebar" collapsible="icon">
      <SidebarHeader className="p-3 group-data-[collapsible=icon]:items-center">
        {collapsed ? (
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="group size-10 p-1"
                aria-label={t("nav.expandSidebar")}
                aria-expanded={false}
                onClick={toggleSidebar}
              >
                <span className="relative flex size-8 items-center justify-center rounded-lg bg-foreground text-background shadow-sm">
                  <MonoizeLogo className="absolute inset-0 !size-full transition-opacity duration-150 group-hover:opacity-0 group-focus-visible:opacity-0" />
                  <PanelLeftOpen
                    data-icon="inline-start"
                    className="opacity-0 transition-opacity duration-150 group-hover:opacity-100 group-focus-visible:opacity-100"
                  />
                </span>
              </Button>
            </TooltipTrigger>
            <TooltipContent side="right" sideOffset={8}>
              {t("nav.expandSidebar")}
            </TooltipContent>
          </Tooltip>
        ) : (
          <div className="flex items-center gap-2">
            <Link
              to="/dashboard"
              onClick={onNavigate}
              className="group flex min-w-0 flex-1 items-center gap-3 rounded-lg px-2.5 py-2.5 transition-colors hover:bg-accent/50"
            >
              <motion.div
                whileHover={{ scale: 1.05 }}
                whileTap={{ scale: 0.95 }}
                transition={springs.snappy}
                className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-foreground text-background shadow-sm"
              >
                <MonoizeLogo className="size-full" />
              </motion.div>
              <div className="flex min-w-0 flex-col leading-none">
                <span className="truncate font-display text-sm font-semibold tracking-tight">
                  Monoize
                </span>
                <span className="mt-0.5 truncate text-xs text-muted-foreground">
                  QQ Bot Proxy
                </span>
              </div>
            </Link>
            {!isMobile && (
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    className="shrink-0"
                    aria-label={t("nav.collapseSidebar")}
                    aria-expanded={true}
                    onClick={toggleSidebar}
                  >
                    <PanelLeftClose data-icon="inline-start" />
                  </Button>
                </TooltipTrigger>
                <TooltipContent side="right" sideOffset={8}>
                  {t("nav.collapseSidebar")}
                </TooltipContent>
              </Tooltip>
            )}
          </div>
        )}
      </SidebarHeader>
      <SidebarSeparator className="mx-3" />
      <SidebarContent>
        <nav aria-label={t("nav.sidebarTitle")}>
          <SidebarGroup className="p-3 group-data-[collapsible=icon]:px-4">
            <SidebarGroupContent>
              <SidebarMenu>
                {navItems.map((item) => (
                  <NavLink key={item.path} to={item.path} icon={navIcons[item.icon] ?? Activity} label={item.title} exact={item.path === "/dashboard"} />
                ))}
              </SidebarMenu>
            </SidebarGroupContent>
          </SidebarGroup>
          {ownerNavItems.length > 0 && (
            <>
              <SidebarSeparator className="mx-3" />
              <SidebarGroup className="p-3 group-data-[collapsible=icon]:px-4">
                <SidebarGroupLabel>平台管理</SidebarGroupLabel>
                <SidebarGroupContent>
                  <SidebarMenu>
                    {ownerNavItems.map((item) => (
                      <NavLink key={item.path} to={item.path} icon={navIcons[item.icon] ?? Activity} label={item.title} />
                    ))}
                  </SidebarMenu>
                </SidebarGroupContent>
              </SidebarGroup>
            </>
          )}
        </nav>
      </SidebarContent>
      <SidebarFooter className="gap-3 p-3">
        <SidebarSeparator className="mx-0" />
        <UserCenterMenu collapsed={collapsed} onNavigate={onNavigate} />
      </SidebarFooter>
    </Sidebar>
  );
}

export function DashboardLayout() {
  const { user, loading } = useQQAuth();
  const { t } = useTranslation();
  const [mainPane, setMainPane] = useState<HTMLElement | null>(null);

  if (loading) {
    return (
      <div className="flex min-h-dvh items-center justify-center bg-background">
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          className="text-muted-foreground"
        >
          {t("common.loading")}
        </motion.div>
      </div>
    );
  }

  if (!user) {
    return <Navigate to="/login" replace />;
  }

  const route = resolveProductRoute(window.location.pathname, user.role);
  if (!route) {
    const hiddenRoute = window.location.pathname.startsWith("/dashboard/")
      ? window.location.pathname
      : "";
    return hiddenRoute ? (
      <div className="flex min-h-dvh items-center justify-center bg-background p-6">
        <EmptyState icon={<LockKeyhole />} title="页面未启用或无权访问" description="此功能没有对当前账号开放；请返回可用页面或联系平台 Owner。" action={<Link className="text-sm underline underline-offset-4" to="/dashboard">返回仪表盘</Link>} />
      </div>
    ) : <Navigate to="/dashboard" replace />;
  }

  return (
    <SidebarProvider className="h-dvh overflow-hidden bg-background">
      <AppSidebar />
      <SidebarTrigger
        variant="outline"
        className="fixed left-4 top-4 z-10 size-11 lg:hidden"
        aria-label={t("nav.openSidebar")}
      >
        <Menu aria-hidden="true" />
      </SidebarTrigger>

      <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden py-6 pt-16 lg:pt-6">
        {/* The pane spans the full width so its scrollbar sits at the viewport edge (DL7c). */}
        <main
          ref={setMainPane}
          className="flex min-h-0 min-w-0 w-full flex-1 flex-col overflow-y-auto px-6 lg:px-8"
        >
          <div className="mx-auto flex w-full min-w-0 max-w-6xl flex-1 flex-col">
            <DashboardScrollParentContext.Provider value={mainPane}>
              <Outlet />
            </DashboardScrollParentContext.Provider>
          </div>
        </main>
      </div>
    </SidebarProvider>
  );
}
