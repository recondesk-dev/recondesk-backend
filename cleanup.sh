#!/bin/bash

for PROJECT in recondesk-frontend recondesk-backend; do
  echo "Cleaning $PROJECT..."
  
  LATEST=$(npx vercel ls $PROJECT --limit 1 2>&1 | grep -o 'https://[^ ]*vercel\.app' | head -1)
  echo "Keeping: $LATEST"
  
  NEXT=""
  while true; do
    if [ -z "$NEXT" ]; then
      OUTPUT=$(npx vercel ls $PROJECT --limit 50 2>&1)
    else
      OUTPUT=$(npx vercel ls $PROJECT --limit 50 --next $NEXT 2>&1)
    fi
    
    URLS=$(echo "$OUTPUT" | grep -o 'https://[^ ]*vercel\.app' | grep -v "$LATEST")
    
    for URL in $URLS; do
      echo "Deleting $URL"
      npx vercel rm "$URL" --yes 2>/dev/null
    done
    
    NEXT=$(echo "$OUTPUT" | grep "\-\-next" | grep -o '[0-9]*$')
    if [ -z "$NEXT" ]; then
      break
    fi
  done
done

echo "Done."
