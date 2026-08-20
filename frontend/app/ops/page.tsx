'use client';

import OpsDashboard from '@/components/OpsDashboard';

export default function OpsPage() {
  return (
    <div className="max-w-7xl mx-auto px-4 py-8">
      <h1 className="text-3xl font-bold text-text-dark dark:text-text-light mb-6">operations</h1>
      <OpsDashboard />
    </div>
  );
}
