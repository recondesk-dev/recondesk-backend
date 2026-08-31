import { Suspense } from "react";

import { ClientsPageContent } from "./ClientsPageContent";

export default function ClientsPage() {
  return (
    <Suspense fallback={<div>Loading...</div>}>
      <ClientsPageContent />
    </Suspense>
  );
}
