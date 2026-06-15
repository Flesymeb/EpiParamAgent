import type { FormEvent, KeyboardEvent, ReactNode } from "react"
import { useEffect, useState } from "react"
import { useNavigate } from "react-router-dom"
import {
  ActivityIcon,
  ArrowUpIcon,
  CheckIcon,
  ChevronsUpDownIcon,
  LoaderCircleIcon,
  MicroscopeIcon,
  PlusIcon,
  SparklesIcon,
} from "lucide-react"
import { useReducedMotion, motion } from "motion/react"
import { toast } from "sonner"

import { createRun } from "@/api/pipeline"
import { HintTooltip } from "@/components/hint-tooltip"
import { BlurText } from "@/components/react-bits/blur-text"
import { Button } from "@/components/ui/button"
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command"
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover"
import { Textarea } from "@/components/ui/textarea"
import { getErrorMessage } from "@/lib/errors"
import { useSettings } from "@/lib/settings"
import { cn } from "@/lib/utils"

const diseaseOptions = ["mpox", "covid19"] as const
const parameterOptions = [
  "serial_interval",
  "reproduction_number",
  "fatality",
] as const

const diseaseHint =
  "Topic profile used to route prompts and ground-truth comparisons (e.g. mpox or covid19)."
const parameterHint =
  "Epidemiological quantity to extract and pool: serial interval (days), reproduction number (R), or case fatality."

type QuickStartExample = {
  label: string
  text: string
  disease: string
  parameter: string
}

const examples: QuickStartExample[] = [
  {
    label: "mpox serial interval",
    text: "mpox serial interval infectiousness household transmission",
    disease: "mpox",
    parameter: "serial_interval",
  },
  {
    label: "covid-19 R₀",
    text: "covid-19 basic reproduction number early outbreak estimates",
    disease: "covid19",
    parameter: "reproduction_number",
  },
  {
    label: "mpox fatality",
    text: "mpox case fatality ratio clade outcomes",
    disease: "mpox",
    parameter: "fatality",
  },
]

const typingPhrases = [
  "What is the serial interval of mpox in the 2022 outbreak?",
  "Estimate the basic reproduction number (R₀) of early COVID-19.",
  "What is the case fatality ratio of clade I mpox?",
]

// Cycles through example questions as an animated, self-typing placeholder.
// Only runs while `enabled` (input empty + motion allowed); setState happens in
// timeout callbacks, not synchronously in the effect body.
function useTypewriter(phrases: string[], enabled: boolean): string {
  const [display, setDisplay] = useState("")

  useEffect(() => {
    if (!enabled) {
      return
    }

    let phraseIndex = 0
    let charIndex = 0
    let deleting = false
    let timer = 0

    const tick = () => {
      const phrase = phrases[phraseIndex % phrases.length]
      if (!deleting) {
        charIndex += 1
        setDisplay(phrase.slice(0, charIndex))
        if (charIndex >= phrase.length) {
          deleting = true
          timer = window.setTimeout(tick, 2000)
          return
        }
        timer = window.setTimeout(tick, 42)
      } else {
        charIndex -= 1
        setDisplay(phrase.slice(0, Math.max(charIndex, 0)))
        if (charIndex <= 0) {
          deleting = false
          phraseIndex += 1
          timer = window.setTimeout(tick, 320)
          return
        }
        timer = window.setTimeout(tick, 24)
      }
    }

    timer = window.setTimeout(tick, 250)
    return () => window.clearTimeout(timer)
  }, [enabled, phrases])

  return enabled ? display : ""
}

