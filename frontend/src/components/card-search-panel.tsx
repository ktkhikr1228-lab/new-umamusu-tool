"use client";

import { getCardSkills, getTypeStyle, scoreCard } from "../lib/utils";
import { SupportCard } from "../lib/types";

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
  isSmartSortActive: boolean;
  onSmartSortToggle: () => void;
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
  isSmartSortActive,
  onSmartSortToggle,
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
      className={`flex h-full flex-col bg-card shadow-sm ${
        isEmbedded
          ? "w-full rounded-lg border border-border"
          : "w-[420px] flex-shrink-0 border-r border-border"
      }`}
    >
      <div className={`border-b border-border bg-card ${isEmbedded ? "p-4" : "p-5"}`}>
        <h1 className="mb-4 flex items-center gap-2 text-lg font-semibold text-card-foreground">
          <span className="grid size-7 place-items-center rounded-md bg-primary text-sm font-bold text-primary-foreground">
            S
          </span>
          サポカ検索
        </h1>

        <input
          type="text"
          value={searchKeyword}
          onChange={(event) => onSearchChange(event.target.value)}
          placeholder="スキル名・キャラ名・カード名で検索..."
          className="mb-4 w-full rounded-lg border border-input bg-background px-3 py-2.5 text-sm font-medium outline-none transition focus:ring-2 focus:ring-ring"
        />

        <div className="mb-4 flex flex-wrap gap-2">
          {FILTERS.map((filter) => (
            <button
              key={filter}
              onClick={() => onFilterChange(filter)}
              className={`rounded-md px-2.5 py-1.5 text-xs font-semibold transition-colors ${
                activeFilter === filter
                  ? "bg-primary text-primary-foreground"
                  : "bg-secondary text-secondary-foreground hover:bg-muted"
              }`}
            >
              {filter}
            </button>
          ))}
        </div>

        <button
          onClick={onSmartSortToggle}
          className={`w-full rounded-lg px-3 py-2 text-sm font-semibold transition-colors ${
            isSmartSortActive
              ? "bg-emerald-100 text-emerald-800"
              : "bg-slate-900 text-white hover:bg-slate-800"
          }`}
        >
          {isSmartSortActive ? "最適化ソート中" : "不足スキルで最適化"}
        </button>
      </div>

      <div className={`flex min-h-0 flex-1 flex-col bg-background/60 ${isEmbedded ? "p-3" : "p-4"}`}>
        <div className="mb-2 flex items-center justify-between px-1">
          <span className="text-xs font-semibold text-muted-foreground">
            該当: {displayedCards.length}枚
          </span>
          {isSmartSortActive ? (
            <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-[10px] font-semibold text-emerald-700">
              スコア順
            </span>
          ) : null}
        </div>

        <div className="custom-scrollbar flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto pr-1">
          {displayedCards.map((card) => {
            const isAdded = deck.some((deckCard) => deckCard.id === card.id);
            const style = getTypeStyle(card.type);
            const cardScore = scoreCard(
              card,
              missingSuperSkills,
              missingRecommendedSkills
            );

            return (
              <div
                key={card.id}
                className={`rounded-lg border bg-card p-3 shadow-sm ${
                  isSmartSortActive && cardScore > 0 && !isAdded
                    ? "border-emerald-300"
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
                    {isSmartSortActive && cardScore > 0 && !isAdded ? (
                      <span className="rounded-full bg-emerald-600 px-2 py-0.5 text-center text-[10px] font-bold leading-4 text-white">
                        +{cardScore}pt
                      </span>
                    ) : null}
                    <button
                      onClick={() => onAddCard(card)}
                      disabled={isAdded || deck.length >= 6}
                      className={`rounded-md px-2 py-1.5 text-xs font-semibold transition-colors ${
                        isAdded
                          ? "bg-secondary text-muted-foreground"
                          : "bg-primary text-primary-foreground hover:bg-primary/90 disabled:bg-secondary disabled:text-muted-foreground"
                      }`}
                    >
                      {isAdded ? "編成済" : "追加"}
                    </button>
                  </div>
                </div>

                <div className="flex max-h-[4.5rem] flex-wrap gap-1.5 overflow-hidden">
                  {getCardSkills(card)
                    .slice(0, 12)
                    .map((skill) => {
                      const superHit = missingSuperSkills.includes(skill);
                      const recommendedHit =
                        missingRecommendedSkills.includes(skill);
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
