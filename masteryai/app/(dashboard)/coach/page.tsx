'use client'

import { useState, useRef, useEffect } from 'react'
import { Send, Loader2, MessageCircle, Lock } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { cn } from '@/lib/utils'
import Link from 'next/link'

interface Message {
  role: 'user' | 'assistant'
  content: string
}

export default function CoachPage() {
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [isPremium, setIsPremium] = useState(true)
  const [initialized, setInitialized] = useState(false)
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    async function init() {
      const res = await fetch('/api/coach/daily')
      if (res.status === 403) { setIsPremium(false); setInitialized(true); return }
      const data = await res.json()
      if (data.message) setMessages([{ role: 'assistant', content: data.message }])
      setInitialized(true)
    }
    init()
  }, [])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  async function sendMessage() {
    if (!input.trim() || loading) return
    const userMsg = input.trim()
    setInput('')
    setMessages(prev => [...prev, { role: 'user', content: userMsg }])
    setLoading(true)

    try {
      const res = await fetch('/api/coach/message', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: userMsg }),
      })

      if (res.status === 403) {
        setIsPremium(false)
        setMessages(prev => prev.slice(0, -1))
        setLoading(false)
        return
      }

      const reader = res.body?.getReader()
      if (!reader) throw new Error('No stream')

      let assistantMsg = ''
      setMessages(prev => [...prev, { role: 'assistant', content: '' }])

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        assistantMsg += new TextDecoder().decode(value)
        setMessages(prev => {
          const updated = [...prev]
          updated[updated.length - 1] = { role: 'assistant', content: assistantMsg }
          return updated
        })
      }
    } catch {
      setMessages(prev => [...prev, { role: 'assistant', content: "Sorry, I had trouble connecting. Please try again." }])
    } finally {
      setLoading(false)
    }
  }

  if (!isPremium) {
    return (
      <div className="max-w-2xl mx-auto text-center py-20">
        <div className="w-20 h-20 rounded-2xl bg-violet-50 dark:bg-violet-900/20 flex items-center justify-center mx-auto mb-6">
          <Lock className="w-10 h-10 text-violet-400" />
        </div>
        <h1 className="text-3xl font-bold mb-3">AI Coach is Premium</h1>
        <p className="text-gray-500 dark:text-gray-400 mb-8 max-w-md mx-auto">
          Get 24/7 personalized coaching, accountability, and expert guidance on your learning journey with MasteryAI Premium.
        </p>
        <Link href="/upgrade">
          <Button size="xl" className="bg-gradient-to-r from-violet-600 to-indigo-600">
            Upgrade to Premium — $19/month
          </Button>
        </Link>
      </div>
    )
  }

  return (
    <div className="max-w-3xl mx-auto flex flex-col h-[calc(100vh-10rem)]">
      <div className="mb-6">
        <h1 className="text-3xl font-bold mb-1">AI Coach</h1>
        <p className="text-gray-500 dark:text-gray-400">Your personal learning coach — always here to help, motivate, and guide you.</p>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto space-y-4 pr-1">
        {!initialized && (
          <div className="flex justify-center py-8">
            <Loader2 className="w-8 h-8 animate-spin text-violet-400" />
          </div>
        )}
        {messages.map((msg, i) => (
          <div key={i} className={cn('flex gap-3', msg.role === 'user' ? 'justify-end' : 'justify-start')}>
            {msg.role === 'assistant' && (
              <div className="w-8 h-8 rounded-full bg-gradient-to-br from-violet-500 to-indigo-600 flex items-center justify-center shrink-0 mt-1">
                <MessageCircle className="w-4 h-4 text-white" />
              </div>
            )}
            <div className={cn(
              'max-w-[75%] rounded-2xl px-4 py-3 text-sm leading-relaxed',
              msg.role === 'user'
                ? 'bg-violet-600 text-white rounded-br-sm'
                : 'bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-700 text-gray-900 dark:text-gray-100 rounded-bl-sm shadow-sm'
            )}>
              {msg.content || (loading && i === messages.length - 1 ? (
                <span className="flex gap-1 items-center">
                  <span className="w-2 h-2 rounded-full bg-gray-400 animate-bounce" style={{ animationDelay: '0ms' }} />
                  <span className="w-2 h-2 rounded-full bg-gray-400 animate-bounce" style={{ animationDelay: '150ms' }} />
                  <span className="w-2 h-2 rounded-full bg-gray-400 animate-bounce" style={{ animationDelay: '300ms' }} />
                </span>
              ) : '')}
            </div>
          </div>
        ))}
        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <div className="pt-4 border-t border-gray-200 dark:border-gray-800">
        <div className="flex gap-3">
          <Textarea
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage() } }}
            placeholder="Ask your coach anything about your learning journey..."
            className="flex-1 min-h-[44px] max-h-[120px] resize-none"
            rows={1}
          />
          <Button onClick={sendMessage} disabled={loading || !input.trim()} size="icon" className="h-11 w-11 shrink-0">
            {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
          </Button>
        </div>
      </div>
    </div>
  )
}
