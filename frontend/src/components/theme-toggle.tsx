"use client";

import { Moon, Sun } from "lucide-react";
import { useTheme } from "next-themes";
import { Button } from "@/components/ui/button";
import { useRef, useState, useEffect } from "react";

export function ThemeToggle() {
  const { resolvedTheme, setTheme } = useTheme();
  const toggleRef = useRef<HTMLButtonElement>(null);
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);

  function handleToggle() {
    if (!resolvedTheme) return;
    const newTheme = resolvedTheme === "dark" ? "light" : "dark";

    const btn = toggleRef.current;
    const rect = btn?.getBoundingClientRect();
    const x = rect ? rect.left + rect.width / 2 : window.innerWidth / 2;
    const y = rect ? rect.top + rect.height / 2 : window.innerHeight / 2;
    document.documentElement.style.setProperty("--vt-x", `${x}px`);
    document.documentElement.style.setProperty("--vt-y", `${y}px`);

    if (!("startViewTransition" in document)) {
      setTheme(newTheme);
      return;
    }

    (
      document as Document & {
        startViewTransition: (cb: () => void | Promise<void>) => void;
      }
    ).startViewTransition(() => setTheme(newTheme));
  }

  return (
    <Button
      ref={toggleRef}
      variant="ghost"
      size="icon"
      onClick={handleToggle}
      className="h-9 w-9 shrink-0 rounded-full"
      title={
        mounted && resolvedTheme === "dark"
          ? "Switch to light mode"
          : "Switch to dark mode"
      }
    >
      <span
        key={mounted ? resolvedTheme : "init"}
        style={{
          animation: mounted
            ? "icon-spin-in 300ms cubic-bezier(0.16,1,0.3,1) both"
            : undefined,
          display: "flex",
        }}
      >
        {mounted && resolvedTheme === "dark" ? (
          <Sun className="h-[17px] w-[17px]" strokeWidth={1.5} />
        ) : (
          <Moon className="h-[17px] w-[17px]" strokeWidth={1.5} />
        )}
      </span>
    </Button>
  );
}
