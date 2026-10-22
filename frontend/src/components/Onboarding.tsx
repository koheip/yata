import { Button } from "@/components/ui/button"
import { AiKeyCard } from "./AiKeyCard"
import type { AiProvider } from "../types"

type OnboardingProps = {
  provider: AiProvider
  onConnect: (providerId: string, key: string) => Promise<{ message: string }>
  onDisconnect: (providerId: string) => Promise<void>
  onOther: () => void
}

/** はじめて開いたときの案内。無料で使える Gemini のキーを、画面の中だけでつなげる。 */
export function Onboarding({ provider, onConnect, onDisconnect, onOther }: OnboardingProps) {
  return (
    <section aria-labelledby="onboarding-title" className="mx-auto flex w-full max-w-xl flex-col gap-3 px-5 pt-6">
      <div className="flex flex-col gap-1">
        <h2 id="onboarding-title" className="font-maru text-xl font-bold">
          はじめに、AI をつなぎましょう
        </h2>
        <p className="text-sm leading-6 text-muted-foreground">
          ヤタが考えるには、AI の「API キー」が1つ必要です。Google の Gemini なら無料で作れて、2〜3分で終わります。
        </p>
      </div>
      <AiKeyCard provider={provider} featured onConnect={onConnect} onDisconnect={onDisconnect} />
      <Button type="button" variant="link" className="h-10 self-start px-0" onClick={onOther}>
        ChatGPT・Claude・Grok などや、パソコンの中の AI を使う
      </Button>
    </section>
  )
}
