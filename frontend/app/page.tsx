"use client";

import { useEffect, useMemo, useState } from "react";
import { CardSearchPanel } from "../src/components/card-search-panel";
import { DeckSlot } from "../src/components/deck-slot";
import { SkillList } from "../src/components/skill-list";
import { RaceData, StrategyDetail, SupportCard } from "../src/lib/types";
import { cn, getCardSkills, scoreCard } from "../src/lib/utils";

import cardsData from "../src/data/cards.json";
import raceDataRaw from "../src/data/race_data.json";

const STRATEGY_ORDER = ["逃げ", "先行", "差し", "追込"];
const CONTACT_FORM_URL =
  "https://docs.google.com/forms/d/e/1FAIpQLSfGUiRhR6bkJ3V54ywE-D9R_s5LJKAlppjFP2qt4YWFaYucuA/viewform";
const INITIAL_CARDS = cardsData as SupportCard[];
const INITIAL_RACE_DATA = raceDataRaw as unknown as RaceData;
const INITIAL_RACE = Object.keys(INITIAL_RACE_DATA)[0] || "";

const emptyStrategyDetail: StrategyDetail = {
  super_recommended: [],
  recommended: [],
};

type MobileTab = "search" | "skills" | "deck";

function getApiBaseUrl() {
  const envUrl = process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "");
  if (!envUrl) return "";

  if (
    typeof window !== "undefined" &&
    !["localhost", "127.0.0.1"].includes(window.location.hostname) &&
    envUrl.includes("localhost")
  ) {
    return "";
  }

  return envUrl;
}

function normalizeCardsPayload(payload: unknown) {
  if (Array.isArray(payload)) return payload as SupportCard[];
  if (
    payload &&
    typeof payload === "object" &&
    Array.isArray((payload as { cards?: unknown }).cards)
  ) {
    return (payload as { cards: SupportCard[] }).cards;
  }
  return null;
}

