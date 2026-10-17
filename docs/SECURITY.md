# Security

## Threat Model

This project runs in a public GitHub repository. Key threats:

1. **Secret exposure**: API keys, bot tokens, and chat IDs must never appear in
   code, logs, commits, or artifacts.
2. **Malicious content**: Feed and article content is untrusted and may contain
   prompt injection attempts.
3. **Supply chain**: Dependencies could be compromised.
4. **Fork attacks**: Malicious PRs could attempt to exfiltrate secrets.

## Mitigations

See the full security requirements in the project plan (section 12).
Detailed mitigations documented after Phase 5 security review.

## Reporting Vulnerabilities

Use GitHub's private security advisory feature to report vulnerabilities.
Do NOT open public issues for security concerns.