export function QuickStartBox() {
  const navigate = useNavigate()
  const shouldReduceMotion = useReducedMotion()
  const { settings } = useSettings()
  const [text, setText] = useState("")
  const [disease, setDisease] = useState(() => settings.defaultDisease)
  const [parameter, setParameter] = useState(() => settings.defaultParameter)
  const [isCreating, setIsCreating] = useState(false)
  const trimmedText = text.trim()
  const canCreate = trimmedText.length > 0 && !isCreating
  // Typewriter placeholder runs regardless of reduced-motion: it's a low-key
  // text hint the user explicitly asked for, not a jarring transition.
  const typed = useTypewriter(typingPhrases, text.length === 0 && !isCreating)
  const placeholder = `${typed}▌`

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!trimmedText) {
      return
    }

    setIsCreating(true)

    try {
      const keywords =
        trimmedText
          .split(/\r?\n/)
          .map((line) => line.trim())
          .find(Boolean) ?? trimmedText
      const run = await createRun({
        keywords,
        research_question: trimmedText,
        disease,
        parameter,
      })

      navigate(`/runs/${run.id}`)
    } catch (error) {
      setIsCreating(false)
      toast.error(`Failed to create run: ${getErrorMessage(error)}`)
    }
  }

  function handleTextKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (
      event.key !== "Enter" ||
      event.shiftKey ||
      event.nativeEvent.isComposing
    ) {
      return
    }

    event.preventDefault()
    if (canCreate) {
      event.currentTarget.form?.requestSubmit()
    }
  }

  function applyExample(example: QuickStartExample) {
    setText(example.text)
    setDisease(example.disease)
    setParameter(example.parameter)
  }

  const enter = (delay: number) =>
    shouldReduceMotion
      ? undefined
      : {
          initial: { opacity: 0, y: 12 },
          animate: { opacity: 1, y: 0 },
          transition: { duration: 0.32, delay, ease: "easeOut" as const },
        }

  return (
    <form className="py-6 sm:py-10" onSubmit={handleSubmit}>
      <div className="mx-auto flex w-full max-w-3xl flex-col items-center gap-6">
        <motion.div
          className="flex flex-col items-center gap-3 text-center"
          {...enter(0)}
        >
          <motion.span
            aria-hidden="true"
            className="text-primary"
            animate={
              shouldReduceMotion
                ? undefined
                : { scale: [1, 1.18, 1], rotate: [0, 10, -10, 0] }
            }
            transition={{ duration: 3.6, repeat: Infinity, ease: "easeInOut" }}
          >
            <SparklesIcon className="size-9" />
          </motion.span>
          <h2 className="text-3xl font-semibold tracking-tight">
            <BlurText text="What would you like to review?" />
          </h2>
          <p className="max-w-md text-sm text-muted-foreground sm:text-base">
            Describe your question — I'll set up the 5-step systematic-review
            pipeline and you stay in control of every step.
          </p>
        </motion.div>

        <motion.div
          className="w-full rounded-2xl border border-border/60 bg-card shadow-sm transition-[border-color,box-shadow] focus-within:border-ring/60 focus-within:shadow-lg dark:bg-input/30"
          {...enter(0.08)}
        >
          <Textarea
            className="max-h-44 min-h-16 w-full resize-none border-0 bg-transparent px-4 pt-4 text-base shadow-none focus-visible:border-transparent focus-visible:ring-0 dark:bg-transparent"
            disabled={isCreating}
            onChange={(event) => setText(event.target.value)}
            onKeyDown={handleTextKeyDown}
            placeholder={placeholder}
            value={text}
          />
          <div className="flex flex-wrap items-center gap-2 px-2.5 pb-2.5">
            <ComposerSelect
              ariaLabel="Disease"
              disabled={isCreating}
              hint={diseaseHint}
              hintLabel="About disease"
              icon={<MicroscopeIcon className="size-3.5" />}
              onValueChange={setDisease}
              options={diseaseOptions}
              value={disease}
            />
            <ComposerSelect
              ariaLabel="Parameter"
              disabled={isCreating}
              hint={parameterHint}
              hintLabel="About parameter"
              icon={<ActivityIcon className="size-3.5" />}
              onValueChange={setParameter}
              options={parameterOptions}
              value={parameter}
            />
            <Button
              aria-label="Start run"
              className="ml-auto size-9 shrink-0 rounded-full p-0 transition-transform hover:scale-105 active:scale-95 motion-reduce:transition-none motion-reduce:hover:scale-100"
              disabled={!canCreate}
              type="submit"
            >
              {isCreating ? (
                <LoaderCircleIcon className="size-5 motion-safe:animate-spin motion-reduce:animate-none" />
              ) : (
                <ArrowUpIcon className="size-5" />
              )}
            </Button>
          </div>
        </motion.div>

        <motion.div
          className="flex flex-wrap items-center justify-center gap-2"
          {...enter(0.18)}
        >
          <span className="mr-1 text-xs text-muted-foreground">Try</span>
          {examples.map((example, index) => (
            <motion.button
              className="rounded-full border border-border/60 bg-card/60 px-3.5 py-1.5 text-sm font-normal text-foreground/80 shadow-sm transition-colors hover:bg-muted hover:text-foreground disabled:cursor-not-allowed disabled:opacity-50"
              disabled={isCreating}
              key={example.label}
              onClick={() => applyExample(example)}
              type="button"
              {...(shouldReduceMotion
                ? undefined
                : {
                    initial: { opacity: 0, scale: 0.92 },
                    animate: { opacity: 1, scale: 1 },
                    transition: {
                      duration: 0.25,
                      delay: 0.24 + index * 0.06,
                      ease: "easeOut" as const,
                    },
                  })}
            >
              {example.label}
            </motion.button>
          ))}
        </motion.div>
      </div>
    </form>
  )
}

