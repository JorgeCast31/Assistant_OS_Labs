'use client'

import type { ReactNode } from 'react'

interface PanelProps {
  title?: string
  titleRight?: ReactNode
  children: ReactNode
  className?: string
  /** removes default padding */
  noPad?: boolean
}

export function Panel({ title, titleRight, children, className = '', noPad = false }: PanelProps) {
  return (
    <div className={`bg-os-surface border border-os-border rounded-lg overflow-hidden ${className}`}>
      {title && (
        <div className="flex items-center justify-between px-4 py-2.5 border-b border-os-border">
          <span className="text-xs font-mono font-medium text-tx-secondary uppercase tracking-wider">
            {title}
          </span>
          {titleRight && <div>{titleRight}</div>}
        </div>
      )}
      <div className={noPad ? '' : 'p-4'}>
        {children}
      </div>
    </div>
  )
}
