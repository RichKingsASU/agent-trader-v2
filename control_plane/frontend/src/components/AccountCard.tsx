import { Wallet, TrendingUp } from 'lucide-react';

interface AccountSummary {
    equity: number;
    buying_power: number;
    cash: number;
    currency: string;
    status: string;
}

export const AccountCard = ({ account }: { account: AccountSummary | null }) => {
    if (!account) return <div className="animate-pulse h-32 bg-gray-800 rounded-xl"></div>;

    const formatCurrency = (val: number) =>
        new Intl.NumberFormat('en-US', { style: 'currency', currency: account.currency }).format(val);

    return (
        <div className="bg-gray-900 rounded-xl border border-gray-800 p-6 shadow-xl">
            <h2 className="text-xl font-bold text-white mb-6 flex items-center gap-2">
                <Wallet className="w-5 h-5 text-blue-400" />
                Trading Account
            </h2>

            <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                <div>
                    <label className="text-xs text-gray-500 uppercase font-bold tracking-wider">Equity</label>
                    <div className="text-2xl font-bold text-white flex items-center gap-2">
                        {formatCurrency(account.equity)}
                    </div>
                </div>
                <div>
                    <label className="text-xs text-gray-500 uppercase font-bold tracking-wider">Buying Power</label>
                    <div className="text-2xl font-bold text-white">
                        {formatCurrency(account.buying_power)}
                    </div>
                </div>
                <div>
                    <label className="text-xs text-gray-500 uppercase font-bold tracking-wider">Cash</label>
                    <div className="text-2xl font-bold text-gray-300">
                        {formatCurrency(account.cash)}
                    </div>
                </div>
            </div>

            <div className="mt-6 pt-4 border-t border-gray-800 flex items-center justify-between text-sm">
                <span className="text-gray-500">Account Status: <span className="text-green-400 capitalize">{account.status}</span></span>
                <div className="flex items-center gap-1 text-blue-400 font-medium">
                    <TrendingUp className="w-4 h-4" />
                    <span>Real-time Data Active</span>
                </div>
            </div>
        </div>
    );
};
