"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import { motion, AnimatePresence } from "framer-motion";

// --- Custom Fetch Wrapper ---
const apiFetch = async (input: RequestInfo | URL, init?: RequestInit) => {
  const apiKey = "ops_center_secure_key_9x8q2z";
  const headers = new Headers(init?.headers);
  if (apiKey) headers.set("X-API-Key", apiKey);
  
  let url = input.toString();
  if (typeof window !== "undefined" && url.includes("http://localhost:8000")) {
    url = url.replace("http://localhost:8000", `http://${window.location.hostname}:8000`);
  }
  
  return fetch(url, { ...init, headers });
};
import {
  Send, Bot, Mail, ShieldAlert, CheckCircle2,
  FileText, Calendar, XCircle, Wifi, WifiOff,
  Upload, Database, Zap, BookOpen, AlertCircle,
  RefreshCw, Inbox, MailCheck, Clock, Search,
  X, BarChart3, Mic, MicOff, Moon, Sun, Eye,
  TrendingUp, Activity, MessageSquare, Layers,
  ChevronRight, Sparkles,
} from "lucide-react";

type LogEntry    = { id: string; msg: string; icon: any; color?: string };
type StreamStatus = "idle" | "streaming" | "paused" | "done" | "error";
type Tab         = "incident" | "knowledge";
type Toast       = { id: string; subject: string; priority: string; time: string };
type SentimentPt = { processed_at: string; sentiment: number; priority: string; subject: string };
type ChatMsg     = { role: "user" | "assistant"; content: string; time: string };
type KanbanCard  = { id: string; subject: string; priority: string; email_type: string;
                     ticket_key: string; reply_sent: boolean; processed_at: string;
                     kanban_status: string; summary?: string; };
type SlaData     = { compliance: any; active_incidents: any[]; sla_targets: any };
type TrendDay    = { date: string; total: number; P1: number; P2: number; P3: number; P4: number };
type OnCallPerson = { id: number; name: string; email: string; phone: string; telegram_id: string; whatsapp: string; start_date: string; end_date: string; notes: string } | null;

const ICON_MAP: Record<string, any> = {
  "Email Agent":     Mail,
  "Manager Agent":   Bot,
  "Incident Agent":  ShieldAlert,
  "Parallel Agents": Zap,
  "Human Gate":      ShieldAlert,
  "Ticket Agent":    FileText,
  "Meeting Agent":   Calendar,
  "Knowledge Agent": BookOpen,
  "Summary Agent":   CheckCircle2,
};

