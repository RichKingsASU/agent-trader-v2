import { AlertTriangle, ShieldAlert } from 'lucide-react';

interface LockdownBannerProps {
    isHalted: boolean;
    onLockdown: () => void;
    isLoading: boolean;
}

export const LockdownBanner = ({ isHalted, onLockdown, isLoading }: LockdownBannerProps) => {
    if (isHalted) {
        return (
            <div className="bg-red-900/50 border border-red-500/50 rounded-xl p-6 mb-8 animate-pulse">
                <div className="flex items-center gap-4">
                    <ShieldAlert className="w-12 h-12 text-red-500" />
                    <div>
                        <h1 className="text-2xl font-bold text-red-100">SYSTEM LOCKED DOWN</h1>
                        <p className="text-red-200 mt-1">
                            Execution is globally halted (`EXECUTION_HALTED=1`). No new intents can be submitted.
                            Check logs and manually reset environment variables to resume.
                        </p>
                    </div>
                </div>
            </div>
        );
    }

    return (
        <div className="flex justify-end mb-8">
            <button
                onClick={onLockdown}
                disabled={isLoading}
                className="flex items-center gap-2 bg-red-900/30 hover:bg-red-900/50 text-red-400 hover:text-red-300 px-4 py-2 rounded-lg border border-red-900/50 transition-colors"
            >
                <AlertTriangle className="w-4 h-4" />
                {isLoading ? 'Locking...' : 'Emergency Lockdown'}
            </button>
        </div>
    );
};
