# Running ReviewPilot as a GitHub App

The App mode reviews every pull request in the repositories you install it on, and comments as `reviewpilot[bot]`.

## 1. Deploy the server

```bash
cp .env.example .env        # fill in the values below
docker compose up -d
```

It must be reachable from GitHub over HTTPS. For local testing, a tunnel such as `cloudflared tunnel --url http://localhost:8000` works.

## 2. Create the App

GitHub → **Settings → Developer settings → GitHub Apps → New GitHub App**

| Setting | Value |
|---|---|
| Webhook URL | `https://<your-host>/webhooks/github` |
| Webhook secret | a long random string → `GITHUB_WEBHOOK_SECRET` |
| Repository permissions | **Pull requests: Read & write**, **Contents: Read**, **Commit statuses: Read & write**, Metadata: Read |
| Subscribe to events | **Pull request** |

After creating it, note the **App ID** (`GITHUB_APP_ID`) and generate a **private key** (`.pem`), mounting it at `GITHUB_PRIVATE_KEY_PATH`, or pass its contents in `GITHUB_PRIVATE_KEY` with `\n` for newlines.

## 3. Install it

On the App's page, choose **Install App** and pick the repositories. Open a pull request: within a few seconds the commit shows a pending `reviewpilot` status, then the review appears with inline comments.

## How a review flows

1. GitHub sends `pull_request` (`opened`, `synchronize`, `reopened`, `ready_for_review`). Drafts and closed PRs are ignored.
2. The webhook checks `X-Hub-Signature-256` with a constant-time compare and returns `202` immediately; the review runs in the background.
3. The server signs a 9-minute RS256 JWT as the App, exchanges it for an installation token, and fetches the PR diff.
4. The agents run. The result is posted as one review with inline comments on the right side of the diff. If GitHub rejects a comment position (HTTP 422), the review is re-posted as a summary so nothing is lost.
5. The commit status is set to `failure` when there are high or critical findings, which you can make a required check in branch protection.
