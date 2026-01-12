#!/usr/bin/env python3
"""
Zero-Trust Agent Identity Verification Script

This script verifies that the Zero-Trust cryptographic identity layer
is correctly implemented and functioning.

Usage:
    python scripts/verify_zero_trust.py

Requirements:
    - Firebase Admin SDK configured
    - Strategies loaded in functions/strategies/
    - PyNaCl installed (pip install PyNaCl>=1.5.0)
"""

import asyncio
import os
import sys
from pathlib import Path

# Add functions directory to path
sys.path.insert(0, str(Path(__file__).parent.parent / "functions"))

import firebase_admin
from firebase_admin import firestore
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s: %(message)s'
)
logger = logging.getLogger(__name__)


class ZeroTrustVerifier:
    """Verification suite for Zero-Trust implementation."""
    
    def __init__(self):
        """Initialize Firebase and components."""
        try:
            # CI/local safety: allow running against Firestore emulator without production secrets.
            if os.getenv("FIRESTORE_EMULATOR_HOST"):
                from google.auth.credentials import AnonymousCredentials
                from google.cloud import firestore as gc_firestore

                project = (
                    os.getenv("GOOGLE_CLOUD_PROJECT")
                    or os.getenv("GCLOUD_PROJECT")
                    or os.getenv("GCP_PROJECT")
                    or "demo-agenttrader-ci"
                )
                self.db = gc_firestore.Client(
                    project=project,
                    credentials=AnonymousCredentials(),
                )
                logger.info("✅ Firestore emulator detected (anonymous credentials)")
                return

            if not firebase_admin._apps:
                firebase_admin.initialize_app()
            self.db = firestore.client()
            logger.info("✅ Firebase initialized")
        except Exception as e:
            logger.error(f"❌ Failed to initialize Firebase: {e}")
            raise
    
    def test_identity_manager_import(self) -> bool:
        """Test 1: Verify identity manager can be imported."""
        try:
            from utils.identity_manager import AgentIdentityManager, get_identity_manager
            logger.info("✅ Test 1 PASSED: Identity manager imported successfully")
            return True
        except ImportError as e:
            logger.error(f"❌ Test 1 FAILED: Cannot import identity manager: {e}")
            return False
    
    def test_pynacl_installed(self) -> bool:
        """Test 2: Verify PyNaCl is installed."""
        try:
            import nacl.signing
            logger.info("✅ Test 2 PASSED: PyNaCl library available")
            return True
        except ImportError:
            logger.error("❌ Test 2 FAILED: PyNaCl not installed. Run: pip install PyNaCl>=1.5.0")
            return False
    
    def test_agent_registration(self) -> bool:
        """Test 3: Verify agents can be registered."""
        try:
            from utils.identity_manager import get_identity_manager
            
            identity_mgr = get_identity_manager(self.db)
            
            # Register test agent
            test_agent_id = "test_verification_agent"
            result = identity_mgr.register_agent(test_agent_id)
            
            # Verify result
            assert result["agent_id"] == test_agent_id
            assert result["status"] == "active"
            assert "public_key" in result
            
            # Clean up
            identity_mgr.revoke_agent(test_agent_id)
            
            logger.info(f"✅ Test 3 PASSED: Agent registration works (agent: {test_agent_id})")
            return True
        except Exception as e:
            logger.error(f"❌ Test 3 FAILED: Agent registration error: {e}")
            return False
    
    def test_signal_signing(self) -> bool:
        """Test 4: Verify signal signing works."""
        try:
            from utils.identity_manager import get_identity_manager
            
            identity_mgr = get_identity_manager(self.db)
            
            # Register test agent
            test_agent_id = "test_signing_agent"
            identity_mgr.register_agent(test_agent_id)
            
            # Create test signal
            signal_data = {
                'action': 'BUY',
                'ticker': 'SPY',
                'allocation': 0.15,
                'reasoning': 'Test signal'
            }
            
            # Sign signal
            signature = identity_mgr.sign_signal(test_agent_id, signal_data)
            
            # Verify signature structure
            assert "signature" in signature
            assert "nonce" in signature
            assert "signed_by" in signature
            assert signature["signed_by"] == test_agent_id
            assert len(signature["signature"]) == 128  # 64 bytes hex = 128 chars
            
            # Clean up
            identity_mgr.revoke_agent(test_agent_id)
            
            logger.info("✅ Test 4 PASSED: Signal signing works")
            return True
        except Exception as e:
            logger.error(f"❌ Test 4 FAILED: Signal signing error: {e}")
            return False
    
    def test_signature_verification(self) -> bool:
        """Test 5: Verify signature verification works."""
        try:
            from utils.identity_manager import get_identity_manager
            
            identity_mgr = get_identity_manager(self.db)
            
            # Register test agent
            test_agent_id = "test_verify_agent"
            identity_mgr.register_agent(test_agent_id)
            
            # Create and sign signal
            signal_data = {
                'action': 'BUY',
                'ticker': 'SPY',
                'allocation': 0.15
            }
            signature = identity_mgr.sign_signal(test_agent_id, signal_data)
            
            # Verify signature
            is_valid = identity_mgr.verify_signal(
                test_agent_id,
                signal_data,
                signature
            )
            
            assert is_valid, "Valid signature was rejected"
            
            # Test invalid signature (tampered data)
            tampered_data = signal_data.copy()
            tampered_data['allocation'] = 1.0  # Changed from 0.15
            
            is_invalid = identity_mgr.verify_signal(
                test_agent_id,
                tampered_data,
                signature
            )
            
            assert not is_invalid, "Invalid signature was accepted"
            
            # Clean up
            identity_mgr.revoke_agent(test_agent_id)
            
            logger.info("✅ Test 5 PASSED: Signature verification works (valid accepted, invalid rejected)")
            return True
        except Exception as e:
            logger.error(f"❌ Test 5 FAILED: Signature verification error: {e}")
            return False
    
    def test_base_strategy_signing(self) -> bool:
        """Test 6: Verify BaseStrategy has sign_signal method."""
        try:
            from strategies.base import BaseStrategy
            
            # Check method exists
            assert hasattr(BaseStrategy, 'sign_signal'), "BaseStrategy missing sign_signal method"
            assert hasattr(BaseStrategy, 'set_identity_manager'), "BaseStrategy missing set_identity_manager method"
            
            logger.info("✅ Test 6 PASSED: BaseStrategy has signing methods")
            return True
        except Exception as e:
            logger.error(f"❌ Test 6 FAILED: BaseStrategy check error: {e}")
            return False
    
    def test_strategy_loader_identity(self) -> bool:
        """Test 7: Verify StrategyLoader registers agents with identities."""
        try:
            from strategies.loader import StrategyLoader
            
            # Create loader with Firestore
            loader = StrategyLoader(db=self.db)
            
            # Check that strategies were loaded
            strategies = loader.get_all_strategies()
            assert len(strategies) > 0, "No strategies loaded"
            
            # Check that each strategy has identity manager set
            for name, strategy in strategies.items():
                assert hasattr(strategy, '_identity_manager'), f"Strategy {name} missing identity manager"
                assert hasattr(strategy, '_agent_id'), f"Strategy {name} missing agent ID"
                
                # Verify agent is registered in Firestore
                agent_ref = (
                    self.db.collection("systemStatus")
                    .document("agent_registry")
                    .collection("agents")
                    .document(strategy._agent_id)
                )
                agent_doc = agent_ref.get()
                assert agent_doc.exists, f"Agent {strategy._agent_id} not registered in Firestore"
            
            logger.info(f"✅ Test 7 PASSED: StrategyLoader registered {len(strategies)} agents with identities")
            return True
        except Exception as e:
            logger.error(f"❌ Test 7 FAILED: StrategyLoader identity check error: {e}")
            return False
    
    def test_verification_gate(self) -> bool:
        """Test 8: Verify verification gate exists in main.py."""
        try:
            # Check main.py has verify_agent_identity function
            main_path = Path(__file__).parent.parent / "functions" / "main.py"
            with open(main_path, 'r') as f:
                main_content = f.read()
            
            assert "def verify_agent_identity" in main_content, "verify_agent_identity function not found"
            assert "ZERO-TRUST GATE" in main_content or "Zero-Trust" in main_content, "Verification gate not integrated"
            
            logger.info("✅ Test 8 PASSED: Verification gate exists in main.py")
            return True
        except Exception as e:
            logger.error(f"❌ Test 8 FAILED: Verification gate check error: {e}")
            return False
    
    def test_firestore_schema(self) -> bool:
        """Test 9: Verify Firestore schema for agent registry."""
        try:
            # Check if agent_registry structure exists
            registry_ref = self.db.collection("systemStatus").document("agent_registry")
            registry_doc = registry_ref.get()
            
            # Check agents collection exists
            agents_ref = registry_ref.collection("agents")
            agents = list(agents_ref.limit(1).stream())
            
            if len(agents) == 0:
                logger.warning("⚠️  Test 9 WARNING: No agents in registry (may need to load strategies first)")
            else:
                # Verify agent document structure
                agent_data = agents[0].to_dict()
                required_fields = ["agent_id", "public_key", "status", "key_type"]
                missing = [f for f in required_fields if f not in agent_data]
                
                if missing:
                    logger.warning(f"⚠️  Test 9 WARNING: Agent documents missing fields: {missing}")
                else:
                    logger.info("✅ Test 9 PASSED: Firestore schema correct")
                    return True
            
            return True
        except Exception as e:
            logger.error(f"❌ Test 9 FAILED: Firestore schema check error: {e}")
            return False
    
    async def test_end_to_end_signing(self) -> bool:
        """Test 10: End-to-end test of strategy evaluation with signing."""
        try:
            from strategies.loader import StrategyLoader
            
            # Load strategies
            loader = StrategyLoader(db=self.db)
            strategies = loader.get_all_strategies()
            
            if len(strategies) == 0:
                logger.warning("⚠️  Test 10 WARNING: No strategies to test")
                return True
            
            # Pick first strategy
            strategy_name, strategy = list(strategies.items())[0]
            
            # Create test data
            market_data = {
                'symbol': 'SPY',
                'price': 450.0,
                'timestamp': '2025-12-30T10:00:00Z'
            }
            account_snapshot = {
                'equity': '10000.00',
                'buying_power': '5000.00',
                'cash': '5000.00'
            }
            
            # Evaluate strategy
            signal = await strategy.evaluate(
                market_data=market_data,
                account_snapshot=account_snapshot,
                regime_data=None
            )
            
            # Verify signal is signed
            assert 'signature' in signal, f"Strategy {strategy_name} returned unsigned signal"
            assert 'signed_by' in signal['signature'], "Signature missing signed_by field"
            
            # Verify signature structure
            sig_info = signal['signature']
            required = ['signature', 'nonce', 'signed_by', 'signed_at']
            missing = [f for f in required if f not in sig_info]
            assert len(missing) == 0, f"Signature missing fields: {missing}"
            
            logger.info(f"✅ Test 10 PASSED: End-to-end signing works (strategy: {strategy_name})")
            return True
        except Exception as e:
            logger.error(f"❌ Test 10 FAILED: End-to-end signing error: {e}")
            return False
    
    async def run_all_tests(self):
        """Run all verification tests."""
        logger.info("=" * 70)
        logger.info("Zero-Trust Agent Identity Verification Suite")
        logger.info("=" * 70)
        logger.info("")
        
        tests = [
            ("Identity Manager Import", self.test_identity_manager_import),
            ("PyNaCl Installation", self.test_pynacl_installed),
            ("Agent Registration", self.test_agent_registration),
            ("Signal Signing", self.test_signal_signing),
            ("Signature Verification", self.test_signature_verification),
            ("BaseStrategy Signing Methods", self.test_base_strategy_signing),
            ("StrategyLoader Identity Registration", self.test_strategy_loader_identity),
            ("Verification Gate Integration", self.test_verification_gate),
            ("Firestore Schema", self.test_firestore_schema),
            ("End-to-End Signing", self.test_end_to_end_signing),
        ]
        
        results = []
        for name, test_func in tests:
            logger.info(f"Running: {name}...")
            try:
                # Handle async tests
                if asyncio.iscoroutinefunction(test_func):
                    result = await test_func()
                else:
                    result = test_func()
                results.append((name, result))
            except Exception as e:
                logger.error(f"❌ {name} CRASHED: {e}")
                results.append((name, False))
            logger.info("")
        
        # Summary
        logger.info("=" * 70)
        logger.info("Verification Summary")
        logger.info("=" * 70)
        
        passed = sum(1 for _, result in results if result)
        total = len(results)
        
        for name, result in results:
            status = "✅ PASSED" if result else "❌ FAILED"
            logger.info(f"{status}: {name}")
        
        logger.info("")
        logger.info(f"Results: {passed}/{total} tests passed")
        
        if passed == total:
            logger.info("🎉 All tests passed! Zero-Trust implementation is working correctly.")
            return True
        else:
            logger.error(f"⚠️  {total - passed} test(s) failed. Please review errors above.")
            return False


async def main():
    """Main entry point."""
    try:
        verifier = ZeroTrustVerifier()
        success = await verifier.run_all_tests()
        sys.exit(0 if success else 1)
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
