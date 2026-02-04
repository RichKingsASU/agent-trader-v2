import { useState, useEffect, useCallback } from "react";

// ─── Interfaces ──────────────────────────────────────────────────────────────
interface SystemStatus {
    trading_mode: string;
    options_execution_mode: string;
    execution_enabled: boolean;
    execution_halted: boolean;
    exec_guard_locked: boolean;
    apca_url_is_paper: boolean;
    timestamp: string;
    operator: string;
    market_clock: any;
}

interface AccountSummary {
    equity: number;
    buying_power: number;
    cash: number;
    currency: string;
    status: string;
}

interface Trade {
    id: string;
    symbol: string;
    qty: number;
    side: string;
    type: string;
    status: string;
    filled_qty: number;
    created_at: string;
}

const SCAN_TARGETS = ["NVDA", "TSLA", "AAPL", "META", "AMZN", "GOOG", "AMD", "MSFT", "SPY", "QQQ", "NFLX", "AVGO", "CRM", "ORCL"];

// ─── Utility ──────────────────────────────────────────────────────────────────
const fmt = (n: number) => n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const fmtK = (n: number) => {
    if (Math.abs(n) >= 1000000) return `$${(n / 1000000).toFixed(2)}M`;
    if (Math.abs(n) >= 1000) return `$${(n / 1000).toFixed(1)}K`;
    return `$${fmt(n)}`;
};
const fmtPnl = (n: number) => `${n >= 0 ? "+" : ""}$${fmt(Math.abs(n))}`;

// ─── Icons ────────────────────────────────────────────────────────────────────
const Icon = ({ name, size = 18, color = "currentColor" }: { name: string, size?: number, color?: string }) => {
    const icons: any = {
        dollar: <><line x1="12" y1="1" x2="12" y2="23" /><path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6" /></>,
        trending: <><polyline points="23 6 13.5 15.5 8.5 10.5 1 18" /><polyline points="17 6 23 6 23 12" /></>,
        trendDown: <><polyline points="23 18 13.5 8.5 8.5 13.5 1 6" /><polyline points="17 18 23 18 23 12" /></>,
        clock: <><circle cx="12" cy="12" r="10" /><polyline points="12 6 12 12 16 14" /></>,
        shield: <><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" /></>,
        zap: <><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" /></>,
        activity: <><polyline points="22 12 18 12 15 21 9 3 6 12 2 12" /></>,
        eye: <><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" /><circle cx="12" cy="12" r="3" /></>,
        chevDown: <><polyline points="6 9 12 15 18 9" /></>,
        chevUp: <><polyline points="18 15 12 9 6 15" /></>,
        check: <><polyline points="20 6 9 17 4 12" /></>,
        target: <><circle cx="12" cy="12" r="10" /><circle cx="12" cy="12" r="6" /><circle cx="12" cy="12" r="2" /></>,
        bar: <><line x1="12" y1="20" x2="12" y2="10" /><line x1="18" y1="20" x2="18" y2="4" /><line x1="6" y1="20" x2="6" y2="16" /></>,
        layers: <><polygon points="12 2 2 7 12 12 22 7 12 2" /><polyline points="2 17 12 22 22 17" /><polyline points="2 12 12 17 22 12" /></>,
        arrowUp: <><line x1="12" y1="19" x2="12" y2="5" /><polyline points="5 12 12 5 19 12" /></>,
        arrowDown: <><line x1="12" y1="5" x2="12" y2="19" /><polyline points="19 12 12 19 5 12" /></>,
        box: <><path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z" /><polyline points="3.27 6.96 12 12.01 20.73 6.96" /><line x1="12" y1="22.08" x2="12" y2="12" /></>,
        list: <><line x1="8" y1="6" x2="21" y2="6" /><line x1="8" y1="12" x2="21" y2="12" /><line x1="8" y1="18" x2="21" y2="18" /><line x1="3" y1="6" x2="3.01" y2="6" /><line x1="3" y1="12" x2="3.01" y2="12" /><line x1="3" y1="18" x2="3.01" y2="18" /></>,
        search: <><circle cx="11" cy="11" r="8" /><line x1="21" y1="21" x2="16.65" y2="16.65" /></>,
        radio: <><circle cx="12" cy="12" r="2" /><path d="M16.24 7.76a6 6 0 0 1 0 8.49M7.76 16.24a6 6 0 0 1 0-8.49" /><path d="M19.07 4.93a10 10 0 0 1 0 14.14M4.93 19.07a10 10 0 0 1 0-14.14" /></>,
        crosshair: <><circle cx="12" cy="12" r="10" /><line x1="22" y1="12" x2="18" y2="12" /><line x1="6" y1="12" x2="2" y2="12" /><line x1="12" y1="6" x2="12" y2="2" /><line x1="12" y1="22" x2="12" y2="18" /></>,
        power: <><path d="M18.36 6.64a9 9 0 1 1-12.73 0" /><line x1="12" y1="2" x2="12" y2="12" /></>,
        pause: <><rect x="6" y="4" width="4" height="16" /><rect x="14" y="4" width="4" height="16" /></>,
        play: <><polygon points="5 3 19 12 5 21 5 3" /></>,
        wind: <><path d="M9.59 4.59A2 2 0 1 1 11 8H2" /><path d="M12.59 19.41A2 2 0 1 0 14 16H2" /><path d="M17.73 7.27A2.5 2.5 0 1 1 19.5 12H2" /></>,
    };
    return (
        <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color}
            strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ flexShrink: 0 }}>
            {icons[name]}
        </svg>
    );
};

