# Traviz Support Panel

Next.js frontend for the customer support team. The Flask backend remains in `../functions`.

## Local Development

```bash
npm install
npm run dev
```

Set `NEXT_PUBLIC_API_BASE` when the Flask API is served somewhere other than `/support`.

```bash
NEXT_PUBLIC_API_BASE=http://127.0.0.1:5001/<project>/<region>/customerService_app
```

## File Map

- `app/page.tsx`: overview dashboard
- `app/requests/page.tsx`: request queue
- `app/orders/page.tsx`: service orders
- `components/`: shared UI
- `lib/api.ts`: Flask API client
