"use client";

import { type ReactNode, useEffect, useMemo, useState } from "react";
import { CardSearchPanel } from "../src/components/card-search-panel";
import { DeckSlot } from "../src/components/deck-slot";
import { SkillList } from "../src/components/skill-list";
import { RaceData, StrategyDetail, SupportCard, UsageMode } from "../src/lib/types";
import {
  cn,
  filterSkillsForUsageMode,
  getCardSkills,
  scoreCard,
} from "../src/lib/utils";

import cardsData from "../src/data/cards.json";
import raceDataRaw from "../src/data/race_data.json";

const STRATEGY_ORDER = ["逃げ", "先行", "差し", "追込"];
const CONTACT_FORM_URL =
  "https://docs.google.com/forms/d/e/1FAIpQLSfGUiRhR6bkJ3V54ywE-D9R_s5LJKAlppjFP2qt4YWFaYucuA/viewform";
const DECK_STORAGE_KEY = "uma-tool-deck-v1"; // 旧形式(単一編成)。移行用に参照のみ
const DECKS_STORAGE_KEY = "uma-tool-decks-v1";
const DECK_SLOT_COUNT = 3;

type DeckStore = { active: number; slots: number[][] };
const INITIAL_CARDS = cardsData as SupportCard[];
const INITIAL_RACE_DATA = raceDataRaw as unknown as RaceData;
const INITIAL_RACE = Object.keys(INITIAL_RACE_DATA)[0] || "";

const emptyStrategyDetail: StrategyDetail = {
  super_recommended: [],
  recommended: [],
};

type MobileTab = "search" | "skills" | "deck";

const USAGE_MODE_OPTIONS: Array<{
  value: UsageMode;
  label: string;
  shortLabel: string;
}> = [
  { value: "factor", label: "因子周回", shortLabel: "周回" },
  { value: "training", label: "本育成", shortLabel: "本番" },
];

function idsToCards(ids: unknown, cards: SupportCard[]): SupportCard[] {
  if (!Array.isArray(ids)) return [];
  const cardById = new Map(cards.map((card) => [card.id, card]));
  return ids
    .map((id) => cardById.get(id as number))
    .filter((card): card is SupportCard => Boolean(card))
    .slice(0, 6);
}

function emptyDeckStore(): DeckStore {
  return { active: 0, slots: Array.from({ length: DECK_SLOT_COUNT }, () => []) };
}

function loadDeckStore(): DeckStore {
  if (typeof window === "undefined") return emptyDeckStore();

  try {
    const raw = window.localStorage.getItem(DECKS_STORAGE_KEY);
    if (raw) {
      const parsed = JSON.parse(raw) as Partial<DeckStore>;
      const slots = Array.from({ length: DECK_SLOT_COUNT }, (_, index) => {
        const slot = parsed.slots?.[index];
        return Array.isArray(slot) ? (slot as number[]) : [];
      });
      const active =
        typeof parsed.active === "number" &&
        parsed.active >= 0 &&
        parsed.active < DECK_SLOT_COUNT
          ? parsed.active
          : 0;
      return { active, slots };
    }

    // 旧形式(単一編成)からの移行
    const legacy = window.localStorage.getItem(DECK_STORAGE_KEY);
    if (legacy) {
      const ids = JSON.parse(legacy) as unknown;
      const store = emptyDeckStore();
      if (Array.isArray(ids)) store.slots[0] = ids as number[];
      return store;
    }
  } catch {
    // fall through
  }
  return emptyDeckStore();
}

