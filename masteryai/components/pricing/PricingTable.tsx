'use client'

import { useState } from 'react'
import { Check, Loader2, Zap, Sparkles } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { PLANS } from '@/lib/stripe'
import { cn } from '@/lib/utils'

interface Props {
  currentPlan: 'free' | 'premium'
}

export function PricingTable({ currentPlan }: Props) {
  const [loading, setLoading] = useState(false)

  async function handleUpgrade() {
    setLoading(true)
    const res = await fetch('/api/stripe/create-checkout', { method: 'POST' })
    const { url } = await res.json()
    if (url) window.location.href = url
    setLoading(false)
  }

  return (
    <div className="grid md:grid-cols-2 gap-6 max-w-3xl mx-auto">
      {/* Free */}
      <Card className={cn(
        'relative',
        currentPlan === 'free' ? 'border-violet-300 dark:border-violet-700' : ''
      )}>
        {currentPlan === 'free' && (
          <div className="absolute -top-3 left-1/2 -translate-x-1/2">
            <Badge variant="secondary">Current Plan</Badge>
          </div>
        )}
        <CardHeader className="pb-4">
          <div className="flex items-center gap-2 mb-2">
            <Sparkles className="w-5 h-5 text-gray-400" />
            <CardTitle className="text-xl">Free</CardTitle>
          </div>
          <div className="text-4xl font-bold">$0<span className="text-lg font-normal text-gray-500">/mo</span></div>
          <p className="text-sm text-gray-500 dark:text-gray-400">Get started and explore</p>
        </CardHeader>
        <CardContent className="space-y-3">
          {PLANS.free.features.map(f => (
            <div key={f} className="flex items-center gap-2 text-sm">
              <Check className="w-4 h-4 text-gray-400 shrink-0" />
              <span className="text-gray-600 dark:text-gray-400">{f}</span>
            </div>
          ))}
          <div className="pt-4">
            <Button variant="outline" className="w-full" disabled>
              {currentPlan === 'free' ? 'Current Plan' : 'Downgrade'}
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Premium */}
      <Card className={cn(
        'relative border-2 border-violet-500 bg-gradient-to-br from-violet-50 to-indigo-50 dark:from-violet-900/20 dark:to-indigo-900/20',
        currentPlan === 'premium' ? 'border-green-500 from-green-50 to-emerald-50 dark:from-green-900/20 dark:to-emerald-900/20' : ''
      )}>
        <div className="absolute -top-3 left-1/2 -translate-x-1/2">
          <Badge className="bg-gradient-to-r from-violet-600 to-indigo-600 text-white px-4">
            {currentPlan === 'premium' ? '✓ Active' : 'Most Popular'}
          </Badge>
        </div>
        <CardHeader className="pb-4">
          <div className="flex items-center gap-2 mb-2">
            <Zap className="w-5 h-5 text-violet-600" />
            <CardTitle className="text-xl">Premium</CardTitle>
          </div>
          <div className="text-4xl font-bold">$19<span className="text-lg font-normal text-gray-500">/mo</span></div>
          <p className="text-sm text-gray-500 dark:text-gray-400">Everything you need to master any skill</p>
        </CardHeader>
        <CardContent className="space-y-3">
          {PLANS.premium.features.map(f => (
            <div key={f} className="flex items-center gap-2 text-sm">
              <Check className="w-4 h-4 text-violet-600 shrink-0" />
              <span className="font-medium">{f}</span>
            </div>
          ))}
          <div className="pt-4">
            {currentPlan === 'premium' ? (
              <Button className="w-full" variant="outline" disabled>
                ✓ Premium Active
              </Button>
            ) : (
              <Button
                className="w-full bg-gradient-to-r from-violet-600 to-indigo-600 hover:from-violet-700 hover:to-indigo-700 gap-2"
                onClick={handleUpgrade}
                disabled={loading}
                size="lg"
              >
                {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Zap className="w-4 h-4" />}
                Upgrade to Premium
              </Button>
            )}
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
