import { useEffect, useState } from 'react';
import { StatusCard } from './components/StatusCard';
import { LockdownBanner } from './components/LockdownBanner';
import { ExecutionForm } from './components/ExecutionForm';
import { ShieldCheck, Activity } from 'lucide-react';

interface SystemStatus {
    trading_mode: string;
    options_execution_mode: string;
    execution_enabled: boolean;
    execution_halted: boolean;
    exec_guard_locked: boolean;
    apca_url_is_paper: boolean;
    timestamp: string;
    operator: string;
}

function App() {
    const [status, setStatus] = useState<SystemStatus | null>(null);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [successMsg, setSuccessMsg] = useState<string | null>(null);

    const fetchStatus = async () => {
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
    };

    // Poll status
    useEffect(() => {
        fetchStatus();
        const interval = setInterval(fetchStatus, 5000);
        return () => clearInterval(interval);
    }, []);

    const handleLockdown = async () => {
        if (!confirm("Are you sure you want to HALT execution globally?")) return;

        setLoading(true);
        try {
            const res = await fetch('/api/lockdown', { method: 'POST' });
            const data = await res.json();
            if (data.success) {
                setSuccessMsg("Global Lockdown Enabled");
                fetchStatus();
            }
        } catch (err) {
            setError("Failed to apply lockdown");
        } finally {
            setLoading(false);
        }
    };

    const handleSubmitIntent = async (token: string) => {
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

            if (!res.ok) {
                throw new Error(data.detail || data.message || "Execution failed");
            }

            setSuccessMsg(`Success! Intent Submitted. System is now LOCKED DOWN.`);
            fetchStatus();

        } catch (err: any) {
            setError(err.message);
            // Even on error, refresher status as lockdown might have triggered
            fetchStatus();
        } finally {
            setLoading(false);
        }
    };

    const isExecutionAllowed = status ? (
        !status.execution_halted &&
        status.execution_enabled &&
        !status.exec_guard_locked &&
        status.trading_mode === 'paper' &&
        status.options_execution_mode === 'paper' &&
        status.apca_url_is_paper
    ) : false;

    return (
        <div className="min-h-screen bg-black text-gray-100 p-4 md:p-8 font-sans">
            <div className="max-w-4xl mx-auto">

                {/* Header */}
                <header className="flex items-center justify-between mb-8 pb-6 border-b border-gray-800">
                    <div className="flex items-center gap-3">
                        <ShieldCheck className="w-8 h-8 text-blue-500" />
                        <div>
                            <h1 className="text-2xl font-bold tracking-tight">Operator Control Plane</h1>
                            <p className="text-gray-500 text-sm">Supervised Paper Options Trading</p>
                        </div>
                    </div>
                    <div className="flex items-center gap-2 px-3 py-1 bg-gray-900 rounded-full border border-gray-800">
                        <Activity className="w-4 h-4 text-green-500 animate-pulse" />
                        <span className="text-xs font-mono text-gray-400">LIVE CONNECTION</span>
                    </div>
                </header>

                {/* Global Alerts */}
                {error && (
                    <div className="mb-6 p-4 bg-red-900/40 border border-red-500/50 rounded-lg text-red-200">
                        <strong>Error:</strong> {error}
                    </div>
                )}
                {successMsg && (
                    <div className="mb-6 p-4 bg-green-900/40 border border-green-500/50 rounded-lg text-green-200">
                        <strong>Result:</strong> {successMsg}
                    </div>
                )}

                {/* Components */}
                <LockdownBanner
                    isHalted={status?.execution_halted ?? false}
                    onLockdown={handleLockdown}
                    isLoading={loading}
                />

                <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
                    <div className="space-y-8">
                        <StatusCard status={status} />

                        {/* Operator Notes */}
                        <div className="bg-gray-900/50 p-6 rounded-xl border border-gray-800/50">
                            <h3 className="text-sm font-bold text-gray-400 uppercase tracking-wider mb-3">
                                Operator Checklist
                            </h3>
                            <ul className="space-y-2 text-sm text-gray-500">
                                <li>• Verify Status is all GREEN</li>
                                <li>• Have kill switch ready</li>
                                <li>• Monitor Alpaca Dashboard</li>
                                <li>• Reset flags after trade</li>
                            </ul>
                        </div>
                    </div>

                    <div>
                        <ExecutionForm
                            onSubmit={handleSubmitIntent}
                            isAllowed={isExecutionAllowed}
                            isLoading={loading}
                        />
                    </div>
                </div>
            </div>
        </div>
    )
}

export default App
