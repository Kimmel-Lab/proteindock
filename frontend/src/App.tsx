import { Toaster } from "@/components/ui/toaster";
import { Toaster as Sonner } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Routes, Route, useLocation } from "react-router-dom";
import { ThemeProvider } from "next-themes";

/** Detect OOD reverse-proxy prefix for React Router basename. */
function getBasename(): string {
  const match = window.location.pathname.match(/^(\/r?node\/[^/]+\/\d+)/);
  return match ? match[1] : "/";
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
