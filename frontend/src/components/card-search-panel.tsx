"use client";

import { getCardSkills, getTypeStyle, scoreCard } from "../lib/utils";
import { SupportCard, UsageMode } from "../lib/types";

const FILTERS = [
  "すべて",
  "スピード",
  "スタミナ",
  "パワー",
  "根性",
  "賢さ",
  "友人/グループ",
];

type CardSearchPanelProps = {
  searchKeyword: string;
  onSearchChange: (value: string) => void;
  activeFilter: string;
  onFilterChange: (filter: string) => void;
  usageMode: UsageMode;
  displayedCards: SupportCard[];
  deck: SupportCard[];
  missingSuperSkills: string[];
  missingRecommendedSkills: string[];
  onAddCard: (card: SupportCard) => void;
  variant?: "sidebar" | "embedded";
};

export function CardSearchPanel({
  searchKeyword,
  onSearchChange,
  activeFilter,
  onFilterChange,
  usageMode,
  displayedCards,
  deck,
  missingSuperSkills,
  missingRecommendedSkills,
  onAddCard,
  variant = "sidebar",
}: CardSearchPanelProps) {
  const isEmbedded = variant === "embedded";

  return (
    <aside
      className={`flex h-full flex-col bg-card ${
        isEmbedded
          ? "w-full rounded-lg border border-border"
          : "w-[420px] flex-shrink-0 border-r border-border"
      }`}
    >
      <div className={`border-b border-border bg-card ${isEmbedded ? "p-4" : "p-5"}`}>
        <h1 className="mb-4 flex items-center gap-2 text-lg font-semibold text-card-foreground">
          サポカを探す
        </h1>

        <input
          type="text"
          value={searchKeyword}
          onChange={(event) => onSearchChange(event.target.value)}
          placeholder="スキル名・キャラ名・カード名で検索..."
          className="mb-4 w-full rounded-md border border-input bg-card px-3 py-2.5 text-sm font-medium outline-none transition focus:ring-2 focus:ring-ring"
        />

        <div className="mb-4 flex flex-wrap gap-2">
          {FILTERS.map((filter) => (
            <button
              key={filter}
              onClick={() => onFilterChange(filter)}
              className={`rounded-md px-2.5 py-1.5 text-xs font-semibold transition-colors ${
                activeFilter === filter
                  ? "material-button-primary"
                  : "bg-secondary text-secondary-foreground hover:bg-muted"
              }`}
            >
              {filter}
            </button>
          ))}
        </div>

      </div>

      <div className={`flex min-h-0 flex-1 flex-col bg-background/60 ${isEmbedded ? "p-3" : "p-4"}`}>
        <div className="mb-2 flex items-center justify-between px-1">
          <span className="text-xs font-semibold text-card-foreground">
            候補 {displayedCards.length}枚
          </span>
          <div className="flex items-center gap-1.5">
            <span className="rounded-full bg-secondary px-2 py-0.5 text-[10px] font-semibold text-secondary-foreground">
              おすすめ順
            </span>
            <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-[10px] font-semibold text-emerald-700">
              {usageMode === "factor" ? "因子用" : "本育成用"}
            </span>
          </div>
        </div>

        <div className="custom-scrollbar flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto pr-1">
          {displayedCards.map((card) => {
            const isAdded = deck.some((deckCard) => deckCard.id === card.id);
            const style = getTypeStyle(card.type);
            const cardScore = scoreCard(
              card,
              missingSuperSkills,
              missingRecommendedSkills,
              usageMode
            );
            const cardSkills = getCardSkills(card, usageMode);

            return (
              <div
                key={card.id}
                className={`rounded-md border bg-card p-3 ${
                  cardScore > 0 && !isAdded
                    ? "border-emerald-400"
                    : "border-border"
                }`}
              >
                <div className="mb-2 flex items-start justify-between gap-3">
                  <div className="min-w-0 flex-1">
                    <div className="mb-1.5 flex items-center gap-1.5">
                      <span
                        className={`rounded px-2 py-0.5 text-[10px] font-semibold ${style.bg} ${style.text}`}
                      >
                        {card.type}
                      </span>
                      <span
                        className={`text-[10px] font-semibold ${
                          card.rarity === "SSR"
                            ? "text-amber-600"
                            : "text-muted-foreground"
                        }`}
                      >
                        {card.rarity}
                      </span>
                    </div>
                    <div className="line-clamp-2 text-sm font-semibold leading-snug text-card-foreground">
                      {card.name}
                    </div>
                  </div>
                  <div className="flex w-[64px] flex-shrink-0 flex-col items-stretch gap-1">
                    <button
                      onClick={() => onAddCard(card)}
                      disabled={isAdded || deck.length >= 6}
                      className={`rounded-md px-2 py-1.5 text-xs font-semibold transition ${
                        isAdded
                          ? "material-button-secondary"
                          : "material-button-primary disabled:bg-secondary disabled:text-muted-foreground"
                      }`}
                    >
                      {isAdded ? "編成済" : "追加"}
                    </button>
                  </div>
                </div>

                <div className="flex max-h-[4.5rem] flex-wrap gap-1.5 overflow-hidden">
                  {cardSkills.slice(0, 12).map((skill) => {
                    const superHit = missingSuperSkills.includes(skill);
                    const recommendedHit = missingRecommendedSkills.includes(skill);

                    return (
                        <span
                          key={skill}
                          className={`rounded px-1.5 py-0.5 text-[10px] font-semibold ${
                            superHit
                              ? "border border-rose-300 bg-rose-50 text-rose-700"
                              : recommendedHit
                                ? "border border-amber-300 bg-amber-50 text-amber-700"
                                : "bg-secondary text-muted-foreground"
                          }`}
                        >
                          {skill}
                        </span>
                    );
                  })}
                </div>
              </div>
            );
          })}
        </div>

      </div>
    </aside>
  );
}
