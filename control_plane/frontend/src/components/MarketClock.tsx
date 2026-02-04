import { Moon, Sun } from 'lucide-react';
import { useEffect, useState } from 'react';

interface MarketClockData {
    is_open: boolean;
    next_open: string;
    next_close: string;
    timestamp: string;
}

export const MarketClock = ({ clock }: { clock: MarketClockData | null }) => {
    const [timeLeft, setTimeLeft] = useState<string>('--:--:--');

    useEffect(() => {
        if (!clock) return;

        const timer = setInterval(() => {
            const target = clock.is_open ? new Date(clock.next_close) : new Date(clock.next_open);
            const now = new Date();
            const diff = target.getTime() - now.getTime();

            if (diff <= 0) {
                setTimeLeft('00:00:00');
                return;
            }

            const hours = Math.floor(diff / (1000 * 60 * 60));
            const mins = Math.floor((diff % (1000 * 60 * 60)) / (1000 * 60));
            const secs = Math.floor((diff % (1000 * 60)) / 1000);

            setTimeLeft(
                `${hours.toString().padStart(2, '0')}:${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`
            );
        }, 1000);

        return () => clearInterval(timer);
    }, [clock]);

    if (!clock) return <div className="h-20 w-48 bg-gray-800 animate-pulse rounded-full" />;

    return (
        <div className="flex items-center gap-4 px-4 py-2 bg-gray-900 rounded-full border border-gray-800 shadow-inner">
            <div className={`p-2 rounded-full ${clock.is_open ? 'bg-green-500/10' : 'bg-blue-500/10'}`}>
                {clock.is_open ? (
                    <Sun className="w-5 h-5 text-yellow-500" />
                ) : (
                    <Moon className="w-5 h-5 text-blue-400" />
                )}
            </div>
            <div>
                <div className="text-[10px] text-gray-500 uppercase font-bold tracking-tighter">
                    {clock.is_open ? 'Market Closes In' : 'Market Opens In'}
                </div>
                <div className="text-xl font-mono font-bold text-white leading-none">
                    {timeLeft}
                </div>
            </div>
        </div>
    );
};
