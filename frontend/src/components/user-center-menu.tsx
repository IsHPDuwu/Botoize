import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { LogOut, Monitor, Moon, Settings, Sun } from "lucide-react";
import { motion } from "framer-motion";
import { useQQAuth } from "@/hooks/use-qq-auth";
import { useTheme } from "@/hooks/use-theme";
import { cn } from "@/lib/utils";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { springs } from "@/components/ui/motion";

function ThemeToggle() {
  const { theme, setTheme } = useTheme();
  const { t } = useTranslation();
  const themes = [
    { value: "light", icon: Sun, label: t("theme.light") },
    { value: "dark", icon: Moon, label: t("theme.dark") },
    { value: "system", icon: Monitor, label: t("theme.system") },
  ] as const;

  return (
    <div className="flex items-center justify-between gap-2 px-2 py-1.5">
      <span className="text-sm text-muted-foreground">{t("theme.toggle")}</span>
      <div className="relative flex h-8 items-center rounded-full bg-muted p-1">
        {themes.map(({ value, icon: Icon, label }) => (
          <button
            key={value}
            type="button"
            title={label}
            aria-label={label}
            onClick={(event) => {
              event.preventDefault();
              event.stopPropagation();
              setTheme(value);
            }}
            className={cn(
              "relative z-10 flex h-6 w-8 items-center justify-center rounded-full transition-colors",
              theme === value ? "text-foreground" : "text-muted-foreground hover:text-foreground",
            )}
          >
            {theme === value && (
              <motion.span
                layoutId="qq-theme-toggle-indicator"
                className="absolute inset-0 rounded-full bg-background shadow-sm"
                transition={springs.snappy}
              />
            )}
            <Icon className="relative z-10 h-3.5 w-3.5" aria-hidden="true" />
          </button>
        ))}
      </div>
    </div>
  );
}

export function UserCenterMenu({
  collapsed = false,
  onNavigate,
}: {
  collapsed?: boolean;
  onNavigate?: () => void;
}) {
  const { user, logout } = useQQAuth();
  const navigate = useNavigate();
  const { t } = useTranslation();
  const role = user?.role ?? "";
  const initial = user?.username?.[0]?.toUpperCase() ?? "U";

  return (
    <DropdownMenu>
      <Tooltip>
        <TooltipTrigger asChild>
          <DropdownMenuTrigger asChild>
            <Button
              variant="ghost"
              size="sm"
              className={cn("group w-full", collapsed ? "justify-center px-2" : "justify-start gap-3 px-2.5")}
              aria-label={user ? `${user.username} · ${role}` : "账户菜单"}
            >
              <Avatar className="h-6 w-6 shrink-0">
                <AvatarFallback className="text-xs">{initial}</AvatarFallback>
              </Avatar>
              {!collapsed && (
                <div className="flex min-w-0 flex-1 flex-col items-start leading-tight">
                  <span className="truncate text-sm font-medium">{user?.username}</span>
                  <span className="truncate text-xs text-muted-foreground">{role} · QQ Bot Proxy</span>
                </div>
              )}
            </Button>
          </DropdownMenuTrigger>
        </TooltipTrigger>
        {collapsed && (
          <TooltipContent side="right" sideOffset={8}>
            <p className="font-medium">{user?.username}</p>
            <p className="text-xs text-muted-foreground">{role}</p>
          </TooltipContent>
        )}
      </Tooltip>
      <DropdownMenuContent align={collapsed ? "center" : "start"} side={collapsed ? "right" : "top"} className="w-72">
        <div className="flex items-center gap-2.5 px-2 py-1.5">
          <Avatar className="h-8 w-8 shrink-0">
            <AvatarFallback>{initial}</AvatarFallback>
          </Avatar>
          <div className="flex min-w-0 flex-1 flex-col">
            <div className="flex items-center justify-between gap-2">
              <span className="truncate text-sm font-medium">{user?.username}</span>
              <Badge variant="outline" className="shrink-0 px-1.5 py-0 text-xs font-normal text-muted-foreground">{role}</Badge>
            </div>
            <span className="truncate text-xs text-muted-foreground">QQ 官方机器人中转控制台</span>
          </div>
        </div>
        <DropdownMenuSeparator />
        <DropdownMenuGroup>
          <DropdownMenuItem onClick={() => { onNavigate?.(); navigate("/dashboard/admin-settings"); }}>
            <Settings data-icon="inline-start" aria-hidden="true" />
            接入与系统设置
          </DropdownMenuItem>
        </DropdownMenuGroup>
        <DropdownMenuSeparator />
        <DropdownMenuGroup>
          <DropdownMenuItem
            onClick={() => {
              onNavigate?.();
              void logout();
            }}
            className="text-error-foreground"
          >
            <LogOut data-icon="inline-start" aria-hidden="true" />
            {t("auth.signOut")}
          </DropdownMenuItem>
        </DropdownMenuGroup>
        <DropdownMenuSeparator />
        <div className="px-0 font-normal"><ThemeToggle /></div>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