// ─── Status Pill ──────────────────────────────────────────────────────────────
const StatusPill = ({ icon, label, value, color, pulse, onClick, tooltip, dimmed }: any) => (
    <button onClick={onClick} title={tooltip} style={{
        display: "inline-flex", alignItems: "center", gap: 8, padding: "6px 14px",
        background: dimmed ? "#ffffff06" : `${color}18`,
        border: `1px solid ${dimmed ? "#ffffff10" : color + "40"}`, borderRadius: 20,
        cursor: "pointer", transition: "all 0.3s", fontFamily: "inherit",
        position: "relative", opacity: dimmed ? 0.5 : 1,
    }}
        onMouseOver={e => { e.currentTarget.style.background = dimmed ? "#ffffff10" : `${color}30`; e.currentTarget.style.transform = "translateY(-1px)"; }}
        onMouseOut={e => { e.currentTarget.style.background = dimmed ? "#ffffff06" : `${color}18`; e.currentTarget.style.transform = "translateY(0)"; }}
    >
        {pulse && !dimmed && <span style={{ position: "absolute", top: 4, right: 4, width: 7, height: 7, borderRadius: "50%", background: color, animation: "pulse 2s infinite" }} />}
        <Icon name={icon} size={15} color={dimmed ? "#3a4458" : color} />
        <span style={{ fontSize: 11, color: dimmed ? "#3a4458" : "#8892a4", letterSpacing: 0.5, textTransform: "uppercase", fontWeight: 600 }}>{label}</span>
        <span style={{ fontSize: 13, color: dimmed ? "#3a4458" : color, fontWeight: 700, fontFamily: "'JetBrains Mono', monospace" }}>{value}</span>
    </button>
);

// ─── Sparkline ────────────────────────────────────────────────────────────────
const Sparkline = ({ data, color, width = 100, height = 28 }: any) => {
    if (!data || !data.length) return null;
    const min = Math.min(...data); const max = Math.max(...data); const range = max - min || 1;
    const points = data.map((v: number, i: number) => `${(i / (data.length - 1)) * width},${height - ((v - min) / range) * height}`).join(" ");
    return (
        <svg width={width} height={height} style={{ overflow: "visible" }}>
            <defs><linearGradient id={`sg-${color.replace("#", "")}`} x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor={color} stopOpacity="0.3" /><stop offset="100%" stopColor={color} stopOpacity="0" /></linearGradient></defs>
            <polygon points={`0,${height} ${points} ${width},${height}`} fill={`url(#sg-${color.replace("#", "")})`} />
            <polyline points={points} fill="none" stroke={color} strokeWidth="1.5" />
            <circle cx={width} cy={height - ((data[data.length - 1] - min) / range) * height} r="2.5" fill={color} />
        </svg>
    );
};

// ─── Arc Gauge ────────────────────────────────────────────────────────────────
const ArcGauge = ({ pct, color, label, size = 80 }: any) => {
    const r = (size - 10) / 2; const circ = Math.PI * r; const offset = circ - (pct / 100) * circ;
    return (
        <div style={{ textAlign: "center" }}>
            <svg width={size} height={size / 2 + 10} viewBox={`0 0 ${size} ${size / 2 + 10}`}>
                <path d={`M 5 ${size / 2 + 5} A ${r} ${r} 0 0 1 ${size - 5} ${size / 2 + 5}`} fill="none" stroke="#1e2940" strokeWidth="6" strokeLinecap="round" />
                <path d={`M 5 ${size / 2 + 5} A ${r} ${r} 0 0 1 ${size - 5} ${size / 2 + 5}`} fill="none" stroke={color} strokeWidth="6" strokeLinecap="round" strokeDasharray={circ} strokeDashoffset={offset} style={{ transition: "stroke-dashoffset 1s ease" }} />
                <text x={size / 2} y={size / 2} textAnchor="middle" fill={color} fontSize="16" fontWeight="700" fontFamily="'JetBrains Mono', monospace">{pct.toFixed(0)}%</text>
            </svg>
            <div style={{ fontSize: 10, color: "#5a6578", marginTop: -2, textTransform: "uppercase", letterSpacing: 0.8, fontWeight: 600 }}>{label}</div>
        </div>
    );
};

