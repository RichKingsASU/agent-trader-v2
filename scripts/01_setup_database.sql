-- Add session column to market_data_1m for historical bars
ALTER TABLE public.market_data_1m
ADD COLUMN IF NOT EXISTS session TEXT;

-- Create live_quotes table for realtime streaming data
CREATE TABLE IF NOT EXISTS public.live_quotes (
    symbol TEXT NOT NULL PRIMARY KEY,
    ts TIMESTAMPTZ NOT NULL,
    bid_price NUMERIC(10, 2) NOT NULL,
    bid_size BIGINT NOT NULL,
    ask_price NUMERIC(10, 2) NOT NULL,
    ask_size BIGINT NOT NULL,
    session TEXT
);

-- Grant basic permissions to the anon role as per Phase 3 requirements
GRANT SELECT ON public.live_quotes TO anon;
GRANT SELECT ON public.market_data_1m TO anon;

-- Production readiness improvements for Phase 3
ALTER TABLE public.live_quotes ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.live_quotes REPLICA IDENTITY FULL;

-- Allow anonymous users to read from the live_quotes table
CREATE POLICY "Allow anonymous read access to live quotes"
ON public.live_quotes
FOR SELECT
TO anon
USING (true);

-- Allow anonymous users to read from the market_data_1m table
ALTER TABLE public.market_data_1m ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Allow anonymous read access to market data"
ON public.market_data_1m
FOR SELECT
TO anon
USING (true);
