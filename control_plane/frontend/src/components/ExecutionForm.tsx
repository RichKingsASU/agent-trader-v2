import { useState } from 'react';
import { Send, AlertOctagon, Info } from 'lucide-react';

interface ExecutionFormProps {
    onSubmit: (token: string) => Promise<void>;
    isAllowed: boolean;
    isLoading: boolean;
}

export const ExecutionForm = ({ onSubmit, isAllowed, isLoading }: ExecutionFormProps) => {
    const [token, setToken] = useState('');
    const [showConfirm, setShowConfirm] = useState(false);

    const handleSubmit = (e: React.FormEvent) => {
        e.preventDefault();
        if (!token) return;
        setShowConfirm(true);
    };

    const handleConfirm = () => {
        onSubmit(token);
        setToken(''); // Clear token immediately
        setShowConfirm(false);
    };

    if (!isAllowed) {
        return (
            <div className="bg-gray-900 rounded-xl border border-gray-800 p-8 text-center text-gray-500">
                <LockIcon className="w-12 h-12 mx-auto mb-4 opacity-20" />
                <h3 className="text-lg font-medium text-gray-300">Execution Disabled</h3>
                <p className="mt-2 text-sm">
                    System safety invariants are not met. Check the status panel above.
                </p>
            </div>
        );
    }

    return (
        <div className="bg-gray-900 rounded-xl border border-gray-800 p-6 shadow-xl">
            <h2 className="text-xl font-bold text-white mb-4 flex items-center gap-2">
                <Send className="w-5 h-5 text-blue-500" />
                Submit Supervised Intent
            </h2>

            <div className="mb-6 bg-blue-900/20 border border-blue-900/50 rounded-lg p-4">
                <h4 className="text-blue-200 font-medium flex items-center gap-2 text-sm mb-2">
                    <Info className="w-4 h-4" />
                    Execution Parameters (Fixed)
                </h4>
                <ul className="text-sm text-blue-300/80 space-y-1 list-disc pl-5 font-mono">
                    <li>Symbol: SPY</li>
                    <li>Type: ATM CALL (Next Friday)</li>
                    <li>Quantity: 1</li>
                    <li>Mode: PAPER TRADING ONLY</li>
                </ul>
            </div>

            <form onSubmit={handleSubmit} className="space-y-4">
                <div>
                    <label className="block text-sm font-medium text-gray-400 mb-1">
                        Execution Confirmation Token
                    </label>
                    <input
                        type="password"
                        value={token}
                        onChange={(e) => setToken(e.target.value)}
                        disabled={isLoading}
                        placeholder="Enter secure token to unlock execution..."
                        className="w-full bg-gray-950 border border-gray-800 rounded-lg px-4 py-3 text-white focus:ring-2 focus:ring-blue-500 focus:border-transparent outline-none transition-all font-mono"
                        autoComplete="off"
                    />
                </div>

                <button
                    type="submit"
                    disabled={!token || isLoading}
                    className="w-full bg-blue-600 hover:bg-blue-500 disabled:bg-gray-800 disabled:text-gray-500 text-white font-bold py-3 rounded-lg transition-all flex items-center justify-center gap-2"
                >
                    {isLoading ? 'Submitting...' : 'Submit Paper Trade'}
                </button>
            </form>

            {/* Confirmation Modal */}
            {showConfirm && (
                <div className="fixed inset-0 bg-black/80 backdrop-blur-sm flex items-center justify-center z-50 p-4">
                    <div className="bg-gray-900 border border-red-500/50 rounded-xl p-8 max-w-md w-full shadow-2xl">
                        <div className="flex items-center gap-3 text-red-500 mb-4">
                            <AlertOctagon className="w-8 h-8" />
                            <h3 className="text-xl font-bold text-white">Confirm Execution</h3>
                        </div>

                        <p className="text-gray-300 mb-6 leading-relaxed">
                            You are about to submit a <strong>REAL PAPER TRADE</strong> order to Alpaca.
                            <br /><br />
                            This will place an order for <strong>1x SPY Call</strong>.
                            <br />
                            The system will <strong>AUTO-LOCK</strong> immediately after execution.
                        </p>

                        <div className="flex gap-3">
                            <button
                                onClick={() => setShowConfirm(false)}
                                className="flex-1 px-4 py-2 bg-gray-800 text-gray-300 rounded-lg hover:bg-gray-700 font-medium"
                            >
                                Cancel
                            </button>
                            <button
                                onClick={handleConfirm}
                                className="flex-1 px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-500 font-bold"
                            >
                                CONFIRM & EXECUTE
                            </button>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
};

const LockIcon = (props: any) => (
    <svg
        {...props}
        xmlns="http://www.w3.org/2000/svg"
        width="24"
        height="24"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
    >
        <rect width="18" height="11" x="3" y="11" rx="2" ry="2" />
        <path d="M7 11V7a5 5 0 0 1 10 0v4" />
    </svg>
)
