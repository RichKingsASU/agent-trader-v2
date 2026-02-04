import { History, ArrowUpRight, ArrowDownRight } from 'lucide-react';

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

export const TradeHistory = ({ trades }: { trades: Trade[] | null }) => {
    if (!trades) return <div className="animate-pulse h-48 bg-gray-800 rounded-xl"></div>;

    return (
        <div className="bg-gray-900 rounded-xl border border-gray-800 p-6 shadow-xl overflow-hidden">
            <h2 className="text-xl font-bold text-white mb-6 flex items-center gap-2">
                <History className="w-5 h-5 text-purple-400" />
                Recent Orders
            </h2>

            <div className="overflow-x-auto">
                <table className="w-full text-left">
                    <thead>
                        <tr className="text-xs text-gray-500 uppercase font-bold border-b border-gray-800 pb-2">
                            <th className="px-2 py-3">Asset</th>
                            <th className="px-2 py-3">Side</th>
                            <th className="px-2 py-3">Qty</th>
                            <th className="px-2 py-3">Status</th>
                            <th className="px-2 py-3 text-right">Time</th>
                        </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-800">
                        {trades.length === 0 ? (
                            <tr>
                                <td colSpan={5} className="py-8 text-center text-gray-500 text-sm">No recent trades found</td>
                            </tr>
                        ) : (
                            trades.map((trade) => (
                                <tr key={trade.id} className="text-sm hover:bg-gray-800/30 transition-colors">
                                    <td className="px-2 py-4 font-bold text-white">{trade.symbol}</td>
                                    <td className="px-2 py-4">
                                        <div className="flex items-center gap-1">
                                            {trade.side === 'buy' ? (
                                                <ArrowUpRight className="w-4 h-4 text-green-400" />
                                            ) : (
                                                <ArrowDownRight className="w-4 h-4 text-red-400" />
                                            )}
                                            <span className={trade.side === 'buy' ? 'text-green-400' : 'text-red-400'}>
                                                {trade.side.toUpperCase()}
                                            </span>
                                        </div>
                                    </td>
                                    <td className="px-2 py-4 text-gray-300">{trade.qty}</td>
                                    <td className="px-2 py-4">
                                        <span className={`px-2 py-0.5 rounded-full text-[10px] font-bold uppercase ${trade.status === 'filled' ? 'bg-green-500/20 text-green-400' :
                                                trade.status === 'canceled' ? 'bg-gray-500/20 text-gray-400' :
                                                    'bg-blue-500/20 text-blue-400'
                                            }`}>
                                            {trade.status}
                                        </span>
                                    </td>
                                    <td className="px-2 py-4 text-right text-gray-500 text-xs">
                                        {new Date(trade.created_at).toLocaleTimeString()}
                                    </td>
                                </tr>
                            ))
                        )}
                    </tbody>
                </table>
            </div>
        </div>
    );
};
