#!/usr/bin/env python3
"""
Seed Firestore with sample sentiment data for the Sentiment Heatmap treemap.

This script populates the marketData/sentiment/sectors collection with
realistic sector sentiment data for visualization testing.

Usage:
    python scripts/seed_sentiment_data.py
"""

import os
import sys
from datetime import datetime

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import firebase_admin
from firebase_admin import credentials, firestore
from backend.persistence.firebase_client import require_firestore_emulator_or_allow_prod

# Sample sector data with realistic market caps and sentiment scores
SECTOR_DATA = [
    {
        "id": "Technology",
        "value": 1_500_000_000_000,  # $1.5T
        "sentiment": 0.75,
        "leadingTicker": "NVDA",
        "description": "AI and semiconductor boom driving strong sentiment"
    },
    {
        "id": "Healthcare",
        "value": 1_200_000_000_000,  # $1.2T
        "sentiment": 0.05,
        "leadingTicker": "UNH",
        "description": "Stable but facing regulatory headwinds"
    },
    {
        "id": "Financials",
        "value": 1_100_000_000_000,  # $1.1T
        "sentiment": 0.35,
        "leadingTicker": "JPM",
        "description": "Benefiting from higher interest rates"
    },
    {
        "id": "Consumer Discretionary",
        "value": 950_000_000_000,  # $950B
        "sentiment": -0.25,
        "leadingTicker": "AMZN",
        "description": "Concerns about consumer spending slowdown"
    },
    {
        "id": "Communication Services",
        "value": 850_000_000_000,  # $850B
        "sentiment": 0.42,
        "leadingTicker": "GOOGL",
        "description": "AI integration driving optimism"
    },
    {
        "id": "Industrials",
        "value": 800_000_000_000,  # $800B
        "sentiment": 0.18,
        "leadingTicker": "BA",
        "description": "Recovery momentum with supply chain improvements"
    },
    {
        "id": "Consumer Staples",
        "value": 750_000_000_000,  # $750B
        "sentiment": -0.12,
        "leadingTicker": "WMT",
        "description": "Defensive sector with margin pressure"
    },
    {
        "id": "Energy",
        "value": 650_000_000_000,  # $650B
        "sentiment": -0.68,
        "leadingTicker": "XOM",
        "description": "Oil price weakness and green energy transition concerns"
    },
    {
        "id": "Utilities",
        "value": 450_000_000_000,  # $450B
        "sentiment": -0.35,
        "leadingTicker": "NEE",
        "description": "High debt levels and rate sensitivity"
    },
    {
        "id": "Real Estate",
        "value": 400_000_000_000,  # $400B
        "sentiment": -0.45,
        "leadingTicker": "PLD",
        "description": "Commercial real estate headwinds persist"
    },
    {
        "id": "Materials",
        "value": 350_000_000_000,  # $350B
        "sentiment": 0.22,
        "leadingTicker": "LIN",
        "description": "Industrial demand supporting moderate optimism"
    }
]


def initialize_firebase():
    """Initialize Firebase Admin SDK."""
    if not firebase_admin._apps:
        # Try to use Application Default Credentials first
        try:
            require_firestore_emulator_or_allow_prod(caller="scripts.seed_sentiment_data.initialize_firebase")
            firebase_admin.initialize_app()
            print("✓ Initialized Firebase with Application Default Credentials")
        except Exception as e:
            print(f"✗ Failed to initialize Firebase: {e}")
            print("\nPlease ensure you have:")
            print("1. Set GOOGLE_APPLICATION_CREDENTIALS environment variable, or")
            print("2. Run 'gcloud auth application-default login'")
            sys.exit(1)
    
    return firestore.client()


def seed_sentiment_data(db):
    """Seed the Firestore database with sentiment data."""
    print("\n🌱 Seeding sentiment data to Firestore...\n")
    
    batch = db.batch()
    timestamp = firestore.SERVER_TIMESTAMP
    
    for sector in SECTOR_DATA:
        # Create document reference
        doc_ref = (
            db.collection("marketData")
            .document("sentiment")
            .collection("sectors")
            .document(sector["id"])
        )
        
        # Prepare document data
        doc_data = {
            "value": sector["value"],
            "sentiment": sector["sentiment"],
            "leadingTicker": sector["leadingTicker"],
            "description": sector["description"],
            "lastUpdated": timestamp,
            "seededAt": datetime.utcnow().isoformat()
        }
        
        batch.set(doc_ref, doc_data)
        
        # Color indicator for display
        sentiment_val = sector["sentiment"]
        if sentiment_val > 0.3:
            color = "🟢"
        elif sentiment_val < -0.3:
            color = "🔴"
        else:
            color = "⚪"
        
        print(f"{color} {sector['id']:25s} | "
              f"Sentiment: {sector['sentiment']:+.2f} | "
              f"Leading: {sector['leadingTicker']}")
    
    # Commit the batch
    try:
        batch.commit()
        print(f"\n✓ Successfully seeded {len(SECTOR_DATA)} sectors to Firestore!")
        print("\nFirestore Path: marketData/sentiment/sectors")
        print("\nYou can now view the Sentiment Heatmap in the Analytics dashboard.")
    except Exception as e:
        print(f"\n✗ Error seeding data: {e}")
        sys.exit(1)


def verify_data(db):
    """Verify the seeded data."""
    print("\n🔍 Verifying seeded data...\n")
    
    sectors_ref = (
        db.collection("marketData")
        .document("sentiment")
        .collection("sectors")
    )
    
    docs = sectors_ref.stream()
    count = 0
    
    for doc in docs:
        count += 1
        data = doc.to_dict()
        print(f"  ✓ {doc.id}: sentiment={data.get('sentiment')}, "
              f"ticker={data.get('leadingTicker')}")
    
    if count == len(SECTOR_DATA):
        print(f"\n✓ All {count} sectors verified successfully!")
    else:
        print(f"\n⚠ Warning: Expected {len(SECTOR_DATA)} sectors, found {count}")


def main():
    """Main execution function."""
    print("=" * 70)
    print("  Sentiment Heatmap Data Seeder")
    print("=" * 70)
    
    # Initialize Firebase
    db = initialize_firebase()
    
    # Seed the data
    seed_sentiment_data(db)
    
    # Verify the data
    verify_data(db)
    
    print("\n" + "=" * 70)
    print("  Seeding Complete!")
    print("=" * 70)
    print("\n💡 Next Steps:")
    print("   1. Open the frontend application")
    print("   2. Navigate to the Analytics page")
    print("   3. Click on the 'Sentiment' tab")
    print("   4. You should see the treemap with all 11 sectors!\n")


if __name__ == "__main__":
    main()
