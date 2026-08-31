import { Suspense } from "react";

import { VendorsPageContent } from "./VendorsPageContent";

export default function VendorsPage() {
  return (
    <Suspense fallback={<div>Loading...</div>}>
      <VendorsPageContent />
    </Suspense>
  );
}
