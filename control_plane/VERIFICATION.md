# Operator Control Plane - Verification Checklist

## Code Verification

### Compilation
- [x] All Python files compile without syntax errors
- [x] No import errors in static analysis

### File Structure
```
control_plane/
├── __init__.py                 ✓ Created
├── app.py                      ✓ Created
├── auth.py                     ✓ Created
├── config.py                   ✓ Created
├── routes/
│   ├── __init__.py            ✓ Created
│   ├── status.py              ✓ Created
│   └── intent.py              ✓ Created
├── requirements.txt            ✓ Created
├── Dockerfile                  ✓ Created
├── DEPLOYMENT.md               ✓ Created
└── SECURITY.md                 ✓ Created
```

## Safety Invariant Verification

### 1. Paper Trading Only
- [x] `config.py` validates `APCA_API_BASE_URL` is paper-api
- [x] `is_execution_allowed()` checks paper URL
- [x] No live trading paths exist

### 2. Default to Shadow Mode
- [x] `TRADING_MODE` defaults to `"shadow"`
- [x] `OPTIONS_EXECUTION_MODE` defaults to `"shadow"`
- [x] Execution disabled by default

### 3. 5-Step Execution Gate
- [x] Checks `TRADING_MODE=paper`
- [x] Checks `OPTIONS_EXECUTION_MODE=paper`
- [x] Checks `EXECUTION_ENABLED=1`
- [x] Checks `EXEC_GUARD_UNLOCK=1`
- [x] Checks `EXECUTION_CONFIRM_TOKEN` present

### 4. Auto-Lockdown
- [x] `_apply_lockdown()` sets `EXECUTION_HALTED=1`
- [x] Called immediately after execution
- [x] Called even on execution failure

### 5. UI Isolation
- [x] UI never talks to Alpaca (backend-only execution)
- [x] All execution via `process_option_intent()`
- [x] No direct Alpaca client in routes

### 6. No Secret Storage
- [x] All config from environment variables
- [x] No hardcoded credentials
- [x] No secrets in code

### 7. Kill Switch
- [x] `EXECUTION_HALTED` checked in `is_execution_allowed()`
- [x] `/api/lockdown` endpoint sets halt flag
- [x] Execution blocked when halted

## API Endpoint Verification

### GET /api/status
- [x] Returns current system state
- [x] Read-only (no modifications)
- [x] Requires authentication
- [x] Returns all safety flags

### GET /api/intents
- [x] Reads from Firestore (read-only)
- [x] Requires authentication
- [x] Returns last N intents
- [x] No execution capability

### POST /api/intent/submit
- [x] Validates confirmation token
- [x] Checks ALL 5 safety invariants
- [x] Creates SPY ATM CALL only
- [x] Quantity hardcoded to 1
- [x] Calls existing `process_option_intent()`
- [x] Applies lockdown immediately
- [x] Applies lockdown even on failure
- [x] Requires authentication

### POST /api/lockdown
- [x] Sets `EXECUTION_HALTED=1`
- [x] Returns confirmation
- [x] Requires authentication

## Authentication Verification

### OAuth Flow
- [x] Google OAuth configured
- [x] Email allowlist enforced
- [x] Session-based authentication
- [x] 1-hour session timeout
- [x] HTTPS-only cookies

### Authorization
- [x] All `/api/*` routes require auth
- [x] Public routes: `/auth/*`, `/health`, `/`
- [x] Unauthorized users redirected to login

## Deployment Verification

### Docker
- [x] Dockerfile created
- [x] Copies backend code (for imports)
- [x] Installs dependencies
- [x] Exposes port 8080
- [x] Runs uvicorn

### Cloud Run
- [x] Deployment instructions provided
- [x] Environment variables documented
- [x] Max instances set to 1
- [x] HTTPS enforced
- [x] Custom domain instructions

## Security Verification

### Threat Mitigation
- [x] Unauthorized access: OAuth + allowlist
- [x] Accidental live trading: Paper URL validation
- [x] Repeat executions: Auto-lockdown
- [x] Secret exposure: Environment-only config
- [x] Concurrent executions: max-instances=1
- [x] Session hijacking: HTTPS + secure cookies

### Documentation
- [x] Security notes created
- [x] Threat model documented
- [x] Operator warnings included
- [x] Incident response plan
- [x] Audit trail documented

## Testing Checklist (Manual)

### Local Testing
- [ ] Install dependencies: `pip install -r control_plane/requirements.txt`
- [ ] Set environment variables (see DEPLOYMENT.md)
- [ ] Run: `python3 control_plane/app.py`
- [ ] Test `/health` endpoint
- [ ] Test OAuth login flow
- [ ] Test `/api/status` endpoint
- [ ] Test safety invariant validation

### Cloud Run Testing
- [ ] Build Docker image
- [ ] Push to Artifact Registry
- [ ] Deploy to Cloud Run
- [ ] Configure OAuth redirect URI
- [ ] Test OAuth login
- [ ] Test `/api/status` with auth
- [ ] Enable execution flags
- [ ] Test `/api/intent/submit` (PAPER ONLY)
- [ ] Verify auto-lockdown
- [ ] Test `/api/lockdown`
- [ ] Review Cloud Run logs

## Operator Warnings

> [!CAUTION]
> **Before First Execution**
> 
> 1. Verify `APCA_API_BASE_URL=https://paper-api.alpaca.markets`
> 2. Verify Alpaca credentials are for PAPER account
> 3. Test with small quantity (qty=1 is hardcoded)
> 4. Have kill switch ready (`/api/lockdown`)
> 5. Monitor Cloud Run logs in real-time

> [!WARNING]
> **After Each Execution**
> 
> 1. Verify auto-lockdown applied (`EXECUTION_HALTED=1`)
> 2. Check Alpaca paper account for order
> 3. Review Cloud Run logs for errors
> 4. Manually reset flags if another trade needed

## Next Steps

1. **Local Testing**: Test the backend locally with mock environment
2. **Cloud Run Deployment**: Deploy to staging environment
3. **OAuth Configuration**: Set up Google OAuth credentials
4. **Operator Training**: Train operators on the workflow
5. **Production Deployment**: Deploy to production with monitoring
6. **First Paper Trade**: Execute supervised paper trade
7. **Post-Trade Review**: Review logs and verify lockdown

## Sign-Off

- [ ] Code reviewed by senior engineer
- [ ] Security review completed
- [ ] Deployment tested in staging
- [ ] Operator trained on workflow
- [ ] Incident response plan documented
- [ ] Monitoring configured
- [ ] Ready for production deployment
