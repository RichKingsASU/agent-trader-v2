import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { 
  Check, 
  TrendingUp, 
  Zap, 
  Shield, 
  BarChart3, 
  Activity,
  ChevronRight,
  Sparkles
} from "lucide-react";
import { useAuth } from "@/contexts/AuthContext";

interface PricingTier {
  name: string;
  price: string;
  period: string;
  description: string;
  features: string[];
  highlighted?: boolean;
  cta: string;
}

const pricingTiers: PricingTier[] = [
  {
    name: "Basic",
    price: "$49",
    period: "/month",
    description: "Perfect for individual traders getting started with algorithmic trading",
    features: [
      "Up to 3 active strategies",
      "Real-time market data",
      "Paper trading mode",
      "Basic analytics dashboard",
      "Email support",
      "Community access",
    ],
    cta: "Start Free Trial",
  },
  {
    name: "Pro",
    price: "$199",
    period: "/month",
    description: "Advanced features for professional traders and active portfolios",
    features: [
      "Unlimited strategies",
      "Live trading with Alpaca",
      "Advanced risk management",
      "Custom indicators & signals",
      "Priority support (24/7)",
      "API access",
      "Multi-account management",
      "Performance analytics",
    ],
    highlighted: true,
    cta: "Get Started",
  },
  {
    name: "Institutional",
    price: "Custom",
    period: "pricing",
    description: "Enterprise-grade solution for institutions and hedge funds",
    features: [
      "Everything in Pro",
      "White-label solution",
      "Dedicated infrastructure",
      "Custom integrations",
      "SLA guarantees",
      "Dedicated account manager",
      "On-premise deployment options",
      "Custom compliance tools",
    ],
    cta: "Contact Sales",
  },
];

