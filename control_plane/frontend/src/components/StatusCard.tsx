import { AlertCircle, CheckCircle2, Lock, Unlock } from 'lucide-react';

interface StatusItemProps {
    label: string;
    value: boolean | string;
    expected?: boolean | string;
    isBoolean?: boolean;
}

const StatusItem = ({ label, value, expected, isBoolean = false }: StatusItemProps) => {
    let isGood = false;
    if (isBoolean) {
        isGood = value === (expected ?? true);
    } else {
        isGood = value === expected;
    }

    return (
        <div className="flex items-center justify-between p-3 bg-gray-800 rounded-lg border border-gray-700">
            <span className="text-gray-300 font-medium">{label}</span>
            <div className="flex items-center gap-2">
                <span className={`font-mono text-sm ${isGood ? 'text-green-400' : 'text-red-400'}`}>
                    {String(value)}
                </span>
                {isGood ? (
                    <CheckCircle2 className="w-5 h-5 text-green-500" />
                ) : (
                    <AlertCircle className="w-5 h-5 text-red-500" />
                )}
            </div>
        </div>
    );
};

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

export const StatusCard = ({ status }: { status: SystemStatus | null }) => {
    if (!status) return <div className="animate-pulse h-64 bg-gray-800 rounded-xl"></div>;

    const isLockedDown = status.execution_halted;

    return (
        <div className="bg-gray-900 rounded-xl border border-gray-800 p-6 shadow-xl">
            <div className="flex items-center justify-between mb-6">
                <h2 className="text-xl font-bold text-white flex items-center gap-2">
                    <div className={`w-3 h-3 rounded-full ${isLockedDown ? 'bg-red-500 animate-pulse' : 'bg-green-500'}`}></div>
                    System Status
                </h2>
                <span className="text-xs text-gray-500 font-mono">
                    {new Date(status.timestamp).toLocaleTimeString()}
                </span>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <StatusItem
                    label="Trading Mode"
                    value={status.trading_mode}
                    expected="paper"
                />
                <StatusItem
                    label="Execution Mode"
                    value={status.options_execution_mode}
                    expected="paper"
                />
                <StatusItem
                    label="Execution Enabled"
                    value={status.execution_enabled}
                    isBoolean
                    expected={true}
                />
                <StatusItem
                    label="Guard Locked"
                    value={status.exec_guard_locked}
                    isBoolean
                    expected={false}
                />
                <StatusItem
                    label="Paper API URL"
                    value={status.apca_url_is_paper}
                    isBoolean
                    expected={true}
                />
                <StatusItem
                    label="Execution Halted"
                    value={status.execution_halted}
                    isBoolean
                    expected={false}
                />
            </div>

            <div className="mt-6 pt-4 border-t border-gray-800 flex justify-between text-sm text-gray-400">
                <span>Operator: <span className="text-white">{status.operator}</span></span>
                <div className="flex items-center gap-1">
                    {status.exec_guard_locked ? <Lock className="w-3 h-3" /> : <Unlock className="w-3 h-3 text-yellow-500" />}
                    <span>{status.exec_guard_locked ? 'Guard Active' : 'Guard Unlocked'}</span>
                </div>
            </div>
        </div>
    );
};
