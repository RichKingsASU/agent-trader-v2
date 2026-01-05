#!/bin/bash
# Multi-Tenant SaaS Migration Verification Script
# Usage: ./scripts/verify_saas_migration.sh

set -e

echo "🔍 Multi-Tenant SaaS Migration Verification"
echo "============================================"
echo ""

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Counters
PASS=0
FAIL=0
WARN=0

# Helper functions
check_pass() {
    echo -e "${GREEN}✅ PASS${NC}: $1"
    ((PASS++))
}

check_fail() {
    echo -e "${RED}❌ FAIL${NC}: $1"
    ((FAIL++))
}

check_warn() {
    echo -e "${YELLOW}⚠️  WARN${NC}: $1"
    ((WARN++))
}

echo "1. Backend Files Verification"
echo "------------------------------"

# Check functions/main.py for user-scoped paths
if grep -q 'users/{userId}/data/snapshot' functions/main.py; then
    check_pass "Multi-tenant path in functions/main.py"
else
    check_fail "Multi-tenant path NOT found in functions/main.py"
fi

if grep -q 'users.*shadowTradeHistory' functions/main.py; then
    check_pass "User-scoped shadowTradeHistory in functions/main.py"
else
    check_fail "User-scoped shadowTradeHistory NOT found"
fi

if grep -q 'users.*signals' functions/main.py; then
    check_pass "User-scoped signals in functions/main.py"
else
    check_fail "User-scoped signals NOT found"
fi

# Check backend/strategy_service/routers/trades.py
if [ -f backend/strategy_service/routers/trades.py ]; then
    if grep -q 'users.*shadowTradeHistory' backend/strategy_service/routers/trades.py; then
        check_pass "User-scoped shadowTradeHistory in trades.py"
    else
        check_fail "User-scoped shadowTradeHistory NOT found in trades.py"
    fi
else
    check_warn "backend/strategy_service/routers/trades.py not found"
fi

echo ""
echo "2. Frontend Files Verification"
echo "-------------------------------"

# Check UserTradingContext.tsx
if [ -f frontend/src/contexts/UserTradingContext.tsx ]; then
    check_pass "UserTradingContext.tsx created"
    
    if grep -q 'users.*uid.*data.*snapshot' frontend/src/contexts/UserTradingContext.tsx; then
        check_pass "UserTradingContext listens to user-scoped account snapshot"
    else
        check_fail "UserTradingContext missing account snapshot listener"
    fi
    
    if grep -q 'shadowTradeHistory' frontend/src/contexts/UserTradingContext.tsx; then
        check_pass "UserTradingContext listens to shadowTradeHistory"
    else
        check_fail "UserTradingContext missing shadowTradeHistory listener"
    fi
else
    check_fail "UserTradingContext.tsx NOT created"
fi

# Check UserTradingPanel.tsx
if [ -f frontend/src/components/UserTradingPanel.tsx ]; then
    check_pass "UserTradingPanel.tsx created"
else
    check_fail "UserTradingPanel.tsx NOT created"
fi

# Check App.tsx for provider
if [ -f frontend/src/App.tsx ]; then
    if grep -q 'UserTradingProvider' frontend/src/App.tsx; then
        check_pass "UserTradingProvider integrated in App.tsx"
    else
        check_fail "UserTradingProvider NOT integrated in App.tsx"
    fi
else
    check_warn "frontend/src/App.tsx not found"
fi

echo ""
echo "3. Security Rules Verification"
echo "-------------------------------"

if [ -f firestore.rules ]; then
    if grep -q 'match /users/{userId}' firestore.rules; then
        check_pass "User-scoped rules defined"
    else
        check_fail "User-scoped rules NOT defined"
    fi
    
    if grep -q 'shadowTradeHistory' firestore.rules; then
        check_pass "shadowTradeHistory rules defined"
    else
        check_fail "shadowTradeHistory rules NOT defined"
    fi
    
    if grep -q 'signals' firestore.rules; then
        check_pass "signals rules defined"
    else
        check_fail "signals rules NOT defined"
    fi
    
    if grep -q 'isOwner' firestore.rules; then
        check_pass "isOwner() function defined"
    else
        check_fail "isOwner() function NOT defined"
    fi
else
    check_fail "firestore.rules NOT found"
fi

echo ""
echo "4. Documentation Verification"
echo "------------------------------"

if [ -f SAAS_ARCHITECTURE.md ]; then
    check_pass "SAAS_ARCHITECTURE.md created"
else
    check_fail "SAAS_ARCHITECTURE.md NOT created"
fi

if [ -f SAAS_QUICK_REFERENCE.md ]; then
    check_pass "SAAS_QUICK_REFERENCE.md created"
else
    check_fail "SAAS_QUICK_REFERENCE.md NOT created"
fi

if [ -f SAAS_IMPLEMENTATION_SUMMARY.md ]; then
    check_pass "SAAS_IMPLEMENTATION_SUMMARY.md created"
else
    check_fail "SAAS_IMPLEMENTATION_SUMMARY.md NOT created"
fi

echo ""
echo "5. Data Isolation Checks"
echo "------------------------"

# Check for any remaining global paths (legacy)
LEGACY_PATTERNS=(
    "collection(\"alpacaAccounts\")"
    "collection(\"tradingSignals\")"
    "collection(\"shadowTradeHistory\")"
)

for pattern in "${LEGACY_PATTERNS[@]}"; do
    # Count occurrences in main.py (should have comments about legacy or be in migration code)
    if grep -q "$pattern" functions/main.py 2>/dev/null; then
        check_warn "Legacy pattern found: $pattern (verify it's for backward compatibility)"
    fi
done

echo ""
echo "============================================"
echo "Verification Summary"
echo "============================================"
echo -e "${GREEN}✅ PASS: $PASS${NC}"
echo -e "${YELLOW}⚠️  WARN: $WARN${NC}"
echo -e "${RED}❌ FAIL: $FAIL${NC}"
echo ""

if [ $FAIL -eq 0 ]; then
    echo -e "${GREEN}🎉 All critical checks passed!${NC}"
    echo ""
    echo "Next Steps:"
    echo "1. Deploy backend: firebase deploy --only functions"
    echo "2. Deploy security rules: firebase deploy --only firestore:rules"
    echo "3. Deploy frontend: cd frontend && npm run build && firebase deploy --only hosting"
    echo "4. Test with multiple user accounts"
    echo ""
    exit 0
else
    echo -e "${RED}⚠️  Some checks failed. Please review the output above.${NC}"
    echo ""
    exit 1
fi