export default function Landing() {
  const navigate = useNavigate();
  const { user, login } = useAuth();
  const [isConnecting, setIsConnecting] = useState(false);

  const handleConnectAlpaca = async () => {
    if (!user) {
      // If not logged in, redirect to auth
      await login();
      return;
    }

    setIsConnecting(true);
    
    // Redirect to settings or Alpaca connection page
    // For now, just navigate to the dashboard
    setTimeout(() => {
      setIsConnecting(false);
      navigate("/");
    }, 1000);
  };

  const handleGetStarted = (tier: PricingTier) => {
    if (tier.name === "Institutional") {
      // Open contact form or email
      window.location.href = "mailto:sales@agenttrader.com?subject=Institutional Plan Inquiry";
    } else {
      handleConnectAlpaca();
    }
  };

  return (
    <div className="min-h-screen bg-gradient-to-b from-background via-background to-muted/20">
      {/* Hero Section */}
      <div className="relative overflow-hidden">
        <div className="absolute inset-0 bg-gradient-to-r from-primary/10 via-accent/10 to-primary/10 animate-pulse opacity-20"></div>
        
        <div className="container mx-auto px-4 py-24 relative z-10">
          <div className="text-center max-w-4xl mx-auto space-y-6">
            <Badge className="glass-card px-4 py-2 text-sm neon-border-blue">
              <Sparkles className="h-4 w-4 mr-2 inline" />
              AI-Powered Trading Platform
            </Badge>
            
            <h1 className="text-5xl md:text-7xl font-bold tracking-tight">
              Trade Smarter with{" "}
              <span className="text-transparent bg-clip-text bg-gradient-to-r from-primary to-accent neon-glow-blue">
                AgentTrader
              </span>
            </h1>
            
            <p className="text-xl md:text-2xl text-muted-foreground max-w-2xl mx-auto">
              Professional algorithmic trading platform powered by AI. Connect your Alpaca account and start trading in minutes.
            </p>
            
            <div className="flex flex-col sm:flex-row gap-4 justify-center pt-6">
              <Button 
                size="lg" 
                onClick={handleConnectAlpaca}
                disabled={isConnecting}
                className="glass-intense text-lg px-8 py-6 neon-border-blue hover:neon-glow-blue transition-all"
              >
                {isConnecting ? (
                  <>
                    <Activity className="h-5 w-5 mr-2 animate-spin" />
                    Connecting...
                  </>
                ) : (
                  <>
                    <Zap className="h-5 w-5 mr-2" />
                    Connect Alpaca Account
                  </>
                )}
              </Button>
              
              <Button 
                size="lg" 
                variant="outline"
                onClick={() => navigate("/mission-control")}
                className="glass-subtle text-lg px-8 py-6 hover:glass-card transition-all"
              >
                View Demo
                <ChevronRight className="h-5 w-5 ml-2" />
              </Button>
            </div>
          </div>
        </div>
      </div>

      {/* Features Section */}
      <div className="container mx-auto px-4 py-24">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-8">
          <Card className="glass-card p-8 hover:glass-intense transition-all">
            <div className="space-y-4">
              <div className="h-12 w-12 rounded-full bg-primary/20 flex items-center justify-center">
                <TrendingUp className="h-6 w-6 text-primary" />
              </div>
              <h3 className="text-2xl font-bold ui-label">Smart Trading</h3>
              <p className="text-muted-foreground">
                AI-powered strategies that adapt to market conditions in real-time
              </p>
            </div>
          </Card>
          
          <Card className="glass-card p-8 hover:glass-intense transition-all">
            <div className="space-y-4">
              <div className="h-12 w-12 rounded-full bg-bull/20 flex items-center justify-center">
                <Shield className="h-6 w-6 text-bull" />
              </div>
              <h3 className="text-2xl font-bold ui-label">Risk Management</h3>
              <p className="text-muted-foreground">
                Advanced risk controls to protect your portfolio at all times
              </p>
            </div>
          </Card>
          
          <Card className="glass-card p-8 hover:glass-intense transition-all">
            <div className="space-y-4">
              <div className="h-12 w-12 rounded-full bg-accent/20 flex items-center justify-center">
                <BarChart3 className="h-6 w-6 text-accent" />
              </div>
              <h3 className="text-2xl font-bold ui-label">Analytics</h3>
              <p className="text-muted-foreground">
                Comprehensive performance tracking and detailed trade analytics
              </p>
            </div>
          </Card>
        </div>
      </div>

      {/* Pricing Section */}
      <div className="container mx-auto px-4 py-24">
        <div className="text-center mb-16 space-y-4">
          <h2 className="text-4xl md:text-5xl font-bold tracking-tight">
            Choose Your Plan
          </h2>
          <p className="text-xl text-muted-foreground max-w-2xl mx-auto">
            Start with a free trial. No credit card required. Cancel anytime.
          </p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-8 max-w-7xl mx-auto">
          {pricingTiers.map((tier, index) => (
            <Card
              key={index}
              className={`p-8 relative overflow-hidden transition-all ${
                tier.highlighted
                  ? "glass-intense neon-border-blue scale-105 md:scale-110"
                  : "glass-card hover:glass-intense"
              }`}
            >
              {tier.highlighted && (
                <Badge className="absolute top-4 right-4 bg-primary text-primary-foreground">
                  Most Popular
                </Badge>
              )}
              
              <div className="space-y-6">
                <div>
                  <h3 className="text-2xl font-bold ui-label mb-2">{tier.name}</h3>
                  <div className="flex items-baseline gap-1">
                    <span className="text-4xl font-bold number-mono">{tier.price}</span>
                    <span className="text-muted-foreground">{tier.period}</span>
                  </div>
                  <p className="text-sm text-muted-foreground mt-4">
                    {tier.description}
                  </p>
                </div>

                <div className="space-y-3">
                  {tier.features.map((feature, idx) => (
                    <div key={idx} className="flex items-start gap-3">
                      <Check className="h-5 w-5 text-bull flex-shrink-0 mt-0.5" />
                      <span className="text-sm">{feature}</span>
                    </div>
                  ))}
                </div>

                <Button
                  onClick={() => handleGetStarted(tier)}
                  className={`w-full ${
                    tier.highlighted
                      ? "neon-border-blue bg-primary hover:bg-primary/90"
                      : "glass-subtle hover:glass-card"
                  }`}
                  size="lg"
                >
                  {tier.cta}
                  <ChevronRight className="h-4 w-4 ml-2" />
                </Button>
              </div>
            </Card>
          ))}
        </div>

        <div className="text-center mt-12">
          <p className="text-sm text-muted-foreground">
            All plans include a 14-day free trial. No credit card required.
          </p>
        </div>
      </div>

      {/* CTA Section */}
      <div className="container mx-auto px-4 py-24">
        <Card className="glass-intense p-12 text-center space-y-6 fintech-gradient-intense">
          <h2 className="text-3xl md:text-4xl font-bold">
            Ready to Transform Your Trading?
          </h2>
          <p className="text-xl text-muted-foreground max-w-2xl mx-auto">
            Join thousands of traders using AI-powered strategies to maximize returns.
          </p>
          <Button 
            size="lg" 
            onClick={handleConnectAlpaca}
            disabled={isConnecting}
            className="glass-card text-lg px-8 py-6 neon-border-green hover:pulse-glow transition-all"
          >
            <Zap className="h-5 w-5 mr-2" />
            Connect Your Alpaca Account Now
          </Button>
          
          <p className="text-sm text-muted-foreground">
            Secure OAuth connection. Your credentials are never stored.
          </p>
        </Card>
      </div>

      {/* Footer */}
      <footer className="border-t border-white/10 py-8">
        <div className="container mx-auto px-4">
          <div className="flex flex-col md:flex-row justify-between items-center gap-4">
            <p className="text-sm text-muted-foreground">
              © 2025 AgentTrader. All rights reserved.
            </p>
            <div className="flex gap-6 text-sm text-muted-foreground">
              <a href="#" className="hover:text-foreground transition-colors">Terms</a>
              <a href="#" className="hover:text-foreground transition-colors">Privacy</a>
              <a href="#" className="hover:text-foreground transition-colors">Docs</a>
              <a href="#" className="hover:text-foreground transition-colors">Support</a>
            </div>
          </div>
        </div>
      </footer>
    </div>
  );
}
