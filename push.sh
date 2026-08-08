#!/bin/bash
set -e

COMMIT_MSG="${1:-feat: update frontend and backend}"

echo "========================================="
echo "1. Validating Next.js Frontend Production Build..."
echo "========================================="
cd recondesk-frontend
npm run build
cd ..

echo ""
echo "========================================="
echo "2. Staging and Committing Changes..."
echo "========================================="
git add recondesk-backend/ recondesk-frontend/ supabase/ alembic/ 2>/dev/null || git add -A
git commit -m "$COMMIT_MSG" || echo "No new changes to commit."

echo ""
echo "========================================="
echo "3. Pushing Backend to GitHub (origin/main)..."
echo "========================================="
git push origin main

echo ""
echo "========================================="
echo "4. Pushing Frontend to GitHub (frontend/main)..."
echo "========================================="
git subtree push --prefix recondesk-frontend frontend main

echo ""
echo "========================================="
echo "SUCCESS! Both backend (Railway) and frontend (Vercel) have been built and deployed!"
echo "========================================="