function ComposerSelect({
  ariaLabel,
  disabled,
  hint,
  hintLabel,
  icon,
  onValueChange,
  options,
  value,
}: {
  ariaLabel: string
  disabled: boolean
  hint: string
  hintLabel: string
  icon: ReactNode
  onValueChange: (value: string) => void
  options: readonly string[]
  value: string
}) {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState("")
  const trimmedQuery = query.trim()
  const filtered = options.filter((option) =>
    option.toLowerCase().includes(trimmedQuery.toLowerCase())
  )
  const canCreate =
    trimmedQuery.length > 0 && !options.some((option) => option === trimmedQuery)

  function commit(next: string) {
    onValueChange(next)
    setQuery("")
    setOpen(false)
  }

  return (
    <div className="flex items-center gap-1">
      <span className="text-muted-foreground">{icon}</span>
      <Popover onOpenChange={setOpen} open={open}>
        <PopoverTrigger asChild>
          <Button
            aria-expanded={open}
            aria-label={ariaLabel}
            className="h-8 w-auto min-w-28 justify-between gap-1 border-0 bg-muted/50 text-sm font-normal hover:bg-muted dark:bg-muted/40"
            disabled={disabled}
            role="combobox"
            type="button"
            variant="outline"
          >
            <span className="truncate">
              {value || `Select ${ariaLabel.toLowerCase()}`}
            </span>
            <ChevronsUpDownIcon className="size-3.5 shrink-0 opacity-50" />
          </Button>
        </PopoverTrigger>
        <PopoverContent align="start" className="w-56 p-0">
          <Command shouldFilter={false}>
            <CommandInput
              onValueChange={setQuery}
              placeholder={`Search or type custom…`}
              value={query}
            />
            <CommandList>
              {filtered.length === 0 && !canCreate ? (
                <CommandEmpty>No match.</CommandEmpty>
              ) : null}
              <CommandGroup>
                {filtered.map((option) => (
                  <CommandItem
                    key={option}
                    onSelect={() => commit(option)}
                    value={option}
                  >
                    <span className="truncate">{option}</span>
                    <CheckIcon
                      className={cn(
                        "ml-auto size-4",
                        value === option ? "opacity-100" : "opacity-0"
                      )}
                    />
                  </CommandItem>
                ))}
                {canCreate ? (
                  <CommandItem
                    onSelect={() => commit(trimmedQuery)}
                    value={`create-${trimmedQuery}`}
                  >
                    <PlusIcon className="size-3.5" />
                    <span className="truncate">Use “{trimmedQuery}”</span>
                  </CommandItem>
                ) : null}
              </CommandGroup>
            </CommandList>
          </Command>
        </PopoverContent>
      </Popover>
      <HintTooltip content={hint} label={hintLabel} />
    </div>
  )
}