export default function Dashboard() {
  const [emailText,     setEmailText]     = useState("");
  const [logs,          setLogs]          = useState<LogEntry[]>([]);
  const [result,        setResult]        = useState<any>(null);
  const [threadId,      setThreadId]      = useState<string | null>(null);
  const [streamStatus,  setStreamStatus]  = useState<StreamStatus>("idle");
  const abortRef = useRef<AbortController | null>(null);

  // KB Upload state
  const [activeTab,   setActiveTab]   = useState<Tab>("incident");
  const [kbTitle,     setKbTitle]     = useState("");
  const [kbContent,   setKbContent]   = useState("");
  const [kbUploading, setKbUploading] = useState(false);
  const [kbStatus,    setKbStatus]    = useState<{ ok: boolean; msg: string } | null>(null);

  // Email poller status
  const [pollerStatus, setPollerStatus] = useState<any>(null);
  // Auto-processed email results
  const [autoResults, setAutoResults]   = useState<any[]>([]);
  // Live stats
  const [stats,       setStats]         = useState<any>(null);
  // Toast notifications
  const [toasts,      setToasts]        = useState<Toast[]>([]);
  const prevCountRef = useRef<number>(0);

  // ── New Feature States ──────────────────────────────────────────────────
  // A. Voice recorder
  const [isRecording,   setIsRecording]   = useState(false);
  const [voiceStatus,   setVoiceStatus]   = useState<"idle"|"recording"|"transcribing"|"done"|"error">("idle");
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const audioChunksRef   = useRef<Blob[]>([]);
  // E. Sentiment trend chart
  const [sentiment, setSentiment] = useState<SentimentPt[]>([]);
  // F. KB Search
  const [kbQuery,      setKbQuery]      = useState("");
  const [kbSearching,  setKbSearching]  = useState(false);
  const [kbSearchRes,  setKbSearchRes]  = useState<any[]>([]);
  // G. Email preview modal
  const [modalEmail,   setModalEmail]   = useState<any>(null);
  // H. Theme toggle
  const [darkMode,     setDarkMode]     = useState(true);
  // A-Tier. AI Chatbot
  const [chatOpen,     setChatOpen]     = useState(false);
  const [chatInput,    setChatInput]    = useState("");
  const [chatMsgs,     setChatMsgs]     = useState<ChatMsg[]>([]);
  const [chatLoading,  setChatLoading]  = useState(false);
  const [suggestions,  setSuggestions]  = useState<string[]>([]);
  const chatEndRef = useRef<HTMLDivElement | null>(null);
  // B-Tier. Kanban Board
  const [kanbanBoard,  setKanbanBoard]  = useState<Record<string, KanbanCard[]>>({
    "New": [], "Triaged": [], "In Progress": [], "Resolved": []
  });
  const [kanbanMoving,    setKanbanMoving]    = useState<string | null>(null);
  const [kanbanSearch,    setKanbanSearch]    = useState("");
  const [kanbanFilter,    setKanbanFilter]    = useState("all");
  const [kanbanExpanded,  setKanbanExpanded]  = useState<Record<string, boolean>>({});
  const [kanbanClearing,  setKanbanClearing]  = useState(false);
  const [demoLoading,     setDemoLoading]     = useState(false);

  // ── Analytics states ──────────────────────────────────────────────────────
  const [slaData,      setSlaData]      = useState<SlaData | null>(null);
  const [trends,       setTrends]       = useState<TrendDay[]>([]);
  const [oncall,       setOncall]       = useState<OnCallPerson>(null);
  const [dupStats,     setDupStats]     = useState<any>(null);
  const [analyticsTab, setAnalyticsTab] = useState<"sla"|"trends"|"oncall"|"duplicates">("sla");
  const [newOncall,    setNewOncall]    = useState({ name:"", email:"", phone:"", telegram_id:"", whatsapp:"", start_date:"", end_date:"", notes:"" });
  const [oncallSaving, setOncallSaving] = useState(false);

  const dismissToast = useCallback((id: string) =>
    setToasts(t => t.filter(x => x.id !== id)), []);

  // Poll email-poller status every 10 seconds
  useEffect(() => {
    const fetchPollerStatus = async () => {
      try {
        const r = await apiFetch("http://localhost:8000/api/email-poller/status");
        if (r.ok) {
          setPollerStatus(await r.json());
        } else {
          console.error("Poller status error:", r.status);
          setPollerStatus({ error: `HTTP ${r.status}` });
        }
      } catch (err: any) { 
        console.error("Poller fetch failed:", err);
        setPollerStatus({ error: err.message });
      }
    };
    fetchPollerStatus();
    const interval = setInterval(fetchPollerStatus, 10_000);
    return () => clearInterval(interval);
  }, []);

  // Poll auto-processed results every 10 seconds + fire toasts on new arrivals
  useEffect(() => {
    const fetchResults = async () => {
      try {
        const r = await apiFetch("http://localhost:8000/api/email-poller/results");
        if (r.ok) {
          const d = await r.json();
          const newResults: any[] = d.results ?? [];
          setAutoResults(newResults);

          // Fire toast for each newly arrived email
          if (newResults.length > prevCountRef.current) {
            const incoming = newResults.slice(0, newResults.length - prevCountRef.current);
            incoming.forEach(item => {
              const toast: Toast = {
                id:       Math.random().toString(36).slice(2),
                subject:  item.subject,
                priority: item.priority ?? "unknown",
                time:     item.processed_at,
              };
              setToasts(t => [toast, ...t].slice(0, 5));
              // Auto-dismiss after 6 seconds
              setTimeout(() => dismissToast(toast.id), 6000);
            });
          }
          prevCountRef.current = newResults.length;
        }
      } catch { /* backend not running */ }
    };
    fetchResults();
    const interval = setInterval(fetchResults, 10_000);
    return () => clearInterval(interval);
  }, [dismissToast]);

  // Build kanban board from autoResults (client-side grouping + auto-triage)
  useEffect(() => {
    if (autoResults.length === 0) return;
    const board: Record<string, KanbanCard[]> = {
      "New": [], "Triaged": [], "In Progress": [], "Resolved": []
    };
    autoResults.forEach((item: any) => {
      // Auto-triage: P1/P2 that are still "New" should show as "Triaged"
      let status = item.kanban_status ?? "New";
      if (status === "New" && (item.priority === "P1-critical" || item.priority === "P2-high")) {
        status = "Triaged";
      }
      const col = board[status] ?? board["New"];
      col.push({
        id: item.id ?? item.email_id ?? Math.random().toString(36).slice(2),
        subject: item.subject ?? "(no subject)",
        priority: item.priority ?? "unknown",
        email_type: item.email_type ?? "",
        ticket_key: item.ticket_key ?? "",
        reply_sent: item.reply_sent ?? false,
        processed_at: item.processed_at ?? "",
        kanban_status: status,
        summary: item.summary,
      });
    });
    setKanbanBoard(board);
  }, [autoResults]);


  // Poll aggregate stats every 15 seconds
  useEffect(() => {
    const fetchStats = async () => {
      try {
        const r = await apiFetch("http://localhost:8000/api/email-poller/stats");
        if (r.ok) setStats(await r.json());
      } catch { /* backend not running */ }
    };
    fetchStats();
    const interval = setInterval(fetchStats, 15_000);
    return () => clearInterval(interval);
  }, []);

  // Poll analytics data every 30 seconds
  useEffect(() => {
    const fetchAnalytics = async () => {
      try {
        const [slaR, trendR, oncallR, dupR] = await Promise.allSettled([
          apiFetch("http://localhost:8000/api/analytics/sla"),
          apiFetch("http://localhost:8000/api/analytics/trends"),
          apiFetch("http://localhost:8000/api/oncall/current"),
          apiFetch("http://localhost:8000/api/analytics/duplicates"),
        ]);
        if (slaR.status === "fulfilled" && slaR.value.ok) setSlaData(await slaR.value.json());
        if (trendR.status === "fulfilled" && trendR.value.ok) { const d = await trendR.value.json(); setTrends(d.trends ?? []); }
        if (oncallR.status === "fulfilled" && oncallR.value.ok) { const d = await oncallR.value.json(); setOncall(d.oncall); }
        if (dupR.status === "fulfilled" && dupR.value.ok) setDupStats(await dupR.value.json());
      } catch { /* backend not running */ }
    };
    fetchAnalytics();
    const interval = setInterval(fetchAnalytics, 30_000);
    return () => clearInterval(interval);
  }, []);


  // Poll sentiment trend every 60 seconds
  useEffect(() => {
    const fetchSentiment = async () => {
      try {
        const r = await apiFetch("http://localhost:8000/api/email-poller/sentiment-trend");
        if (r.ok) { const d = await r.json(); setSentiment(d.trend ?? []); }
      } catch { /* backend not running */ }
    };
    fetchSentiment();
    const interval = setInterval(fetchSentiment, 60_000);
    return () => clearInterval(interval);
  }, []);

  // Theme toggle — apply to <html>
  useEffect(() => {
    document.documentElement.classList.toggle("light-mode", !darkMode);
  }, [darkMode]);

  // ── Voice Recording Handler ─────────────────────────────────────────────────
  const handleVoiceToggle = async () => {
    if (isRecording) {
      mediaRecorderRef.current?.stop();
      setIsRecording(false);
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mr = new MediaRecorder(stream, { mimeType: "audio/webm" });
      audioChunksRef.current = [];
      mr.ondataavailable = e => { if (e.data.size > 0) audioChunksRef.current.push(e.data); };
      mr.onstop = async () => {
        stream.getTracks().forEach(t => t.stop());
        setVoiceStatus("transcribing");
        try {
          const blob = new Blob(audioChunksRef.current, { type: "audio/webm" });
          const fd   = new FormData();
          fd.append("audio", blob, "recording.webm");
          const res  = await apiFetch("http://localhost:8000/api/voice/transcribe", { method: "POST", body: fd });
          if (!res.ok) throw new Error(await res.text());
          const data = await res.json();
          setEmailText(data.text);
          setVoiceStatus("done");
        } catch (e: any) {
          setVoiceStatus("error");
        }
      };
      mr.start();
      mediaRecorderRef.current = mr;
      setIsRecording(true);
      setVoiceStatus("recording");
    } catch {
      setVoiceStatus("error");
    }
  };

  // ── KB Search Handler ────────────────────────────────────────────────────────
  const handleKbSearch = async () => {
    if (!kbQuery.trim()) return;
    setKbSearching(true);
    setKbSearchRes([]);
    try {
      const r = await apiFetch("http://localhost:8000/api/knowledge/search", {
        method:  "POST",
        headers: { "Content-Type": "application/json" },
        body:    JSON.stringify({ query: kbQuery, top_k: 5 }),
      });
      if (r.ok) { const d = await r.json(); setKbSearchRes(d.results ?? []); }
    } catch { /* error */ }
    setKbSearching(false);
  };

  // ── A-Tier: AI Chatbot handlers ───────────────────────────────────────────
  useEffect(() => {
    if (!chatOpen) return;
    // Fetch suggestions when chat first opens
    apiFetch("http://localhost:8000/api/chatbot/suggestions")
      .then(r => r.json())
      .then(d => setSuggestions(d.suggestions ?? []))
      .catch(() => {});
  }, [chatOpen]);

  useEffect(() => {
    // Auto-scroll to bottom on new message
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [chatMsgs]);

  const sendChatMessage = async (msg?: string) => {
    const text = (msg ?? chatInput).trim();
    if (!text || chatLoading) return;
    setChatInput("");
    const ts = new Date().toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit" });
    setChatMsgs(prev => [...prev, { role: "user", content: text, time: ts }]);
    setChatLoading(true);
    try {
      const r = await apiFetch("http://localhost:8000/api/chatbot/message", {
        method:  "POST",
        headers: { "Content-Type": "application/json" },
        body:    JSON.stringify({ message: text }),
      });
      if (!r.ok) throw new Error("Chat request failed");
      const d = await r.json();
      setChatMsgs(prev => [...prev, {
        role: "assistant", content: d.reply, time: d.timestamp ?? ts
      }]);
    } catch (err) {
      console.error("Chat message failed:", err);
      setChatMsgs(prev => [...prev, {
        role: "assistant",
        content: "❌ Could not reach the AI. Make sure the backend is running.",
        time: ts,
      }]);
    }
    setChatLoading(false);
  };

  // ── B-Tier: Kanban Board handlers ─────────────────────────────────────────
  const fetchKanban = useCallback(async () => {
    try {
      const r = await apiFetch("http://localhost:8000/api/kanban/board");
      if (r.ok) { 
        const d = await r.json(); 
        setKanbanBoard(d.board ?? {}); 
      } else {
        console.error("Kanban fetch error:", r.status, await r.text());
      }
    } catch (err) { 
      console.error("Kanban fetch failed:", err);
    }
  }, []);

  useEffect(() => {
    fetchKanban();
    const interval = setInterval(fetchKanban, 30_000);
    return () => clearInterval(interval);
  }, [fetchKanban]);

  const moveKanbanCard = async (id: string, newStatus: string) => {
    setKanbanMoving(id);
    try {
      await apiFetch(`http://localhost:8000/api/kanban/${id}/status`, {
        method:  "PATCH",
        headers: { "Content-Type": "application/json" },
        body:    JSON.stringify({ status: newStatus }),
      });
      await fetchKanban();
    } catch { /* ignore */ }
    setKanbanMoving(null);
  };

  const isProcessing = streamStatus === "streaming";

  const addLog = (msg: string, icon: any, color?: string) =>
    setLogs(prev => [...prev, { id: crypto.randomUUID(), msg, icon, color }]);

  // ── SSE Stream Handler ────────────────────────────────────────────────────
  const handleProcessEmail = async () => {
    if (!emailText.trim()) return;

    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    setLogs([]);
    setResult(null);
    setThreadId(null);
    setStreamStatus("streaming");
    addLog("Connecting to agent pipeline...", Wifi, "text-indigo-400");

    try {
      const response = await apiFetch("http://localhost:8000/api/stream-email", {
        method:  "POST",
        headers: { "Content-Type": "application/json" },
        body:    JSON.stringify({ raw_email: emailText }),
        signal:  controller.signal,
      });

      if (!response.ok || !response.body) {
        const err = await response.text();
        throw new Error(`HTTP ${response.status}: ${err.slice(0, 200)}`);
      }

      addLog("✅ Pipeline connected — agents are starting", Wifi, "text-green-400");

      const reader  = response.body.getReader();
      const decoder = new TextDecoder();
      let   buffer  = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const parts = buffer.split("\n\n");
        buffer = parts.pop() ?? "";

        for (const part of parts) {
          if (!part.startsWith("event:")) continue;
          const lines     = part.split("\n");
          const eventType = lines[0].replace("event: ", "").trim();
          const dataLine  = lines.find(l => l.startsWith("data:")) ?? "";
          let   data: any = {};
          try { data = JSON.parse(dataLine.replace("data: ", "")); } catch {}

          if (eventType === "agent_start") {
            const Icon = ICON_MAP[data.agent] ?? Bot;
            addLog(data.message ?? `${data.agent} started`, Icon, "text-slate-400");
          } else if (eventType === "agent_done") {
            const Icon    = ICON_MAP[data.agent] ?? CheckCircle2;
            const isError = (data.message ?? "").startsWith("❌");
            addLog(data.message ?? `${data.agent} complete`, Icon,
              isError ? "text-red-400" : "text-emerald-400");
          } else if (eventType === "complete") {
            setResult(data.result ?? {});
            setThreadId(data.thread_id ?? null);
            setStreamStatus("done");
            addLog("🎉 All agents finished!", CheckCircle2, "text-green-400");
          } else if (eventType === "paused") {
            setResult(data.result ?? {});
            setThreadId(data.thread_id ?? null);
            setStreamStatus("paused");
            addLog("⏸️ Paused — awaiting human approval.", ShieldAlert, "text-orange-400");
          } else if (eventType === "error") {
            addLog(`❌ Error: ${data.message}`, XCircle, "text-red-400");
            setStreamStatus("error");
          }
        }
      }
    } catch (err: any) {
      if (err?.name !== "AbortError") {
        addLog(`❌ Connection error: ${err?.message ?? err}`, WifiOff, "text-red-400");
        setStreamStatus("error");
      }
    }
  };

  // ── Human Approval ────────────────────────────────────────────────────────
  const handleApprove = async () => {
    addLog("✅ Ticket approved — resuming workflow...", CheckCircle2, "text-green-400");
    try {
      const url = threadId
        ? `http://localhost:8000/api/approve-ticket?thread_id=${threadId}`
        : "http://localhost:8000/api/approve-ticket";
      const r = await apiFetch(url, { method: "POST" });
      const d = await r.json();
      if (d.status === "resumed") {
        const s = d.result;
        if (s?.ticket_result?.key)
          addLog(`🎫 Jira ticket created: ${s.ticket_result.key}`, FileText, "text-blue-400");
        addLog("🎉 Workflow complete!", CheckCircle2, "text-green-400");
        setResult(s);
        setStreamStatus("done");
      }
    } catch {
      addLog("❌ Error resuming workflow.", ShieldAlert, "text-red-400");
      setStreamStatus("error");
    }
  };

  const handleReject = async () => {
    addLog("🚫 Ticket creation rejected by operator.", XCircle, "text-red-400");
    try {
      const url = threadId
        ? `http://localhost:8000/api/reject-ticket?thread_id=${threadId}`
        : "http://localhost:8000/api/reject-ticket";
      await apiFetch(url, { method: "POST" });
    } catch { /* best-effort */ }
    setResult((p: any) => ({ ...p, human_approved: "rejected" }));
    setThreadId(null);
    setStreamStatus("done");
  };

  // ── KB Upload ─────────────────────────────────────────────────────────────
  const handleKbUpload = async () => {
    if (!kbTitle.trim() || !kbContent.trim()) {
      setKbStatus({ ok: false, msg: "Title and content are required." });
      return;
    }
    setKbUploading(true);
    setKbStatus(null);
    try {
      const r = await apiFetch("http://localhost:8000/api/knowledge/upload", {
        method:  "POST",
        headers: { "Content-Type": "application/json" },
        body:    JSON.stringify({ title: kbTitle, content: kbContent }),
      });
      const d = await r.json();
      if (r.ok) {
        setKbStatus({
          ok:  true,
          msg: `✅ Indexed "${kbTitle}" — ${d.chunks_created} chunks added (${d.total_docs_in_kb} total in KB)`,
        });
        setKbTitle("");
        setKbContent("");
      } else {
        setKbStatus({ ok: false, msg: `❌ ${d.detail ?? "Upload failed"}` });
      }
    } catch (e: any) {
      setKbStatus({ ok: false, msg: `❌ Network error: ${e?.message}` });
    }
    setKbUploading(false);
  };

  const needsApproval =
    streamStatus === "paused" &&
    result?.human_approved === false &&
    ["P1-critical", "P2-high"].includes(result?.email_data?.priority);

  // ── Render ────────────────────────────────────────────────────────────────
  return (
    <div className="container mx-auto p-6 max-w-7xl">

      {/* ── Toast Notifications (PREMIUM) ────────────────────────── */}
      <div className="fixed top-5 right-5 z-50 flex flex-col gap-2.5 pointer-events-none">
        <AnimatePresence>
          {toasts.map(toast => {
            const cfg = {
              "P1-critical": { bg: "bg-red-950/95 border-red-500/50",    icon: "🔴", glow: "shadow-red-500/20" },
              "P2-high":     { bg: "bg-orange-950/95 border-orange-500/50", icon: "🟠", glow: "shadow-orange-500/20" },
              "P3-medium":   { bg: "bg-yellow-950/95 border-yellow-500/40", icon: "🟡", glow: "shadow-yellow-500/15" },
            }[toast.priority] ?? { bg: "bg-slate-900/95 border-slate-600/50", icon: "📩", glow: "shadow-slate-500/15" };
            return (
              <motion.div key={toast.id}
                initial={{ opacity: 0, x: 80, scale: 0.85 }}
                animate={{ opacity: 1, x: 0, scale: 1 }}
                exit={{ opacity: 0, x: 80, scale: 0.85 }}
                transition={{ type: "spring", stiffness: 400, damping: 30 }}
                className={`pointer-events-auto toast-premium flex items-start gap-3 p-3.5 pr-4 max-w-sm shadow-2xl ${cfg.glow} ${cfg.bg}`}
              >
                <span className="text-xl mt-0.5 flex-shrink-0">{cfg.icon}</span>
                <div className="flex-1 min-w-0">
                  <p className="text-xs font-semibold text-white tracking-wide">Auto-processed incident</p>
                  <p className="text-xs text-slate-300 truncate mt-0.5">{toast.subject}</p>
                  <p className="text-xs text-slate-500 mt-1 font-mono">{toast.priority} · {toast.time}</p>
                </div>
                <button onClick={() => dismissToast(toast.id)}
                  className="shrink-0 text-slate-600 hover:text-white transition-colors mt-0.5">
                  <X className="w-3.5 h-3.5" />
                </button>
              </motion.div>
            );
          })}
        </AnimatePresence>
      </div>

      {/* PREMIUM HEADER */}
      <header className="mb-8 relative">
        <div className="flex items-center gap-4">
          {/* Logo orb */}
          <div className="relative flex-shrink-0">
            <div className="w-14 h-14 rounded-2xl bg-gradient-to-br from-indigo-500 via-violet-500 to-indigo-700
                            flex items-center justify-center shadow-xl shadow-indigo-500/30 glow-indigo">
              <Bot className="w-7 h-7 text-white" />
            </div>
            <span className="absolute -top-1 -right-1 w-3.5 h-3.5 rounded-full bg-emerald-400
                             border-2 border-slate-950 animate-pulse" />
          </div>
          {/* Title block */}
          <div className="flex-1">
            <div className="flex items-center gap-3 flex-wrap">
              <h1 className="text-4xl font-black tracking-tight gradient-text" style={{ fontFamily: 'Outfit, Inter, sans-serif' }}>
                AI Operations Center
              </h1>
              <span className="px-2.5 py-0.5 rounded-full text-xs font-bold tracking-widest uppercase
                               bg-indigo-500/15 border border-indigo-500/30 text-indigo-400">v3.0</span>
            </div>
            <p className="text-slate-500 text-sm mt-0.5 tracking-wide">
              Enterprise Multi-Agent · Real-time SSE · Parallel Execution · RAG Knowledge Base
            </p>
          </div>
          {/* Controls */}
          <div className="flex items-center gap-2">
            {/* Load Demo Data button — shown when empty */}
            {autoResults.length === 0 && (
              <button
                id="btn-load-demo"
                disabled={demoLoading}
                onClick={async () => {
                  setDemoLoading(true);
                  try {
                    await apiFetch("http://localhost:8000/api/seed-demo", { method: "POST" });
                    const r = await apiFetch("http://localhost:8000/api/email-poller/results");
                    if (r.ok) { const d = await r.json(); setAutoResults(d.results ?? []); }
                  } catch {}
                  setDemoLoading(false);
                }}
                className="flex items-center gap-1.5 px-3 py-2 text-xs font-semibold rounded-xl
                           bg-gradient-to-r from-emerald-600 to-teal-600 text-white
                           hover:from-emerald-500 hover:to-teal-500 transition-all
                           shadow-lg shadow-emerald-500/25 disabled:opacity-50
                           animate-pulse hover:animate-none"
                title="Seed 12 realistic demo incidents">
                {demoLoading
                  ? <><div className="w-3 h-3 border-2 border-white/30 border-t-white rounded-full animate-spin" /> Loading…</>
                  : <><Sparkles className="w-3.5 h-3.5" /> Load Demo Data</>}
              </button>
            )}
            <button onClick={() => setDarkMode(d => !d)}
              className="p-2.5 rounded-xl border border-slate-700/40 bg-slate-900/60
                         hover:border-indigo-500/40 hover:bg-indigo-500/10 transition-all group"
              title="Toggle theme">
              {darkMode
                ? <Sun className="w-4.5 h-4.5 text-amber-400 group-hover:rotate-45 transition-transform duration-300" />
                : <Moon className="w-4.5 h-4.5 text-indigo-400" />}
            </button>
          </div>
        </div>
        <hr className="gradient-divider mt-6" />
      </header>

      {/* ── Live Stats Bar ───────────────────────────────────────────────── */}
      {stats && (
        <motion.div
          initial={{ opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }}
          className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-8"
        >
          {[
            {
              label: "Total Processed",
              value: stats.total_processed,
              icon:  BarChart3,
              color: "text-indigo-400",
              bg:    "from-indigo-500/15 to-indigo-600/5 border-indigo-500/25",
              shadow: "shadow-indigo-500/10",
            },
            {
              label: "P1 Critical",
              value: stats.by_priority?.["P1"] ?? 0,
              icon:  ShieldAlert,
              color: "text-red-400",
              bg:    "from-red-500/15 to-red-600/5 border-red-500/25",
              shadow: "shadow-red-500/10",
            },
            {
              label: "P2 High",
              value: stats.by_priority?.["P2"] ?? 0,
              icon:  AlertCircle,
              color: "text-orange-400",
              bg:    "from-orange-500/15 to-orange-600/5 border-orange-500/25",
              shadow: "shadow-orange-500/10",
            },
            {
              label: "Avg Process",
              value: stats.avg_process_ms > 0
                ? `${(stats.avg_process_ms / 1000).toFixed(1)}s`
                : "—",
              icon:  Clock,
              color: "text-emerald-400",
              bg:    "from-emerald-500/15 to-emerald-600/5 border-emerald-500/25",
              shadow: "shadow-emerald-500/10",
            },
          ].map(({ label, value, icon: Icon, color, bg, shadow }) => (
            <motion.div key={label} whileHover={{ scale: 1.02, y: -2 }} transition={{ type: "spring", stiffness: 400, damping: 25 }}
              className={`glass-panel bg-gradient-to-br ${bg} border rounded-2xl px-5 py-4 flex items-center gap-4 shadow-lg ${shadow}`}>
              <div className={`w-10 h-10 rounded-xl bg-current/10 flex items-center justify-center flex-shrink-0 ${color}`}>
                <Icon className={`w-5 h-5 ${color}`} />
              </div>
              <div>
                <p className="text-xs text-slate-500 font-medium tracking-wide uppercase">{label}</p>
                <p className={`text-2xl font-black mt-0.5 ${color}`} style={{ fontFamily: 'Outfit, sans-serif', letterSpacing: '-0.04em' }}>{value}</p>
              </div>
            </motion.div>
          ))}
        </motion.div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">

        {/* ── Left Column: Tabs ────────────────────────────────────────────── */}
        <div className="lg:col-span-1 space-y-6">

          {/* Tab selector — PREMIUM */}
          <div className="flex p-1 rounded-2xl bg-slate-900/80 border border-slate-700/40 shadow-inner gap-1">
            <button onClick={() => setActiveTab("incident")}
              className={`flex-1 py-2.5 text-sm font-semibold flex items-center justify-center gap-2 rounded-xl transition-all duration-200
                ${ activeTab === "incident"
                  ? "bg-gradient-to-r from-indigo-600 to-violet-600 text-white shadow-lg shadow-indigo-500/25"
                  : "text-slate-500 hover:text-slate-300 hover:bg-slate-800/60"}`}>
              <Mail className="w-4 h-4" /> Incident
            </button>
            <button onClick={() => setActiveTab("knowledge")}
              className={`flex-1 py-2.5 text-sm font-semibold flex items-center justify-center gap-2 rounded-xl transition-all duration-200
                ${ activeTab === "knowledge"
                  ? "bg-gradient-to-r from-indigo-600 to-violet-600 text-white shadow-lg shadow-indigo-500/25"
                  : "text-slate-500 hover:text-slate-300 hover:bg-slate-800/60"}`}>
              <Database className="w-4 h-4" /> Knowledge
            </button>
          </div>

          {/* ── Incident Input tab ── */}
          {activeTab === "incident" && (
            <div className="glass-panel p-6 shadow-2xl">
              <textarea
                value={emailText}
                onChange={e => setEmailText(e.target.value)}
                placeholder="Paste email content here — or 🎙️ click the mic to record a voice incident report..."
                className="w-full h-48 bg-[#0f1117]/50 border border-slate-700/50 rounded-lg p-4 text-slate-200
                           placeholder:text-slate-600 focus:outline-none focus:ring-2 focus:ring-indigo-500/50
                           transition-all resize-none"
              />
              <div className="mt-4 flex gap-3">
                {/* A. Voice Recorder Button */}
                <button
                  id="btn-voice-record"
                  onClick={handleVoiceToggle}
                  disabled={voiceStatus === "transcribing"}
                  title={isRecording ? "Stop recording" : "Record voice incident"}
                  className={`shrink-0 px-4 py-3 rounded-lg font-medium flex items-center gap-2 transition-all
                    ${isRecording
                      ? "bg-red-600 hover:bg-red-500 text-white animate-pulse"
                      : voiceStatus === "transcribing"
                        ? "bg-amber-600/50 text-amber-300 cursor-wait"
                        : "bg-slate-700 hover:bg-slate-600 text-slate-200"
                    }`}
                >
                  {voiceStatus === "transcribing"
                    ? <div className="w-4 h-4 border-2 border-amber-300/40 border-t-amber-300 rounded-full animate-spin" />
                    : isRecording
                      ? <MicOff className="w-4 h-4" />
                      : <Mic className="w-4 h-4" />
                  }
                  {voiceStatus === "transcribing" ? "Transcribing…" : isRecording ? "Stop" : "Record"}
                </button>

                <button
                  id="btn-process-email"
                  onClick={handleProcessEmail}
                  disabled={isProcessing}
                  className="flex-1 bg-indigo-600 hover:bg-indigo-500 text-white font-medium py-3 px-4
                             rounded-lg flex items-center justify-center gap-2 transition-colors
                             disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {isProcessing
                    ? <div className="w-5 h-5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                    : <><Send className="w-4 h-4" /> Process with AI Agents</>}
                </button>
              </div>
              {/* Voice status hint */}
              {voiceStatus !== "idle" && (
                <p className={`text-xs mt-2 ${
                  voiceStatus === "done"  ? "text-emerald-400" :
                  voiceStatus === "error" ? "text-red-400"     :
                  voiceStatus === "recording" ? "text-red-400" : "text-amber-400"
                }`}>
                  {voiceStatus === "recording"    && "🔴 Recording… speak now, then click Stop"}
                  {voiceStatus === "transcribing" && "⏳ Transcribing via Groq Whisper…"}
                  {voiceStatus === "done"         && "✅ Transcribed! Review above, then click Process."}
                  {voiceStatus === "error"        && "❌ Recording failed — check microphone permissions."}
                </p>
              )}
            </div>
          )}

          {/* ── KB Upload tab ── */}
          {activeTab === "knowledge" && (
            <div className="glass-panel p-6 shadow-2xl space-y-4">
              <p className="text-xs text-slate-400">
                Add runbooks, SOPs, or any internal documentation. Agents will use it for
                RAG-based answers automatically.
              </p>

              <div>
                <label className="text-xs text-slate-400 mb-1 block">Document Title *</label>
                <input
                  value={kbTitle}
                  onChange={e => setKbTitle(e.target.value)}
                  placeholder="e.g. VPN Troubleshooting Runbook"
                  className="w-full bg-[#0f1117]/50 border border-slate-700/50 rounded-lg px-4 py-2.5
                             text-slate-200 placeholder:text-slate-600 focus:outline-none
                             focus:ring-2 focus:ring-indigo-500/50 text-sm"
                />
              </div>

              <div>
                <label className="text-xs text-slate-400 mb-1 block">Document Content *</label>
                <textarea
                  value={kbContent}
                  onChange={e => setKbContent(e.target.value)}
                  placeholder="Paste the full runbook, SOP, or documentation text here..."
                  className="w-full h-36 bg-[#0f1117]/50 border border-slate-700/50 rounded-lg p-4
                             text-slate-200 placeholder:text-slate-600 focus:outline-none
                             focus:ring-2 focus:ring-indigo-500/50 transition-all resize-none text-sm"
                />
              </div>

              <button
                onClick={handleKbUpload}
                disabled={kbUploading}
                className="w-full bg-emerald-600 hover:bg-emerald-500 text-white font-medium py-3 px-4
                           rounded-lg flex items-center justify-center gap-2 transition-colors
                           disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {kbUploading
                  ? <div className="w-5 h-5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                  : <><Upload className="w-4 h-4" /> Upload to Knowledge Base</>}
              </button>

              {kbStatus && (
                <p className={`text-sm ${kbStatus.ok ? "text-emerald-400" : "text-red-400"}`}>
                  {kbStatus.msg}
                </p>
              )}
            </div>
          )}

          {/* Human Approval Panel */}
          <AnimatePresence>
            {needsApproval && (
              <motion.div
                initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -10 }}
                className="glass-panel p-6 shadow-2xl border-orange-500/30 bg-orange-500/5"
              >
                <h2 className="text-lg font-semibold text-orange-400 mb-2 flex items-center gap-2">
                  <ShieldAlert className="w-5 h-5" /> Human Approval Required
                </h2>
                <p className="text-sm text-slate-300 mb-4">
                  P1/P2 Incident detected. The Ticket Agent is paused. Review the triage and approve or reject.
                </p>
                <div className="flex gap-3">
                  <button id="btn-approve-ticket" onClick={handleApprove}
                    className="flex-1 bg-green-600/80 hover:bg-green-500 text-white py-2 rounded-lg
                               transition-colors font-medium">
                    ✓ Approve
                  </button>
                  <button id="btn-reject-ticket" onClick={handleReject}
                    className="flex-1 bg-red-600/80 hover:bg-red-500 text-white py-2 rounded-lg
                               transition-colors font-medium">
                    ✗ Reject
                  </button>
                </div>
              </motion.div>
            )}
          </AnimatePresence>

          {/* Rejected Notice */}
          <AnimatePresence>
            {result?.human_approved === "rejected" && (
              <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
                className="glass-panel p-4 border-red-500/30 bg-red-500/5 flex items-center gap-3">
                <XCircle className="w-5 h-5 text-red-400 shrink-0" />
                <p className="text-sm text-slate-300">
                  Ticket creation <span className="text-red-400 font-medium">rejected</span>. No action taken.
                </p>
              </motion.div>
            )}
          </AnimatePresence>

          {/* ── Email Poller Status Card ── */}
          <div className={`glass-panel p-4 shadow-xl border ${
            pollerStatus?.running
              ? "border-emerald-500/30 bg-emerald-500/5"
              : "border-slate-700/40 bg-white/2"
          }`}>
            <div className="flex items-center gap-2 mb-3">
              {pollerStatus?.running
                ? <MailCheck className="w-4 h-4 text-emerald-400" />
                : <Inbox className="w-4 h-4 text-slate-500" />}
              <span className="text-sm font-medium text-white">Email Auto-Processor</span>
              {pollerStatus?.running && (
                <span className="ml-auto flex items-center gap-1 text-xs text-emerald-400">
                  <span className="w-1.5 h-1.5 bg-emerald-400 rounded-full animate-pulse" />
                  Live
                </span>
              )}
            </div>

            {pollerStatus?.enabled ? (
              <div className="space-y-1.5">
                <div className="flex justify-between text-xs">
                  <span className="text-slate-400">Inbox</span>
                  <span className="text-slate-200 font-mono truncate max-w-[140px]">
                    {pollerStatus.username}
                  </span>
                </div>
                <div className="flex justify-between text-xs">
                  <span className="text-slate-400">Processed today</span>
                  <span className="text-emerald-300 font-medium">
                    {pollerStatus.processed_count ?? 0} emails
                  </span>
                </div>
                <div className="flex justify-between text-xs">
                  <span className="text-slate-400">Last checked</span>
                  <span className="text-slate-300">
                    {pollerStatus.last_poll ?? "not yet"}
                  </span>
                </div>
                <div className="flex justify-between text-xs">
                  <span className="text-slate-400">Interval</span>
                  <span className="text-slate-300">{pollerStatus.poll_interval_s}s</span>
                </div>
                {pollerStatus.last_error && (
                  <p className="text-xs text-red-400 mt-1 break-all">
                    ⚠ {pollerStatus.last_error.slice(0, 80)}
                  </p>
                )}
              </div>
            ) : pollerStatus?.error ? (
              <div className="text-xs text-red-400 mt-2 p-2 bg-red-500/10 rounded border border-red-500/20">
                Connection Error: {pollerStatus.error}
              </div>
            ) : (
              <p className="text-xs text-slate-500 leading-relaxed">
                Not configured. Add <code className="text-indigo-400">EMAIL_IMAP_HOST</code>,{" "}
                <code className="text-indigo-400">EMAIL_USERNAME</code> and{" "}
                <code className="text-indigo-400">EMAIL_PASSWORD</code> to your <code>.env</code> to
                automatically process incoming emails.
              </p>
            )}
          </div>

          {/* ── Auto-Processed Inbox Feed ── */}
          {autoResults.length > 0 && (
            <div className="glass-panel p-4 shadow-xl border border-slate-700/30">
              <div className="flex items-center gap-2 mb-3">
                <Inbox className="w-4 h-4 text-indigo-400" />
                <span className="text-sm font-medium text-white">Auto-Processed Inbox</span>
                <span className="ml-auto text-xs text-slate-500 bg-slate-800/60 px-2 py-0.5 rounded-full">
                  {autoResults.length} total
                </span>
              </div>
              <div className="space-y-2 max-h-64 overflow-y-auto hide-scrollbar">
                {[...autoResults].reverse().slice(0, 8).map((item: any, i: number) => {
                  const priorityColor: Record<string, string> = {
                    "P1-critical": "text-red-400 bg-red-500/15 border-red-500/25",
                    "P2-high":     "text-orange-400 bg-orange-500/15 border-orange-500/25",
                    "P3-medium":   "text-yellow-400 bg-yellow-500/15 border-yellow-500/25",
                    "P4-low":      "text-green-400 bg-green-500/15 border-green-500/25",
                  };
                  const pc = priorityColor[item.priority] ?? "text-slate-400 bg-slate-700/30 border-slate-600/30";
                  return (
                    <div key={item.id ?? i}
                      className="flex items-start gap-2.5 p-2.5 rounded-lg bg-slate-800/40
                                 border border-slate-700/20 hover:border-indigo-500/20
                                 cursor-pointer transition-all group"
                      onClick={() => setModalEmail(item)}>
                      <div className={`mt-0.5 w-1.5 h-1.5 rounded-full flex-shrink-0 ${
                        item.priority === "P1-critical" ? "bg-red-400 animate-pulse" :
                        item.priority === "P2-high"    ? "bg-orange-400" :
                        item.priority === "P3-medium"  ? "bg-yellow-400" : "bg-green-400"
                      }`} />
                      <div className="flex-1 min-w-0">
                        <p className="text-xs text-slate-200 truncate font-medium
                                      group-hover:text-white transition-colors">
                          {item.subject ?? "(no subject)"}
                        </p>
                        <div className="flex items-center gap-1.5 mt-1">
                          <span className={`text-xs px-1.5 py-0.5 rounded border ${pc}`}>
                            {item.priority ?? "unknown"}
                          </span>
                          {item.reply_sent && (
                            <span className="text-xs text-emerald-400">✓ replied</span>
                          )}
                          <span className="text-xs text-slate-600 ml-auto">
                            {item.processed_at?.slice(11, 16)}
                          </span>
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
              {autoResults.length > 8 && (
                <p className="text-xs text-slate-600 text-center mt-2">
                  + {autoResults.length - 8} more in Kanban board
                </p>
              )}
            </div>
          )}

        </div>

        {/* ── Middle Column: Live Agent Feed ──────────────────────────────── */}
        <div className="lg:col-span-1">
          <div className="glass-panel p-6 shadow-2xl h-full min-h-[600px] flex flex-col">
            <h2 className="text-lg font-semibold text-white mb-6 flex items-center gap-2">
              <Bot className="w-5 h-5 text-indigo-400" /> Live Agent Feed
              {isProcessing && (
                <span className="ml-auto flex items-center gap-1.5 text-xs text-indigo-400 font-normal">
                  <span className="w-1.5 h-1.5 bg-indigo-400 rounded-full animate-pulse" />
                  Streaming
                </span>
              )}
            </h2>

            <div className="flex-1 space-y-3 overflow-y-auto hide-scrollbar">
              <AnimatePresence initial={false}>
                {logs.map((log, i) => (
                  <motion.div key={log.id}
                    initial={{ opacity: 0, x: -16 }} animate={{ opacity: 1, x: 0 }}
                    transition={{ delay: Math.min(i * 0.04, 0.3) }}
                    className="flex items-start gap-3 p-3 rounded-lg bg-white/5 border border-white/5">
                    <div className="mt-0.5 p-1.5 bg-indigo-500/20 rounded-md shrink-0">
                      <log.icon className={`w-4 h-4 ${log.color ?? "text-indigo-400"}`} />
                    </div>
                    <p className={`text-sm leading-snug ${log.color ?? "text-slate-300"}`}>{log.msg}</p>
                  </motion.div>
                ))}
              </AnimatePresence>

              {logs.length === 0 && !isProcessing && (
                <div className="h-48 flex items-center justify-center text-slate-600 text-sm
                                border border-dashed border-slate-700/50 rounded-xl">
                  Agent events will appear here in real-time...
                </div>
              )}
            </div>
          </div>
        </div>

        {/* ── Right Column: Executive Summary ─────────────────────────────── */}
        <div className="lg:col-span-1">
          <div className="glass-panel p-6 shadow-2xl h-full bg-gradient-to-br from-indigo-900/10
                          to-transparent overflow-y-auto max-h-[90vh]">
            <h2 className="text-lg font-semibold text-white mb-6 flex items-center gap-2">
              <FileText className="w-5 h-5 text-indigo-400" /> Executive Summary
            </h2>

            {!result ? (
              <div className="h-48 flex items-center justify-center text-slate-500 text-sm
                              border border-dashed border-slate-700/50 rounded-xl">
                Awaiting agent processing...
              </div>
            ) : (
              <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}
                className="space-y-4">

                {/* Meta grid */}
                <div className="grid grid-cols-2 gap-3">
                  {[
                    { label: "Priority",   value: result.email_data?.priority,   color: "text-red-400" },
                    { label: "Department", value: result.email_data?.department,  color: "text-indigo-400" },
                    { label: "Type",       value: result.email_data?.email_type,  color: "text-slate-200" },
                    { label: "Sentiment",  value: result.email_data?.sentiment != null
                        ? `${Math.round(result.email_data.sentiment * 100)}%`
                        : undefined,                                              color: "text-slate-200" },
                  ].map(({ label, value, color }) => (
                    <div key={label} className="p-3 bg-white/5 rounded-lg border border-white/5">
                      <div className="text-xs text-slate-400 mb-1">{label}</div>
                      <div className={`font-semibold text-sm ${color}`}>{value ?? "N/A"}</div>
                    </div>
                  ))}
                </div>

                {/* Summary text */}
                {result.executive_summary && (
                  <div>
                    <h3 className="text-sm font-medium text-slate-300 mb-2">Final Report</h3>
                    <div className="p-4 bg-[#0f1117]/60 rounded-xl border border-slate-700/50
                                    text-sm text-slate-300 leading-relaxed">
                      {result.executive_summary}
                    </div>
                  </div>
                )}

                {/* Root Cause */}
                {result.incident_result?.rca?.root_cause && (
                  <div>
                    <h3 className="text-sm font-medium text-red-300 mb-2 flex items-center gap-1.5">
                      <AlertCircle className="w-4 h-4" /> Root Cause
                    </h3>
                    <div className="p-4 bg-red-500/5 rounded-xl border border-red-500/20
                                    text-sm text-slate-300">
                      {result.incident_result.rca.root_cause}
                    </div>
                  </div>
                )}

                {/* Remediation Plan */}
                {result.incident_result?.rca?.remediation_plan?.length > 0 && (
                  <div>
                    <h3 className="text-sm font-medium text-emerald-300 mb-2">Remediation Plan</h3>
                    <ol className="space-y-1.5">
                      {result.incident_result.rca.remediation_plan.map((step: string, i: number) => (
                        <li key={i}
                          className="flex items-start gap-2.5 p-2.5 bg-emerald-500/5 rounded-lg
                                     border border-emerald-500/15">
                          <span className="shrink-0 w-5 h-5 bg-emerald-500/20 text-emerald-400
                                           rounded-full flex items-center justify-center text-xs font-bold">
                            {i + 1}
                          </span>
                          <span className="text-sm text-slate-300">{step}</span>
                        </li>
                      ))}
                    </ol>
                  </div>
                )}

                {/* Estimated resolution time */}
                {result.incident_result?.rca?.estimated_resolution_time && (
                  <div className="p-3 bg-yellow-500/5 rounded-lg border border-yellow-500/20
                                  flex items-center gap-2">
                    <span className="text-xs text-slate-400">Est. resolution:</span>
                    <span className="text-sm text-yellow-300 font-medium">
                      {result.incident_result.rca.estimated_resolution_time}
                    </span>
                  </div>
                )}

                {/* KB Sources */}
                {result.knowledge_results?.sources?.length > 0 && (
                  <div>
                    <h3 className="text-sm font-medium text-slate-300 mb-2 flex items-center gap-1.5">
                      <BookOpen className="w-4 h-4 text-indigo-400" /> KB Sources Used
                    </h3>
                    <div className="flex flex-wrap gap-2">
                      {result.knowledge_results.sources.map((src: string) => (
                        <span key={src}
                          className="px-2.5 py-1 bg-indigo-500/10 border border-indigo-500/20
                                     rounded-full text-xs text-indigo-300">
                          {src}
                        </span>
                      ))}
                    </div>
                  </div>
                )}

                {/* Jira ticket badge */}
                {result.ticket_result?.key && (
                  <div className="p-3 bg-blue-500/10 rounded-lg border border-blue-500/20
                                  flex items-center gap-2">
                    <FileText className="w-4 h-4 text-blue-400" />
                    <span className="text-sm text-blue-300 font-medium">
                      Jira: {result.ticket_result.key}
                    </span>
                    {result.ticket_result.url && (
                      <a href={result.ticket_result.url} target="_blank" rel="noopener noreferrer"
                        className="ml-auto text-xs text-blue-400 underline hover:text-blue-300">
                        View →
                      </a>
                    )}
                  </div>
                )}

              </motion.div>
            )}
          </div>
        </div>
      </div>

      {/* ── INCIDENT KANBAN BOARD ─────────────────────────────────────────── */}
      <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} className="mt-12">
        {/* Header */}
        <div className="flex items-center gap-3 mb-5 flex-wrap">
          <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-emerald-500 to-teal-600 flex items-center justify-center shadow-lg">
            <Layers className="w-4 h-4 text-white" />
          </div>
          <div>
            <h2 className="text-xl font-bold text-white">Incident Kanban Board</h2>
            <p className="text-xs text-slate-500">{autoResults.length} total · click card to advance status</p>
          </div>
          {stats?.bot_skipped > 0 && (
            <span className="px-2 py-0.5 bg-slate-500/10 border border-slate-600/30 text-slate-400 text-xs rounded-full">
              {stats.bot_skipped} bot filtered
            </span>
          )}
          {/* Controls */}
          <div className="ml-auto flex items-center gap-2 flex-wrap">
            {/* Search */}
            <div className="relative">
              <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-500" />
              <input value={kanbanSearch} onChange={e => setKanbanSearch(e.target.value)}
                placeholder="Search incidents…"
                className="pl-8 pr-3 py-1.5 text-xs bg-slate-800/60 border border-slate-700/50 rounded-lg text-slate-200
                           placeholder:text-slate-600 focus:outline-none focus:ring-1 focus:ring-indigo-500/50 w-44" />
            </div>
            {/* Priority filter */}
            <select value={kanbanFilter} onChange={e => setKanbanFilter(e.target.value)}
              className="text-xs bg-slate-800/60 border border-slate-700/50 rounded-lg px-2 py-1.5 text-slate-300
                         focus:outline-none focus:ring-1 focus:ring-indigo-500/50">
              <option value="all">All priorities</option>
              <option value="P1-critical">P1 Critical</option>
              <option value="P2-high">P2 High</option>
              <option value="P3-medium">P3 Medium</option>
              <option value="P4-low">P4 Low</option>
            </select>
            {/* Refresh */}
            <button onClick={async () => {
              const r = await apiFetch("http://localhost:8000/api/email-poller/results");
              if (r.ok) { const d = await r.json(); setAutoResults(d.results ?? []); }
            }} className="p-1.5 rounded-lg border border-slate-700/40 hover:border-indigo-500/40 hover:bg-indigo-500/10 transition-all">
              <RefreshCw className="w-3.5 h-3.5 text-slate-400" />
            </button>
            {/* Clear all */}
            <button disabled={kanbanClearing} onClick={async () => {
              if (!confirm("Clear all incident history? This cannot be undone.")) return;
              setKanbanClearing(true);
              await apiFetch("http://localhost:8000/api/email-poller/results", { method: "DELETE" });
              setAutoResults([]); prevCountRef.current = 0;
              setKanbanClearing(false);
            }} className="flex items-center gap-1.5 px-2.5 py-1.5 text-xs text-red-400 border border-red-500/25
                          hover:bg-red-500/10 rounded-lg transition-all disabled:opacity-40">
              <X className="w-3 h-3" /> {kanbanClearing ? "Clearing…" : "Clear All"}
            </button>
          </div>
        </div>
        <hr className="gradient-divider mb-5" />

        {/* Columns */}
        {autoResults.length === 0 ? (
          <div className="glass-panel border border-slate-700/30 rounded-2xl p-12 flex flex-col items-center gap-3 text-center">
            <Inbox className="w-12 h-12 text-slate-600 float" />
            <p className="text-slate-400 text-sm font-medium">No incidents yet</p>
            <p className="text-slate-600 text-xs max-w-xs">The email poller checks every 30s — processed emails appear here as incident cards automatically.</p>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4">
            {(["New","Triaged","In Progress","Resolved"] as const).map(col => {
              const colCfg = {
                "New":         { dot: "bg-slate-400",   border: "border-slate-600/50",   header: "text-slate-300",   badge: "bg-slate-700/60",   icon: "⚪" },
                "Triaged":     { dot: "bg-amber-400",   border: "border-amber-500/30",   header: "text-amber-300",   badge: "bg-amber-500/15",   icon: "🟡" },
                "In Progress": { dot: "bg-blue-400",    border: "border-blue-500/30",    header: "text-blue-300",    badge: "bg-blue-500/15",    icon: "🔵" },
                "Resolved":    { dot: "bg-emerald-400", border: "border-emerald-500/30", header: "text-emerald-300", badge: "bg-emerald-500/15", icon: "🟢" },
              }[col];

              const NEXT_STATUS: Record<string, string> = {
                "New": "Triaged", "Triaged": "In Progress", "In Progress": "Resolved", "Resolved": "New"
              };

              // Filter cards
              const rawCards = kanbanBoard[col] ?? [];
              const filtered = rawCards.filter(c => {
                const matchSearch = !kanbanSearch || c.subject.toLowerCase().includes(kanbanSearch.toLowerCase());
                const matchPrio   = kanbanFilter === "all" || c.priority === kanbanFilter;
                return matchSearch && matchPrio;
              });

              const LIMIT = 10;
              const expanded = kanbanExpanded[col];
              const visible  = expanded ? filtered : filtered.slice(0, LIMIT);
              const hasMore  = filtered.length > LIMIT;

              return (
                <div key={col} className={`glass-panel border ${colCfg.border} rounded-2xl p-3 flex flex-col gap-2 min-h-[200px]`}>
                  {/* Column Header */}
                  <div className="flex items-center gap-2 px-1 pb-2 border-b border-slate-700/30">
                    <span className={`w-2 h-2 rounded-full ${colCfg.dot} flex-shrink-0`} />
                    <span className={`text-sm font-semibold ${colCfg.header}`}>{col}</span>
                    <span className={`ml-auto text-xs font-bold px-2 py-0.5 rounded-full ${colCfg.badge} ${colCfg.header}`}>
                      {filtered.length}
                    </span>
                  </div>

                  {/* Cards */}
                  <div className="flex flex-col gap-2 flex-1 overflow-hidden">
                    {visible.length === 0 ? (
                      <div className="flex-1 flex items-center justify-center py-8 text-slate-600 text-xs border border-dashed border-slate-700/30 rounded-xl">
                        Empty
                      </div>
                    ) : (
                      <AnimatePresence>
                        {visible.map(card => {
                          const pBadge = ({
                            "P1-critical": "badge-p1",
                            "P2-high":     "badge-p2",
                            "P3-medium":   "badge-p3",
                            "P4-low":      "badge-p4",
                          } as Record<string,string>)[card.priority] ?? "bg-slate-700/40 text-slate-400";

                          const isMoving = kanbanMoving === card.id;
                          return (
                            <motion.div key={card.id}
                              initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }}
                              exit={{ opacity: 0, scale: 0.95 }}
                              onClick={async () => {
                                if (isMoving || col === "Resolved") return;
                                setKanbanMoving(card.id);
                                const nextStatus = NEXT_STATUS[col];
                                try {
                                  await apiFetch(`http://localhost:8000/api/kanban/${card.id}/status`, {
                                    method: "PATCH", headers: { "Content-Type": "application/json" },
                                    body: JSON.stringify({ status: nextStatus }),
                                  });
                                  setKanbanBoard(prev => {
                                    const next = { ...prev };
                                    next[col] = (next[col] ?? []).filter(c => c.id !== card.id);
                                    next[nextStatus] = [{ ...card, kanban_status: nextStatus }, ...(next[nextStatus] ?? [])];
                                    return next;
                                  });
                                } catch {}
                                setKanbanMoving(null);
                              }}
                              className={`kanban-card p-3 rounded-xl ${col !== "Resolved" ? "cursor-pointer" : "cursor-default"} ${
                                isMoving ? "opacity-40 animate-pulse" : ""
                              }`}
                            >
                              <p className="text-xs font-medium text-slate-200 line-clamp-2 mb-2 leading-relaxed">{card.subject}</p>
                              <div className="flex items-center gap-1.5 flex-wrap">
                                <span className={`chip ${pBadge}`}>{card.priority ?? "unknown"}</span>
                                {card.ticket_key && (
                                  <span className="chip bg-blue-500/10 border border-blue-500/20 text-blue-300">🎫 {card.ticket_key}</span>
                                )}
                                {card.reply_sent && (
                                  <span className="chip bg-emerald-500/10 border border-emerald-500/20 text-emerald-400">✓ replied</span>
                                )}
                              </div>
                              {col !== "Resolved" && (
                                <p className="text-xs text-slate-600 mt-2 flex items-center gap-1">
                                  <ChevronRight className="w-3 h-3" /> Click to move to {NEXT_STATUS[col]}
                                </p>
                              )}
                              <p className="text-xs text-slate-700 mt-1">{card.processed_at?.slice(0, 10)}</p>
                            </motion.div>
                          );
                        })}
                      </AnimatePresence>
                    )}

                    {/* Show more / less */}
                    {hasMore && (
                      <button onClick={() => setKanbanExpanded(e => ({ ...e, [col]: !e[col] }))}
                        className="text-xs text-indigo-400 hover:text-indigo-300 transition-colors py-1 text-center border border-indigo-500/20 rounded-lg hover:border-indigo-500/40">
                        {expanded ? `Show less` : `Show ${filtered.length - LIMIT} more →`}
                      </button>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </motion.div>

      {/* ── E. Sentiment Trend Chart ──────────────────────────────────────── */}
      {sentiment.length > 1 && (() => {
        const W = 600, H = 120, PAD = 16;
        const vals  = sentiment.map(p => p.sentiment);
        const minV  = Math.min(...vals);
        const maxV  = Math.max(...vals);
        const range = maxV - minV || 0.001;
        const pts   = sentiment.map((p, i) => {
          const x = PAD + (i / (sentiment.length - 1)) * (W - PAD * 2);
          const y = H - PAD - ((p.sentiment - minV) / range) * (H - PAD * 2);
          return `${x},${y}`;
        }).join(" ");
        const avgSent = (vals.reduce((a, b) => a + b, 0) / vals.length);
        const trend   = vals[vals.length - 1] > vals[0] ? "↑ Improving" : "↓ Declining";
        return (
          <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} className="mt-10">
            <div className="flex items-center gap-3 mb-4">
              <Activity className="w-5 h-5 text-emerald-400" />
              <h2 className="text-lg font-semibold text-white">Email Sentiment Trend</h2>
              <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${
                avgSent > 0.6 ? "bg-emerald-500/15 text-emerald-400" : "bg-red-500/15 text-red-400"
              }`}>{trend} · avg {(avgSent * 100).toFixed(0)}%</span>
            </div>
            <div className="glass-panel border border-slate-700/30 rounded-xl p-5">
              <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-28" preserveAspectRatio="none">
                <defs>
                  <linearGradient id="sentGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#10b981" stopOpacity="0.3" />
                    <stop offset="100%" stopColor="#10b981" stopOpacity="0" />
                  </linearGradient>
                </defs>
                <polygon
                  points={`${PAD},${H - PAD} ${pts} ${W - PAD},${H - PAD}`}
                  fill="url(#sentGrad)"
                />
                <polyline points={pts} fill="none" stroke="#10b981" strokeWidth="2"
                  strokeLinejoin="round" strokeLinecap="round" />
                {sentiment.map((p, i) => {
                  const x = PAD + (i / (sentiment.length - 1)) * (W - PAD * 2);
                  const y = H - PAD - ((p.sentiment - minV) / range) * (H - PAD * 2);
                  const col = p.priority === "P1-critical" ? "#ef4444"
                            : p.priority === "P2-high"     ? "#f97316" : "#10b981";
                  return <circle key={i} cx={x} cy={y} r="3" fill={col} />;
                })}
              </svg>
              <div className="flex justify-between mt-1">
                <span className="text-xs text-slate-600">{sentiment[0]?.processed_at}</span>
                <span className="text-xs text-slate-600">{sentiment[sentiment.length - 1]?.processed_at}</span>
              </div>
              <p className="text-xs text-slate-500 mt-1">
                🟢 green dots = P3/P4 &nbsp;·&nbsp; 🟠 orange = P2 &nbsp;·&nbsp; 🔴 red = P1
              </p>
            </div>
          </motion.div>
        );
      })()}

      {/* ── ANALYTICS DASHBOARD ─────────────────────────────────────────────── */}
      <motion.div initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.2 }} className="mt-12">
        {/* Header */}
        <div className="flex items-center gap-3 mb-6">
          <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-violet-500 to-indigo-600 flex items-center justify-center shadow-lg shadow-violet-500/25">
            <BarChart3 className="w-4 h-4 text-white" />
          </div>
          <div>
            <h2 className="text-xl font-bold text-white tracking-tight">Analytics Dashboard</h2>
            <p className="text-xs text-slate-500">SLA · Trends · Duplicates · On-Call</p>
          </div>
          {oncall && (
            <div className="ml-auto flex items-center gap-2 px-3 py-1.5 rounded-full bg-emerald-500/10 border border-emerald-500/25">
              <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
              <span className="text-xs text-emerald-400 font-medium">On-Call: {oncall.name}</span>
            </div>
          )}
        </div>

        {/* Tab bar */}
        <div className="flex gap-1 p-1 rounded-xl bg-slate-800/50 border border-slate-700/40 mb-6 w-fit">
          {(["sla","trends","duplicates","oncall"] as const).map(tab => (
            <button key={tab} onClick={() => setAnalyticsTab(tab)}
              className={`px-4 py-1.5 rounded-lg text-xs font-medium transition-all capitalize ${
                analyticsTab === tab
                  ? "bg-indigo-600 text-white shadow-lg shadow-indigo-500/25"
                  : "text-slate-400 hover:text-slate-200"
              }`}>
              {tab === "sla" ? "⏱ SLA" : tab === "trends" ? "📈 Trends" : tab === "duplicates" ? "🔄 Duplicates" : "👤 On-Call"}
            </button>
          ))}
        </div>

        {/* ── SLA TAB ── */}
        {analyticsTab === "sla" && (
          <div className="space-y-4">
            {/* Overall compliance banner */}
            {slaData && (
              <div className="glass-panel border border-slate-700/30 rounded-xl p-5">
                <div className="flex items-center justify-between mb-4">
                  <p className="text-sm font-semibold text-white">Overall SLA Compliance (7 days)</p>
                  <span className={`text-2xl font-bold ${
                    (slaData.compliance?.overall_compliance ?? 0) >= 80 ? "text-emerald-400" : "text-red-400"
                  }`}>{slaData.compliance?.overall_compliance ?? 0}%</span>
                </div>
                {/* Progress bar */}
                <div className="h-2.5 bg-slate-700/50 rounded-full overflow-hidden">
                  <motion.div initial={{ width: 0 }} animate={{ width: `${slaData.compliance?.overall_compliance ?? 0}%` }}
                    transition={{ duration: 1, ease: "easeOut" }}
                    className={`h-full rounded-full ${
                      (slaData.compliance?.overall_compliance ?? 0) >= 80
                        ? "bg-gradient-to-r from-emerald-500 to-teal-400"
                        : "bg-gradient-to-r from-red-500 to-orange-400"
                    }`} />
                </div>
                {/* Per-priority SLA gauges */}
                <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mt-5">
                  {(["P1-critical","P2-high","P3-medium","P4-low"] as const).map(p => {
                    const pData = slaData.compliance?.per_priority?.[p];
                    const pct = pData?.compliance ?? 0;
                    const color = p === "P1-critical" ? "#ef4444" : p === "P2-high" ? "#f97316" : p === "P3-medium" ? "#eab308" : "#22c55e";
                    const target = slaData.sla_targets?.[p] ?? "";
                    return (
                      <div key={p} className="bg-slate-800/60 border border-slate-700/30 rounded-xl p-3 text-center">
                        <svg viewBox="0 0 40 40" className="w-16 h-16 mx-auto -rotate-90">
                          <circle cx="20" cy="20" r="16" fill="none" stroke="#1e293b" strokeWidth="4" />
                          <circle cx="20" cy="20" r="16" fill="none" stroke={color} strokeWidth="4"
                            strokeDasharray={`${(pct / 100) * 100.5} 100.5`}
                            strokeLinecap="round" style={{ transition: "stroke-dasharray 1s ease" }} />
                        </svg>
                        <p className="text-sm font-bold text-white -mt-1">{pct}%</p>
                        <p className="text-xs text-slate-500">{p.split("-")[0].toUpperCase()}</p>
                        <p className="text-xs text-slate-600 mt-0.5">{target}</p>
                      </div>
                    );
                  })}
                </div>
              </div>
            )}

            {/* Active SLA incidents */}
            {slaData?.active_incidents && slaData.active_incidents.length > 0 && (
              <div className="glass-panel border border-slate-700/30 rounded-xl p-4">
                <p className="text-sm font-semibold text-white mb-3">⚠️ Active SLA Incidents</p>
                <div className="space-y-2">
                  {slaData.active_incidents.slice(0,6).map((inc: any, i: number) => {
                    const sla = inc.sla;
                    const isBreached = sla.status === "breached";
                    const isWarn = sla.status === "warning";
                    return (
                      <div key={i} className={`flex items-center gap-3 p-2.5 rounded-lg border ${
                        isBreached ? "bg-red-500/8 border-red-500/20" :
                        isWarn     ? "bg-orange-500/8 border-orange-500/20" :
                                     "bg-slate-800/40 border-slate-700/20"
                      }`}>
                        <span className={`w-2 h-2 rounded-full flex-shrink-0 ${
                          isBreached ? "bg-red-400 animate-pulse" : isWarn ? "bg-orange-400 animate-pulse" : "bg-slate-600"
                        }`} />
                        <div className="flex-1 min-w-0">
                          <p className="text-xs text-slate-300 truncate">{inc.subject}</p>
                          <p className="text-xs text-slate-600">{inc.priority}</p>
                        </div>
                        <span className={`text-xs font-mono px-2 py-0.5 rounded-full ${
                          isBreached ? "bg-red-500/15 text-red-400" :
                          isWarn     ? "bg-orange-500/15 text-orange-400" :
                                       "bg-slate-700/50 text-slate-400"
                        }`}>
                          {isBreached ? `+${sla.elapsed_minutes?.toFixed(0)}m` : `${sla.minutes_remaining?.toFixed(0)}m left`}
                        </span>
                      </div>
                    );
                  })}
                </div>
              </div>
            )}

            {!slaData && (
              <div className="glass-panel border border-slate-700/30 rounded-xl p-8 text-center text-slate-500">
                <Clock className="w-8 h-8 mx-auto mb-2 opacity-30" />
                <p className="text-sm">SLA data loading... Start backend to see compliance stats.</p>
              </div>
            )}
          </div>
        )}

        {/* ── TRENDS TAB ── */}
        {analyticsTab === "trends" && (
          <div className="glass-panel border border-slate-700/30 rounded-xl p-5">
            <p className="text-sm font-semibold text-white mb-4">📈 7-Day Incident Volume</p>
            {trends.length > 0 ? (
              <div className="space-y-3">
                {/* Bar chart */}
                <div className="flex items-end gap-2 h-32">
                  {trends.map((day, i) => {
                    const maxTotal = Math.max(...trends.map(d => d.total), 1);
                    const heightPct = (day.total / maxTotal) * 100;
                    return (
                      <div key={i} className="flex-1 flex flex-col items-center gap-1">
                        <span className="text-xs text-slate-400 font-medium">{day.total}</span>
                        <div className="w-full rounded-t-md overflow-hidden" style={{ height: "100px" }}>
                          <div className="w-full flex flex-col-reverse" style={{ height: `${heightPct}%`, minHeight: day.total > 0 ? "4px" : "0" }}>
                            {(["P1","P2","P3","P4"] as const).map(p => {
                              const count = day[p] ?? 0;
                              const colors: Record<string,string> = { P1:"bg-red-500", P2:"bg-orange-500", P3:"bg-yellow-500", P4:"bg-emerald-500" };
                              return count > 0 ? (
                                <div key={p} className={`${colors[p]} opacity-80 transition-all`}
                                  style={{ height: `${(count / day.total) * 100}%`, minHeight: "3px" }} />
                              ) : null;
                            })}
                          </div>
                        </div>
                        <span className="text-xs text-slate-600">{day.date.slice(5)}</span>
                      </div>
                    );
                  })}
                </div>
                {/* Legend */}
                <div className="flex gap-4 text-xs text-slate-500">
                  {[["P1","bg-red-500"],["P2","bg-orange-500"],["P3","bg-yellow-500"],["P4","bg-emerald-500"]].map(([label, cls]) => (
                    <span key={label} className="flex items-center gap-1.5">
                      <span className={`w-2.5 h-2.5 rounded-sm ${cls}`} />{label}
                    </span>
                  ))}
                </div>
                {/* Summary row */}
                <div className="grid grid-cols-4 gap-3 mt-2 pt-3 border-t border-slate-700/30">
                  {(["P1","P2","P3","P4"] as const).map(p => {
                    const total = trends.reduce((s, d) => s + (d[p] ?? 0), 0);
                    const colors: Record<string,string> = { P1:"text-red-400", P2:"text-orange-400", P3:"text-yellow-400", P4:"text-emerald-400" };
                    return (
                      <div key={p} className="text-center">
                        <p className={`text-lg font-bold ${colors[p]}`}>{total}</p>
                        <p className="text-xs text-slate-600">{p} this week</p>
                      </div>
                    );
                  })}
                </div>
              </div>
            ) : (
              <div className="text-center py-8 text-slate-500">
                <TrendingUp className="w-8 h-8 mx-auto mb-2 opacity-30" />
                <p className="text-sm">No trend data yet — incidents will appear here after processing.</p>
              </div>
            )}
          </div>
        )}

        {/* ── DUPLICATES TAB ── */}
        {analyticsTab === "duplicates" && (
          <div className="space-y-4">
            {dupStats ? (
              <>
                <div className="grid grid-cols-2 gap-4">
                  <div className="glass-panel border border-slate-700/30 rounded-xl p-5 text-center">
                    <p className="text-3xl font-bold text-violet-400">{dupStats.total_groups ?? 0}</p>
                    <p className="text-xs text-slate-500 mt-1">Duplicate Groups</p>
                  </div>
                  <div className="glass-panel border border-slate-700/30 rounded-xl p-5 text-center">
                    <p className="text-3xl font-bold text-orange-400">{dupStats.total_duplicates ?? 0}</p>
                    <p className="text-xs text-slate-500 mt-1">Suppressed Tickets</p>
                  </div>
                </div>
                {(dupStats.top_groups ?? []).length > 0 && (
                  <div className="glass-panel border border-slate-700/30 rounded-xl p-4">
                    <p className="text-sm font-semibold text-white mb-3">Top Duplicate Groups</p>
                    <div className="space-y-2">
                      {(dupStats.top_groups ?? []).map((g: any, i: number) => (
                        <div key={i} className="flex items-center gap-3 p-2.5 bg-slate-800/40 rounded-lg border border-slate-700/20">
                          <span className="w-6 h-6 rounded-full bg-violet-500/20 border border-violet-500/30 text-violet-400 text-xs font-bold flex items-center justify-center">{g.count}</span>
                          <div className="flex-1 min-w-0">
                            <p className="text-xs text-slate-300 truncate">{g.parent_subject}</p>
                            <p className="text-xs text-slate-600">{g.priority} · {g.count - 1} duplicates suppressed</p>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
                {(dupStats.total_groups ?? 0) === 0 && (
                  <div className="glass-panel border border-slate-700/30 rounded-xl p-8 text-center text-slate-500">
                    <CheckCircle2 className="w-8 h-8 mx-auto mb-2 opacity-30" />
                    <p className="text-sm">No duplicate incidents detected in the last 7 days. Great job!</p>
                  </div>
                )}
              </>
            ) : (
              <div className="glass-panel border border-slate-700/30 rounded-xl p-8 text-center text-slate-500">
                <Layers className="w-8 h-8 mx-auto mb-2 opacity-30" />
                <p className="text-sm">Loading duplicate analysis...</p>
              </div>
            )}
          </div>
        )}

        {/* ── ON-CALL TAB ── */}
        {analyticsTab === "oncall" && (
          <div className="space-y-4">
            {/* Current on-call */}
            <div className="glass-panel border border-slate-700/30 rounded-xl p-5">
              <p className="text-sm font-semibold text-white mb-3">👤 Currently On Call</p>
              {oncall ? (
                <div className="flex items-center gap-4">
                  <div className="w-12 h-12 rounded-full bg-gradient-to-br from-indigo-500 to-violet-600 flex items-center justify-center text-white text-lg font-bold shadow-lg">
                    {oncall.name[0]?.toUpperCase()}
                  </div>
                  <div>
                    <p className="text-base font-bold text-white">{oncall.name}</p>
                    {oncall.email && <p className="text-xs text-slate-400">📧 {oncall.email}</p>}
                    {oncall.phone && <p className="text-xs text-slate-400">📞 {oncall.phone}</p>}
                    <p className="text-xs text-slate-600 mt-1">{oncall.start_date} → {oncall.end_date}</p>
                  </div>
                  <div className="ml-auto">
                    <span className="flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-emerald-500/15 border border-emerald-500/25 text-xs text-emerald-400">
                      <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" /> Active
                    </span>
                  </div>
                </div>
              ) : (
                <div className="text-center py-4 text-slate-500">
                  <p className="text-sm">No one scheduled. Add an on-call person below.</p>
                </div>
              )}
            </div>

            {/* Add on-call form */}
            <div className="glass-panel border border-slate-700/30 rounded-xl p-5">
              <p className="text-sm font-semibold text-white mb-4">➕ Add On-Call Person</p>
              <div className="grid grid-cols-2 gap-3">
                {([
                  ["name","Name *","text"],["email","Email","email"],
                  ["phone","Phone","tel"],["telegram_id","Telegram Chat ID","text"],
                  ["whatsapp","WhatsApp (+91...)","tel"],["start_date","Start Date","date"],
                  ["end_date","End Date","date"],["notes","Notes","text"],
                ] as const).map(([field, label, type]) => (
                  <div key={field} className={field === "notes" ? "col-span-2" : ""}>
                    <label className="text-xs text-slate-500 mb-1 block">{label}</label>
                    <input type={type}
                      value={(newOncall as any)[field]}
                      onChange={e => setNewOncall(p => ({ ...p, [field]: e.target.value }))}
                      className="w-full bg-slate-800/60 border border-slate-700/50 rounded-lg px-3 py-2 text-xs text-slate-200
                                 placeholder:text-slate-600 focus:outline-none focus:ring-2 focus:ring-indigo-500/40 transition-all"
                    />
                  </div>
                ))}
              </div>
              <button
                disabled={oncallSaving || !newOncall.name.trim()}
                onClick={async () => {
                  if (!newOncall.name.trim()) return;
                  setOncallSaving(true);
                  try {
                    const r = await apiFetch("http://localhost:8000/api/oncall/schedule", {
                      method: "POST", headers: { "Content-Type": "application/json" },
                      body: JSON.stringify(newOncall),
                    });
                    if (r.ok) {
                      setNewOncall({ name:"", email:"", phone:"", telegram_id:"", whatsapp:"", start_date:"", end_date:"", notes:"" });
                      const d = await apiFetch("http://localhost:8000/api/oncall/current").then(r=>r.json());
                      setOncall(d.oncall);
                    }
                  } catch {}
                  setOncallSaving(false);
                }}
                className="mt-4 w-full py-2.5 bg-gradient-to-r from-indigo-600 to-violet-600 hover:from-indigo-500 hover:to-violet-500
                           text-white text-sm font-semibold rounded-lg transition-all disabled:opacity-40 disabled:cursor-not-allowed"
              >
                {oncallSaving ? "Saving…" : "Save On-Call Entry"}
              </button>
            </div>
          </div>
        )}
      </motion.div>

      {/* ── F. KB Search Panel ───────────────────────────────────────────────── */}
      <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} className="mt-10">
        <div className="flex items-center gap-3 mb-4">
          <Search className="w-5 h-5 text-indigo-400" />
          <h2 className="text-lg font-semibold text-white">Knowledge Base Search</h2>
          <span className="text-xs text-slate-500">Search runbooks, SOPs, documentation</span>
        </div>
        <div className="glass-panel border border-slate-700/30 rounded-xl p-5">
          <div className="flex gap-3">
            <input
              value={kbQuery}
              onChange={e => setKbQuery(e.target.value)}
              onKeyDown={e => e.key === "Enter" && handleKbSearch()}
              placeholder="e.g. 'how to restart api gateway' or 'database recovery steps'…"
              className="flex-1 bg-slate-800/60 border border-slate-700/50 rounded-lg px-4 py-2.5
                         text-slate-200 text-sm placeholder:text-slate-600
                         focus:outline-none focus:ring-2 focus:ring-indigo-500/40 transition-all"
            />
            <button
              onClick={handleKbSearch}
              disabled={kbSearching || !kbQuery.trim()}
              className="px-4 py-2.5 bg-indigo-600 hover:bg-indigo-500 text-white text-sm font-medium
                         rounded-lg flex items-center gap-2 transition-colors
                         disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {kbSearching
                ? <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                : <Search className="w-4 h-4" />}
              Search
            </button>
          </div>
          {kbSearchRes.length > 0 && (
            <div className="mt-4 space-y-3">
              {kbSearchRes.map((r: any, i: number) => (
                <div key={i} className="p-3 bg-slate-800/40 border border-slate-700/30 rounded-lg">
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-xs font-semibold text-indigo-300">{r.title || `Result ${i + 1}`}</span>
                    {r.score != null && (
                      <span className="text-xs text-slate-500">
                        relevance {(r.score * 100).toFixed(0)}%
                      </span>
                    )}
                  </div>
                  <p className="text-xs text-slate-400 leading-relaxed line-clamp-3">
                    {r.content || r.text || r.payload?.content || "No preview available"}
                  </p>
                </div>
              ))}
            </div>
          )}
          {kbSearchRes.length === 0 && kbQuery && !kbSearching && (
            <p className="text-xs text-slate-600 mt-3">
              Press Enter or click Search to query the knowledge base.
            </p>
          )}
        </div>
      </motion.div>

      {/* ── ABOUT THE PROJECT ───────────────────────────────────────────────── */}
      <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} className="mt-10 mb-10">
        <div className="flex items-center gap-3 mb-4">
          <div className="p-2 bg-indigo-500/20 rounded-lg">
            <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-indigo-400"><circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/></svg>
          </div>
          <div>
            <h2 className="text-lg font-semibold text-white">About AI Operations Center</h2>
            <span className="text-xs text-slate-500">Enterprise AI incident management platform</span>
          </div>
        </div>
        
        <div className="glass-panel border border-slate-700/30 rounded-xl p-6 bg-slate-800/20">
          <div className="grid md:grid-cols-2 gap-8">
            <div className="space-y-4">
              <h3 className="text-sm font-semibold text-indigo-300">Intelligent Automation</h3>
              <p className="text-sm text-slate-400 leading-relaxed">
                The AI Operations Center is a multi-agent system designed to completely automate Level 1 and Level 2 IT Support. 
                Using LangGraph and large language models, it constantly polls incoming support emails, categorizes them by priority, 
                and automatically extracts the root cause and remediation steps for complex incidents.
              </p>
              <div className="flex flex-wrap gap-2 mt-2">
                <span className="text-xs bg-slate-800 border border-slate-700 text-slate-300 px-2 py-1 rounded-md">Next.js 14</span>
                <span className="text-xs bg-slate-800 border border-slate-700 text-slate-300 px-2 py-1 rounded-md">FastAPI</span>
                <span className="text-xs bg-slate-800 border border-slate-700 text-slate-300 px-2 py-1 rounded-md">LangGraph</span>
                <span className="text-xs bg-slate-800 border border-slate-700 text-slate-300 px-2 py-1 rounded-md">SQLite</span>
              </div>
            </div>
            
            <div className="space-y-4">
              <h3 className="text-sm font-semibold text-indigo-300">How It Works</h3>
              <ul className="text-sm text-slate-400 space-y-2 list-disc list-inside marker:text-indigo-500">
                <li><strong className="text-slate-300 font-medium">Email Poller:</strong> Connects to IMAP to fetch incoming tickets.</li>
                <li><strong className="text-slate-300 font-medium">Routing Agent:</strong> Determines if an email is an incident, inquiry, or spam.</li>
                <li><strong className="text-slate-300 font-medium">Incident Agent:</strong> Diagnoses the problem and writes a post-mortem RCA.</li>
                <li><strong className="text-slate-300 font-medium">Ticket Agent:</strong> Mocks creating a Jira/ServiceNow ticket.</li>
                <li><strong className="text-slate-300 font-medium">Knowledge Base:</strong> Uses Qdrant Vector DB to recall past resolutions.</li>
              </ul>
            </div>
          </div>
        </div>
      </motion.div>

      {/* ── G. Email Preview Modal ───────────────────────────────────────────── */}
      <AnimatePresence>
        {modalEmail && (
          <motion.div
            initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
            className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4"
            onClick={() => setModalEmail(null)}
          >
            <motion.div
              initial={{ scale: 0.95, opacity: 0 }} animate={{ scale: 1, opacity: 1 }}
              exit={{ scale: 0.95, opacity: 0 }}
              className="relative bg-slate-900 border border-slate-700/50 rounded-2xl shadow-2xl
                         w-full max-w-2xl max-h-[85vh] overflow-y-auto"
              onClick={e => e.stopPropagation()}
            >
              {/* Modal header */}
              <div className="sticky top-0 bg-slate-900 border-b border-slate-700/50 p-5 flex items-start gap-3">
                <div className="flex-1 min-w-0">
                  <p className="text-xs text-slate-500 mb-1">Email Preview</p>
                  <h3 className="text-base font-semibold text-white leading-snug">
                    {modalEmail.subject}
                  </h3>
                  <p className="text-xs text-slate-400 mt-0.5">{modalEmail.sender}</p>
                </div>
                <button onClick={() => setModalEmail(null)}
                  className="shrink-0 p-1.5 hover:bg-slate-700 rounded-lg transition-colors">
                  <X className="w-4 h-4 text-slate-400" />
                </button>
              </div>
              {/* Modal body */}
              <div className="p-5 space-y-4">
                {/* Badges row */}
                <div className="flex flex-wrap gap-2">
                  {[
                    { label: modalEmail.priority,   color: "bg-red-500/15 text-red-300"     },
                    { label: modalEmail.email_type, color: "bg-indigo-500/15 text-indigo-300" },
                    { label: modalEmail.department, color: "bg-slate-600/30 text-slate-400"  },
                    { label: modalEmail.reply_sent ? "✅ Reply sent" : "⏳ No reply",
                      color: modalEmail.reply_sent ? "bg-emerald-500/15 text-emerald-400"
                                                   : "bg-slate-700/40 text-slate-500" },
                  ].filter(b => b.label).map((b, i) => (
                    <span key={i} className={`px-2.5 py-1 rounded-full text-xs font-medium ${b.color}`}>
                      {b.label}
                    </span>
                  ))}
                  {modalEmail.ticket_key && (
                    modalEmail.ticket_url
                      ? <a href={modalEmail.ticket_url} target="_blank" rel="noopener noreferrer"
                           className="px-2.5 py-1 rounded-full text-xs font-medium bg-blue-500/15 text-blue-300
                                      hover:text-blue-200 transition-colors">
                          🎫 {modalEmail.ticket_key} →
                        </a>
                      : <span className="px-2.5 py-1 rounded-full text-xs bg-blue-500/15 text-blue-300">
                          🎫 {modalEmail.ticket_key}
                        </span>
                  )}
                </div>

                {/* Root cause */}
                {modalEmail.root_cause && (
                  <div className="p-3 bg-indigo-500/5 border border-indigo-500/20 rounded-lg">
                    <p className="text-xs font-semibold text-indigo-400 mb-1">🔍 Root Cause</p>
                    <p className="text-sm text-slate-300 leading-relaxed">{modalEmail.root_cause}</p>
                  </div>
                )}

                {/* Remediation steps */}
                {modalEmail.remediation?.length > 0 && (
                  <div className="p-3 bg-emerald-500/5 border border-emerald-500/20 rounded-lg">
                    <p className="text-xs font-semibold text-emerald-400 mb-2">📋 Remediation Plan</p>
                    <ol className="space-y-1.5">
                      {modalEmail.remediation.map((step: string, i: number) => (
                        <li key={i} className="flex gap-2 text-sm text-slate-300">
                          <span className="text-emerald-500 font-bold shrink-0">{i + 1}.</span>
                          <span>{step}</span>
                        </li>
                      ))}
                    </ol>
                  </div>
                )}

                {/* AI Summary */}
                {modalEmail.summary && (
                  <div className="p-3 bg-slate-800/50 border border-slate-700/30 rounded-lg">
                    <p className="text-xs font-semibold text-slate-400 mb-1">📝 AI Summary</p>
                    <p className="text-sm text-slate-300 leading-relaxed">{modalEmail.summary}</p>
                  </div>
                )}

                {/* Metadata */}
                <div className="grid grid-cols-2 gap-3 pt-2 border-t border-slate-700/30">
                  <div>
                    <p className="text-xs text-slate-600">Processed At</p>
                    <p className="text-sm text-slate-300">{modalEmail.processed_at}</p>
                  </div>
                  <div>
                    <p className="text-xs text-slate-600">Sentiment</p>
                    <p className="text-sm text-slate-300">
                      {modalEmail.sentiment != null
                        ? `${(modalEmail.sentiment * 100).toFixed(0)}% positive`
                        : "—"}
                    </p>
                  </div>
                </div>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* ── A-Tier: AI Chatbot Floating Widget ───────────────────────────────── */}

      {/* Floating bubble */}
      <motion.button
        onClick={() => setChatOpen(o => !o)}
        whileHover={{ scale: 1.08 }} whileTap={{ scale: 0.95 }}
        className={`fixed bottom-6 right-6 z-50 w-14 h-14 rounded-full shadow-2xl
          flex items-center justify-center transition-all
          ${chatOpen
            ? "bg-slate-700 hover:bg-slate-600"
            : "bg-gradient-to-br from-indigo-600 to-purple-600 hover:from-indigo-500 hover:to-purple-500"}`}
        title="AI Ops Assistant"
      >
        <AnimatePresence mode="wait">
          {chatOpen
            ? <motion.div key="close" initial={{ rotate: -90, opacity: 0 }} animate={{ rotate: 0, opacity: 1 }} exit={{ rotate: 90, opacity: 0 }}>
                <X className="w-6 h-6 text-white" />
              </motion.div>
            : <motion.div key="chat" initial={{ scale: 0 }} animate={{ scale: 1 }} exit={{ scale: 0 }}>
                <MessageSquare className="w-6 h-6 text-white" />
              </motion.div>}
        </AnimatePresence>
        {/* Unread badge */}
        {!chatOpen && chatMsgs.length > 0 && (
          <span className="absolute -top-1 -right-1 w-4 h-4 bg-red-500 rounded-full
                           text-white text-xs flex items-center justify-center font-bold">
            {chatMsgs.filter(m => m.role === "assistant").length}
          </span>
        )}
      </motion.button>

      {/* Chat panel */}
      <AnimatePresence>
        {chatOpen && (
          <motion.div
            initial={{ opacity: 0, y: 24, scale: 0.95 }}
            animate={{ opacity: 1, y: 0,  scale: 1    }}
            exit={{    opacity: 0, y: 24, scale: 0.95 }}
            className="fixed bottom-24 right-6 z-50 w-96 max-h-[70vh]
                       bg-slate-900 border border-slate-700/50 rounded-2xl shadow-2xl
                       flex flex-col overflow-hidden"
          >
            {/* Header */}
            <div className="flex items-center gap-3 p-4 border-b border-slate-700/50
                            bg-gradient-to-r from-indigo-600/20 to-purple-600/20">
              <div className="w-8 h-8 bg-indigo-600 rounded-full flex items-center justify-center">
                <Sparkles className="w-4 h-4 text-white" />
              </div>
              <div className="flex-1">
                <p className="text-sm font-semibold text-white">AI Ops Assistant</p>
                <p className="text-xs text-slate-400">Ask about your incidents &amp; data</p>
              </div>
              <button onClick={() => { setChatMsgs([]); setSuggestions([]); }}
                className="text-xs text-slate-600 hover:text-slate-400 transition-colors px-2">
                Clear
              </button>
            </div>

            {/* Messages */}
            <div className="flex-1 overflow-y-auto p-4 space-y-3 min-h-0">
              {chatMsgs.length === 0 && (
                <div className="text-center py-4">
                  <Bot className="w-8 h-8 text-indigo-400/50 mx-auto mb-2" />
                  <p className="text-xs text-slate-600 mb-3">
                    Ask me anything about your ops data!
                  </p>
                  {/* Suggestions */}
                  <div className="space-y-2">
                    {suggestions.slice(0, 4).map((s, i) => (
                      <button key={i} onClick={() => sendChatMessage(s)}
                        className="block w-full text-left text-xs text-slate-400
                                   bg-slate-800/60 hover:bg-slate-700/60 border border-slate-700/40
                                   hover:border-indigo-500/40 rounded-lg px-3 py-2 transition-all">
                        {s}
                      </button>
                    ))}
                  </div>
                </div>
              )}
              {chatMsgs.map((msg, i) => (
                <div key={i}
                  className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}>
                  <div className={`max-w-[85%] rounded-xl px-3 py-2 text-xs leading-relaxed
                    ${msg.role === "user"
                      ? "bg-indigo-600 text-white rounded-br-sm"
                      : "bg-slate-800 text-slate-300 border border-slate-700/40 rounded-bl-sm"}`}>
                    {msg.content}
                    <p className={`text-xs mt-1 ${msg.role === "user" ? "text-indigo-300" : "text-slate-600"}`}>
                      {msg.time}
                    </p>
                  </div>
                </div>
              ))}
              {chatLoading && (
                <div className="flex justify-start">
                  <div className="bg-slate-800 border border-slate-700/40 rounded-xl rounded-bl-sm px-3 py-2">
                    <div className="flex gap-1">
                      {[0,1,2].map(i => (
                        <div key={i} className="w-1.5 h-1.5 bg-indigo-400 rounded-full animate-bounce"
                          style={{ animationDelay: `${i * 0.15}s` }} />
                      ))}
                    </div>
                  </div>
                </div>
              )}
              <div ref={chatEndRef} />
            </div>

            {/* Input */}
            <div className="p-3 border-t border-slate-700/50 flex gap-2">
              <input
                value={chatInput}
                onChange={e => setChatInput(e.target.value)}
                onKeyDown={e => e.key === "Enter" && sendChatMessage()}
                placeholder="Ask about incidents, P1s, stats…"
                className="flex-1 bg-slate-800/60 border border-slate-700/50 rounded-xl
                           px-3 py-2 text-xs text-slate-200 placeholder:text-slate-600
                           focus:outline-none focus:ring-2 focus:ring-indigo-500/40 transition-all"
              />
              <button onClick={() => sendChatMessage()} disabled={chatLoading || !chatInput.trim()}
                className="p-2 bg-indigo-600 hover:bg-indigo-500 text-white rounded-xl
                           transition-colors disabled:opacity-40 disabled:cursor-not-allowed">
                <Send className="w-3.5 h-3.5" />
              </button>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

    </div>
  );
}
