# ReconDesk Development & Deployment Guidelines

## Git & Deployment Rules (CRITICAL - ALWAYS ENFORCE)

Whenever committing and pushing changes in ReconDesk, **ALWAYS** push to **BOTH** remotes:

1. **Backend / EC2 / EC3**: `origin main`
   - Remote URL: `https://github.com/recondesk-dev/recondesk-backend.git`
2. **Frontend / Vercel**: `frontend main`
   - Remote URL: `https://github.com/recondesk-dev/recondesk-frontend.git`

### Standard Push Procedure:
Before pushing:
1. Ensure backend tests pass:
   ```bash
   pytest recondesk-backend/tests/
   ```
2. Ensure frontend production build succeeds:
   ```bash
   cd recondesk-frontend && npm run build && cd ..
   ```
3. Stage and commit changes:
   ```bash
   git add ...
   git commit -m "<message>"
   ```
4. Push to both remotes:
   ```bash
   git push origin main
   git push frontend main
   ```
   *(Or execute `./push.sh "<message>"` which automates this workflow)*

**Never push to only one remote when the user asks to commit and push, unless explicitly instructed otherwise.**
