import { useState } from "react";
import { Settings2, CheckCircle2, XCircle, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { toast } from "@/components/ui/use-toast";
import { getBackendUrl, setBackendUrl } from "@/services/api";

type ProbeState = "idle" | "checking" | "ok" | "fail";

export function BackendSettings() {
  const [open, setOpen] = useState(false);
  const [url, setUrl] = useState(getBackendUrl());
  const [probe, setProbe] = useState<ProbeState>("idle");
  const [probeMsg, setProbeMsg] = useState<string>("");

  async function checkConnection(candidate: string) {
    const target = candidate.trim().replace(/\/+$/, "");
    if (!target) {
      setProbe("fail");
      setProbeMsg("URL is empty.");
      return false;
    }
    setProbe("checking");
    setProbeMsg("");
    try {
      const res = await fetch(`${target}/`, { method: "GET" });
      if (res.ok) {
        setProbe("ok");
        setProbeMsg(`Reachable (HTTP ${res.status}).`);
        return true;
      }
      setProbe("fail");
      setProbeMsg(`Reachable but returned HTTP ${res.status}.`);
      return false;
    } catch (err) {
      setProbe("fail");
      setProbeMsg(
        err instanceof Error
          ? `Network error: ${err.message}`
          : "Could not reach that URL.",
      );
      return false;
    }
  }

  async function handleSave() {
    const ok = await checkConnection(url);
    setBackendUrl(url);
    toast({
      title: ok ? "Backend saved" : "Backend saved (unreachable)",
      description: ok
        ? "Reloading to connect."
        : "URL stored, but the health check failed. Reload to try anyway.",
    });
    setTimeout(() => window.location.reload(), 500);
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="ghost" size="icon" aria-label="Backend settings">
          <Settings2 className="h-5 w-5" />
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-[520px]">
        <DialogHeader>
          <DialogTitle>Backend connection</DialogTitle>
          <DialogDescription>
            ProteinDock's frontend is hosted; you supply your own backend URL.
            Install the backend on your compute environment and paste its address here.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-2">
          <div className="space-y-2">
            <Label htmlFor="backend-url">Backend URL</Label>
            <Input
              id="backend-url"
              placeholder="https://your-cluster.example.edu:8000"
              value={url}
              onChange={(e) => {
                setUrl(e.target.value);
                setProbe("idle");
              }}
              spellCheck={false}
              autoComplete="off"
            />
            <p className="text-xs text-muted-foreground">
              Leave empty to use the same origin as this page (default for local development).
            </p>
          </div>

          <div className="flex items-center gap-2 text-sm">
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => checkConnection(url)}
              disabled={probe === "checking"}
            >
              {probe === "checking" ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  Checking...
                </>
              ) : (
                "Test connection"
              )}
            </Button>
            {probe === "ok" && (
              <span className="flex items-center gap-1 text-green-600 dark:text-green-400">
                <CheckCircle2 className="h-4 w-4" />
                {probeMsg}
              </span>
            )}
            {probe === "fail" && (
              <span className="flex items-center gap-1 text-red-600 dark:text-red-400">
                <XCircle className="h-4 w-4" />
                {probeMsg}
              </span>
            )}
          </div>

          <div className="rounded-md bg-muted/50 p-3 text-xs text-muted-foreground">
            <p className="mb-1 font-medium text-foreground">Don't have a backend?</p>
            <p>
              Install instructions:{" "}
              <a
                href="https://github.com/Kimmel-Lab/proteindock#install"
                target="_blank"
                rel="noreferrer noopener"
                className="underline underline-offset-2 hover:text-foreground"
              >
                github.com/Kimmel-Lab/proteindock
              </a>
            </p>
          </div>
        </div>

        <DialogFooter>
          <Button variant="ghost" onClick={() => setOpen(false)}>
            Cancel
          </Button>
          <Button onClick={handleSave}>Save &amp; reload</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
