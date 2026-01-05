-- Create paper_trades table
CREATE TABLE IF NOT EXISTS public.paper_trades (
    trade_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at TIMESTAMPTZ DEFAULT now() NOT NULL,
    user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE,
    broker_account_id UUID NOT NULL, -- Could reference a broker_accounts table if exists
    strategy_id UUID, -- Optional: link to a strategy if applicable
    symbol TEXT NOT NULL,
    side TEXT NOT NULL, -- 'buy' or 'sell'
    qty NUMERIC NOT NULL,
    price NUMERIC(10, 2) NOT NULL,
    order_type TEXT NOT NULL, -- 'market', 'limit', 'stop'
    time_in_force TEXT NOT NULL, -- 'day', 'gtc'
    status TEXT NOT NULL, -- 'filled', 'open', 'canceled'
    notional NUMERIC(10, 2), -- Total value of the trade
    commission NUMERIC(10, 2) DEFAULT 0.0,
    filled_avg_price NUMERIC(10, 2),
    filled_qty NUMERIC,
    source TEXT, -- e.g., 'manual', 'algobot'
    -- Constraints
    CONSTRAINT chk_side CHECK (side IN ('buy', 'sell')),
    CONSTRAINT chk_order_type CHECK (order_type IN ('market', 'limit', 'stop')),
    CONSTRAINT chk_time_in_force CHECK (time_in_force IN ('day', 'gtc')),
    CONSTRAINT chk_status CHECK (status IN ('filled', 'open', 'canceled'))
);

-- Enable Row Level Security for paper_trades
ALTER TABLE public.paper_trades ENABLE ROW LEVEL SECURITY;

-- Allow anonymous users to insert (optional, for paper trading testing)
CREATE POLICY "Allow anon insert for paper trades"
ON public.paper_trades
FOR INSERT
TO anon
WITH CHECK (true); -- Consider more restrictive check in prod for specific users

-- Allow anonymous users to select their own paper trades (assuming user_id is passed, or for all if no user_id)
CREATE POLICY "Allow anon select for paper trades"
ON public.paper_trades
FOR SELECT
TO anon
USING (true); -- Adjust for user_id based filtering if applicable (auth.uid() = user_id)

-- Optional: Allow authenticated users to manage their own trades
-- CREATE POLICY "Users can manage their own paper trades"
--   ON public.paper_trades FOR ALL USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id);

-- Set REPLICA IDENTITY FULL for realtime updates
ALTER TABLE public.paper_trades REPLICA IDENTITY FULL;
