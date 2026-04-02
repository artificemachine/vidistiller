'use client';

import { Separator } from 'react-resizable-panels';

interface ResizeHandleProps {
  direction?: 'horizontal' | 'vertical';
}

export default function ResizeHandle({ direction = 'horizontal' }: ResizeHandleProps) {
  const isVertical = direction === 'vertical';

  return (
    <Separator
      className={`group relative flex items-center justify-center ${
        isVertical ? 'h-1.5 cursor-row-resize' : 'w-1.5 cursor-col-resize'
      }`}
    >
      <div
        className={`rounded-full bg-gray-300 dark:bg-gray-600 group-hover:bg-blue-500 group-active:bg-blue-600 transition-colors ${
          isVertical ? 'h-0.5 w-8' : 'w-0.5 h-8'
        }`}
      />
    </Separator>
  );
}
