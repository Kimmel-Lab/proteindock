import { Toaster } from "@/components/ui/toaster";
import { Toaster as Sonner } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Routes, Route, useLocation } from "react-router-dom";
import { ThemeProvider } from "next-themes";

/**
 * React Router basename resolution:
 *   1. OSC OnDemand reverse-proxy prefix, if present.
 *   2. Vite's build-time BASE_URL (e.g. "/app/" when deployed to proteindock.com/app,
 *      "/" for local dev).
 */
function getBasename(): string {
  const oodMatch = window.location.pathname.match(/^(\/r?node\/[^/]+\/\d+)/);
  if (oodMatch) return oodMatch[1];
  const base = import.meta.env.BASE_URL || "/";
  return base.replace(/\/+$/, "") || "/";
}
import Dashboard from "./pages/Dashboard";
import DockingPage from "./pages/DockingPage";
import AlaScanPage from "./pages/AlaScanPage";
import NcaaOptPage from "./pages/NcaaOptPage";
import BenchmarkPage from "./pages/BenchmarkPage";
import MpnnPage from "./pages/MpnnPage";
import NotFound from "./pages/NotFound";

const queryClient = new QueryClient();

function AnimatedRoutes() {
  const location = useLocation();
  return (
    <div key={location.pathname} className="animate-fade-in">
      <Routes location={location}>
        <Route path="/" element={<Dashboard />} />
        <Route path="/docking" element={<DockingPage />} />
        <Route path="/alanine-scanning" element={<AlaScanPage />} />
        <Route path="/ncaa-optimize" element={<NcaaOptPage />} />
        <Route path="/benchmark" element={<BenchmarkPage />} />
        <Route path="/mpnn-design" element={<MpnnPage />} />
        {/* ADD ALL CUSTOM ROUTES ABOVE THE CATCH-ALL "*" ROUTE */}
        <Route path="*" element={<NotFound />} />
      </Routes>
    </div>
  );
}

const App = () => (
  <ThemeProvider attribute="class" defaultTheme="light" enableSystem>
  <QueryClientProvider client={queryClient}>
    <TooltipProvider>
      <Toaster />
      <Sonner />
      <BrowserRouter basename={getBasename()}>
        <AnimatedRoutes />
      </BrowserRouter>
    </TooltipProvider>
  </QueryClientProvider>
  </ThemeProvider>
);

export default App;
