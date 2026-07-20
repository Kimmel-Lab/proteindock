import { Moon, Sun } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { useTheme } from 'next-themes';
import { useEffect, useState } from 'react';

interface ThemeToggleProps {
  variant?: 'default' | 'header';
}

export function ThemeToggle({ variant = 'default' }: ThemeToggleProps) {
  const { theme, setTheme } = useTheme();
  const [mounted, setMounted] = useState(false);

  // Avoid hydration mismatch
  useEffect(() => {
    setMounted(true);
  }, []);

  if (!mounted) {
    return (
      <Button
        variant="ghost"
        size="sm"
        className="w-10 h-10 p-0"
        disabled
      >
        <Sun className="w-4 h-4" />
      </Button>
    );
  }

  const isDark = theme === 'dark';

  if (variant === 'header') {
    return (
      <Button
        variant="ghost"
        size="sm"
        className="w-10 h-10 p-0 bg-white/10 hover:bg-white/25 text-white border border-white/30 hover:border-white/50 backdrop-blur-sm transition-smooth hover:scale-110 shadow-layered"
        onClick={() => setTheme(isDark ? 'light' : 'dark')}
        aria-label="Toggle theme"
      >
        {isDark ? (
          <Sun className="w-4 h-4 text-yellow-300" />
        ) : (
          <Moon className="w-4 h-4" />
        )}
      </Button>
    );
  }

  return (
    <Button
      variant="ghost"
      size="sm"
      className="w-10 h-10 p-0 transition-smooth hover:scale-110 hover:bg-muted"
      onClick={() => setTheme(isDark ? 'light' : 'dark')}
      aria-label="Toggle theme"
    >
      {isDark ? (
        <Sun className="w-4 h-4 text-yellow-400" />
      ) : (
        <Moon className="w-4 h-4" />
      )}
    </Button>
  );
}

