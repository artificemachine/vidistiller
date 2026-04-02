'use client';

import { createContext, useContext, useState } from 'react';

type JobStatus = 'pending' | 'processing' | 'completed' | 'failed' | null;

interface JobStatusContextValue {
  jobStatus: JobStatus;
  setJobStatus: (status: JobStatus) => void;
}

const JobStatusContext = createContext<JobStatusContextValue>({
  jobStatus: null,
  setJobStatus: () => {},
});

export function useJobStatus() {
  return useContext(JobStatusContext);
}

export default function JobStatusProvider({ children }: { children: React.ReactNode }) {
  const [jobStatus, setJobStatus] = useState<JobStatus>(null);
  return (
    <JobStatusContext.Provider value={{ jobStatus, setJobStatus }}>
      {children}
    </JobStatusContext.Provider>
  );
}
