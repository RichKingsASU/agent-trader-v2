import firebase_admin
from firebase_admin import credentials, firestore
from decimal import Decimal
import uuid

# Initialize Firebase Admin
# Assumes GOOGLE_APPLICATION_CREDENTIALS environment variable is set
firebase_admin.initialize_app()
db = firestore.client()

def initialize_users(count=1000):
    batch = db.batch()
    batch_count = 0
    total_initialized = 0

    print(f"🚀 Initializing {count} user paths...")

    for i in range(count):
        # Generate a deterministic or random UID for the simulation
        # In production, these correspond to Firebase Auth UIDs
        uid = str(uuid.uuid4())
        user_ref = db.collection('users').document(uid)
        
        # 1. Base User Profile
        batch.set(user_ref, {
            'tenantId': uid,
            'createdAt': firestore.SERVER_TIMESTAMP,
            'status': 'active',
            'tier': 'institutional'
        })

        # 2. Risk Guards Initial State (Smart Risk Guards Module)
        risk_ref = user_ref.collection('config').document('riskGuards')
        batch.set(risk_ref, {
            'dailyLossLimit': str(Decimal('500.00')), # Precision enforcement
            'vixGuardEnabled': True,
            'maxDrawdown': str(Decimal('0.02'))
        })

        # 3. Trade Journal Placeholder (AI Post-Game Journal Module)
        journal_ref = user_ref.collection('tradeJournal').document('init')
        batch.set(journal_ref, {
            'note': 'System initialized. Awaiting first trade for Gemini analysis.',
            'timestamp': firestore.SERVER_TIMESTAMP
        })

        batch_count += 3 # Three docs per user
        
        # Firestore batch limit is 500 operations
        if batch_count >= 450:
            batch.commit()
            total_initialized += (batch_count // 3)
            print(f"✅ Committed batch. Total users created: {total_initialized}")
            batch = db.batch()
            batch_count = 0

    # Final commit for remaining
    if batch_count > 0:
        batch.commit()
        total_initialized += (batch_count // 3)

    print(f"🏁 Successfully initialized {total_initialized} user tenants.")

if __name__ == "__main__":
    initialize_users(1000)
