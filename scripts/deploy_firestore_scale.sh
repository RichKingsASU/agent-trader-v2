#!/bin/bash

# Firestore Scale & Optimization Deployment Script
# 
# This script deploys all components needed for SaaS scale:
# - Firestore indexes
# - Firestore security rules
# - Cloud Functions (onboarding, rate limiting)
#
# Usage: ./scripts/deploy_firestore_scale.sh [--skip-functions]

set -e

echo "🚀 Firestore Scale & Optimization Deployment"
echo "============================================"
echo ""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check if Firebase CLI is installed
if ! command -v firebase &> /dev/null; then
    echo -e "${RED}❌ Firebase CLI not found${NC}"
    echo "Install: npm install -g firebase-tools"
    exit 1
fi

echo -e "${GREEN}✅ Firebase CLI found${NC}"
echo ""

# Check if user is logged in
if ! firebase projects:list &> /dev/null; then
    echo -e "${RED}❌ Not logged in to Firebase${NC}"
    echo "Run: firebase login"
    exit 1
fi

echo -e "${GREEN}✅ Firebase authentication verified${NC}"
echo ""

# Get current project
PROJECT=$(firebase use | grep "active project" | awk '{print $NF}' | tr -d '()')
echo -e "📦 Current project: ${GREEN}${PROJECT}${NC}"
echo ""

# Confirm deployment
read -p "Deploy to project ${PROJECT}? (y/n) " -n 1 -r
echo ""
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Deployment cancelled"
    exit 0
fi

echo ""
echo "🔧 Step 1/4: Deploying Firestore indexes..."
echo "⏱️  This will take 2-5 minutes (indexes build in background)"
echo ""

firebase deploy --only firestore:indexes

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✅ Indexes deployed successfully${NC}"
else
    echo -e "${RED}❌ Index deployment failed${NC}"
    exit 1
fi

echo ""
echo "🔐 Step 2/4: Deploying Firestore security rules..."
echo ""

firebase deploy --only firestore:rules

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✅ Security rules deployed successfully${NC}"
else
    echo -e "${RED}❌ Security rules deployment failed${NC}"
    exit 1
fi

# Check if --skip-functions flag is set
if [[ "$1" == "--skip-functions" ]]; then
    echo ""
    echo -e "${YELLOW}⚠️  Skipping Cloud Functions deployment (--skip-functions flag)${NC}"
    echo ""
    echo "🎉 Deployment complete (indexes + rules only)"
    echo ""
    echo "Next steps:"
    echo "1. Deploy functions manually: firebase deploy --only functions"
    echo "2. Enable Identity Platform blocking functions in Firebase Console"
    echo "3. Test user onboarding"
    exit 0
fi

echo ""
echo "⚡ Step 3/4: Deploying Cloud Functions..."
echo ""

# Change to functions directory
cd functions

# Check if requirements.txt exists
if [ ! -f "requirements.txt" ]; then
    echo -e "${RED}❌ requirements.txt not found in functions/${NC}"
    echo "Run from project root: cd /workspace && ./scripts/deploy_firestore_scale.sh"
    exit 1
fi

# Deploy onboarding functions
echo "Deploying user_onboarding functions..."
firebase deploy --only functions:on_user_signup,functions:on_user_created,functions:provision_user_manually

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✅ Cloud Functions deployed successfully${NC}"
else
    echo -e "${RED}❌ Cloud Functions deployment failed${NC}"
    exit 1
fi

# Return to project root
cd ..

echo ""
echo "🎯 Step 4/4: Configuration checklist"
echo ""

echo -e "${YELLOW}⚠️  Manual configuration required:${NC}"
echo ""
echo "1. Enable Identity Platform:"
echo "   - Go to Firebase Console → Authentication → Settings → Advanced"
echo "   - Enable 'Identity Platform'"
echo ""
echo "2. Enable Blocking Functions:"
echo "   - Go to Identity Platform → Settings → Blocking Functions"
echo "   - Enable 'on_user_signup' (Before user created)"
echo "   - Enable 'on_user_created' (After user created)"
echo ""
echo "3. Verify indexes are building:"
echo "   - Go to Firebase Console → Firestore → Indexes"
echo "   - Wait for all indexes to show 'Enabled' status (2-5 minutes)"
echo ""

echo ""
echo "🎉 Deployment complete!"
echo ""
echo "Summary:"
echo "  ✅ Firestore indexes: Deployed (building in background)"
echo "  ✅ Security rules: Deployed"
echo "  ✅ Cloud Functions: Deployed"
echo "  ⚠️  Identity Platform: Manual setup required (see above)"
echo ""

echo "Next steps:"
echo "1. Complete manual configuration (see above)"
echo "2. Test user onboarding:"
echo "   - Create test user in Firebase Console → Authentication"
echo "   - Verify Firestore documents are created"
echo "3. Monitor logs:"
echo "   firebase functions:log --only on_user_created"
echo "4. Review documentation:"
echo "   - FIRESTORE_SCALE_OPTIMIZATION.md (full guide)"
echo "   - FIRESTORE_SCALE_QUICK_START.md (quick reference)"
echo ""

echo "Questions? Check the documentation or file a GitHub issue."
echo ""
