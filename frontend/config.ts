const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api';

export const config = {
  api: {
    baseUrl: API_URL,
    timeout: 30000,
  },
  app: {
    name: 'Vidistiller',
    version: '1.1.0',
  },
};
