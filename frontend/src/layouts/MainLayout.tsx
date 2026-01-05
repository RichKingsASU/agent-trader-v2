import { ReactNode, useState, useEffect } from "react";
import { SidebarProvider, SidebarTrigger } from "@/components/ui/sidebar";
import { AppSidebar } from "@/components/AppSidebar";
import { ShadowModeIndicator } from "@/components/ShadowModeIndicator";

const SIDEBAR_STORAGE_KEY = "sidebar-open";

interface MainLayoutProps {
  children: ReactNode;
}

export function MainLayout({ children }: MainLayoutProps) {
  const [open, setOpen] = useState(() => {
    const stored = localStorage.getItem(SIDEBAR_STORAGE_KEY);
    return stored !== null ? stored === "true" : true;
  });

  useEffect(() => {
    localStorage.setItem(SIDEBAR_STORAGE_KEY, String(open));
  }, [open]);

  return (
    <SidebarProvider open={open} onOpenChange={setOpen}>
      <div className="min-h-screen flex w-full">
        <AppSidebar />
        <main className="flex-1 flex flex-col overflow-hidden">
          {children}
        </main>
        {/* Shadow Mode Visual Indicator */}
        <ShadowModeIndicator />
      </div>
    </SidebarProvider>
  );
}

export function SidebarToggle() {
  return (
    <SidebarTrigger className="h-8 w-8 p-0" />
  );
}