export default function Home() {
  const [searchKeyword, setSearchKeyword] = useState("");
  const [activeFilter, setActiveFilter] = useState("すべて");
  const cards = INITIAL_CARDS;
  const raceData = INITIAL_RACE_DATA;
  const [deck, setDeck] = useState<SupportCard[]>([]);
  const [selectedRace, setSelectedRace] = useState(INITIAL_RACE);
  const [strategy, setStrategy] = useState("先行");
  const [usageMode, setUsageMode] = useState<UsageMode>("factor");
  const [mobileTab, setMobileTab] = useState<MobileTab>("search");
  const [deckRestored, setDeckRestored] = useState(false);
  const [saveFlash, setSaveFlash] = useState(false);
  const [activeSlot, setActiveSlot] = useState(0);

  // 初回マウント時にlocalStorageから編成を復元する
  useEffect(() => {
    const store = loadDeckStore();
    setActiveSlot(store.active);
    setDeck(idsToCards(store.slots[store.active], INITIAL_CARDS));
    setDeckRestored(true);
  }, []);

  // 編成が変わるたびに自動保存する(復元前の空編成で上書きしない)
  useEffect(() => {
    if (!deckRestored) return;
    const store = loadDeckStore();
    store.active = activeSlot;
    store.slots[activeSlot] = deck.map((card) => card.id);
    window.localStorage.setItem(DECKS_STORAGE_KEY, JSON.stringify(store));
    setSaveFlash(true);
    const timer = window.setTimeout(() => setSaveFlash(false), 1500);
    return () => window.clearTimeout(timer);
  }, [deck, activeSlot, deckRestored]);

  const switchDeckSlot = (slot: number) => {
    if (slot === activeSlot) return;
    const store = loadDeckStore();
    setActiveSlot(slot);
    setDeck(idsToCards(store.slots[slot], INITIAL_CARDS));
  };

  const handleSkillSearch = (skill: string) => {
    setSearchKeyword(skill);
    setActiveFilter("すべて");
    setMobileTab("search");
  };

  const raceOptions = useMemo(() => Object.keys(raceData), [raceData]);

  const strategyOptions = useMemo(() => {
    if (!selectedRace || !raceData[selectedRace]) return [];
    return Object.keys(raceData[selectedRace]).sort((a, b) => {
      const indexA = STRATEGY_ORDER.indexOf(a);
      const indexB = STRATEGY_ORDER.indexOf(b);
      return (indexA === -1 ? 99 : indexA) - (indexB === -1 ? 99 : indexB);
    });
  }, [raceData, selectedRace]);

  const availableStrategies = useMemo(
    () => new Set(strategyOptions),
    [strategyOptions]
  );

  const effectiveStrategy = availableStrategies.has(strategy)
    ? strategy
    : strategyOptions[0] || "";

  const currentStrategyDetail = useMemo(() => {
    if (!selectedRace || !raceData[selectedRace] || !effectiveStrategy) {
      return emptyStrategyDetail;
    }

    const detail = raceData[selectedRace][effectiveStrategy];
    if (!detail || Array.isArray(detail)) return emptyStrategyDetail;
    return detail;
  }, [effectiveStrategy, raceData, selectedRace]);

  const visibleStrategyDetail = useMemo(() => {
    const superRecommended = filterSkillsForUsageMode(
      currentStrategyDetail.super_recommended,
      usageMode
    );
    const superRecommendedSet = new Set(superRecommended);
    const recommended = filterSkillsForUsageMode(
      currentStrategyDetail.recommended,
      usageMode
    ).filter((skill) => !superRecommendedSet.has(skill));

    return {
      super_recommended: superRecommended,
      recommended,
    };
  }, [currentStrategyDetail, usageMode]);

  const allTargetSkills = useMemo(
    () => [
      ...visibleStrategyDetail.super_recommended,
      ...visibleStrategyDetail.recommended,
    ],
    [visibleStrategyDetail]
  );

  const deckSkills = useMemo(() => {
    const skills = new Set<string>();
    deck.forEach((card) => {
      getCardSkills(card, usageMode).forEach((skill) => skills.add(skill));
    });
    return skills;
  }, [deck, usageMode]);

  const missingSuperSkills = useMemo(
    () =>
      visibleStrategyDetail.super_recommended.filter(
        (skill) => !deckSkills.has(skill)
      ),
    [visibleStrategyDetail, deckSkills]
  );

  const missingRecommendedSkills = useMemo(
    () =>
      visibleStrategyDetail.recommended.filter(
        (skill) => !deckSkills.has(skill)
      ),
    [visibleStrategyDetail, deckSkills]
  );

  const displayedCards = useMemo(() => {
    let filtered = [...cards];

    if (activeFilter !== "すべて") {
      filtered =
        activeFilter === "友人/グループ"
          ? filtered.filter(
              (card) =>
                card.type.includes("友人") || card.type.includes("グループ")
            )
          : filtered.filter((card) => card.type.includes(activeFilter));
    }

    if (searchKeyword.trim() !== "") {
      const keyword = searchKeyword.toLowerCase();
      filtered = filtered.filter((card) => {
        const allSkills = getCardSkills(card, usageMode);
        return (
          card.name.toLowerCase().includes(keyword) ||
          card.char.toLowerCase().includes(keyword) ||
          card.card.toLowerCase().includes(keyword) ||
          allSkills.some((skill) => skill.toLowerCase().includes(keyword))
        );
      });
    }

    filtered = filtered.sort(
      (a, b) =>
        scoreCard(b, missingSuperSkills, missingRecommendedSkills, usageMode) -
        scoreCard(a, missingSuperSkills, missingRecommendedSkills, usageMode)
    );

    return filtered;
  }, [
    activeFilter,
    cards,
    missingRecommendedSkills,
    missingSuperSkills,
    searchKeyword,
    usageMode,
  ]);

  const addToDeck = (card: SupportCard) => {
    if (deck.length >= 6 || deck.some((deckCard) => deckCard.id === card.id)) {
      return;
    }
    setDeck((currentDeck) => [...currentDeck, card]);
  };

  const removeFromDeck = (card?: SupportCard) => {
    if (!card) return;
    setDeck((currentDeck) =>
      currentDeck.filter((deckCard) => deckCard.id !== card.id)
    );
  };

  const cardSearchPanelProps = {
    searchKeyword,
    onSearchChange: setSearchKeyword,
    activeFilter,
    onFilterChange: setActiveFilter,
    usageMode,
    displayedCards,
    deck,
    missingSuperSkills,
    missingRecommendedSkills,
    onAddCard: addToDeck,
    onSkillClick: handleSkillSearch,
  };

  const renderDeckActionButtons = (compact = false) => (
    <>
      <span
        className={`whitespace-nowrap text-[11px] transition-colors ${
          saveFlash ? "font-semibold text-emerald-600" : "text-muted-foreground"
        }`}
      >
        {saveFlash ? "保存しました ✓" : "自動保存"}
      </span>
      <button
        onClick={() => setDeck([])}
        className={cn(
          "material-button-secondary flex items-center justify-center gap-1.5 whitespace-nowrap rounded-md text-xs font-semibold transition",
          compact ? "min-w-[92px] px-3 py-1.5" : "min-w-[64px] px-2.5 py-1.5"
        )}
      >
        {compact ? "編成クリア" : "クリア"}
      </button>
    </>
  );

  const renderRaceHeader = (compact = false) => {
    if (compact) {
      return (
        <header className="flex-shrink-0 border-b border-border bg-card px-3 py-2">
          <div className="flex items-center justify-between gap-2">
            <h1 className="whitespace-nowrap text-sm font-semibold text-card-foreground">
              目標条件
            </h1>
            <a
              href={CONTACT_FORM_URL}
              target="_blank"
              rel="noreferrer"
              className="material-button-secondary flex min-w-[56px] items-center justify-center whitespace-nowrap rounded-md px-2.5 py-1 text-[11px] font-semibold transition"
            >
              要望
            </a>
          </div>

          <div className="mt-2 grid grid-cols-[minmax(0,1fr)_auto] gap-2">
            <div className="relative min-w-0">
              <select
                value={selectedRace}
                onChange={(event) => setSelectedRace(event.target.value)}
                className="h-9 w-full min-w-0 appearance-none truncate whitespace-nowrap rounded-md border border-input bg-card px-3 pr-8 text-sm font-medium outline-none focus:ring-2 focus:ring-ring"
              >
                {raceOptions.length === 0 ? (
                  <option value="">レースデータなし</option>
                ) : (
                  raceOptions.map((race) => (
                    <option key={race} value={race}>
                      {race}
                    </option>
                  ))
                )}
              </select>
              <span className="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2 text-xs text-muted-foreground">
                v
              </span>
            </div>

            <div className="flex shrink-0 rounded-md border border-border bg-secondary p-0.5">
              {USAGE_MODE_OPTIONS.map((option) => (
                <button
                  key={option.value}
                  onClick={() => setUsageMode(option.value)}
                  className={cn(
                    "min-w-[48px] whitespace-nowrap rounded px-2 py-1 text-xs font-semibold transition",
                    usageMode === option.value
                      ? "material-tab-active text-card-foreground"
                      : "text-muted-foreground hover:text-foreground"
                  )}
                >
                  {option.shortLabel}
                </button>
              ))}
            </div>
          </div>

          <div className="mt-2">
            {selectedRace ? (
              <div className="grid w-full grid-cols-4 rounded-md border border-border bg-secondary p-0.5">
                {STRATEGY_ORDER.map((option) => {
                  const isAvailable = availableStrategies.has(option);
                  const isActive = effectiveStrategy === option;
                  return (
                    <button
                      key={option}
                      onClick={() => {
                        if (isAvailable) setStrategy(option);
                      }}
                      disabled={!isAvailable}
                      title={isAvailable ? option : `${option}は準備中です`}
                      className={cn(
                        "min-h-8 rounded px-1.5 py-0.5 text-xs font-medium transition",
                        isActive
                          ? "material-tab-active text-card-foreground"
                          : isAvailable
                            ? "text-muted-foreground hover:text-foreground"
                            : "cursor-not-allowed text-muted-foreground/45"
                      )}
                    >
                      <span className="block leading-tight">{option}</span>
                      {!isAvailable ? (
                        <span className="block whitespace-nowrap text-[9px] font-normal leading-tight">
                          準備中
                        </span>
                      ) : null}
                    </button>
                  );
                })}
              </div>
            ) : (
              <span className="block rounded-md bg-secondary px-3 py-1.5 text-xs font-medium text-muted-foreground">
                脚質なし
              </span>
            )}
          </div>
        </header>
      );
    }

    return (
      <header className="flex-shrink-0 border-b border-border bg-card px-6 py-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex min-w-0 flex-wrap items-center gap-3">
            <h1 className="flex items-center gap-2 whitespace-nowrap text-base font-semibold text-card-foreground">
              目標条件
            </h1>

            <div className="flex min-w-0 flex-wrap items-center gap-3">
              <div className="relative min-w-0">
                <select
                  value={selectedRace}
                  onChange={(event) => setSelectedRace(event.target.value)}
                  className="w-full min-w-0 appearance-none truncate whitespace-nowrap rounded-md border border-input bg-card px-3 py-1.5 pr-8 text-sm font-medium outline-none focus:ring-2 focus:ring-ring md:w-[220px] lg:w-[260px]"
                >
                  {raceOptions.length === 0 ? (
                    <option value="">レースデータなし</option>
                  ) : (
                    raceOptions.map((race) => (
                      <option key={race} value={race}>
                        {race}
                      </option>
                    ))
                  )}
                </select>
                <span className="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2 text-xs text-muted-foreground">
                  v
                </span>
              </div>

              {selectedRace ? (
                <div className="grid w-[280px] shrink-0 grid-cols-4 rounded-md border border-border bg-secondary p-0.5">
                  {STRATEGY_ORDER.map((option) => {
                    const isAvailable = availableStrategies.has(option);
                    const isActive = effectiveStrategy === option;
                    return (
                      <button
                        key={option}
                        onClick={() => {
                          if (isAvailable) setStrategy(option);
                        }}
                        disabled={!isAvailable}
                        title={isAvailable ? option : `${option}は準備中です`}
                        className={cn(
                          "min-h-9 rounded px-2 py-1 text-xs font-medium transition",
                          isActive
                            ? "material-tab-active text-card-foreground"
                            : isAvailable
                              ? "text-muted-foreground hover:text-foreground"
                              : "cursor-not-allowed text-muted-foreground/45"
                        )}
                      >
                        <span className="block leading-tight">{option}</span>
                        {!isAvailable ? (
                          <span className="block whitespace-nowrap text-[10px] font-normal leading-tight">
                            準備中
                          </span>
                        ) : null}
                      </button>
                    );
                  })}
                </div>
              ) : (
                <span className="rounded-lg bg-secondary px-3 py-1.5 text-xs font-medium text-muted-foreground">
                  脚質なし
                </span>
              )}
            </div>

            <div className="flex shrink-0 rounded-md border border-border bg-secondary p-0.5">
              {USAGE_MODE_OPTIONS.map((option) => (
                <button
                  key={option.value}
                  onClick={() => setUsageMode(option.value)}
                  className={cn(
                    "min-w-[72px] whitespace-nowrap rounded px-3 py-1 text-xs font-semibold transition",
                    usageMode === option.value
                      ? "material-tab-active text-card-foreground"
                      : "text-muted-foreground hover:text-foreground"
                  )}
                >
                  {option.label}
                </button>
              ))}
            </div>
          </div>

          <div className="flex shrink-0 flex-wrap items-center justify-end gap-2">
            <a
              href={CONTACT_FORM_URL}
              target="_blank"
              rel="noreferrer"
              className="material-button-secondary flex min-w-[96px] items-center justify-center gap-1.5 whitespace-nowrap rounded-md px-3 py-1.5 text-xs font-semibold transition"
            >
              不具合・要望
            </a>
          </div>
        </div>
      </header>
    );
  };

  const renderSkillPanel = () => (
    <section className="flex-shrink-0 overflow-hidden rounded-lg border border-border bg-card px-4 py-3">
      <SkillList
        strategyDetail={visibleStrategyDetail}
        deckSkills={deckSkills}
        onSkillClick={handleSkillSearch}
      />
    </section>
  );

  const renderDeckSlotTabs = () => (
    <div className="flex items-center gap-1" role="tablist" aria-label="編成スロット">
      {Array.from({ length: DECK_SLOT_COUNT }).map((_, slot) => (
        <button
          key={slot}
          type="button"
          role="tab"
          aria-selected={slot === activeSlot}
          onClick={() => switchDeckSlot(slot)}
          title={`編成${slot + 1}に切り替え`}
          className={cn(
            "rounded-md px-2.5 py-1 text-xs font-semibold transition",
            slot === activeSlot
              ? "material-button-primary"
              : "bg-secondary text-secondary-foreground hover:bg-muted"
          )}
        >
          {slot + 1}
        </button>
      ))}
    </div>
  );

  const renderDeckGrid = (columns: 2 | 3, headerActions?: ReactNode) => (
    <section className="min-h-0 rounded-lg border border-border bg-card p-4 pb-6">
      <div className="mb-3 flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <h2 className="text-sm font-semibold text-card-foreground">
            編成
          </h2>
          <span className="text-xs font-semibold text-card-foreground">
            {deck.length}/6枚
          </span>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {renderDeckSlotTabs()}
          {headerActions}
        </div>
      </div>
      <div className={columns === 2 ? "grid grid-cols-2 gap-3" : "grid grid-cols-3 gap-3"}>
        {Array.from({ length: 6 }).map((_, index) => (
          <DeckSlot
            key={index}
            card={deck[index]}
            slotIndex={index}
            allTargetSkills={allTargetSkills}
            usageMode={usageMode}
            onRemove={() => removeFromDeck(deck[index])}
          />
        ))}
      </div>
    </section>
  );

  const renderMobileNavButton = ({
    tab,
    label,
    suffix,
  }: {
    tab: MobileTab;
    label: string;
    suffix?: string;
  }) => (
    <button
      onClick={() => setMobileTab(tab)}
      className={cn(
        "flex flex-1 flex-col items-center justify-center rounded-lg px-2 py-2 text-xs font-semibold transition-colors",
        mobileTab === tab
          ? "material-button-primary is-subtle"
          : "text-muted-foreground hover:bg-secondary hover:text-foreground"
      )}
    >
      <span>{label}</span>
      {suffix ? <span className="text-[10px] opacity-80">{suffix}</span> : null}
    </button>
  );

  return (
    <>
      <div className="hidden h-screen overflow-hidden bg-background font-sans text-foreground md:flex">
        <CardSearchPanel {...cardSearchPanelProps} />

        <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
          {renderRaceHeader()}

          <div className="flex-1 overflow-hidden px-4 pb-4 pt-3">
            <div className="mx-auto flex h-full max-w-5xl flex-col gap-3">
              {renderSkillPanel()}
              <div className="min-h-0 flex-1">
                {renderDeckGrid(3, renderDeckActionButtons(true))}
              </div>
            </div>
          </div>
        </div>
      </div>

      <div className="flex h-[100dvh] flex-col overflow-hidden bg-background font-sans text-foreground md:hidden">
        {renderRaceHeader(true)}

        <main className="min-h-0 flex-1 overflow-hidden px-3 pb-3 pt-2">
          {mobileTab === "search" ? (
            <CardSearchPanel {...cardSearchPanelProps} variant="embedded" />
          ) : null}

          {mobileTab === "skills" ? (
            <div className="custom-scrollbar h-full overflow-y-auto">
              {renderSkillPanel()}
            </div>
          ) : null}

          {mobileTab === "deck" ? (
            <div className="custom-scrollbar h-full overflow-y-auto">
              {renderDeckGrid(2, renderDeckActionButtons())}
            </div>
          ) : null}
        </main>

        <nav className="grid grid-cols-3 gap-2 border-t-2 border-border bg-card p-2">
          {renderMobileNavButton({ tab: "search", label: "サポカ探し" })}
          {renderMobileNavButton({ tab: "skills", label: "スキル" })}
          {renderMobileNavButton({
            tab: "deck",
            label: "編成",
            suffix: `${deck.length}/6`,
          })}
        </nav>
      </div>
    </>
  );
}
