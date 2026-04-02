'use client';

import { useState } from 'react';

interface DocumentDisplayProps {
  content: string;
  title?: string;
}

export default function DocumentDisplay({ content, title }: DocumentDisplayProps) {
  const [copyFeedback, setCopyFeedback] = useState(false);

  const handleCopy = () => {
    navigator.clipboard.writeText(content);
    setCopyFeedback(true);
    setTimeout(() => setCopyFeedback(false), 2000);
  };

  return (
    <div className="w-full max-w-4xl mx-auto p-6">
      <div className="flex justify-between items-center mb-6">
        {title && <h1 className="text-3xl font-bold">{title}</h1>}
        <button
          onClick={handleCopy}
          className="px-4 py-2 bg-blue-500 text-white rounded hover:bg-blue-600"
        >
          {copyFeedback ? 'copied!' : 'copy'}
        </button>
      </div>

      <div className="bg-white p-4 rounded border border-gray-200">
        <pre className="whitespace-pre-wrap font-sans text-gray-800">{content}</pre>
      </div>
    </div>
  );
}
