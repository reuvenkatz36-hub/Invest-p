import Stripe from 'stripe'

export const stripe = new Stripe(process.env.STRIPE_SECRET_KEY!, {
  apiVersion: '2026-06-24.dahlia' as const,
})

export const PLANS = {
  free: {
    name: 'Free',
    price: 0,
    features: [
      '1 learning roadmap',
      'First 3 lessons per module',
      'Basic quizzes',
      'Progress tracking',
    ],
    limits: {
      roadmaps: 1,
      lessonsPerModule: 3,
      coach: false,
      knowledgeGraph: false,
    },
  },
  premium: {
    name: 'Premium',
    price: 19,
    priceId: process.env.STRIPE_PREMIUM_PRICE_ID!,
    features: [
      'Unlimited roadmaps',
      'All lessons unlocked',
      'AI Coach (24/7)',
      'Knowledge graph',
      'Advanced analytics',
      'Assignment AI feedback',
      'Priority support',
    ],
    limits: {
      roadmaps: Infinity,
      lessonsPerModule: Infinity,
      coach: true,
      knowledgeGraph: true,
    },
  },
}
