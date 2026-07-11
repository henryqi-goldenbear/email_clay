# Free cloud follow-ups (GitHub Actions — $0)

Follow-ups need something running when your PC is off. **GitHub Actions is free** on private repos (~2000 minutes/month). This project uses ~1 minute per check, ~96 checks/day → well within the free tier.

## One-time setup (~10 minutes)

### 1. Enable GitHub cloud mode

```powershell
python cloud/deploy_github.py
```

This sets `CLOUD_FOLLOWUPS=github` in your `.env`.

### 2. Create a **private** GitHub repo

```powershell
cd c:\Users\zhiha\clay_outbound
git init
git remote add origin https://github.com/henryqi-goldenbear/email_clay.git
git add .
git commit -m "Clay outbound"
git push -u origin main
```

**Must be private** — Gmail tokens live in GitHub Secrets, not in git.

### 3. Add GitHub Actions secrets

In your repo: **Settings → Secrets and variables → Actions → New repository secret**

Add these (values from your `.env`):

| Secret | Example |
|--------|---------|
| `GMAIL_OAUTH_CLIENT_ID` | from `.env` |
| `GMAIL_OAUTH_CLIENT_SECRET` | from `.env` |
| `GMAIL_REFRESH_TOKEN` | `refresh_token` from `.gmail_tokens.json` |
| `SENDER_EMAIL` | `henryqi@berkeley.edu` |
| `SMTP_HOST` | `smtp.gmail.com` |
| `SMTP_PORT` | `587` |
| `SMTP_USER` | `henryqi@berkeley.edu` |
| `BUSINESS_TIMEZONE` | `America/Los_Angeles` |
| `BUSINESS_HOUR_START` | `8` |
| `BUSINESS_HOUR_END` | `17` |

### 4. Push initial state

```powershell
python github_sync.py push
```

### 5. Verify

Go to **Actions** tab → **Clay Outbound Follow-ups** → **Run workflow**

## Day-to-day

```powershell
python main.py Notion
```

Step 1 sends locally, state auto-syncs to GitHub, follow-ups (+1 day, +3 days) send from GitHub Actions — **even when your PC is off**.

## How it works

| Where | What |
|-------|------|
| **Your PC** | `main.py` — Clay search, Mistral emails, step 1 |
| **GitHub Actions** | Runs every 15 min, sends due follow-ups |
| **`cloud-state` branch** | Stores `contacts.db` and resume |

## Useful commands

```powershell
python github_sync.py push     # upload state after scheduling
python github_sync.py pull     # download updated DB/logs
python cloud_sync.py push      # same (auto-detects GitHub mode)
```

## Cost

**$0** on GitHub's free plan.

## Paid alternative (optional)

If you prefer a VPS instead of GitHub: `python cloud/deploy.py --host user@server` (~$5/mo).

## Troubleshooting

| Issue | Fix |
|-------|-----|
| Workflow fails "Missing state" | Run `python github_sync.py push` |
| Gmail auth fails | Re-run `python gmail_oauth.py`, then `github_sync.py push` |
| Workflow not running | Enable Actions in repo settings; check cron is enabled |
| Still using Windows task | Set `CLOUD_FOLLOWUPS=github` in `.env` |
