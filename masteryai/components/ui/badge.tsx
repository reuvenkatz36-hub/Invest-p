import * as React from 'react'
import { cva, type VariantProps } from 'class-variance-authority'
import { cn } from '@/lib/utils'

const badgeVariants = cva(
  'inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-semibold transition-colors',
  {
    variants: {
      variant: {
        default: 'border-transparent bg-violet-600 text-white',
        secondary: 'border-transparent bg-gray-100 dark:bg-gray-800 text-gray-900 dark:text-gray-100',
        destructive: 'border-transparent bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200',
        success: 'border-transparent bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200',
        outline: 'border-gray-200 dark:border-gray-700 text-gray-700 dark:text-gray-300',
        warning: 'border-transparent bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200',
      },
    },
    defaultVariants: { variant: 'default' },
  }
)

export interface BadgeProps extends React.HTMLAttributes<HTMLDivElement>, VariantProps<typeof badgeVariants> {}

function Badge({ className, variant, ...props }: BadgeProps) {
  return <div className={cn(badgeVariants({ variant }), className)} {...props} />
}

export { Badge, badgeVariants }
