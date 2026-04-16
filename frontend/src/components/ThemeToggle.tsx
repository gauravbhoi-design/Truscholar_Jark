"use client";

import { useTheme } from "next-themes";
import { useEffect, useState } from "react";
import { Sun, Moon, Monitor } from "lucide-react";

export function ThemeToggle() {
  const { theme, setTheme } = useTheme();
  const [mounted, setMounted] = useState(false);

  // Avoid hydration mismatch — only render after mount
  useEffect(() => setMounted(true), []);
  if (!mounted) return <div className="w-8 h-8" />;

  const options = [
    { value: "light", icon: Sun, label: "Light" },
    { value: "dark", icon: Moon, label: "Dark" },
    { value: "system", icon: Monitor, label: "System" },
  ] as const;

  const next = () => {
    const order = ["light", "dark", "system"];
    const idx = order.indexOf(theme ?? "dark");
    setTheme(order[(idx + 1) % order.length]);
  };

  const current = options.find((o) => o.value === theme) ?? options[1];
  const Icon = current.icon;

  return (
    <button
      onClick={next}
      className="p-1.5 rounded-md hover:bg-muted text-muted-foreground transition-colors"
      title={`Theme: ${current.label} (click to switch)`}
    >
      <Icon className="h-4 w-4" />
    </button>
  );
}