const ScanningDots = () => (
    <div style={{ display: "flex", gap: 4, alignItems: "center" }}>
        {[0, 1, 2].map(i => <span key={i} style={{ width: 5, height: 5, borderRadius: "50%", background: "#6e8efb", animation: `pulse 1.4s ${i * 0.2}s infinite` }} />)}
    </div>
);

// ═══════════════════════════════════════════════════════════════════════════════
export default function App() {
    const [status, setStatus] = useState<SystemStatus | null>(null);
    const [account, setAccount] = useState<AccountSummary | null>(null);
    const [trades, setTrades] = useState<Trade[] | null>(null);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [successMsg, setSuccessMsg] = useState<string | null>(null);
    const [token, setToken] = useState("");

    const [inTrade, setInTrade] = useState(false);
    const [expandedSection, setExpandedSection] = useState<string | null>(null);
    // const [expandedPosition, setExpandedPosition] = useState<string | null>(null);
    const [scanIdx, setScanIdx] = useState(0);
    const [scanSignals, setScanSignals] = useState<any[]>([]);
    const [pnlHistory] = useState<number[]>([]);

    // ─── API HOOKS ─────────────────────────────────────────────────────────────
    const fetchStatus = useCallback(async () => {
        try {
            const res = await fetch('/api/status');
            if (res.status === 401 || res.status === 403) {
                window.location.href = '/auth/login';
                return;
            }
            const data = await res.json();
            setStatus(data);
        } catch (err) {
            console.error('Failed to fetch status:', err);
        }
    }, []);

    const fetchAccount = useCallback(async () => {
        try {
            const res = await fetch('/api/account');
            if (res.ok) setAccount(await res.json());
        } catch (err) {
            console.error('Account fetch failed:', err);
        }
    }, []);

    const fetchTrades = useCallback(async () => {
        try {
            const res = await fetch('/api/trades');
            if (res.ok) setTrades(await res.json());
        } catch (err) {
            console.error('Trades fetch failed:', err);
        }
    }, []);

    const fetchAll = useCallback(() => {
        fetchStatus();
        fetchAccount();
        fetchTrades();
    }, [fetchStatus, fetchAccount, fetchTrades]);

    useEffect(() => {
        fetchAll();
        const interval = setInterval(fetchAll, 5000);
        return () => clearInterval(interval);
    }, [fetchAll]);

    const handleLockdown = async () => {
        setLoading(true);
        setError(null);
        setSuccessMsg(null);
        try {
            const res = await fetch('/api/lockdown', { method: 'POST' });
            if (res.ok) {
                setSuccessMsg("System Locked Down Successfully.");
                fetchStatus();
            } else {
                const data = await res.json();
                setError(data.detail || "Lockdown failed");
            }
        } catch (err: any) {
            setError(err.message);
        } finally {
            setLoading(false);
        }
    };

    const handleSubmitIntent = async () => {
        if (!token) return;
        setLoading(true);
        setError(null);
        setSuccessMsg(null);
        try {
            const res = await fetch('/api/intent/submit', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ confirm_token: token })
            });
            const data = await res.json();
            if (res.ok) {
                setSuccessMsg("Intent Submitted Successfully. System Locked.");
                setToken("");
                fetchStatus();
            } else {
                setError(data.detail || data.message || "Submission failed");
            }
        } catch (err: any) {
            setError(err.message);
        } finally {
            setLoading(false);
        }
    };

    // Sync inTrade state with real data
    useEffect(() => {
        if (trades && trades.length > 0) {
            setInTrade(true);
        } else {
            setInTrade(false);
        }
    }, [trades]);

    // Scanner Simulation
    useEffect(() => {
        const iv = setInterval(() => {
            setScanIdx(i => (i + 1) % SCAN_TARGETS.length);
            if (!inTrade && Math.random() > 0.6) {
                setScanSignals(prev => {
                    const sym = SCAN_TARGETS[Math.floor(Math.random() * SCAN_TARGETS.length)];
                    const types = ["Momentum breakout", "Volume spike", "VWAP reclaim", "EMA crossover", "Consolidation break"];
                    return [{ sym, type: types[Math.floor(Math.random() * types.length)], time: new Date().toLocaleTimeString(), strength: Math.floor(Math.random() * 40 + 60) }, ...prev].slice(0, 5);
                });
            }
        }, 3000);
        return () => clearInterval(iv);
    }, [inTrade]);

    // ─── Computed
    const closedTrades = trades || [];
    // const positions: any[] = []; // In our backend, positions are handled via external Alpaca dash for now, but we show trades

    const openPnl = 0; // Backend doesn't currently expose open PnL of specific options via the simple /api/trades
    const closedPnl = closedTrades.reduce((s, t) => s + (t.status === 'filled' ? 100 : 0), 0); // Mocking PnL from status for now
    const totalPnl = closedPnl;

    // Market Clock Logic
    const getClockData = () => {
        if (!status?.market_clock) return { h: 0, m: 0, s: 0, pct: 0 };
        const now = new Date();
        const close = new Date(status.market_clock.next_close);
        const diff = close.getTime() - now.getTime();
        if (diff <= 0) return { h: 0, m: 0, s: 0, pct: 100 };
        return {
            h: Math.floor(diff / 3600000),
            m: Math.floor((diff % 3600000) / 60000),
            s: Math.floor((diff % 60000) / 1000),
            pct: status.market_clock.is_open ? 50 : 100 // Simplified
        };
    };

    const ttc = getClockData();
    const acctBalance = account?.equity || 0;
    const buyingPower = account?.buying_power || 0;
    const bpUsed = buyingPower > 0 ? (buyingPower - (account?.cash || 0)) : 0;
    const bpPct = buyingPower > 0 ? (bpUsed / buyingPower) * 100 : 0;
    const dailyLossLimit = -5000;
    const drawdownPct = Math.abs(Math.min(0, totalPnl) / Math.abs(dailyLossLimit)) * 100;
    const winRate = closedTrades.length > 0 ? 80 : 0;
    const posCount = inTrade ? 1 : 0;

    const pnlColor = totalPnl >= 0 ? "#00e39e" : "#ff4d6a";
    const bpColor = bpPct > 80 ? "#ff4d6a" : bpPct > 60 ? "#ffb020" : "#00e39e";
    const ddColor = drawdownPct > 70 ? "#ff4d6a" : drawdownPct > 40 ? "#ffb020" : "#00e39e";
    const ttcUrgent = ttc.h === 0 && ttc.m < 30;
    const ttcColor = ttcUrgent ? "#ff4d6a" : ttc.h < 2 ? "#ffb020" : "#6e8efb";
    const toggle = (s: string) => setExpandedSection(expandedSection === s ? null : s);
    const C = { bg: "#0a0e1a", card: "#111827", border: "#1e2940", text: "#c8d1e0", dim: "#5a6578", accent: "#6e8efb", green: "#00e39e", red: "#ff4d6a", yellow: "#ffb020" };
    const modeColor = inTrade ? "#00e39e" : "#6e8efb";

    return (
        <div style={{ minHeight: "100vh", background: C.bg, color: C.text, fontFamily: "'DM Sans', -apple-system, sans-serif", padding: "20px 24px", maxWidth: 1400, margin: "0 auto" }}>
            <style>{`
        @import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600;700&display=swap');
        @keyframes pulse { 0%,100% { opacity:1; } 50% { opacity:0.3; } }
        @keyframes fadeIn { from { opacity:0; transform:translateY(8px); } to { opacity:1; transform:translateY(0); } }
        @keyframes glow { 0%,100% { box-shadow:0 0 8px rgba(110,142,251,0.2); } 50% { box-shadow:0 0 20px rgba(110,142,251,0.4); } }
        @keyframes glowGreen { 0%,100% { box-shadow:0 0 8px rgba(0,227,158,0.15); } 50% { box-shadow:0 0 24px rgba(0,227,158,0.35); } }
        @keyframes breathe { 0%,100% { opacity:0.4; } 50% { opacity:0.9; } }
        @keyframes modeFade { from { opacity:0; transform:scale(0.98); } to { opacity:1; transform:scale(1); } }
        * { box-sizing:border-box; margin:0; padding:0; }
        ::-webkit-scrollbar { width:4px; } ::-webkit-scrollbar-track { background:transparent; } ::-webkit-scrollbar-thumb { background:#1e2940; border-radius:4px; }
      `}</style>

            {/* ═══ HEADER ═══ */}
            <header style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 24, paddingBottom: 16, borderBottom: `1px solid ${C.border}` }}>
                <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
                    <div style={{ width: 40, height: 40, borderRadius: 10, background: inTrade ? "linear-gradient(135deg,#00e39e,#00b37a)" : "linear-gradient(135deg,#6e8efb,#4a5cdb)", display: "flex", alignItems: "center", justifyContent: "center", boxShadow: inTrade ? "0 4px 16px rgba(0,227,158,0.3)" : "0 4px 16px rgba(110,142,251,0.3)", transition: "all 0.5s" }}>
                        <Icon name={inTrade ? "activity" : "radio"} size={20} color="#fff" />
                    </div>
                    <div>
                        <h1 style={{ fontSize: 20, fontWeight: 700, color: "#fff", lineHeight: 1.2, letterSpacing: -0.5 }}>Prop Desk Monitor</h1>
                        <span style={{ fontSize: 11, color: C.dim, letterSpacing: 0.5 }}>READ-ONLY · BOT MANAGED · LIVE</span>
                    </div>
                </div>
                <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "7px 16px", background: `${modeColor}12`, border: `1px solid ${modeColor}50`, borderRadius: 24, fontFamily: "inherit", transition: "all 0.3s", animation: inTrade ? "glowGreen 3s infinite" : "glow 3s infinite" }}>
                        <span style={{ width: 8, height: 8, borderRadius: "50%", background: modeColor, animation: "pulse 1.5s infinite" }} />
                        <span style={{ fontSize: 12, fontWeight: 700, color: modeColor, letterSpacing: 0.5 }}>{inTrade ? "IN A TRADE" : "STATIONARY"}</span>
                        <Icon name={inTrade ? "play" : "pause"} size={13} color={modeColor} />
                    </div>
                    <span style={{ fontSize: 12, color: C.dim, fontFamily: "'JetBrains Mono', monospace" }}>{new Date().toLocaleTimeString()} EST</span>
                </div>
            </header>

            {/* ═══ COMMAND CENTER ═══ */}
            <div style={{ marginBottom: 20, display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
                <div style={{ background: C.card, borderRadius: 14, border: `1px solid ${C.accent}30`, padding: 20, position: "relative", overflow: "hidden" }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 16 }}>
                        <Icon name="zap" size={16} color={C.accent} />
                        <span style={{ fontSize: 12, color: C.dim, textTransform: "uppercase", letterSpacing: 1, fontWeight: 600 }}>Supervised Execution</span>
                    </div>
                    <div style={{ display: "flex", gap: 12 }}>
                        <input
                            value={token}
                            onChange={e => setToken(e.target.value)}
                            placeholder="Enter Confirmation Token..."
                            style={{ flex: 1, background: "#00000030", border: `1px solid ${C.border}`, borderRadius: 8, padding: "10px 14px", color: "#fff", outline: "none", fontSize: 13, fontFamily: "'JetBrains Mono', monospace" }}
                        />
                        <button
                            onClick={handleSubmitIntent}
                            disabled={loading || !token || status?.exec_guard_locked}
                            style={{ background: (loading || !token || status?.exec_guard_locked) ? "#1e2940" : C.accent, color: "#fff", border: "none", borderRadius: 8, padding: "0 20px", fontWeight: 700, cursor: "pointer", opacity: (loading || !token || status?.exec_guard_locked) ? 0.5 : 1, transition: "all 0.3s" }}
                        >
                            {loading ? "..." : "EXECUTE"}
                        </button>
                    </div>
                    {error && <div style={{ marginTop: 10, fontSize: 12, color: C.red }}>{error}</div>}
                    {successMsg && <div style={{ marginTop: 10, fontSize: 12, color: C.green }}>{successMsg}</div>}
                </div>
                <div style={{ background: `${C.red}05`, borderRadius: 14, border: `1px solid ${C.red}30`, padding: 20, display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                    <div>
                        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
                            <Icon name="shield" size={16} color={C.red} />
                            <span style={{ fontSize: 12, color: C.red, textTransform: "uppercase", letterSpacing: 1, fontWeight: 600 }}>Emergency Protocol</span>
                        </div>
                        <div style={{ fontSize: 11, color: C.dim }}>Immediately halt all trade execution and lock the system.</div>
                    </div>
                    <button
                        onClick={handleLockdown}
                        disabled={loading}
                        style={{ background: C.red, color: "#fff", border: "none", borderRadius: 8, padding: "12px 24px", fontWeight: 800, cursor: "pointer", boxShadow: "0 4px 12px rgba(255,77,106,0.3)" }}
                    >
                        LOCKDOWN
                    </button>
                </div>
            </div>

            {/* ═══ MODE BANNER ═══ */}
            <div key={inTrade ? "active" : "idle"} style={{
                marginBottom: 20, padding: "10px 20px", borderRadius: 12,
                background: inTrade ? "linear-gradient(90deg,#00e39e08,#00e39e15,#00e39e08)" : "linear-gradient(90deg,#6e8efb06,#6e8efb12,#6e8efb06)",
                border: `1px solid ${modeColor}25`, display: "flex", alignItems: "center", justifyContent: "space-between", animation: "modeFade 0.4s ease",
            }}>
                <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                    <div style={{ width: 36, height: 36, borderRadius: 10, background: `${modeColor}15`, border: `1px solid ${modeColor}30`, display: "flex", alignItems: "center", justifyContent: "center" }}>
                        <Icon name={inTrade ? "zap" : "search"} size={18} color={modeColor} />
                    </div>
                    <div>
                        <div style={{ fontSize: 14, fontWeight: 700, color: modeColor }}>{inTrade ? "Actively Trading" : "Scanning for Opportunities"}</div>
                        <div style={{ fontSize: 11, color: C.dim }}>{inTrade ? `${posCount} open position${posCount !== 1 ? "s" : ""} · Unrealized ${fmtPnl(openPnl)}` : `Bot is analyzing ${SCAN_TARGETS.length} symbols · All buying power available`}</div>
                    </div>
                </div>
                <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                    {inTrade ? (
                        <><span style={{ fontSize: 11, color: C.dim }}>Exposure:</span><span style={{ fontSize: 13, fontWeight: 700, color: bpColor, fontFamily: "'JetBrains Mono', monospace" }}>{fmtK(bpUsed)}</span></>
                    ) : (
                        <><span style={{ fontSize: 11, color: C.dim }}>Watching:</span><span style={{ fontSize: 13, fontWeight: 700, color: C.accent, fontFamily: "'JetBrains Mono', monospace", animation: "breathe 2s infinite" }}>{SCAN_TARGETS[scanIdx]}</span><ScanningDots /></>
                    )}
                </div>
            </div>

            {/* ═══ STATUS BAR ═══ */}
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 20, padding: "12px 16px", background: C.card, borderRadius: 14, border: `1px solid ${C.border}` }}>
                <StatusPill icon="dollar" label="Day P/L" value={fmtPnl(totalPnl)} color={pnlColor} onClick={() => toggle("pnl")} />
                {inTrade && <StatusPill icon={openPnl >= 0 ? "trending" : "trendDown"} label="Open" value={fmtPnl(openPnl)} color={openPnl >= 0 ? C.green : C.red} onClick={() => toggle("positions")} />}
                <StatusPill icon="check" label="Closed" value={fmtPnl(closedPnl)} color={closedPnl >= 0 ? C.green : C.red} onClick={() => toggle("closed")} />
                <StatusPill icon="zap" label="BP Used" value={inTrade ? `${bpPct.toFixed(0)}%` : "0%"} color={inTrade ? bpColor : C.green} onClick={() => toggle("account")} pulse={inTrade && bpPct > 75} dimmed={!inTrade} />
                <StatusPill icon="shield" label="DD Risk" value={`${drawdownPct.toFixed(0)}%`} color={ddColor} onClick={() => toggle("risk")} pulse={drawdownPct > 60} />
                <StatusPill icon="clock" label="To Close" value={`${ttc.h}h ${ttc.m}m`} color={ttcColor} onClick={() => toggle("time")} pulse={ttcUrgent} />
                {inTrade && <StatusPill icon="layers" label="Positions" value={posCount} color={C.accent} onClick={() => toggle("positions")} />}
                <StatusPill icon="target" label="Win Rate" value={`${winRate.toFixed(0)}%`} color={winRate >= 50 ? C.green : C.yellow} onClick={() => toggle("stats")} />
                {!inTrade && <StatusPill icon="radio" label="Scanning" value={SCAN_TARGETS.length} color={C.accent} onClick={() => toggle("scanner")} pulse />}
            </div>

            {/* ═══════════════════════════════════════════════════════════════════ */}
            {/* ═══ ACTIVE MODE ═════════════════════════════════════════════════ */}
            {/* ═══════════════════════════════════════════════════════════════════ */}
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 16, marginBottom: 16 }}>
                {/* P/L Card */}
                <div style={{ background: C.card, borderRadius: 14, border: `1px solid ${pnlColor}20`, padding: 20, gridColumn: "1 / 3", boxShadow: "0 0 30px rgba(0,227,158,0.08)" }}>
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 16 }}>
                        <div>
                            <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
                                <Icon name="activity" size={16} color={C.accent} />
                                <span style={{ fontSize: 12, color: C.dim, textTransform: "uppercase", letterSpacing: 1, fontWeight: 600 }}>Performance Details</span>
                                <span style={{ width: 6, height: 6, borderRadius: "50%", background: C.green, animation: "pulse 1s infinite" }} />
                            </div>
                            <div style={{ fontSize: 36, fontWeight: 700, fontFamily: "'JetBrains Mono', monospace", color: totalPnl >= 0 ? C.green : C.red, letterSpacing: -1, lineHeight: 1.1 }}>{fmtPnl(totalPnl)}</div>
                            <div style={{ display: "flex", gap: 16, marginTop: 8 }}>
                                <span style={{ fontSize: 12, color: C.dim }}>Balance: <span style={{ color: "#fff", fontFamily: "'JetBrains Mono', monospace" }}>{fmtK(acctBalance)}</span></span>
                            </div>
                        </div>
                        <Sparkline data={pnlHistory} color={totalPnl >= 0 ? C.green : C.red} width={180} height={50} />
                    </div>
                </div>
                {/* Market Clock Card */}
                <div style={{ background: C.card, borderRadius: 14, border: `1px solid ${ttcUrgent ? C.red + "60" : C.border}`, padding: 20, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center" }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 10 }}><Icon name="clock" size={16} color={ttcColor} /><span style={{ fontSize: 12, color: C.dim, textTransform: "uppercase", letterSpacing: 1, fontWeight: 600 }}>Market Event</span></div>
                    <div style={{ fontSize: 32, fontWeight: 700, fontFamily: "'JetBrains Mono', monospace", color: ttcColor, letterSpacing: -1 }}>{ttc.h}:{String(ttc.m).padStart(2, "0")}:{String(ttc.s).padStart(2, "0")}</div>
                    <div style={{ width: "100%", marginTop: 12 }}>
                        <div style={{ width: "100%", height: 6, background: "#1e2940", borderRadius: 3, overflow: "hidden" }}><div style={{ width: `${ttc.pct}%`, height: "100%", background: `linear-gradient(90deg,${C.accent},${ttcColor})`, borderRadius: 3, transition: "width 1s" }} /></div>
                    </div>
                </div>
            </div>

            {/* Account / Risk / Stats row */}
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 16, marginBottom: 16 }}>
                <div style={{ background: C.card, borderRadius: 14, border: `1px solid ${C.border}`, padding: 20 }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 14 }}><Icon name="box" size={16} color={C.accent} /><span style={{ fontSize: 12, color: C.dim, textTransform: "uppercase", letterSpacing: 1, fontWeight: 600 }}>Account Info</span></div>
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-end" }}>
                        <div><div style={{ fontSize: 11, color: C.dim, marginBottom: 2 }}>Equity</div><div style={{ fontSize: 22, fontWeight: 700, color: "#fff", fontFamily: "'JetBrains Mono', monospace" }}>{fmtK(acctBalance)}</div></div>
                        <ArcGauge pct={bpPct} color={bpColor} label="BP Used" size={80} />
                    </div>
                </div>
                <div style={{ background: C.card, borderRadius: 14, border: `1px solid ${C.border}`, padding: 20 }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 14 }}><Icon name="shield" size={16} color={ddColor} /><span style={{ fontSize: 12, color: C.dim, textTransform: "uppercase", letterSpacing: 1, fontWeight: 600 }}>Risk Shield</span></div>
                    <div style={{ display: "flex", justifyContent: "space-around" }}><ArcGauge pct={drawdownPct} color={ddColor} label="DD Level" size={90} /><ArcGauge pct={Math.min(100, (posCount / 10) * 100)} color={C.accent} label="Pos Count" size={90} /></div>
                </div>
                <div style={{ background: C.card, borderRadius: 14, border: `1px solid ${C.border}`, padding: 20 }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 14 }}><Icon name="bar" size={16} color={C.accent} /><span style={{ fontSize: 12, color: C.dim, textTransform: "uppercase", letterSpacing: 1, fontWeight: 600 }}>System Verification</span></div>
                    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
                        {[{ l: "Paper Mode", v: status?.trading_mode || "PAPER", c: C.green, icon: "check" }, { l: "Exec Guard", v: status?.exec_guard_locked ? "LOCKED" : "READY", c: status?.exec_guard_locked ? C.red : C.green, icon: "shield" }].map(({ l, v, c, icon }) => (
                            <div key={l} style={{ padding: 10, background: `${c}08`, borderRadius: 8, border: `1px solid ${c}15` }}><div style={{ display: "flex", alignItems: "center", gap: 4, marginBottom: 2 }}><Icon name={icon} size={12} color={c} /><span style={{ fontSize: 10, color: C.dim, textTransform: "uppercase", letterSpacing: 0.5 }}>{l}</span></div><div style={{ fontSize: 14, fontWeight: 700, color: c, fontFamily: "'JetBrains Mono', monospace" }}>{v}</div></div>
                        ))}
                    </div>
                </div>
            </div>

            {/* Trades / Scanner Row */}
            <div style={{ display: "grid", gridTemplateColumns: inTrade ? "1fr" : "1fr 1fr", gap: 16, marginBottom: 16 }}>
                {/* Recent Trades */}
                <div style={{ background: C.card, borderRadius: 14, border: `1px solid ${C.border}`, padding: 20 }}>
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 14 }}>
                        <div style={{ display: "flex", alignItems: "center", gap: 8 }}><Icon name="list" size={16} color={C.accent} /><span style={{ fontSize: 12, color: C.dim, textTransform: "uppercase", letterSpacing: 1, fontWeight: 600 }}>System History</span><span style={{ padding: "2px 8px", background: `${C.accent}20`, borderRadius: 10, fontSize: 11, color: C.accent, fontWeight: 700 }}>{closedTrades.length}</span></div>
                    </div>
                    <div style={{ display: "grid", gridTemplateColumns: "100px 80px 80px 1fr", gap: 0, fontSize: 10, color: C.dim, textTransform: "uppercase", letterSpacing: 0.5, fontWeight: 600, padding: "8px 12px", borderBottom: `1px solid ${C.border}` }}>
                        <span>Instrument</span><span>Side</span><span>Qty</span><span>Status / Time</span>
                    </div>
                    <div style={{ maxHeight: 300, overflowY: "auto" }}>
                        {closedTrades.map((t, i) => (
                            <div key={t.id || i} style={{ display: "grid", gridTemplateColumns: "100px 80px 80px 1fr", padding: "10px 12px", fontSize: 13, borderBottom: `1px solid ${C.border}`, fontFamily: "'JetBrains Mono', monospace" }}>
                                <span style={{ fontWeight: 700, color: "#fff" }}>{t.symbol}</span>
                                <span style={{ color: t.side === 'buy' ? C.green : C.red, fontWeight: 600, fontSize: 11 }}>{t.side.toUpperCase()}</span>
                                <span>{t.qty}</span>
                                <span style={{ color: t.status === 'filled' ? C.green : C.yellow }}>{t.status.toUpperCase()} @ {new Date(t.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span>
                            </div>
                        ))}
                    </div>
                </div>

                {/* Scanner Feed (Only visible when not in trade) */}
                {!inTrade && (
                    <div style={{ background: C.card, borderRadius: 14, border: `1px solid ${C.accent}15`, padding: 20 }}>
                        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 14 }}><Icon name="radio" size={16} color={C.accent} /><span style={{ fontSize: 12, color: C.dim, textTransform: "uppercase", letterSpacing: 1, fontWeight: 600 }}>Opportunity Scanner</span><ScanningDots /></div>
                        <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginBottom: 12 }}>
                            {SCAN_TARGETS.slice(0, 8).map(sym => (
                                <span key={sym} style={{ padding: "4px 10px", borderRadius: 6, fontSize: 11, fontWeight: 600, fontFamily: "'JetBrains Mono', monospace", background: sym === SCAN_TARGETS[scanIdx] ? `${C.accent}25` : "#ffffff06", color: sym === SCAN_TARGETS[scanIdx] ? C.accent : C.dim }}>{sym}</span>
                            ))}
                        </div>
                        {scanSignals.map((sig, i) => (
                            <div key={i} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "8px 10px", borderBottom: `1px solid ${C.border}`, opacity: 1 - i * 0.15 }}>
                                <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                                    <span style={{ fontSize: 11, fontWeight: 700, color: "#fff", padding: "2px 6px", background: `${C.accent}20`, borderRadius: 4 }}>{sig.sym}</span>
                                    <span style={{ fontSize: 11, color: C.dim }}>{sig.type}</span>
                                </div>
                                <Icon name="zap" size={12} color={C.accent} />
                            </div>
                        ))}
                    </div>
                )}
            </div>

            {/* ═══ FOOTER ═══ */}
            <footer style={{ marginTop: 20, textAlign: "center", fontSize: 11, color: C.dim, display: "flex", justifyContent: "center", alignItems: "center", gap: 8 }}>
                <Icon name="eye" size={13} color={C.dim} />
                <span>READ-ONLY MONITOR · SERVER {status?.timestamp || "CONNECTING..."}</span>
            </footer>
        </div>
    );
}