export default function Home() {
  const [searchKeyword, setSearchKeyword] = useState("");
  const [activeFilter, setActiveFilter] = useState("すべて");
  const [cards, setCards] = useState<SupportCard[]>(INITIAL_CARDS);
  const [deck, setDeck] = useState<SupportCard[]>([]);
  const [raceData, setRaceData] = useState<RaceData>(INITIAL_RACE_DATA);
  const [selectedRace, setSelectedRace] = useState(INITIAL_RACE);
  const [strategy, setStrategy] = useState("先行");
  const [isSmartSortActive, setIsSmartSortActive] = useState(false);
  const [mobileTab, setMobileTab] = useState<MobileTab>("search");

  const raceOptions = useMemo(() => Object.keys(raceData), [raceData]);

  const strategyOptions = useMemo(() => {
    if (!selectedRace || !raceData[selectedRace]) return [];
    return Object.keys(raceData[selectedRace]).sort((a, b) => {
      const indexA = STRATEGY_ORDER.indexOf(a);
      const indexB = STRATEGY_ORDER.indexOf(b);
      return (indexA === -1 ? 99 : indexA) - (indexB === -1 ? 99 : indexB);
    });
  }, [raceData, selectedRace]);

  const effectiveStrategy = strategyOptions.includes(strategy)
    ? strategy
    : strategyOptions[0] || "";

  useEffect(() => {
    async function initializeData() {
      try {
        const apiBaseUrl = getApiBaseUrl();
        const [cardsResponse, raceResponse] = await Promise.all([
          fetch(`${apiBaseUrl}/api/cards`),
          fetch(`${apiBaseUrl}/api/race-data`),
        ]);

        if (cardsResponse.ok) {
          const cardsPayload = normalizeCardsPayload(await cardsResponse.json());
          if (cardsPayload) setCards(cardsPayload);
        }

        if (raceResponse.ok) {
          const racePayload = (await raceResponse.json()) as RaceData;
          setRaceData(racePayload);
          setSelectedRace((currentRace) =>
            currentRace && racePayload[currentRace]
              ? currentRace
              : Object.keys(racePayload)[0] || ""
          );
        }
      } catch (error) {
        console.error("Failed to fetch bundled data API:", error);
      }
    }

    initializeData();
  }, []);

  const handleSaveDeck = () => {
    alert("このバージョンでは編成の保存機能は無効化されています。");
  };

  const currentStrategyDetail = useMemo(() => {
    if (!selectedRace || !raceData[selectedRace] || !effectiveStrategy) {
      return emptyStrategyDetail;
    }

    const detail = raceData[selectedRace][effectiveStrategy];
    if (!detail || Array.isArray(detail)) return emptyStrategyDetail;
    return detail;
  }, [effectiveStrategy, raceData, selectedRace]);

  const allTargetSkills = useMemo(
    () => [
      ...currentStrategyDetail.super_recommended,
      ...currentStrategyDetail.recommended,
    ],
    [currentStrategyDetail]
  );

  const deckSkills = useMemo(() => {
    const skills = new Set<string>();
    deck.forEach((card) => {
      getCardSkills(card).forEach((skill) => skills.add(skill));
    });
    return skills;
  }, [deck]);

  const missingSuperSkills = useMemo(
    () =>
      currentStrategyDetail.super_recommended.filter(
        (skill) => !deckSkills.has(skill)
      ),
    [currentStrategyDetail, deckSkills]
  );

  const missingRecommendedSkills = useMemo(
    () =>
      currentStrategyDetail.recommended.filter(
        (skill) => !deckSkills.has(skill)
      ),
    [currentStrategyDetail, deckSkills]
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
        const allSkills = getCardSkills(card);
        return (
          card.name.toLowerCase().includes(keyword) ||
          card.char.toLowerCase().includes(keyword) ||
          card.card.toLowerCase().includes(keyword) ||
          allSkills.some((skill) => skill.toLowerCase().includes(keyword))
        );
      });
    }

    if (isSmartSortActive) {
      filtered = filtered.sort(
        (a, b) =>
          scoreCard(b, missingSuperSkills, missingRecommendedSkills) -
          scoreCard(a, missingSuperSkills, missingRecommendedSkills)
      );
    }

    return filtered;
  }, [
    activeFilter,
    cards,
    isSmartSortActive,
    missingRecommendedSkills,
    missingSuperSkills,
    searchKeyword,
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
    onSearchChange: (value: string) => {
      setSearchKeyword(value);
      setIsSmartSortActive(false);
    },
    activeFilter,
    onFilterChange: (filter: string) => {
      setActiveFilter(filter);
      setIsSmartSortActive(false);
    },
    isSmartSortActive,
    onSmartSortToggle: () =>
      setIsSmartSortActive((currentValue) => !currentValue),
    displayedCards,
    deck,
    missingSuperSkills,
    missingRecommendedSkills,
    onAddCard: addToDeck,
  };

  const renderRaceHeader = (compact = false) => (
    <header
      className={`flex-shrink-0 border-b border-border bg-card ${
        compact ? "px-3 py-3" : "px-6 py-4"
      }`}
    >
      <div
        className={
          compact
            ? "flex flex-col gap-3"
            : "flex items-center justify-between gap-4"
        }
      >
        <div
          className={
            compact
              ? "flex flex-col gap-3"
              : "flex min-w-0 items-center gap-4"
          }
        >
          <h1 className="flex items-center gap-2 whitespace-nowrap text-base font-semibold text-card-foreground">
            因子周回条件
          </h1>

          <div className={compact ? "grid grid-cols-[1fr_auto] gap-2" : "flex items-center gap-4"}>
            <div className="relative min-w-0">
              <select
                value={selectedRace}
                onChange={(event) => setSelectedRace(event.target.value)}
                className="w-full min-w-0 appearance-none rounded-lg border border-input bg-background px-3 py-1.5 pr-8 text-sm font-medium outline-none focus:ring-2 focus:ring-ring md:min-w-[220px]"
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

            {strategyOptions.length > 0 ? (
              <div className="flex rounded-lg bg-secondary p-0.5">
                {strategyOptions.map((option) => (
                  <button
                    key={option}
                    onClick={() => setStrategy(option)}
                    className={cn(
                      "rounded-md px-3 py-1 text-xs font-medium transition-colors",
                      effectiveStrategy === option
                        ? "bg-card text-card-foreground shadow-sm"
                        : "text-muted-foreground hover:text-foreground"
                    )}
                  >
                    {option}
                  </button>
                ))}
              </div>
            ) : (
              <span className="rounded-lg bg-secondary px-3 py-1.5 text-xs font-medium text-muted-foreground">
                脚質なし
              </span>
            )}
          </div>
        </div>

        <div className="flex items-center gap-2">
          <a
            href={CONTACT_FORM_URL}
            target="_blank"
            rel="noreferrer"
            className="flex items-center gap-1.5 rounded-lg bg-secondary px-3 py-1.5 text-xs font-medium text-secondary-foreground transition-colors hover:bg-muted"
          >
            不具合・要望
          </a>
          <button
            onClick={() => setDeck([])}
            className="flex items-center gap-1.5 rounded-lg bg-secondary px-3 py-1.5 text-xs font-medium text-secondary-foreground transition-colors hover:bg-muted"
          >
            <span aria-hidden="true">×</span>
            編成クリア
          </button>
          <button
            onClick={handleSaveDeck}
            className="flex items-center gap-1.5 rounded-lg bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground transition-colors hover:bg-primary/90"
          >
            <span aria-hidden="true">□</span>
            編成保存
          </button>
        </div>
      </div>
    </header>
  );

  const renderSkillPanel = () => (
    <section className="flex-shrink-0 overflow-hidden rounded-lg border border-border bg-card px-4 py-3">
      <SkillList strategyDetail={currentStrategyDetail} deckSkills={deckSkills} />
    </section>
  );

  const renderDeckGrid = (columns: 2 | 3) => (
    <section className="min-h-0 rounded-lg border border-border bg-card p-4">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-sm font-semibold text-card-foreground">
          現在の編成
        </h2>
        <span className="text-xs text-muted-foreground">{deck.length}/6枚</span>
      </div>
      <div className={columns === 2 ? "grid grid-cols-2 gap-3" : "grid grid-cols-3 gap-3"}>
        {Array.from({ length: 6 }).map((_, index) => (
          <DeckSlot
            key={index}
            card={deck[index]}
            slotIndex={index}
            allTargetSkills={allTargetSkills}
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
          ? "bg-primary text-primary-foreground"
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

          <div className="flex-1 overflow-hidden p-5">
            <div className="mx-auto flex h-full max-w-5xl flex-col gap-8">
              {renderSkillPanel()}
              <div className="min-h-0 flex-1">
                {renderDeckGrid(3)}
              </div>
            </div>
          </div>
        </div>
      </div>

      <div className="flex h-[100dvh] flex-col overflow-hidden bg-background font-sans text-foreground md:hidden">
        {renderRaceHeader(true)}

        <main className="min-h-0 flex-1 overflow-hidden p-3">
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
              {renderDeckGrid(2)}
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
