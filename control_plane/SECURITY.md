# Operator Control Plane - Security Notes

## Architecture Security

### Defense in Depth

1. **OAuth Authentication**
   - Google OAuth 2.0 with email allowlist
   - Only pre-approved operators can access
   - Session-based authentication (1 hour timeout)

2. **API Isolation**
   - UI/Frontend NEVER talks to Alpaca directly
   - All execution goes through backend gate
   - No client-side API keys

3. **Environment Variable Safety**
   - Backend NEVER stores secrets
   - All config from environment only
   - Secrets managed by Cloud Run

4. **5-Step Execution Gate**
   - `TRADING_MODE=paper`
   - `OPTIONS_EXECUTION_MODE=paper`
   - `EXECUTION_ENABLED=1`
   - `EXEC_GUARD_UNLOCK=1`
   - `EXECUTION_CONFIRM_TOKEN` present

5. **Auto-Lockdown**
   - After ONE execution, `EXECUTION_HALTED=1`
   - Prevents accidental repeat executions
   - Requires manual reset

6. **Paper Trading Lock**
   - `APCA_API_BASE_URL` validated to be paper-api
   - Live trading is IMPOSSIBLE via this path
   - URL validation in multiple layers

## Threat Model

### Threats Mitigated

✅ **Unauthorized Access**
- Mitigated by: OAuth + email allowlist

✅ **Accidental Live Trading**
- Mitigated by: Paper URL validation, 5-step gate

✅ **Repeat Executions**
- Mitigated by: Auto-lockdown after single execution

✅ **Secret Exposure**
- Mitigated by: No secrets in code, environment-only config

✅ **Concurrent Executions**
- Mitigated by: Cloud Run max-instances=1

✅ **Session Hijacking**
- Mitigated by: HTTPS-only, secure session cookies, 1-hour timeout

### Residual Risks

⚠️ **Operator Account Compromise**
- **Risk**: If operator's Google account is compromised
- **Mitigation**: Require 2FA for operator accounts
- **Detection**: Monitor Cloud Run logs for unusual activity

⚠️ **Environment Variable Tampering**
- **Risk**: If GCP project access is compromised
- **Mitigation**: Limit GCP IAM permissions, audit logs
- **Detection**: Cloud Audit Logs

⚠️ **Dependency Vulnerabilities**
- **Risk**: Vulnerabilities in FastAPI, authlib, etc.
- **Mitigation**: Regular dependency updates
- **Detection**: Dependabot, security scanning

## Operator Warnings

### CRITICAL WARNINGS

> [!CAUTION]
> **This service can execute REAL paper trades on Alpaca.**
> 
> While paper trading uses fake money, it DOES interact with Alpaca's systems.
> Always verify:
> - `APCA_API_BASE_URL` is `https://paper-api.alpaca.markets`
> - `TRADING_MODE` is `paper`
> - You have the correct confirmation token

> [!WARNING]
> **Auto-lockdown is NOT foolproof.**
> 
> The lockdown mechanism sets `EXECUTION_HALTED=1` AFTER execution completes.
> If the service crashes mid-execution, the lockdown may not apply.
> 
> **Always manually verify** the system is locked after execution.

> [!IMPORTANT]
> **One execution per unlock.**
> 
> This service is designed for supervised, one-at-a-time execution.
> After each trade:
> 1. System auto-locks
> 2. Review the trade result
> 3. Manually reset flags if another trade is needed

## Audit Trail

All actions are logged to Cloud Run logs:

- **Authentication**: Login/logout events with email
- **Status Checks**: Who checked status and when
- **Intent Submissions**: Full details of execution requests
- **Lockdowns**: When and by whom

### Log Retention

- Cloud Run logs: 30 days default
- Recommend: Export to Cloud Logging for longer retention
- Consider: Forward to SIEM for security monitoring

## Incident Response

### If Unauthorized Access Detected

1. **Immediate**: Update `OPERATOR_EMAILS` to remove compromised account
2. **Immediate**: Set `EXECUTION_HALTED=1`
3. **Review**: Cloud Run logs for unauthorized actions
4. **Review**: Firestore for unauthorized intents
5. **Review**: Alpaca paper account for unexpected orders
6. **Reset**: All secrets (OAuth, session, confirmation token)

### If Accidental Live Trading Suspected

1. **STOP**: This should be impossible (paper URL validation)
2. **Verify**: Check `APCA_API_BASE_URL` in Cloud Run config
3. **Verify**: Check Alpaca account type (paper vs live)
4. **Review**: All code paths for URL validation
5. **Report**: File incident report

### If Service Compromise Suspected

1. **Immediate**: Set `EXECUTION_HALTED=1`
2. **Immediate**: Disable Cloud Run service
3. **Review**: Cloud Audit Logs for GCP access
4. **Review**: Container image for tampering
5. **Rebuild**: From clean source
6. **Rotate**: All secrets

## Compliance Notes

### Data Privacy

- **User Data**: Only email addresses stored (in session)
- **Trade Data**: Intent history in Firestore (read-only)
- **Logs**: Cloud Run logs contain operator emails
- **Retention**: Follow your organization's data retention policy

### Audit Requirements

- All executions logged with operator identity
- Logs include timestamps, intent details, results
- Recommend: Export logs to immutable storage

## Security Checklist

Before going live, verify:

- [ ] OAuth credentials are production-ready
- [ ] Operator email allowlist is correct
- [ ] Session secret is random and secure (not default)
- [ ] Cloud Run max-instances is 1
- [ ] HTTPS is enforced (Cloud Run default)
- [ ] Alpaca credentials are for PAPER account
- [ ] `APCA_API_BASE_URL` is paper-api.alpaca.markets
- [ ] Execution flags default to safe values
- [ ] Cloud Run service account has minimal permissions
- [ ] Cloud Audit Logs are enabled
- [ ] Log export is configured
- [ ] Incident response plan is documented
- [ ] Operators have 2FA enabled on Google accounts
